"""Connection-scoped native-event redaction, adapted from Nexus.

Known child credentials are injected by the trusted host. Raw native text
fields never leave this boundary on output-delta events; safe normalized text
is delayed by a bounded holdback so secrets split across chunks are masked.
"""

from __future__ import annotations

from dataclasses import replace
import json
import re
from typing import Any, Iterable

from ..models import CoreError
from .adapter_types import HarnessEvent

_MASK = "[REDACTED]"
_TEXT_MASK = "[NATIVE_TEXT_REDACTED]"
_SENSITIVE_KEY = re.compile(
    r"(?:^|_)(?:authorization|api_key|apikey|access_token|refresh_token|"
    r"id_token|password|secret|session_secret|credential|token)(?:$|_)", re.I)
_SENSITIVE_ENV = re.compile(r"(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL|AUTH)", re.I)
_GENERIC_SECRET = re.compile(
    r"(?:nxs_|nxsept_)[A-Za-z0-9_-]+|\bsk-[A-Za-z0-9_-]{12,}|"
    r"\bBearer\s+[^\s\"']+", re.I)
_GENERIC_PREFIX = re.compile(r"(?:nxs_|nxsept_|\bsk-|\bBearer\s+)", re.I)
_TOKEN_END = re.compile(r"[\s\"']")
_MAX_PENDING = 16 * 1024
_MAX_STREAMS = 64
_MAX_NATIVE_EVENT_BYTES = 256 * 1024


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return bool(_SENSITIVE_KEY.search(key) or normalized.endswith((
        "authorization", "apikey", "accesstoken", "refreshtoken", "idtoken",
        "password", "secret", "credential", "token")))


def credential_values(environment: dict[str, str]) -> tuple[str, ...]:
    """Select only approved secret-looking child variables, never PATH/home."""
    return tuple(value for name, value in environment.items()
                 if _SENSITIVE_ENV.search(name) and isinstance(value, str) and value)


def _extract_output(event: HarnessEvent) -> str | None:
    if event.output_text is not None:
        return event.output_text
    if event.kind != "output_delta":
        return None
    payload = event.payload
    for value in (payload.get("delta"), payload.get("text"),
                  (payload.get("assistantMessageEvent") or {}).get("delta")
                  if isinstance(payload.get("assistantMessageEvent"), dict) else None):
        if isinstance(value, str):
            return value
    nested = payload.get("event")
    if isinstance(nested, dict):
        delta = nested.get("delta")
        if isinstance(delta, dict) and isinstance(delta.get("text"), str):
            return delta["text"]
    return None


class NativeSecretRedactor:
    version = 1

    def __init__(self, values: Iterable[str] = ()):
        selected = {value for value in values if isinstance(value, str) and value}
        if (len(selected) > 128 or any(len(value) > 16384 for value in selected)
                or sum(map(len, selected)) > 65536):
            raise CoreError("CAPACITY_EXCEEDED", "native_redaction")
        variants = set(selected)
        for value in selected:
            variants.update((json.dumps(value, ensure_ascii=False)[1:-1],
                             json.dumps(value, ensure_ascii=True)[1:-1],
                             repr(value)[1:-1]))
        self._known = (re.compile("|".join(re.escape(value) for value in
                             sorted(variants, key=len, reverse=True)))
                       if variants else None)
        self._holdback = max(8, max(map(len, variants), default=1) - 1)
        self._pending: dict[tuple[str, str | None, str | None], str] = {}

    def clean(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {self.clean(key): (_MASK if isinstance(key, str) and
                    _is_sensitive_key(key) else self.clean(item))
                    for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.clean(item) for item in value]
        if isinstance(value, str):
            if self._known is not None:
                value = self._known.sub(_MASK, value)
            return _GENERIC_SECRET.sub(_MASK, value)
        return value

    def _withhold_raw_text(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {key: self._withhold_raw_text(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self._withhold_raw_text(item) for item in value]
        if isinstance(value, str):
            return _TEXT_MASK
        return value

    def _split(self, text: str, *, final: bool) -> tuple[str, str]:
        if final:
            return self.clean(text), ""
        cut = max(0, len(text) - self._holdback)
        if self._known is not None:
            for match in self._known.finditer(text):
                if match.start() < cut < match.end():
                    cut = match.start()
                    break
        for match in _GENERIC_PREFIX.finditer(text):
            end = _TOKEN_END.search(text, match.end())
            if match.start() < cut and (end is None or end.start() >= cut):
                cut = match.start()
                break
        return self.clean(text[:cut]), text[cut:]

    def scrub(self, event: HarnessEvent) -> HarnessEvent:
        if len(json.dumps(event.payload, ensure_ascii=False, default=str).encode("utf-8")) > _MAX_NATIVE_EVENT_BYTES:
            raise CoreError("EVENT_TOO_LARGE", "native_redaction")
        payload = self.clean(event.payload)
        output = _extract_output(event)
        key = (event.session_id, event.thread_id, event.turn_id)
        final = event.delivery_phase == "terminal" or event.kind == "turn_completed"
        if event.kind == "output_delta":
            payload = self._withhold_raw_text(payload)
        if output is not None or final:
            pending = self._pending.pop(key, "")
            prior = "" if event.output_snapshot else pending
            if final and not prior and output is None:
                tails = [self._pending.pop(other) for other in tuple(self._pending)
                         if other[0] == event.session_id]
                prior = "".join(tails)
            output, tail = self._split(prior + (output or ""), final=final)
            if tail:
                if key not in self._pending and len(self._pending) >= _MAX_STREAMS:
                    raise CoreError("CAPACITY_EXCEEDED", "native_redaction")
                if len(tail) > _MAX_PENDING:
                    raise CoreError("CAPACITY_EXCEEDED", "native_redaction")
                self._pending[key] = tail
        return replace(event, payload=payload, output_text=output,
                       native_approval=self.clean(event.native_approval))
