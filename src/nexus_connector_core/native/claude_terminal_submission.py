"""Send one admitted plain-text turn through the protected Claude terminal."""

import asyncio
import threading
import time
from dataclasses import replace

from ..models import CoreError, EffectNotSent, EffectRejected, RuntimeEvent
from .claude_chat_facts import (
    CLAUDE_CHAT_EVENT,
    MAX_CLAUDE_CHAT_BYTES,
    valid_claude_chat_fact,
)
from .claude_history_identity import project_claude_history
from .claude_terminal_prompt import CLAUDE_PROMPT_HOOK_TIMEOUT
from .redaction import NativeSecretRedactor

_WRITE_WINDOW = 10.0
_MAX_PASTE_BYTES = 64 * 1024 - len(b"\x1b[200~\x1b[201~\r")
_STAGE = "claude_terminal_submission"


class ClaudeTerminalSubmission:
    def __init__(self, terminal, prompt_gate, *, require_current=None):
        self._terminal = terminal
        self._gate = prompt_gate
        self._require_current = require_current
        self._active_operation = None

    def active_turn(self):
        return self._active_operation is not None

    def owns_turn(self, operation_id):
        return operation_id == self._active_operation

    def confirm_terminal(self, operation_id):
        """Release this slot only when the exact terminal event is durable."""
        if operation_id == self._active_operation:
            self._active_operation = None

    async def submit(self, operation_id, text, verify):
        if self._active_operation is not None:
            raise EffectNotSent("The prior Claude terminal submission is unsettled.", code="STALE_TURN")
        paste = _terminal_prompt(text)
        if paste is None:
            raise EffectNotSent("Only bounded plain text can be sent as a prompt.", code="VALIDATION_ERROR")
        async def verify_profile_and_authority():
            if self._require_current is not None:
                await asyncio.to_thread(self._require_current)
            return await verify()

        if not await verify_profile_and_authority():
            raise EffectNotSent("The durable Claude submission or its authority changed.", code="BINDING_NOT_AUTHORIZED")

        loop = asyncio.get_running_loop()
        deadline = time.monotonic() + _WRITE_WINDOW
        cancelled = threading.Event()

        def authorize_hook():
            if cancelled.is_set():
                return False
            future = asyncio.run_coroutine_threadsafe(verify_profile_and_authority(), loop)
            try:
                # Leave the native hook time to receive the verdict while
                # revalidating the host profile and durable write authority.
                budget = min(CLAUDE_PROMPT_HOOK_TIMEOUT - 1, max(0, deadline - time.monotonic()))
                allowed = future.result(timeout=budget) is True
                return allowed and not cancelled.is_set()
            finally:
                if not future.done():
                    future.cancel()

        self._active_operation = operation_id
        armed = asyncio.create_task(asyncio.to_thread(self._gate.arm, operation_id, text,
                                                      ttl=_WRITE_WINDOW, check=authorize_hook))
        try:
            delivery = await asyncio.shield(armed)
        except CoreError as error:
            self._active_operation = None
            raise EffectNotSent("The terminal permit could not be installed.", code=error.code) from error
        except asyncio.CancelledError:
            cancelled.set()
            try:
                await armed
            finally:
                await asyncio.to_thread(self._gate.discard, operation_id)
            raise
        try:
            async with asyncio.timeout_at(loop.time() + max(0, deadline - time.monotonic())):
                await asyncio.to_thread(self._terminal.write, paste)
                acknowledged = await asyncio.to_thread(delivery.wait, max(0, deadline - time.monotonic()))
                if not acknowledged:
                    raise TimeoutError("Claude terminal submission did not receive a definitive hook reply.")
        except (CoreError, OSError, TimeoutError) as error:
            raise CoreError("OUTCOME_UNKNOWN", _STAGE, possible_effect=True, operation_id=operation_id) from error
        finally:
            cancelled.set()
            await asyncio.to_thread(self._gate.discard, operation_id)


def _terminal_prompt(text):
    if (type(text) is not str or not text.strip() or text.lstrip().startswith(("/", "!"))
            or len(text) > _MAX_PASTE_BYTES
            or any(char != "\n" and (char < " " or "\x7f" <= char <= "\x9f") for char in text)):
        return None
    try:
        data = text.encode("utf-8")
    except UnicodeError:
        return None
    if len(data) > _MAX_PASTE_BYTES:
        return None
    return b"\x1b[200~" + data + b"\x1b[201~\r"


