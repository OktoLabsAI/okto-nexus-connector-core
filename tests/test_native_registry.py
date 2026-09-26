import sys

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.native import registry


def test_metadata_is_fixed_and_does_not_import_connectors(monkeypatch):
    calls = []
    monkeypatch.setattr(registry, "import_module",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    specs = registry.adapter_specs()
    assert {spec.adapter_id for spec in specs} == {
        "codex_app_server", "pi_rpc", "claude_stream", "claude_attach"}
    assert all(spec.module.startswith(".adapters.") for spec in specs)
    assert calls == []


def test_untrusted_adapter_and_module_path_never_reach_dynamic_import(monkeypatch):
    calls = []
    monkeypatch.setattr(registry, "import_module",
                        lambda *args, **kwargs: calls.append((args, kwargs)))
    for value in ("os", "../../os", "nexus_connector_core.native.adapters.pi",
                  "pi_rpc:evil", "", None):
        with pytest.raises(CoreError, match="CAPABILITY_UNSUPPORTED"):
            registry.load_adapter(value)
    assert calls == []


def test_platform_rejected_before_import_and_known_module_loaded_lazily(monkeypatch):
    calls = []

    class StubModule:
        class PiRpcConnector:
            pass

    def importer(module, *, package):
        calls.append((module, package))
        return StubModule

    monkeypatch.setattr(registry, "import_module", importer)
    with pytest.raises(CoreError, match="NATIVE_PLATFORM_UNSUPPORTED"):
        registry.load_adapter("claude_attach", platform="win32")
    assert calls == []
    assert registry.load_adapter("pi_rpc", platform=sys.platform) is StubModule.PiRpcConnector
    assert calls == [(".adapters.pi", "nexus_connector_core.native")]
    assert registry.adapter_spec("claude_attach", platform="freebsd14").mode == "attach"


def test_missing_fixed_adapter_class_is_typed_unqualified(monkeypatch):
    monkeypatch.setattr(registry, "import_module", lambda *args, **kwargs: object())
    with pytest.raises(CoreError, match="NATIVE_VERSION_UNQUALIFIED"):
        registry.load_adapter("pi_rpc", platform="linux")
