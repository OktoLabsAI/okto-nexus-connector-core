"""Exact Windows build qualification earned by the real local campaign."""
import pytest
from nexus_connector_core.native.adapters import compatibility as c

FINGERPRINT = "sha256:0e2a4cd6ac1b329e64ec74745e38b71a3d4fa701102c86f49cf605d23a02c4df"
IDENTITY = "sha256:ac0413e2cd18e80561c8e1e50511f7e05465630dc16bf60656e04d7fff2e994c"


@pytest.mark.parametrize("control", [False, True])
@pytest.mark.parametrize("portable", [False, True])
def test_exact_build_grants_only_recorded_scope(control, portable):
    assert c.qualified_build("codex", "0.159.0", "win32", "x86_64",
        "sha256:" + "0" * 64 if portable else FINGERPRINT,
        build_identity=IDENTITY if portable else None, control=control)
    assert c.CODEX_NATIVE_REQUEST_CONTRACTS.get("0.159.0", ()) == ()


@pytest.mark.parametrize("field,value", [
    (0, "claude_code"), (1, "0.159.1"), (2, "linux"), (3, "aarch64"),
])
@pytest.mark.parametrize("control", [False, True])
def test_grant_does_not_cross_build_platform_or_adapter(field, value, control):
    key = ["codex", "0.159.0", "win32", "x86_64", FINGERPRINT]
    key[field] = value
    assert not c.qualified_build(*key, build_identity=IDENTITY, control=control)


@pytest.mark.parametrize("control", [False, True])
def test_version_alone_cannot_qualify_changed_bytes(control):
    assert not c.qualified_build("codex", "0.159.0", "win32", "x86_64",
        "sha256:" + "0" * 64, build_identity="sha256:" + "1" * 64,
        control=control)
