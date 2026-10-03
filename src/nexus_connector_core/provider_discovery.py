"""Host-local login directory hints. Never read credentials or grant trust."""
import os
from pathlib import Path


def discover_provider_home(adapter_id: str, *, environ=None, home=None) -> str | None:
    """Return an existing config directory, respecting the harness override.

    This is a UI suggestion only, deliberately outside the portable inventory:
    paths stay on the execution host and require explicit operator consent.
    """
    layouts = {
        'codex_app_server': ('CODEX_HOME', ('.codex',)),
        'claude_stream': ('CLAUDE_CONFIG_DIR', ('.claude',)),
        'pi_rpc': ('PI_CODING_AGENT_DIR', ('.pi', 'agent')),
    }
    if adapter_id not in layouts:
        return None
    env = os.environ if environ is None else environ
    name, suffix = layouts[adapter_id]
    try:
        base = Path.home() if home is None else Path(home)
        override = env.get(name)
        path = Path(override).expanduser() if override else base.joinpath(*suffix)
        if not path.is_absolute() or not path.is_dir():
            return None
        return str(path.resolve(strict=True))
    except (OSError, RuntimeError, ValueError):
        return None
