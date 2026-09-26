"""Durable, application-neutral ingestion of extracted adapter events.

The native adapter's replay buffer is transient. A caller may forward an
event only after this component has assigned and committed its NXL identity.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from ..journal import SQLiteJournal
from ..models import CoreError, RuntimeEvent
from ..protocol import canonical_json
from .adapter_types import HarnessEvent
from .redaction import NativeSecretRedactor

_CATEGORY = {
    "turn_started": "turn_state",
    "output_delta": "text_snapshot",
    "turn_completed": "turn_state",
    "tool_activity": "tool_activity",
    "error": "error",
}
_MAX_EVENT_BYTES = 256 * 1024


def translate_native_event(native: HarnessEvent, *, server_id: str,
                           executor_id: str, session_id: str,
                           stream_epoch: str,
                           native_session_id: str | None = None) -> RuntimeEvent:
    if native.session_id != (native_session_id or session_id):
        raise CoreError("EVENT_SESSION_MISMATCH", "event_ingest")
    category = _CATEGORY.get(native.kind, "native_unknown")
    if native.kind == "output_delta" and not native.output_snapshot:
        category = "text_delta"
    payload: dict[str, Any] = dict(native.payload)
    for name, value in (
        ("thread_id", native.thread_id),
        ("turn_id", native.turn_id),
        ("delivery_phase", native.delivery_phase),
        ("delivery_outcome", native.delivery_outcome),
        ("output_text", native.output_text),
        ("native_approval", native.native_approval),
    ):
        if value is not None:
            payload[name] = value
    if len(canonical_json(payload)) > _MAX_EVENT_BYTES:
        raise CoreError("EVENT_TOO_LARGE", "event_ingest")
    return RuntimeEvent(server_id, executor_id, session_id, stream_epoch, 0,
                        category, native.native_event, payload,
                        native.operation_id)


class NativeEventIngestor:
    def __init__(self, journal: SQLiteJournal, *, server_id: str,
                 executor_id: str, session_id: str, stream_epoch: str,
                 publish: Callable[[RuntimeEvent], Awaitable[None]] | None = None,
                 redactor: NativeSecretRedactor | None = None):
        if not all((server_id, executor_id, session_id, stream_epoch)):
            raise ValueError("event identity components must be nonempty")
        self._journal = journal
        self._server_id = server_id
        self._executor_id = executor_id
        self._session_id = session_id
        self._stream_epoch = stream_epoch
        self._publish = publish
        self._redactor = redactor or NativeSecretRedactor()

    async def ingest(self, native: HarnessEvent) -> RuntimeEvent:
        event = translate_native_event(self._redactor.scrub(native), server_id=self._server_id,
                                       executor_id=self._executor_id,
                                       session_id=self._session_id,
                                       stream_epoch=self._stream_epoch)
        durable = await self._journal.record_event(event)
        if self._publish is not None:
            await self._publish(durable)
        return durable
