import sys
import gi
gi.require_version('Gtk','4.0')
from gi.repository import GLib
from .catalog import BY_ID
name=sys.argv[1] if len(sys.argv)>1 else 'files'
if name not in BY_ID:
    sys.exit('Unknown MakOS application')
# Wayland app_id: matches the desktop entry (makos-<id>) so the launcher can show the running dot.
GLib.set_prgname('makos-'+name)
from .apps import Applications
rest=sys.argv[2:]
# Flags such as --full are options for the app (Screenshot); everything else is a file or URI to open.
options=[a for a in rest if a.startswith('--')]
files=[a for a in rest if not a.startswith('--')]
app=Applications(name,options[0] if options else None)
sys.exit(app.run([sys.argv[0],*files]))
