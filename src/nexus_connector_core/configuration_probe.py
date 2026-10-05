"""Bounded CLI-help observation for an explicitly selected Claude installation."""
import subprocess
import threading
from pathlib import Path

from .discovery import selected_fingerprint, _PROBE_ENV
from .harness_configuration import discover_harness_configuration
from .models import CoreError
from .native.process import require_containment, spawn_owned_process, observe_owned_process


def probe_selected_configuration(candidate, *, cwd, env):
    """Observe help only. The host owns selection/authorization; no login is read.

    Codex and Pi use their existing authenticated RPC channels instead. This
    function does not start a conversational session or issue a model prompt.
    """
    require_containment()
    if candidate.adapter_id != 'claude_stream' or candidate.trust != 'selected':
        raise CoreError('BINDING_NOT_AUTHORIZED', 'configuration_discovery')
    if not Path(cwd).is_absolute() or not Path(cwd).is_dir():
        raise CoreError('WORKSPACE_UNAVAILABLE', 'configuration_discovery')
    if selected_fingerprint(candidate) != candidate.fingerprint:
        raise CoreError('PROFILE_DRIFT', 'configuration_discovery')
    proc = spawn_owned_process([candidate.executable, '--help'], cwd=str(cwd),
        env={k:v for k,v in env.items() if k.upper() in _PROBE_ENV},
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    captured = bytearray()
    overflow = threading.Event()
    def drain(stream, capture=False):
        while chunk := stream.read(4096):
            if capture:
                room = max(0, 131072 - len(captured))
                captured.extend(chunk[:room])
                if len(chunk) > room:
                    overflow.set()
    readers = [threading.Thread(target=drain, args=(proc.stdout,True), daemon=True),
               threading.Thread(target=drain, args=(proc.stderr,), daemon=True)]
    try:
        proc.stdin.close()
        for reader in readers:
            reader.start()
        code = proc.wait(timeout=5)
        if not observe_owned_process(proc)['stop_observed']:
            raise CoreError('CAPABILITY_UNSUPPORTED', 'configuration_discovery')
        for reader in readers:
            reader.join(timeout=1)
        if code != 0 or overflow.is_set() or any(r.is_alive() for r in readers):
            raise CoreError('CAPABILITY_UNSUPPORTED', 'configuration_discovery')
        if selected_fingerprint(candidate) != candidate.fingerprint:
            raise CoreError('PROFILE_DRIFT', 'configuration_discovery')
        return discover_harness_configuration(candidate.adapter_id, version=candidate.version,
            candidate_ref=candidate.installation_ref, cli_help=captured.decode('utf-8',errors='strict'))
    finally:
        if not observe_owned_process(proc)['stop_observed']:
            proc.kill()
            proc.wait(timeout=3)
        for reader in readers:
            if reader.ident is not None:
                reader.join(timeout=1)
        proc.stdout.close()
        proc.stderr.close()
