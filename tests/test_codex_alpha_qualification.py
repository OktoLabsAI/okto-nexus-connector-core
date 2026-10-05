import pytest
from nexus_connector_core.native.adapters import compatibility as c

IDENTITY = 'sha256:ae7e2bc6f390e2c8bb2258d0665c7c02e189bc2b414283b1e588a56ef20621a6'
FINGERPRINT = 'sha256:1722907aa64401bcc9b34467ef5c2af43f6aef9a5045ef04d11d19dfae4589fb'

@pytest.mark.parametrize('control', [False, True])
def test_alpha_qualification_is_exact(control):
    assert c.qualified_build('codex', '0.159.0-alpha.12.1', 'win32', 'x86_64', FINGERPRINT, control=control)
    assert c.qualified_build('codex', '0.159.0-alpha.12.1', 'win32', 'x86_64', 'moved', build_identity=IDENTITY, control=control)
    for version in ('0.159.0', '0.159.0-alpha.12.2', '0.159.3'):
        assert not c.qualified_build('codex', version, 'win32', 'x86_64', FINGERPRINT, build_identity=IDENTITY, control=control)
    assert not c.qualified_build('codex', '0.159.0-alpha.12.1', 'linux', 'x86_64', FINGERPRINT, build_identity=IDENTITY, control=control)
    assert not c.qualified_build('codex', '0.159.0-alpha.12.1', 'win32', 'x86_64', 'changed', build_identity='changed', control=control)
    assert c.CODEX_NATIVE_REQUEST_CONTRACTS['0.159.0-alpha.12.1'] == ('item/tool/requestUserInput',)
