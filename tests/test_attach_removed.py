import importlib.util
import pytest

import nexus_connector_core as core
from nexus_connector_core.native.registry import load_adapter


def test_attach_implementation_and_public_api_are_removed():
    assert not hasattr(core, 'AttachTarget')
    assert not hasattr(core, 'AttachPolicy')
    for module in ('attach_testing', 'native.adapters.claude_code_attach', 'native.adapters.windows_attach_pipe'):
        assert importlib.util.find_spec('nexus_connector_core.' + module) is None
    assert {d.adapter_id for d in core.get_runtime_catalog().runtimes} == {
        'codex_app_server', 'pi_rpc', 'claude_stream'}


@pytest.mark.parametrize('platform', ['win32', 'linux', 'darwin', 'freebsd'])
def test_old_attach_identifiers_never_load_a_native_adapter(platform):
    with pytest.raises(core.CoreError, match='CAPABILITY_UNSUPPORTED'):
        load_adapter('claude_attach', platform=platform)