class ClaudeTerminalSession:
    """Core's native session port for an exact, already verified Claude terminal."""

    def __init__(self, terminal, gate, *, native_id, session_id, stream_epoch, context, redactor, observe_finished,
                 observe_interrupted=None, observe_generation=None, observe_chat=None, observe_history=None,
                 require_current=None,
                 allow_interrupt=None, resources=()):
        if not isinstance(redactor, NativeSecretRedactor):
            raise TypeError("An owned Claude terminal requires native secret redaction.")
        if not callable(observe_finished):
            raise TypeError("An owned Claude terminal requires an exact native completion observation.")
        self.native_id = native_id
        self._terminal = terminal
        self._gate = gate
        self._session_id = session_id
        self._stream_epoch = stream_epoch
        self._context = context
        self._redactor = redactor
        self._observe_finished = observe_finished
        self._observe_interrupted = observe_interrupted
        self._observe_generation = observe_generation
        self._observe_chat = observe_chat
        self._observe_history = observe_history
        self._history_turn = None
        self._require_current = require_current
        self._allow_interrupt = allow_interrupt
        self._interrupt_target = None
        self._resources = tuple(resources)
        self._close_lock = asyncio.Lock()
        self._closed = False
        self.terminal_submission = ClaudeTerminalSubmission(terminal, gate, require_current=require_current)

    def _completion_event(self, result):
        payload = {"delivery_phase": "terminal"}
        if result.interrupted:
            payload["delivery_outcome"] = "interrupted"
            kind = "core.claude_terminal_interrupted"
        elif result.failure_code is not None:
            payload["delivery_outcome"] = "failed"
            payload["delivery_error_code"] = result.failure_code
            kind = "StopFailure"
        else:
            payload["delivery_outcome"] = "success"
            payload["output_text"] = self._redactor.clean(result.output_text)
            kind = "Stop"
        event = RuntimeEvent(self._context.server_id, self._context.executor_id, self._session_id,
                             self._stream_epoch, 0, "turn_state", kind, payload, operation_id=result.operation_id)
        if self._history_turn is None:
            return event
        session_uuid, _, _ = self._history_turn
        scoped = replace(event, payload=payload | {"session_id": session_uuid})
        projected = project_claude_history(scoped, {"schema_version": 1, "session_id": session_uuid},
                                           self._redactor.clean)
        return event if projected is scoped else projected

    async def events(self):
        if self._closed or await asyncio.to_thread(self._terminal.poll) is not None:
            return
        yield RuntimeEvent(self._context.server_id, self._context.executor_id, self._session_id,
                           self._stream_epoch, 0, "lifecycle", "core.claude_terminal_ready", {})
        reported_generation = None
        while not self._closed and await asyncio.to_thread(self._terminal.poll) is None:
            result = await asyncio.to_thread(self._gate.take_finished_result, self._observe_finished,
                                             self._observe_interrupted)
            if result is not None:
                self._history_turn = None
                if result.chat_turn is not None and self._observe_chat is not None:
                    entries = await asyncio.to_thread(self._observe_chat, result.chat_turn)
                    if entries and self._observe_history is not None and result.failure_code is None:
                        self._history_turn = (entries[0]["native_session_id"], result.operation_id, result.chat_turn)
                    for raw in entries:
                        fact = self._redactor.clean(raw)
                        text = fact.get("text")
                        if not isinstance(text, str):
                            continue
                        if len(text.encode("utf-8")) > MAX_CLAUDE_CHAT_BYTES:
                            fact["text"] = None
                        if valid_claude_chat_fact(fact):
                            yield RuntimeEvent(self._context.server_id, self._context.executor_id, self._session_id,
                                               self._stream_epoch, 0, "tool_activity", CLAUDE_CHAT_EVENT,
                                               fact, operation_id=result.operation_id)
                yield self._completion_event(result)
                continue
            question = self._gate.take_decision()
            if question is not None:
                operation_id, request = question
                display = self._redactor.clean(request)
                display["request_hash"] = request["request_hash"]
                category = "approval_request" if request["params"]["tool_name"] == "Read" else "input_request"
                yield RuntimeEvent(self._context.server_id, self._context.executor_id, self._session_id,
                                   self._stream_epoch, 0, category, request["method"],
                                   {"native_approval": request, "native_approval_display": display},
                                   operation_id=operation_id)
            elif self._observe_generation is not None:
                generation = await asyncio.to_thread(self._gate.read_generation, self._observe_generation,
                                                     skip_operation=reported_generation)
                if generation is not None:
                    reported_generation, _ = generation
                    payload = {"schema_version": 1}
                    if self._allow_interrupt is not None and await asyncio.to_thread(self._allow_interrupt):
                        payload["interruptible"] = True
                    yield RuntimeEvent(self._context.server_id, self._context.executor_id, self._session_id,
                                       self._stream_epoch, 0, "tool_activity", "core.claude_terminal_generating",
                                       payload, operation_id=reported_generation)
            await asyncio.sleep(0.1)

    def owned_process_birth(self):
        return self._terminal.birth

    def open_terminal_reader(self):
        from .claude_terminal_reader import ClaudeTerminalReader

        return ClaudeTerminalReader(self._terminal)

    async def read_owned_claude_history(self, session_uuid, operation_id):
        claim = self._history_turn
        if self._closed or claim is None or claim[:2] != (session_uuid, operation_id):
            return None

        def observe():
            if self._require_current is not None:
                self._require_current()
            current = self._observe_history()
            if current is None or current.session_uuid != session_uuid or not self._observe_chat(claim[2]):
                return None
            # A different snapshot during the terminal correlation is not retirement evidence.
            return current if self._observe_history() == current else None

        return await asyncio.to_thread(observe)

    async def send(self, _verb, _payload, _operation_id, *, expected_turn_id=None):
        raise EffectNotSent("This action is not available on the owned Claude terminal.")

    async def reply_native_approval(self, request, decision, operator_response):
        if (request.get("method") != "control_request:can_use_tool"
                or request.get("params", {}).get("tool_name") not in {"AskUserQuestion", "Read"}
                or decision not in {"accept", "decline", "cancel"}):
            raise EffectNotSent("This native decision is unavailable in the Claude terminal.")

        def check(operation_id):
            if (self._closed or self._terminal.poll() is not None
                    or not self.terminal_submission.owns_turn(operation_id)):
                raise EffectNotSent("This Claude request no longer belongs to a live turn.", code="STALE_TURN")
            if decision == "accept":
                fence = getattr(self, "effect_fence", None)
                if self._require_current is None or fence is None:
                    raise EffectNotSent("The current Claude answer authority is unavailable.",
                                        code="BINDING_NOT_AUTHORIZED")
                self._require_current()
                fence.check("send_turn")

        await asyncio.to_thread(self._gate.reply_decision, request, decision, operator_response, check)

    async def interrupt(self, operation_id, target, *, verify, fence):
        """Send one Escape to the exact live generating prompt."""
        if (self._observe_generation is None or self._allow_interrupt is None or not target
                or not self.terminal_submission.owns_turn(target) or not await verify()):
            raise EffectNotSent("The reviewed Claude turn is unavailable.", code="STALE_TURN")

        def at_write():
            if self._closed or self._interrupt_target == target:
                raise EffectNotSent("The reviewed Claude turn no longer accepts an interrupt.", code="STALE_TURN")
            if self._require_current is not None:
                self._require_current()
            if not self._allow_interrupt():
                raise EffectNotSent("The Claude terminal key configuration changed.", code="CAPABILITY_UNSUPPORTED")
            evidence = self._gate.read_generation(self._observe_generation)
            if (evidence is None or evidence[0] != target
                    or not self.terminal_submission.owns_turn(target)):
                raise EffectNotSent("The reviewed Claude turn changed before the interrupt.", code="STALE_TURN")
            fence()
            self._interrupt_target = target

        try:
            await asyncio.to_thread(self._terminal.write, b"\x1b", before_write=at_write)
        except (CoreError, OSError) as error:
            if self._interrupt_target == target and not isinstance(error, EffectNotSent):
                raise CoreError("OUTCOME_UNKNOWN", "claude_terminal_interrupt",
                                possible_effect=True, operation_id=operation_id) from error
            raise

    async def steer(self, operation_id, target, text, *, verify, fence, settle, record):
        """Interrupt once and replace only after the original cancel is durable."""
        if _terminal_prompt(text) is None:
            raise EffectNotSent("Only bounded plain text can replace a turn.", code="VALIDATION_ERROR")

        def unknown():
            return CoreError("OUTCOME_UNKNOWN", "claude_terminal_steer",
                             possible_effect=True, operation_id=operation_id)

        try:
            await self.interrupt(operation_id, target, verify=verify, fence=fence)
        except CoreError as error:
            if not error.possible_effect:
                raise
            try:
                await record("interrupt_write_unknown")
                await record("replacement_not_sent")
            except Exception as recording_error:
                raise unknown() from recording_error
            raise unknown() from error

        try:
            await record("interrupt_submitted")
            try:
                stage = await settle()
            except TimeoutError as error:
                await record("replacement_not_sent")
                raise unknown() from error
            if stage != "CANCELLED":
                await record("replacement_not_sent")
                raise EffectRejected("The original turn finished before cancellation.", failure_code="STALE_TURN")
            await record("interrupt_confirmed")
            try:
                await self.terminal_submission.submit(operation_id, text, verify)
            except EffectNotSent as error:
                await record("replacement_not_sent")
                raise EffectRejected("The replacement was refused before writing.", failure_code=error.code) from error
            except CoreError as error:
                if error.retry_safe and not error.possible_effect:
                    await record("replacement_not_sent")
                    raise EffectRejected("The replacement lost authority before writing.",
                                         failure_code=error.code) from error
                await record("replacement_write_unknown")
                raise unknown() from error
            except Exception as error:
                await record("replacement_write_unknown")
                raise unknown() from error
            await record("replacement_submitted")
        except EffectRejected:
            raise
        except Exception as error:
            if isinstance(error, CoreError) and error.code == "OUTCOME_UNKNOWN" and error.possible_effect:
                raise
            raise unknown() from error

    async def observe(self):
        if await asyncio.to_thread(self._terminal.poll) is not None:
            return "STOPPED", "UNKNOWN"
        return "RUNNING", "BUSY" if self.terminal_submission.active_turn() else "IDLE"

    async def close(self):
        async with self._close_lock:
            if self._closed:
                return "already_closed"
            prior_exit = await asyncio.to_thread(self._terminal.poll)
            await asyncio.to_thread(self._terminal.close)
            await asyncio.to_thread(self._gate.__exit__, None, None, None)
            for resource in self._resources:
                await asyncio.to_thread(resource.close)
            self._closed = True
            return "graceful" if prior_exit == 0 else "forced"

    async def force_stop(self):
        await self.close()
