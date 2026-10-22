"""Terminal: one visible entry that starts the preferred installed terminal backend.

MakOS does not draw a terminal emulator. The backend keeps its own profile and colours;
MakOS never edits its configuration, so the backend is themed by GTK/Qt, not by MakOS CSS.
"""
from pathlib import Path
from .. import catalog


def working_directory(path):
    if not path:
        return None
    p = Path(str(path))
    if str(path).startswith('file://'):
        from urllib.parse import unquote, urlparse
        p = Path(unquote(urlparse(str(path)).path))
    p = p if p.is_dir() else p.parent
    return str(p) if p.is_dir() else None


def argv_for(which, path=None):
    """Argument list for the first available backend, or None when no terminal is installed."""
    argv = catalog.resolve(catalog.BY_ID['terminal'], which)
    if not argv:
        return None
    cwd = working_directory(path)
    if cwd:
        exe = argv[0]
        if exe == 'ptyxis':
            argv += ['--working-directory', cwd]
        elif exe == 'konsole':
            argv += ['--workdir', cwd]
    return argv
