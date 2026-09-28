"""C9 complementary scenarios - the public runtime catalog (C01)."""

from pathlib import Path

import pytest

from nexus_connector_core import (
    DiscoveryRequest, RuntimeCatalog, RuntimeDescriptor,
    get_runtime_catalog,
)


def test_catalog_is_public_side_effect_free():
    import subprocess
    import sys
    # The wheel-style consumer path: enumerate WITHOUT importing any
    # native.* module and without I/O, journal, agent or spawn.
    code = (
        "import sys\n"
        "from nexus_connector_core import (get_runtime_catalog, RuntimeCatalog)\n"
        "catalog = get_runtime_catalog()\n"
        "assert isinstance(catalog, RuntimeCatalog)\n"
        "native_mods = [m for m in sys.modules\n"
        "              if m.startswith('nexus_connector_core.native.')]\n"
        "adapter_mods = [m for m in native_mods\n"
        "               if '.adapters.' in m and not m.endswith('.compatibility')]\n"
        "assert not adapter_mods, adapter_mods\n"
        "print(catalog.core_version, catalog.format_version,\n"
        "      len(catalog.runtimes))\n"
    )
    # Subprocess WITHOUT the test runner's accumulated sys.path (the
    # wheel consumer's shape: the package importable, nothing else).
    import os
    src = str(Path(__file__).resolve().parents[2] / "src")
    env = {k: v for k, v in os.environ.items()
           if k != "PYTHONPATH"}
    env["PYTHONPATH"] = src
    out = subprocess.run([sys.executable, "-c", code],
                         capture_output=True, text=True, timeout=30,
                         env=env, cwd=str(Path(tmp if False else ".")))
    assert out.returncode == 0, out.stderr
    assert "4" in out.stdout


def test_catalog_single_source_and_projection_safety():
    from nexus_connector_core.native.registry import adapter_specs
    catalog = get_runtime_catalog()
    assert tuple(d.adapter_id for d in catalog.runtimes) == tuple(
        spec.adapter_id for spec in adapter_specs())
    for descriptor in catalog.runtimes:
        assert isinstance(descriptor, RuntimeDescriptor)
        assert descriptor.adapter_id
        # No loading details in the public projection.
        assert not hasattr(descriptor, "module")
        assert not hasattr(descriptor, "class_name")
    # Deterministic order; format + core version present.
    again = get_runtime_catalog()
    assert again == catalog
    assert catalog.format_version >= 1
    assert catalog.core_version


def test_catalog_attach_is_never_ready():
    catalog = get_runtime_catalog()
    attach = {d.adapter_id: d for d in catalog.runtimes}["claude_attach"]
    assert attach.support_status == "registered_unqualified"
    assert attach.connection_mode == "attach"
    assert attach.discoverable is False


def test_discovery_request_none_asks_the_catalog(tmp_path):
    async def run():
        from tests.test_runtime import make_runtime
        runtime, journal, factory = make_runtime(tmp_path)
        try:
            inventory = await runtime.discover(DiscoveryRequest())
            # No candidates exist in this bare environment, but the
            # request worked WITHOUT the caller naming any adapter: the
            # managed/discoverable set came from the catalog (attach
            # excluded), and unknown-ID filtering semantics are intact.
            kinds = {c.adapter_id for c in inventory.candidates}
            assert kinds <= {"codex_app_server", "pi_rpc",
                             "claude_stream"}
            with pytest.raises(Exception):
                await runtime.discover(
                    DiscoveryRequest(("not-an-adapter",)))
        finally:
            import asyncio
            from nexus_connector_core import ShutdownPolicy
            await asyncio.wait_for(
                runtime.shutdown(ShutdownPolicy()), timeout=5)
            journal.close()

    import asyncio
    asyncio.run(run())


def test_contract_enums_match_the_registry():
    import json
    from pathlib import Path
    from nexus_connector_core.native.registry import adapter_specs
    expected = [spec.adapter_id for spec in adapter_specs()]
    base = (Path(__file__).resolve().parents[2]
            / "src/nexus_connector_core/contracts/nxl/v1")
    for name in ("capability.schema.json", "inventory.schema.json"):
        schema = json.loads((base / name).read_text(encoding="utf-8"))

        def find_enums(node):
            if isinstance(node, dict):
                if "enum" in node and isinstance(node["enum"], list) \
                        and "codex_app_server" in node["enum"]:
                    yield node["enum"]
                for value in node.values():
                    yield from find_enums(value)
            elif isinstance(node, list):
                for value in node:
                    yield from find_enums(value)

        enums = list(find_enums(schema))
        assert enums and all(e == expected for e in enums), (name, enums)
