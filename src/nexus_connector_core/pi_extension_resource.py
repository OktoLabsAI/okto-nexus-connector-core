"""Locate the versioned, Core-owned Pi extension in an installed wheel."""

from importlib.resources import files
from dataclasses import dataclass
from pathlib import Path


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
