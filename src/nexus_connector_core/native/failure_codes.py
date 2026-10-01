"""Classify structured facts and the qualified Pi preflight error format."""
import re


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
        info = error.get("codexErrorInfo") if isinstance(error, dict) else None
        if info == "unauthorized":
            return "PROVIDER_AUTH_REQUIRED"
        if isinstance(info, dict) and len(info) == 1:
            for variant in ("httpConnectionFailed", "responseStreamConnectionFailed", "responseStreamDisconnected"):
                detail = info.get(variant)
                if (isinstance(detail, dict) and type(detail.get("httpStatusCode")) is int
                        and detail["httpStatusCode"] == 401):
                    return "PROVIDER_AUTH_REQUIRED"
    return None


def pi_prompt_failure_code(response):
    # Pi 0.87.1 auth-guidance.js emits this fixed preflight format. This is
    # called only for a correlated negative prompt response, never model text.
    error = response.get("error")
    if isinstance(error, str) and re.match(
            r"No API key found for (?:[A-Za-z0-9_.:-]{1,128}|the selected model)\.\n\n"
            r"Use /login to log into a provider via OAuth or API key\. See:\n", error):
        return "PROVIDER_AUTH_REQUIRED"
    return "NATIVE_OPERATION_FAILED"
