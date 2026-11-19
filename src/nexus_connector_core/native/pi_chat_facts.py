"""Bounded text observed after the reviewed Pi owner retained a message."""

import re


PI_CHAT_EVENT = "nexus_pi_chat_message"
_NATIVE_SESSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,159}\Z", re.ASCII)
_ENTRY_ID = re.compile(r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\Z|[a-f0-9]{8}\Z", re.ASCII)


def valid_pi_chat_fact(payload: dict) -> bool:
    if payload.keys() != {"revision", "native_session_id", "entry_id", "role", "text"}:
        return False
    session, entry, text = (payload[key] for key in ("native_session_id", "entry_id", "text"))
    if (type(payload["revision"]) is not int or payload["revision"] != 1
            or payload["role"] not in ("user", "assistant")
            or not isinstance(session, str) or _NATIVE_SESSION.fullmatch(session) is None
            or not isinstance(entry, str) or _ENTRY_ID.fullmatch(entry) is None):
        return False
    if text is None:
        return True
    if not isinstance(text, str) or not 0 < len(text) <= 12288:
        return False
    try:
        return len(text.encode("utf-8")) <= 12288
    except UnicodeEncodeError:
        return False
