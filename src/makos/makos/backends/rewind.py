"""Rewind (backup) status. No backup, snapshot or restore job is created by MakkOS yet: this module only reports facts."""
from . import sysutil

TOOLS = [('timeshift', 'Timeshift'), ('snapper', 'Snapper'), ('restic', 'restic'), ('borg', 'BorgBackup'), ('deja-dup', 'Backups (Déjà Dup)')]


def status():
    found = [name for tool, name in TOOLS if sysutil.have(tool)]
    return {'implemented': False, 'tools': found,
            'message': 'VigilOS does not create or restore backups yet; no backup job exists. '
                       + ('Installed backup tools you can use yourself: ' + ', '.join(found) + '.' if found
                          else 'No backup tool was found on this computer.')}
