"""Send one admitted plain-text turn through the protected Claude terminal."""

import asyncio
import threading
import time

from ..models import CoreError, EffectNotSent

_WRITE_WINDOW = 10.0
_MAX_PASTE_BYTES = 64 * 1024 - len(b"\x1b[200~\x1b[201~\r")
_STAGE = "claude_terminal_submission"


class ClaudeTerminalSubmission:
    def __init__(self, terminal, prompt_gate):
        self._terminal = terminal
        self._gate = prompt_gate
        self._active_operation = None

    def active_turn(self):
        return self._active_operation is not None

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
        if not await verify():
            raise EffectNotSent("The durable Claude submission or its authority changed.", code="BINDING_NOT_AUTHORIZED")

        loop = asyncio.get_running_loop()
        deadline = time.monotonic() + _WRITE_WINDOW
        cancelled = threading.Event()

        def authorize_hook():
            if cancelled.is_set():
                return False
            future = asyncio.run_coroutine_threadsafe(verify(), loop)
            try:
                allowed = future.result(timeout=min(2.0, max(0, deadline - time.monotonic()))) is True
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
