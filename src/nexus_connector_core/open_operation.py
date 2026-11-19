"""Canonical local semantics shared by opening and its receipt projection."""

import hashlib

from .identifiers import is_codex_thread_id
from .models import CoreError, OpenOperation, Operation
from .native.claude_history_identity import claude_session_uuid


def open_operation_semantic(operation: OpenOperation) -> Operation:
    prepared = operation.prepared
    payload = {
        "adapter_id": prepared.intent.adapter_id,
        "profile_fingerprint": prepared.profile_fingerprint,
        "root_fingerprint": prepared.root_fingerprint,
        "stream_epoch": operation.stream_epoch,
    }
    thread_id = operation.resume_thread_id
    claude_id = operation.resume_claude_session_id
    if claude_id is not None:
        if thread_id is not None or claude_session_uuid(claude_id) is None:
            raise CoreError("VALIDATION_ERROR", "claude_resume", retry_safe=True)
        if prepared.intent.adapter_id != "claude_stream" or prepared.intent.mode != "managed":
            raise CoreError("CAPABILITY_UNSUPPORTED", "claude_resume", retry_safe=True)
        payload["resume_claude_session_sha256"] = hashlib.sha256(claude_id.encode("ascii")).hexdigest()
    if thread_id is not None:
        if not is_codex_thread_id(thread_id):
            raise CoreError("VALIDATION_ERROR", "codex_resume", retry_safe=True)
        if prepared.intent.adapter_id != "codex_app_server" or prepared.intent.mode != "managed":
            raise CoreError("CAPABILITY_UNSUPPORTED", "codex_resume", retry_safe=True)
        # Bind receipts to the target without storing the native identifier
        # in the canonical operation payload.
        payload["resume_thread_sha256"] = hashlib.sha256(thread_id.encode("ascii")).hexdigest()
    return Operation(operation.operation_id, operation.session_id, "runtime.open", payload)
