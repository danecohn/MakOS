"""Switch for "Amerika Agent can use these tools": registers / removes the amerika-studio MCP server in the agent's config."""
import shutil
import subprocess

from . import common
from .common import StudioError


def set_agent_tools(enabled, paths=None):
    """Persist the choice in the Studio settings and, when Amerika Agent is installed, in its settings, then regenerate its
    OpenClaw config. Returns a short human message."""
    s = common.load_settings(paths)
    s['agent_tools'] = bool(enabled)
    common.save_settings(s, paths)
    try:
        from amerika_agent import common as acommon, config as aconfig
    except ImportError:
        return 'Saved. Amerika Agent is not installed; the tools will be offered once it is.'
    try:
        apaths = acommon.Paths()
        a = aconfig.load_settings(apaths)
        a['studio_tools'] = bool(enabled)
        aconfig.save_settings(apaths, a)
    except Exception as e:  # noqa: BLE001 - the Studio setting is already saved; tell the user what failed
        raise StudioError(f'Saved, but Amerika Agent settings could not be updated: {e}', 'agent_settings')
    exe = shutil.which('amerika-agent')
    if exe:
        r = subprocess.run([exe, 'config', 'apply'], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise StudioError('Saved, but "amerika-agent config apply" failed: ' + (r.stderr or r.stdout).strip()[:200], 'agent_apply')
    return 'Amerika Agent can now use the Studio tools.' if enabled else 'Amerika Agent can no longer use the Studio tools.'
