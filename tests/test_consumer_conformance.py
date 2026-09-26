import json
import subprocess
import sys
from importlib.resources import files

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.conformance import verify_contract_bundle
import nexus_connector_core.conformance as conformance


PIN = "sha256:a4fd84304de7ba12041721c07f4edce29d3f39d17d8bd24f375de24b0a728630"


def test_consumer_verifies_pinned_bundle_and_all_fixtures():
    report = verify_contract_bundle(PIN, allow_development_partial=True)
    assert report.manifest_sha256 == PIN
    assert report.status == "development-partial"
    assert report.checked_files == 9
    assert report.checked_frames >= 20
    assert report.checked_models > 0
    assert report.checked_vectors > 0


def test_partial_bundle_requires_explicit_opt_in_and_revision_pin():
    with pytest.raises(CoreError, match="CONTRACT_MISMATCH"):
        verify_contract_bundle(PIN)
    with pytest.raises(CoreError, match="CONTRACT_MISMATCH"):
        verify_contract_bundle("sha256:" + "0" * 64,
                               allow_development_partial=True)
    with pytest.raises(CoreError, match="CONTRACT_MISMATCH"):
        verify_contract_bundle(PIN, expected_revision="nxl-r1",
                               allow_development_partial=True)
    with pytest.raises(CoreError, match="CONTRACT_MISMATCH"):
        verify_contract_bundle(PIN, allow_development_partial="yes")


def test_offline_cli_returns_machine_readable_report():
    result = subprocess.run(
        [sys.executable, "-m", "nexus_connector_core.conformance",
         "--manifest-sha256", PIN, "--allow-development-partial"],
        capture_output=True, text=True, check=True)
    report = json.loads(result.stdout)
    assert report["manifest_sha256"] == PIN
    assert report["checked_files"] == 9
    denied = subprocess.run(
        [sys.executable, "-m", "nexus_connector_core.conformance",
         "--manifest-sha256", PIN], capture_output=True, text=True)
    assert denied.returncode == 1
    assert "CONTRACT_MISMATCH" in denied.stderr


def test_pinned_manifest_rejects_tampered_bundled_resource(tmp_path, monkeypatch):
    package = files("nexus_connector_core.contracts.nxl.v1")
    manifest = json.loads(package.joinpath("manifest.json").read_text(encoding="utf-8"))
    (tmp_path / "manifest.json").write_bytes(package.joinpath("manifest.json").read_bytes())
    for name in manifest["files"]:
        (tmp_path / name).write_bytes(package.joinpath(name).read_bytes())
    (tmp_path / "fixtures.json").write_bytes(
        (tmp_path / "fixtures.json").read_bytes() + b"\n")
    monkeypatch.setattr(conformance, "files", lambda _: tmp_path)
    with pytest.raises(CoreError, match="CONTRACT_MISMATCH"):
        verify_contract_bundle(PIN, allow_development_partial=True)
