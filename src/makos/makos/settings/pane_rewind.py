"""Rewind: honest backup status. No backup job is created by MakkOS yet."""
from ..backends import rewind
from . import widgets as W


def build(col, ctx):
    s = W.section(col, 'Backups')

    def render(box, st):
        W.note(box, st['message'])
        W.note(box, 'Rewind will only be offered once creating and restoring a snapshot can be tested end to end.')
    W.loading(s, rewind.status, render)
