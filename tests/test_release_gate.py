import importlib.util
import io
import tarfile
import zipfile
from pathlib import Path

import pytest


_SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "validate_release.py"
_SPEC = importlib.util.spec_from_file_location("validate_release", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)


def _release_fixture(root, *, version="1.2.3", long_description=True):
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "okto-nexus-connector-core"\nversion = "{version}"\n'
        'readme = "README.md"\nlicense = "LicenseRef-test"\n', encoding="utf-8")
    (root / "README.md").write_text("Core release", encoding="utf-8")
    (root / "LICENSE").write_text("Reviewed license fixture", encoding="utf-8")
    dist = root / "dist"
    dist.mkdir()
    wheel = dist / f"okto_nexus_connector_core-{version}-py3-none-any.whl"
    metadata = (
        f"Metadata-Version: 2.4\nName: okto-nexus-connector-core\nVersion: {version}\n"
        "License-Expression: LicenseRef-test\n"
        "Description-Content-Type: text/markdown\n\n" +
        ("Core release" if long_description else "")
    ).encode()
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(f"okto_nexus_connector_core-{version}.dist-info/METADATA", metadata)
        archive.writestr(f"okto_nexus_connector_core-{version}.dist-info/licenses/LICENSE",
                         (root / "LICENSE").read_bytes())
    sdist = dist / f"okto_nexus_connector_core-{version}.tar.gz"
    with tarfile.open(sdist, "w:gz") as archive:
        for name in ("LICENSE", "README.md"):
            data = (root / name).read_bytes()
            member = tarfile.TarInfo(f"okto_nexus_connector_core-{version}/{name}")
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    return wheel, sdist


def test_release_gate_validates_stable_metadata_and_exact_hashes(tmp_path):
    _release_fixture(tmp_path)
    report = _MODULE.validate(tmp_path, "1.2.3")
    assert report["publishable"] is True
    assert _MODULE.validate(
        tmp_path, "1.2.3", expected_wheel=report["wheel_sha256"],
        expected_sdist=report["sdist_sha256"]) == report
    with pytest.raises(ValueError, match="approved hash"):
        _MODULE.validate(tmp_path, "1.2.3", expected_wheel="0" * 64)


def test_release_gate_refuses_dev_publication_and_missing_description(tmp_path):
    _release_fixture(tmp_path, version="1.2.3.dev0")
    with pytest.raises(ValueError, match="stable version"):
        _MODULE.validate(tmp_path, "1.2.3.dev0")
    assert _MODULE.validate(tmp_path, "1.2.3.dev0",
                            allow_development=True)["publishable"] is False

    other = tmp_path / "other"
    other.mkdir()
    _release_fixture(other, long_description=False)
    with pytest.raises(ValueError, match="long description"):
        _MODULE.validate(other, "1.2.3")


def test_release_gate_refuses_extra_artifact_or_wrong_project_version(tmp_path):
    _release_fixture(tmp_path)
    with pytest.raises(ValueError, match="inconsistent"):
        _MODULE.validate(tmp_path, "1.2.4")
    (tmp_path / "dist" / "okto_nexus_connector_core-old-py3-none-any.whl").write_bytes(b"extra")
    with pytest.raises(ValueError, match="exactly"):
        _MODULE.validate(tmp_path, "1.2.3")
