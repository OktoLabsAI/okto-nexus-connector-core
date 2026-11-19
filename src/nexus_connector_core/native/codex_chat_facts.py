"""Bounded transcript fragments from the owned Codex event stream."""

import re


CODEX_CHAT_DELTA = "nexus_codex_chat_delta"
MAX_CODEX_CHAT_BYTES = 4096
_NATIVE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,159}", re.ASCII)


def is_codex_chat_id(value: object) -> bool:
    return isinstance(value, str) and _NATIVE_ID.fullmatch(value) is not None


def valid_codex_chat_delta(value: object) -> bool:
    if not isinstance(value, dict) or value.keys() != {"revision", "thread_id", "item_id", "text", "truncated"}:
        return False
    text = value["text"]
    if (type(value["revision"]) is not int or value["revision"] != 1
            or not is_codex_chat_id(value["thread_id"]) or not is_codex_chat_id(value["item_id"])
            or type(value["truncated"]) is not bool
            or not isinstance(text, str) or not 0 < len(text) <= MAX_CODEX_CHAT_BYTES):
        return False
    try:
        return len(text.encode("utf-8")) <= MAX_CODEX_CHAT_BYTES
    except UnicodeEncodeError:
        return False
