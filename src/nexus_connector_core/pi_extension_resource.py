"""Locate the versioned, Core-owned Pi extension in an installed wheel."""

import sys
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path

from .discovery import fingerprint
from .models import CoreError, InstallationCandidate

_HOSTED_NODE_BUILD = "sha256:3331e1ffe19874215472217c5e94f5a0c6d8e18c4ac7111d3937aa0ad5e9b4a5"
_HOSTED_PI_BUILD = "sha256:caf8bfad84ea26a7c8eaee06e0cde3dd7e34ef05e00dbebc348dfb3f22de487b"


def reviewed_pi_renderer_build(version, platform, architecture, build_identity) -> bool:
    """Check the exact installation closure covered by the hosted renderer proof."""
    return (version, platform, architecture, build_identity) == ("0.87.1", "win32", "x86_64", _HOSTED_PI_BUILD)


def pi_hosted_rpc_path() -> Path:
    """Launch asset shipped alongside the trusted Pi extension."""
    return Path(str(files("nexus_connector_core").joinpath("pi_extension", "hosted_rpc.js"))).resolve(strict=True)


def qualify_pi_hosted_rpc(command: tuple[str, ...], candidate: InstallationCandidate) -> Path:
    """Only the selected Windows Node/Pi package pair may use the hosted path."""
    if (sys.platform != "win32" or candidate.version != "0.87.1" or candidate.architecture != "x86_64"
            or not candidate.build_identity or not candidate.launch_script
            or tuple(command[:4]) != (candidate.executable, candidate.launch_script, "--mode", "rpc")):
        raise CoreError("CAPABILITY_UNSUPPORTED", "pi_hosted_rpc", retry_safe=True)
    try:
        if fingerprint(Path(candidate.executable)) != _HOSTED_NODE_BUILD:
            raise CoreError("CAPABILITY_UNSUPPORTED", "pi_hosted_rpc", retry_safe=True)
        return pi_hosted_rpc_path()
    except OSError as exc:
        raise CoreError("CAPABILITY_UNSUPPORTED", "pi_hosted_rpc", retry_safe=True) from exc


def pi_extension_path() -> Path:
    """Path passed to Pi's ``--extension`` option; never fetched remotely."""
    path = Path(str(files("nexus_connector_core").joinpath("pi_extension", "index.js")))
    if not path.is_file():
        raise FileNotFoundError("Pi extension missing from installed Core artifact")
    return path


@dataclass(frozen=True, slots=True)
class PiNativeActionLaunch:
    """Trusted host-only Pi launch parameters; never model input."""

    port: int
    capability_ref: str
    session_id: str

    def __post_init__(self) -> None:
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise ValueError("invalid native action port")
        if (not isinstance(self.capability_ref, str) or
                not self.capability_ref.startswith("native-cap:") or
                len(self.capability_ref) > 256 or
                any(char in self.capability_ref for char in "\r\n\x00")):
            raise ValueError("invalid native action capability")
        if (not isinstance(self.session_id, str) or
                not 1 <= len(self.session_id) <= 160 or
                any(char in self.session_id for char in "\r\n\x00")):
            raise ValueError("invalid native action session")
