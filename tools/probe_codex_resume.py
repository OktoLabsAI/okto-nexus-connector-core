"""Authorized real Codex cross-process resume campaign (K05).

Run 1 opens a thread, completes a real turn and closes the connector. The
host side then locates the persisted rollout for that thread under the
user's CODEX_HOME, and Run 2 (a fresh app-server process) resumes exactly
that thread through the adapter's resume path, verifies the returned
identity/status and completes one more tiny real turn. Logs only protocol
metadata — never prompt output, model text or secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from nexus_connector_core.native.adapter_types import HarnessCommand
from nexus_connector_core.native.adapters.codex import CodexAppServerConnector


def _connector(codex_exe: Path, codex_home: Path, cwd: Path):
    environment = {"CODEX_HOME": str(codex_home)}
    for name in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "PATH",
                 "SYSTEMROOT", "TEMP", "TMP"):
        if name in os.environ:
            environment[name] = os.environ[name]
    return CodexAppServerConnector(
        command=(str(codex_exe), "app-server"),
        cwd=str(cwd), env=environment, handshake_timeout_s=60)


def _run_turn(connector, session, text, label):
    methods: list[str] = []
    turn_completed = threading.Event()
    terminal_turn: list[str] = []

    def consume() -> None:
        for event in connector.events():
            if len(methods) < 200:
                methods.append(event.native_event)
            if event.native_event == "turn/completed":
                turn_payload = event.payload.get("turn")
                if isinstance(turn_payload, dict):
                    terminal_turn.append(str(turn_payload.get("status")))
                turn_completed.set()

    reader = threading.Thread(target=consume, daemon=True)
    reader.start()
    connector.send(session, HarnessCommand(
        session.session_id, "send_turn", {"text": text},
        operation_id=label))
    if not turn_completed.wait(timeout=180):
        raise SystemExit(f"{label}: turn did not complete")
    return terminal_turn[-1] if terminal_turn else None


def _find_rollout(codex_home: Path, thread_id: str) -> str | None:
    sessions = codex_home / "sessions"
    if not sessions.is_dir():
        return None
    for path in sorted(sessions.rglob("rollout-*.jsonl"),
                       key=lambda item: item.stat().st_mtime, reverse=True):
        try:
            if thread_id.encode() in path.read_bytes():
                return str(path)
        except OSError:
            continue
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("codex_exe", type=Path)
    parser.add_argument("codex_home", type=Path)
    args = parser.parse_args()
    codex_exe = args.codex_exe.resolve(strict=True)
    codex_home = args.codex_home.resolve(strict=True)
    report: dict[str, object] = {}
    with tempfile.TemporaryDirectory(prefix="nexus-core-codex-resume-") as directory:
        workdir = Path(directory)
        # -- Run 1: open a thread, complete one real turn, close the process.
        first = _connector(codex_exe, codex_home, workdir)
        try:
            session_one = first.start(owning_agent_id="core-resume-one")
            thread_id = session_one.metadata.get("codex_thread_id") if (
                session_one.metadata) else None
            if not thread_id:
                # The session id is Core-minted; the native thread id lives
                # in the start() result path. Read it from the connector.
                state = first._sessions_by_id.get(session_one.session_id)
                thread_id = state.thread_id if state else None
            report["first_thread_opened"] = bool(thread_id)
            report["first_turn_status"] = _run_turn(
                first, session_one, "Reply with exactly: FIRST", "first")
        finally:
            first.close()
        report["thread_id_shape_ok"] = bool(thread_id)
        rollout = _find_rollout(codex_home, thread_id) if thread_id else None
        report["persisted_rollout_observed"] = rollout is not None
        if rollout:
            report["rollout_basename_only"] = Path(rollout).name

        # -- Run 2: a fresh process resumes exactly that thread.
        second = _connector(codex_exe, codex_home, workdir)
        try:
            resumed = second.start(owning_agent_id="core-resume-two",
                                   resume_thread_id=thread_id)
            state = second._sessions_by_id.get(resumed.session_id)
            report["resumed_thread_matches"] = (
                state.thread_id == thread_id if state else False)
            report["resume_turn_status"] = _run_turn(
                second, resumed, "Reply with exactly: RESUMED", "resumed")
            close_begin = time.monotonic()
            second.close()
            report["close_seconds"] = round(time.monotonic() - close_begin, 3)
        except Exception as exc:  # noqa: BLE001 - recorded honestly
            report["resume_error"] = f"{type(exc).__name__}: {exc}"[:300]
        finally:
            second.close()
        print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
