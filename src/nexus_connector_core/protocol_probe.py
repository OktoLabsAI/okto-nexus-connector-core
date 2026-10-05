"""Bounded native startup checks without model work or provider credentials."""
from pathlib import Path
from tempfile import TemporaryDirectory

from .models import CoreError, LaunchIntent
from .profiles import prepare_launch, verify_prepared
from .native.registry import load_adapter
from .native.process import require_containment


def probe_selected_protocol(candidate, *, env):
    """Probe a selected installation in a disposable home before saving it."""
    require_containment()
    essentials = {'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT',
                  'TEMP', 'TMP', 'LANG', 'LC_ALL', 'TERM'}
    clean_env = {k: v for k, v in env.items() if k.upper() in essentials}
    with TemporaryDirectory(prefix='nexus-protocol-') as directory:
        root = Path(directory).resolve()
        clean_env.update(HOME=str(root), USERPROFILE=str(root),
                         CODEX_HOME=str(root / '.codex'), CLAUDE_CONFIG_DIR=str(root / '.claude'))
        prepared = prepare_launch(LaunchIntent('protocol-probe', 'protocol-probe', candidate.adapter_id), candidate, root)
        adapter = load_adapter(candidate.adapter_id)
        if candidate.adapter_id == 'claude_stream':
            connector = adapter(binary=prepared.argv[0], argv=prepared.argv[1:], cwd=str(root), env=clean_env)
        else:
            connector = adapter(command=prepared.argv, cwd=str(root), env=clean_env)
        connector._launch_guard = lambda stage: verify_prepared(prepared)
        try:
            connector.start(owning_agent_id='protocol-probe')
            if candidate.adapter_id == 'claude_stream':
                connector.verify_protocol()
            verify_prepared(prepared)
        except Exception as error:
            raise CoreError('NATIVE_PROTOCOL_INCOMPATIBLE', 'protocol_probe') from error
        finally:
            if connector.close() not in ('graceful', 'forced', 'already_closed'):
                raise CoreError('CONTAINMENT_UNCONFIRMED', 'protocol_probe', possible_effect=True)
    return {'adapter_id': candidate.adapter_id, 'protocol_verified': True}
