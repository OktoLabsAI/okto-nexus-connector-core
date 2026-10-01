"""Classify structured provider authentication facts, never display text."""


def provider_failure_code(native):
    payload = native.payload
    if native.harness_kind == "claude_code" and native.native_event == "assistant":
        raw = payload.get("raw")
        if (isinstance(raw, dict) and raw.get("is_api_error_message") is True
                and raw.get("error") == "authentication_failed"):
            return "PROVIDER_AUTH_REQUIRED"
    if native.harness_kind == "codex" and native.native_event == "turn/completed":
        turn = payload.get("turn")
        error = turn.get("error") if isinstance(turn, dict) and turn.get("status") == "failed" else None
        if isinstance(error, dict) and error.get("codexErrorInfo") == "unauthorized":
            return "PROVIDER_AUTH_REQUIRED"
    return None
