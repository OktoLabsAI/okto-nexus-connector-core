"""Bounded chat facts from the reviewed owned Claude terminal."""

from dataclasses import dataclass, field

from .claude_history_identity import claude_session_uuid


CLAUDE_CHAT_EVENT = "nexus_claude_chat_message"
MAX_CLAUDE_CHAT_BYTES = 12 * 1024


@dataclass(frozen=True, slots=True)
class ClaudeChatTurn:
    """Private correlation from an accepted prompt to its corroborated Stop."""

    prompt_id: str = field(repr=False)
    prompt_digest: bytes = field(repr=False)
    output_sha256: str = field(repr=False)
    admitted_ms: int


def valid_claude_chat_fact(value: object) -> bool:
    if not isinstance(value, dict) or value.keys() != {"revision", "native_session_id", "entry_id", "role", "text"}:
        return False
    if (type(value["revision"]) is not int or value["revision"] != 1
            or claude_session_uuid(value["native_session_id"]) is None
            or claude_session_uuid(value["entry_id"]) is None
            or value["role"] not in ("user", "assistant")):
        return False
    text = value["text"]
    if text is None:
        return True
    if not isinstance(text, str) or not 0 < len(text) <= MAX_CLAUDE_CHAT_BYTES:
        return False
    try:
        return len(text.encode("utf-8")) <= MAX_CLAUDE_CHAT_BYTES
    except UnicodeEncodeError:
        return False
