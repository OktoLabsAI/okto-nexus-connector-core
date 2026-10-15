"""Host-local launch realization and drift detection."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .discovery import selected_fingerprint
from .models import CoreError, InstallationCandidate, LaunchIntent, PreparedLaunch
from .protocol import canonical_json
from .harness_configuration import harness_settings_dict, validate_harness_settings


def _root_fingerprint(root: Path) -> str:
    info = root.stat()
    return f"{root}|{info.st_dev}|{info.st_ino}"


def prepare_launch(intent: LaunchIntent, candidate: InstallationCandidate,
                   workspace_root: str | Path) -> PreparedLaunch:
    if intent.adapter_id != candidate.adapter_id or candidate.trust != "selected":
        raise CoreError("BINDING_NOT_AUTHORIZED", "prepare")
    from .native.registry import registered_managed_contract
    registered = registered_managed_contract(intent.adapter_id)
    if intent.adapter_id not in {"codex_app_server", "pi_rpc", "claude_stream"} and registered is None:
        raise CoreError("CAPABILITY_UNSUPPORTED", "prepare")
    settings = harness_settings_dict(intent.harness_settings)
    validate_harness_settings(intent.adapter_id, settings)
    from .mcp_presets import validate_mcp_preset
    preset = validate_mcp_preset(list(intent.mcp_preset))
    if intent.model is not None and (
            type(intent.model) is not str or not intent.model or
            len(intent.model) > 200):
        raise CoreError("VALIDATION_ERROR", "prepare")
    if intent.mode == "attach":
        # External-session attach was removed. Refuse historical requests
        # before any launch or process access.
        raise CoreError("CAPABILITY_UNSUPPORTED", "prepare",
                        retry_safe=True)
    if intent.mode != "managed":
        raise CoreError("CAPABILITY_UNSUPPORTED", "prepare")
    root = Path(workspace_root)
    if not root.is_absolute():
        raise CoreError("WORKSPACE_UNAVAILABLE", "prepare")
    try:
        resolved = root.resolve(strict=True)
        if not resolved.is_dir():
            raise OSError("workspace is not a directory")
    except OSError as exc:
        raise CoreError("WORKSPACE_UNAVAILABLE", "prepare") from exc
    executable = Path(candidate.executable)
    if selected_fingerprint(candidate) != candidate.fingerprint:
        raise CoreError("PROFILE_DRIFT", "prepare")
    if candidate.build_identity is not None:
        from .build_identity import (executable_build_identity,
                                     pi_build_identity)
        if candidate.launch_script is not None and candidate.adapter_id == "pi_rpc":
            # C2/R06: recompute against the pi-coding-agent PACKAGE root
            # (parents[2]), consistent with the identity computed at
            # selection time.
            current_identity = pi_build_identity(
                candidate.executable, Path(candidate.launch_script).parents[2])
        else:
            current_identity = executable_build_identity(candidate.executable)
        if current_identity != candidate.build_identity:
            raise CoreError("PROFILE_DRIFT", "prepare")
    if registered is not None:
        if intent.model is not None:
            raise CoreError('CAPABILITY_UNSUPPORTED', 'prepare')
        argv = (str(executable), *registered.launch_arguments)
    elif intent.adapter_id == "codex_app_server":
        argv = (str(executable), "app-server")
    elif intent.adapter_id == "pi_rpc":
        argv = ((str(executable), candidate.launch_script, "--mode", "rpc")
                if candidate.launch_script is not None else
                (str(executable), "--mode", "rpc"))
        if intent.model is not None:
            argv += ("--model", intent.model)
        if intent.harness_settings.provider is not None:
            argv += ("--provider", intent.harness_settings.provider)
        if intent.harness_settings.effort is not None:
            argv += ("--thinking", intent.harness_settings.effort)
    elif intent.adapter_id == "claude_stream":
        # Mirrors the copied connector's own qualified default argv: the
        # partial-message flag is load-bearing for interrupt safety and
        # --verbose is part of the proven stream-json shape. An explicit
        # model rides the documented CLI flag - never shell text.
        argv = (str(executable), "-p", "--output-format", "stream-json",
                "--input-format", "stream-json", "--verbose",
                "--include-partial-messages")
        if intent.model is not None:
            argv += ("--model", intent.model)
        if intent.harness_settings.effort is not None:
            argv += ("--effort", intent.harness_settings.effort)
        if intent.harness_settings.permission_mode is not None:
            argv += ("--permission-mode", intent.harness_settings.permission_mode)
    else:
        raise CoreError("CAPABILITY_UNSUPPORTED", "prepare")
    profile = {"adapter_id": intent.adapter_id, "mode": intent.mode,
               "model": intent.model, "auth_refs": list(intent.auth_refs),
               "argv": list(argv), "root": str(resolved)}
    if settings:
        profile['harness_settings'] = settings
    if preset:
        profile['mcp_preset'] = preset
    digest = "sha256:" + hashlib.sha256(canonical_json(profile)).hexdigest()
    return PreparedLaunch(intent, candidate, argv, str(resolved), str(root),
                          _root_fingerprint(resolved), digest, intent.auth_refs)


def verify_prepared(prepared: PreparedLaunch) -> None:
    root = Path(prepared.requested_root)
    executable = Path(prepared.candidate.executable)
    try:
        if (_root_fingerprint(root.resolve(strict=True)) != prepared.root_fingerprint
                or selected_fingerprint(prepared.candidate) != prepared.candidate.fingerprint):
            raise CoreError("PROFILE_DRIFT", "open")
    except OSError as exc:
        raise CoreError("PROFILE_DRIFT", "open") from exc
