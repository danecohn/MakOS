"""Files: the MakkOS file manager (browser, views, ops, preview, tags, search, network).

Importing this package is cheap and GTK-free; the window classes load on first use.

Public API
    Files(app, path=None)               the file-manager window (makos.apps launches it)
    preview(app, path)                  stand-alone Quick Look panel for one file
    open_uri(path)                      open a file with its default application (refuses programs)
    search                              module: ``from makos.files import search`` -> search.search(query, roots, ...)
                                        and search.search_async(...). This is the API Seek calls.
"""
import os

__all__ = ['Files', 'preview', 'open_uri', 'kind', 'entries', 'search', 'model', 'ops', 'tags', 'trash', 'archive']


def __getattr__(name):
    if name == 'Files':
        from .browser import Files
        return Files
    raise AttributeError(name)


def open_uri(path):
    """Open ``path`` with its default application. Raises on refusal or failure (callers show the message)."""
    from gi.repository import Gio
    from . import model
    from .browser import check_openable, launch_context
    p = os.path.abspath(os.fspath(path))
    check_openable(model.content_type(os.path.basename(p)), p)
    Gio.AppInfo.launch_default_for_uri(Gio.File.new_for_path(p).get_uri(), launch_context())


def preview(app, path):
    """Stand-alone Quick Look panel (used by the Preview launcher entry)."""
    from . import model
    from .quicklook import QuickLook
    ql = QuickLook(app)
    ql.show(model.stat_entry(path))
    return ql.win


def kind(path):
    """Icon name for a path (kept for older callers)."""
    from . import model
    return model.stat_entry(path).icon


def entries(path):
    """Visible children of a folder as Paths, folders first (kept for older callers)."""
    from pathlib import Path
    from . import model
    try:
        listing = model.sort_entries(list(model.list_local(path)))
    except model.FolderError:
        return []
    return [Path(e.path) for e in listing[:2000]]
