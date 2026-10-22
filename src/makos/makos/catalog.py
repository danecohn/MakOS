"""A single visible entry per role. Backend executables keep their upstream identities."""
from dataclasses import dataclass

@dataclass(frozen=True)
class App:
    id: str
    name: str
    icon: str
    command: tuple = ()
    internal: bool = False

APPS = [
    App('files', 'Files', 'files', internal=True),
    App('chatgpt', 'ChatGPT', 'chatgpt', ('chatgpt',)),
    App('claude', 'Claude', 'claude', ('claude-desktop',)),
    App('venture', 'Venture', 'browser', ('amerika-venture', 'firefox', 'chromium')),
    App('paper', 'Paper', 'file-document', ('libreoffice --writer',)),
    App('digits', 'Digits', 'file-spreadsheet', ('libreoffice --calc',)),
    App('slides', 'Slides', 'file-presentation', ('libreoffice --impress',)),
    App('makbox', 'MakBox', 'music', ('makos-studio-app makbox',)),
    App('render', 'Render', 'photos', ('makos-studio-app render',)),
    App('engine', 'Engine', 'desktops', ('makos-studio-app engine',)),
    App('sprite', 'Sprite', 'preview', ('makos-studio-app sprite',)),
    App('studio', 'Studio', 'widgets', ('makos-studio-app studio',)),
    App('terminal', 'Terminal', 'terminal', ('ptyxis --new-window', 'konsole --separate', 'xterm')),
    App('text-editor', 'Text Editor', 'text-editor', internal=True),
    App('calculator', 'Calculator', 'calculator', internal=True),
    App('preview', 'Preview', 'preview', internal=True),
    App('notes', 'Notes', 'notes', internal=True),
    App('calendar', 'Calendar', 'calendar', internal=True),
    App('activity', 'Activity', 'activity', internal=True),
    App('disk-utility', 'Disks', 'disk-utility', internal=True),
    App('system-info', 'System Information', 'system-info', internal=True),
    App('settings', 'Settings', 'settings', internal=True),
    App('seek', 'Seek', 'seek', internal=True),
    App('spread', 'Spread', 'spread', internal=True),
    App('desktops', 'Desks', 'desktops', internal=True),
    App('widgets', 'Widgets', 'widgets', internal=True),
    App('trash-empty', 'Trash', 'trash-empty', internal=True),
]
BY_ID = {a.id: a for a in APPS}


def resolve(app, which):
    import shlex
    for candidate in app.command:
        argv = shlex.split(candidate)
        if which(argv[0]):
            return argv
    return None
