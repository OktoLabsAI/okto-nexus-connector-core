"""Public guides must track exported names and fixed adapter IDs."""

import re
from pathlib import Path

import nexus_connector_core as core
from nexus_connector_core.native.registry import adapter_specs


ROOT = Path(__file__).resolve().parents[1]


def test_api_guide_covers_every_top_level_export() -> None:
    guide = (ROOT / "docs/api.md").read_text(encoding="utf-8")
    assert all(f"`{name}`" in guide for name in core.__all__)


def test_compatibility_and_migration_track_registry_and_revision() -> None:
    compatibility = (ROOT / "docs/compatibility.md").read_text(encoding="utf-8")
    adapters = (ROOT / "docs/adapters.md").read_text(encoding="utf-8")
    assert core.__version__ in compatibility
    assert core.CONTRACT_REVISION in compatibility
    for spec in adapter_specs():
        assert f"`{spec.adapter_id}`" in compatibility
        assert f"`{spec.adapter_id}`" in adapters


def test_public_local_links_resolve() -> None:
    for page in [ROOT / "README.md", *(ROOT / "docs").glob("*.md")]:
        text = page.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", text):
            if "://" not in target:
                assert (page.parent / target).is_file(), (page, target)
