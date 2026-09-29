"""The public host discovery facade needs no runtime or provider process."""

from nexus_connector_core import discover_installations, get_runtime_catalog

from tests.regression.test_c11_audit import _LAB_BINARY, _binary_name


def test_public_passive_discovery_preserves_full_candidate(tmp_path):
    binary = tmp_path / _binary_name("codex")
    binary.write_bytes(_LAB_BINARY)
    binary.chmod(0o755)
    inventory = discover_installations(
        adapter_ids=("codex_app_server",),
        trusted_roots=(tmp_path,), path_env=str(tmp_path),
    )
    assert len(inventory.candidates) == 1
    candidate = inventory.candidates[0]
    assert candidate.executable == str(binary.resolve())
    assert candidate.installation_ref.startswith("nexus-install-v1:")
    assert candidate.build_identity.startswith("sha256:")


def test_default_discovery_uses_core_catalog_without_runtime(tmp_path):
    assert any(item.adapter_id == "codex_app_server" and item.discoverable
               for item in get_runtime_catalog().runtimes)
    assert discover_installations(path_env=str(tmp_path)).candidates == ()
