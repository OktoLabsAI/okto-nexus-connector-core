import re
from pathlib import Path


def test_publication_is_manual_separate_and_sha_pinned():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" /
                "core-release.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "pull_request:" not in workflow and "  push:" not in workflow
    assert "    environment: pypi\n" in workflow
    assert "if: ${{ inputs.publish && github.ref == 'refs/heads/main' }}" in workflow
    assert workflow.count("id-token: write") == 1
    assert "CORE_RELEASE_APPROVED_COMMIT" in workflow
    assert "CORE_RELEASE_APPROVED_VERSION" in workflow
    assert "CORE_LICENSE_REVIEWED_COMMIT" in workflow
    assert "python -m twine check --strict" in workflow
    assert "python tools/validate_release.py" in workflow
    assert "run: >-\n          python -m pip download --only-binary=:all:" in workflow
    assert "python tools/verify_offline_artifacts.py --wheelhouse build/offline-wheelhouse" in workflow
    uses = re.findall(r"^\s*uses:\s+(\S+)", workflow, flags=re.MULTILINE)
    assert uses and all(re.fullmatch(r"[\w-]+/[\w-]+@[0-9a-f]{40}", item)
                        for item in uses)


def test_ci_matrix_checks_offline_wheel_and_sdist():
    workflow = (Path(__file__).resolve().parents[1] / ".github" / "workflows" /
                "core-ci.yml").read_text(encoding="utf-8")
    assert "ubuntu-24.04, windows-2022" in workflow
    assert "'3.11', '3.12', '3.13'" in workflow
    assert "run: >-\n          python -m pip download --only-binary=:all:" in workflow
    assert "python tools/verify_offline_artifacts.py --wheelhouse build/offline-wheelhouse" in workflow
