"""Canonical Core delivery evidence for the protected terminal submit path."""

import asyncio
import hashlib
import json
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from urllib.request import Request, urlopen
from uuid import uuid4

import pytest

from nexus_connector_core import (
    CoreError, EventCursor, ExecutionContext, LaunchIntent, OpenOperation,
    OperationKey, RuntimeEvent, ShutdownPolicy, TurnOperation,
)
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.models import EffectNotSent, InstallationCandidate
from nexus_connector_core.native.claude_terminal_prompt import ClaudeTerminalPromptGate
from nexus_connector_core.native.claude_terminal_submission import ClaudeTerminalSession, ClaudeTerminalSubmission
from nexus_connector_core.native.redaction import NativeSecretRedactor
from nexus_connector_core.runtime import LocalRuntimeCore


class _Clock:
    advance = 0

    def monotonic(self):
        return time.monotonic() + self.advance

    def wall_time(self):
        return time.time()


class _HookPeer:
    def __init__(self, gate, cwd, session_uuid, boundary):
        settings, env = gate.launch_settings()
        hook, = settings["hooks"]["UserPromptSubmit"][0]["hooks"]
        if "Stop" in settings["hooks"]:
            self.completion = settings["hooks"]["Stop"][0]["hooks"][0]["url"]
        self._url = hook["url"]
        self._token = next(iter(env.values()))
        self._scope = {"cwd": cwd, "session_id": session_uuid, "permission_mode": "plan",
                       "hook_event_name": "UserPromptSubmit"}
        self.boundary = boundary
        self.writes = []
        self.responses = []
        self.stopped = False
        self.birth = None

    def write(self, data):
        assert data.startswith(b"\x1b[200~") and data.endswith(b"\x1b[201~\r")
        text = data[6:-7].decode()
        self.writes.append(text)
        self.boundary()
        self.responses.append(self.post(self._url, prompt=text, prompt_id=self.prompt_id))

    @property
    def prompt_id(self):
        return "native-prompt-" + str(len(self.writes))

    def post(self, url, **payload):
        request = Request(url, data=json.dumps(self._scope | payload).encode(),
                          headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json"})
        with urlopen(request, timeout=4) as response:
            return json.load(response)

    def poll(self):
        return 0 if self.stopped else None

    def close(self):
        self.stopped = True


class _Factory:
    native_id = "native-terminal"

    def __init__(self, submission):
        self.terminal_submission = submission
        self.queue = asyncio.Queue()
        self.stopped = False

    async def open(self, prepared, session_id, context, *, stream_epoch):
        return self

    async def send(self, verb, *_args, **_kwargs):
        if verb == "send_turn":
            raise AssertionError("The legacy sender must never receive an admitted terminal prompt.")
        raise EffectNotSent("Native controls are unavailable in this fixture.")

    async def events(self):
        while (event := await self.queue.get()) is not None:
            yield event

    async def close(self):
        self.stopped = True
        await self.queue.put(None)
        return "graceful"

    async def observe(self):
        return ("STOPPED" if self.stopped else "RUNNING", "IDLE")


def test_saved_claude_open_is_bound_to_one_exact_native_context(tmp_path):
    async def run():
        saved_id = str(uuid4())
        selected_ids = []

        native = _Factory(None)

        class LegacyFactory:
            async def open(self, prepared, session_id, context, *, stream_epoch):
                return await native.open(prepared, session_id, context, stream_epoch=stream_epoch)

        class ResumingFactory(LegacyFactory):
            async def open(self, prepared, session_id, context, *, stream_epoch, resume_claude_session_id=None):
                selected_ids.append(resume_claude_session_id)
                return await super().open(prepared, session_id, context, stream_epoch=stream_epoch)

        binary = tmp_path / "claude-fixture"
        binary.write_bytes(b"synthetic selected binary")
        candidate = InstallationCandidate("claude_stream", str(binary), fingerprint(binary), "explicit", "selected")
        database = tmp_path / "resume.sqlite"
        context = ExecutionContext("server", "executor", "binding", "agent", "workspace", 1, 1, 1,
                                   time.monotonic() + 60, frozenset({"runtime.open", "runtime.close"}))

        def make_runtime(journal, factory):
            return LocalRuntimeCore(journal, factory, candidates={"claude_stream": candidate},
                                    workspace_roots={"workspace": str(tmp_path)})

        journal = SQLiteJournal(database)
        legacy = make_runtime(journal, LegacyFactory())
        try:
            prepared = await legacy.prepare(LaunchIntent("agent", "workspace", "claude_stream"), context)
            opening = OpenOperation("open", "session", "epoch", prepared, resume_claude_session_id=saved_id)
            with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED") as unsupported:
                await legacy.open(opening, context)
            assert unsupported.value.retry_safe and not unsupported.value.possible_effect
            assert await journal.get_receipt(OperationKey("server", "executor", "open")) is None
        finally:
            await legacy.shutdown(ShutdownPolicy(0, 0))

        runtime = make_runtime(journal, ResumingFactory())
        try:
            for invalid in (replace(opening, resume_claude_session_id="--last"),
                            replace(opening, resume_thread_id="another-target")):
                with pytest.raises(CoreError, match="VALIDATION_ERROR"):
                    await runtime.open(invalid, context)
            receipt = await runtime.open(opening, context)
            assert receipt.stage == "SUBMITTED"
            assert saved_id not in repr(opening) and saved_id not in repr(receipt)
            assert selected_ids == [saved_id]
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()

        journal = SQLiteJournal(database)
        runtime = make_runtime(journal, ResumingFactory())
        try:
            assert await runtime.open(opening, context) == receipt
            for target in (None, str(uuid4())):
                with pytest.raises(CoreError, match="OPERATION_CONFLICT"):
                    await runtime.open(replace(opening, resume_claude_session_id=target), context)
            assert selected_ids == [saved_id]
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()

    asyncio.run(run())


@pytest.mark.parametrize("case", ["accepted", "slow_profile_at_hook", "revoked_at_hook", "lost_after_reply"])
def test_core_binds_the_terminal_hook_to_the_durable_send(tmp_path, case):
    async def run():
        clock = _Clock()
        workspace = str(tmp_path)
        session_uuid = str(uuid4())
        journal = SQLiteJournal(tmp_path / "history.sqlite")
        async with _runtime(journal, clock, session_uuid, workspace, tmp_path, case) as values:
            runtime, context, native, peer = values
            operation = TurnOperation("terminal-turn-1", "session", "An exact approved message.")
            key = OperationKey("server", "executor", operation.operation_id)
            if case in {"accepted", "slow_profile_at_hook"}:
                submitted = await runtime.submit(operation, context)
                assert submitted.stage == "SUBMITTED" and submitted.possible_effect
                assert await runtime.submit(operation, context) == submitted
                assert peer.responses == [{}]
                with pytest.raises(CoreError, match="STALE_TURN"):
                    await runtime.submit(TurnOperation("too-soon", "session", "Different input."), context)
                await native.queue.put(RuntimeEvent("server", "executor", "session", "epoch", 0,
                    "turn_state", "fixture-result", {"delivery_phase": "terminal", "delivery_outcome": "success"},
                    operation_id=operation.operation_id))
                async with asyncio.timeout(5):
                    while native.terminal_submission.active_turn():
                        await asyncio.sleep(.01)
                assert (await journal.get_receipt(key)).stage == "SUCCEEDED"
            else:
                with pytest.raises(CoreError, match="OUTCOME_UNKNOWN") as uncertain:
                    await runtime.submit(operation, context)
                assert uncertain.value.possible_effect and not uncertain.value.retry_safe
                retained = await journal.get_receipt(key)
                assert retained.stage == "OUTCOME_UNKNOWN" and native.terminal_submission.active_turn()
                if case == "revoked_at_hook":
                    assert peer.responses[0]["decision"] == "block"
                else:
                    assert peer.responses == [{}]
                    assert await runtime.submit(operation, context) == retained
            assert peer.writes == [operation.text]

    asyncio.run(run())


@pytest.mark.parametrize("failure", [False, True])
def test_correlated_native_wire_result_settles_only_its_admitted_turn(tmp_path, failure):
    async def run():
        native_uuid = str(uuid4())
        workspace = str(tmp_path)
        idle_since = time.time_ns() // 1_000_000
        confirmed_text_hash = None
        with ClaudeTerminalPromptGate(native_uuid, workspace, "plan", lambda _: True, observe_results=True) as gate:
            peer = _HookPeer(gate, workspace, native_uuid, lambda: None)

            class Factory:
                async def open(self, _prepared, session_id, context, *, stream_epoch):
                    self.native = ClaudeTerminalSession(
                        peer, gate, native_id="native", session_id=session_id, stream_epoch=stream_epoch,
                        context=context, redactor=NativeSecretRedactor(("fixture-private-value",)),
                        observe_finished=lambda digest: idle_since if digest == confirmed_text_hash else None)
                    return self.native

            binary = tmp_path / "claude-fixture"
            binary.write_bytes(b"synthetic selected binary")
            candidate = InstallationCandidate("claude_stream", str(binary), fingerprint(binary), "explicit", "selected")
            journal = SQLiteJournal(tmp_path / "terminal.sqlite")
            factory = Factory()
            runtime = LocalRuntimeCore(journal, factory, candidates={"claude_stream": candidate},
                                       workspace_roots={"workspace": workspace})
            context = ExecutionContext("server", "executor", "binding", "agent", "workspace", 1, 1, 1,
                                       time.monotonic() + 60,
                                       frozenset({"runtime.open", "turn.submit", "runtime.close"}))
            try:
                prepared = await runtime.prepare(LaunchIntent("agent", "workspace", "claude_stream"), context)
                await runtime.open(OpenOperation("open", "session", "epoch", prepared), context)
                operation = TurnOperation("terminal-turn", "session", "A scoped task.")
                receipt = await runtime.submit(operation, context)
                assert receipt.stage == "SUBMITTED"
                key = OperationKey("server", "executor", operation.operation_id)
                stop = {"hook_event_name": "Stop", "prompt_id": peer.prompt_id, "stop_hook_active": False,
                        "background_tasks": [], "session_crons": [],
                        "last_assistant_message": "Answer fixture-private-value " + peer._token}
                post = lambda payload: asyncio.to_thread(peer.post, peer.completion, **payload)
                await post(stop | {"prompt_id": "unrelated-prompt"})
                await post(stop | {"session_id": str(uuid4())})
                await post(stop | {"background_tasks": [{"type": "shell"}]})
                assert factory.native.terminal_submission.active_turn()
                assert (await journal.get_receipt(key)).stage == "SUBMITTED"
                await post(stop | {"last_assistant_message": "Intermediate text"})
                await asyncio.sleep(.22)
                assert (await journal.get_receipt(key)).stage == "SUBMITTED"
                idle_since = None
                with pytest.raises(CoreError, match="STALE_TURN"):
                    await runtime.submit(TurnOperation("while-busy", "session", "Do not dispatch."), context)
                long_output = "X" * (480 * 1024)
                stop["stop_hook_active"] = True
                if not failure:
                    stop["last_assistant_message"] += "\n" + long_output
                else:
                    # Claude may enter idle before sending StopFailure. An old
                    # success candidate must not become terminal in this gap.
                    idle_since = time.time_ns() // 1_000_000
                    await asyncio.sleep(.22)
                    assert (await journal.get_receipt(key)).stage == "SUBMITTED"
                result = (stop | {"hook_event_name": "StopFailure", "error": "unknown"}) if failure else stop
                await post(result)
                await post(result)
                if not failure:
                    await asyncio.sleep(.22)
                    assert (await journal.get_receipt(key)).stage == "SUBMITTED"
                    confirmed_text_hash = hashlib.sha256(stop["last_assistant_message"].encode("utf-8")).hexdigest()
                    idle_since = time.time_ns() // 1_000_000
                async with asyncio.timeout(5):
                    while factory.native.terminal_submission.active_turn():
                        await asyncio.sleep(.01)
                assert (await journal.get_receipt(key)).stage == ("FAILED" if failure else "SUCCEEDED")
                events = [event async for event in journal.events(EventCursor("server", "executor", "session", "epoch"))
                          if event.operation_id == operation.operation_id]
                event, = events
                assert event.operation_id == operation.operation_id and event.category == "turn_state"
                if failure:
                    assert event.payload == {"delivery_phase": "terminal", "delivery_outcome": "failed",
                                             "delivery_error_code": "NATIVE_OPERATION_FAILED"}
                else:
                    assert event.payload["output_text"] == "Answer [REDACTED] [REDACTED]\n" + long_output
                assert await runtime.submit(TurnOperation("next", "session", "A new task."), context)
                await post(result)
                assert factory.native.terminal_submission.active_turn()
            finally:
                await runtime.shutdown(ShutdownPolicy(0, 0))
                journal.close()

    asyncio.run(run())


@asynccontextmanager
async def _runtime(journal, clock, session_uuid, workspace, root, case):
    with ClaudeTerminalPromptGate(session_uuid, workspace, "plan", lambda _op: True) as gate:
        def boundary():
            if case == "revoked_at_hook":
                clock.advance = 120

        peer = _HookPeer(gate, workspace, session_uuid, boundary)
        if case == "lost_after_reply":
            write = peer.write

            def lose_reply(data):
                write(data)
                raise OSError("Simulated loss of the local terminal write result.")

            peer.write = lose_reply
        profile_checks = 0

        def require_current():
            nonlocal profile_checks
            profile_checks += 1
            if case == "slow_profile_at_hook" and profile_checks == 2:
                time.sleep(2.25)

        native = _Factory(ClaudeTerminalSubmission(peer, gate, require_current=require_current))
        binary = root / "claude-fixture"
        binary.write_bytes(b"synthetic selected binary")
        candidate = InstallationCandidate("claude_stream", str(binary), fingerprint(binary), "explicit", "selected")
        runtime = LocalRuntimeCore(journal, native, candidates={"claude_stream": candidate},
                                   workspace_roots={"workspace": workspace}, clock=clock)
        context = ExecutionContext("server", "executor", "binding", "agent", "workspace", 1, 1, 1,
                                   clock.monotonic() + 60, frozenset({"runtime.open", "turn.submit", "runtime.close"}))
        try:
            prepared = await runtime.prepare(LaunchIntent("agent", "workspace", "claude_stream"), context)
            await runtime.open(OpenOperation("open", "session", "epoch", prepared), context)
            if case == "accepted":
                with pytest.raises(CoreError, match="VALIDATION_ERROR") as refused:
                    await runtime.submit(TurnOperation("terminal-command", "session", "/exit"), context)
                assert refused.value.retry_safe and not refused.value.possible_effect and not peer.writes
            yield runtime, context, native, peer
        finally:
            await runtime.shutdown(ShutdownPolicy(0, 0))
            journal.close()
