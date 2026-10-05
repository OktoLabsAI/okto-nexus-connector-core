"""Workspace mutations must not look like replacement of an approved root."""
import asyncio
import pytest

from nexus_connector_core import CoreError, InstallationCandidate, LaunchIntent
from nexus_connector_core.discovery import fingerprint
from nexus_connector_core.native import runtime_bridge
from nexus_connector_core.profiles import prepare_launch
from tests.test_c1_bridge_stubs import harness_session
from tests.test_native_runtime_bridge import context
from tests.regression.test_c5_audit import _pi_launch_fixture


@pytest.mark.parametrize('adapter', ['codex_app_server', 'claude_stream', 'pi_rpc'])
@pytest.mark.parametrize('mutation', ['create', 'rename', 'remove', 'replace_root',
                                    'missing_root', 'root_file', 'redirect_link', 'binary'])
def test_launch_checks_directory_identity_across_environment_wait(tmp_path, monkeypatch,
                                                                  adapter, mutation):
    root = tmp_path / 'workspace'
    root.mkdir()
    existing = root / 'existing.txt'
    existing.write_text('existing', encoding='utf-8')
    requested = root
    alternate = tmp_path / 'alternate'
    if mutation == 'redirect_link':
        alternate.mkdir()
        requested = tmp_path / 'workspace-link'
        try:
            requested.symlink_to(root, target_is_directory=True)
        except OSError:
            pytest.skip('Host does not allow directory symlink creation')
    if adapter == 'pi_rpc':
        node, _, _, _, candidate = _pi_launch_fixture(tmp_path)
        binary = node
    else:
        binary = tmp_path / 'harness.exe'
        binary.write_bytes(b'approved executable')
        candidate = InstallationCandidate(adapter, str(binary), fingerprint(binary),
                                           'explicit', 'selected', version='synthetic')
    prepared = prepare_launch(LaunchIntent('agent', 'ws', adapter), candidate, requested)
    started = []

    class Adapter:
        def __init__(self, **kwargs):
            pass

        def start(self, **kwargs):
            started.append(True)
            return harness_session()

        def close(self):
            pass

    monkeypatch.setattr(runtime_bridge, 'qualified_build', lambda *a, **k: True)
    monkeypatch.setattr(runtime_bridge, 'load_adapter', lambda _: Adapter)
    monkeypatch.setattr('nexus_connector_core.native.process.require_containment', lambda: None)

    async def run():
        entered, release = asyncio.Event(), asyncio.Event()

        async def environment(_):
            entered.set()
            await release.wait()
            return {}

        factory = runtime_bridge.CopiedAdapterFactory(environment)
        opening = asyncio.create_task(factory.open(prepared, 'session', context(), stream_epoch='epoch'))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            if mutation == 'create':
                (root / 'created.txt').write_text('new', encoding='utf-8')
            elif mutation == 'rename':
                existing.rename(root / 'renamed.txt')
            elif mutation == 'remove':
                existing.unlink()
            elif mutation in {'replace_root', 'missing_root', 'root_file'}:
                assert root.resolve().parent == tmp_path.resolve()
                root.rename(tmp_path / 'original-root')
                if mutation == 'replace_root':
                    root.mkdir()
                elif mutation == 'root_file':
                    root.write_text('not a directory', encoding='utf-8')
            elif mutation == 'redirect_link':
                requested.unlink()
                requested.symlink_to(alternate, target_is_directory=True)
            else:
                binary.write_bytes(b'replaced executable with different contents')
            release.set()
            if mutation in {'create', 'rename', 'remove'}:
                await asyncio.wait_for(opening, 5)
                assert started == [True]
            else:
                with pytest.raises(CoreError) as failure:
                    await asyncio.wait_for(opening, 5)
                assert failure.value.code == 'PROFILE_DRIFT'
                assert failure.value.retry_safe and not failure.value.possible_effect
                assert not started
        finally:
            release.set()
            if not opening.done():
                opening.cancel()
                await asyncio.gather(opening, return_exceptions=True)
            factory.close()

    asyncio.run(run())
