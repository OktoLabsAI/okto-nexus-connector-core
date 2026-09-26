"""Compatibility seam for extracted synchronous adapters.

The caller supplies the complete approved overlay; ambient secrets are never
inherited. New code should use :mod:`nexus_connector_core.environment`.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping

from .adapter_types import ErrorCode, NativeAdapterError
from ..pi_extension_resource import PiNativeActionLaunch

_ESSENTIALS = {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "PATH",
               "TEMP", "TMP", "LANG", "LC_ALL", "TERM"}
_MCP_TOKEN_NAME = re.compile(r"NEXUS_MCP_TOKEN_[0-9A-F]{16}\Z", re.ASCII)


def child_environment(overrides: Mapping[str, str] | None = None,
                      *, native_action: PiNativeActionLaunch | None = None) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items()
           if key.upper() in _ESSENTIALS}
    for key, value in (overrides or {}).items():
        if (("NEXUS" in key.upper() and not _MCP_TOKEN_NAME.fullmatch(key))
                or "nxs_" in value or "nxsept_" in value
                or "\x00" in key or "\x00" in value):
            raise NativeAdapterError(ErrorCode.PERMISSION_DENIED,
                                     "privileged environment value denied", {})
        env[key] = value
    if native_action is not None:
        if not isinstance(native_action, PiNativeActionLaunch):
            raise NativeAdapterError(ErrorCode.PERMISSION_DENIED,
                                     "untrusted native action launch", {})
        env["NEXUS_NATIVE_ACTION_PORT"] = str(native_action.port)
        env["NEXUS_NATIVE_CAPABILITY_REF"] = native_action.capability_ref
        env["NEXUS_NATIVE_SESSION_ID"] = native_action.session_id
    return env
