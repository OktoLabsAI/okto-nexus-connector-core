"""The offline packaging gate fails before invoking pip on missing inputs."""

from pathlib import Path

import pytest

from tools.verify_offline_artifacts import verify


def test_offline_gate_requires_local_wheelhouse(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="wheelhouse"):
        verify(tmp_path, tmp_path / "absent")


def test_offline_gate_requires_matching_artifacts(tmp_path: Path) -> None:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    (wheelhouse / "dependency.whl").write_bytes(b"test")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nversion = "0.1.0.dev0"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="matching wheel and sdist"):
        verify(tmp_path, wheelhouse)
