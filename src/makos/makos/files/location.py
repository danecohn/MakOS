"""Locations the Files window can show: folders, remote URIs and virtual lists (Recents, Trash, search, tags)."""
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Loc:
    kind: str                 # dir, remote, trash, recent, network, search, tag
    path: str = ''
    uri: str = ''
    label: str = ''
    arg: str = ''             # search query / tag name
    root: str = ''            # search root folder

    @staticmethod
    def dir(path):
        return Loc('dir', path=os.path.abspath(os.fspath(path)))

    @staticmethod
    def remote(uri):
        return Loc('remote', uri=uri)

    @property
    def virtual(self):
        return self.kind in ('trash', 'recent', 'search', 'tag')

    @property
    def local(self):
        return self.kind == 'dir'

    @property
    def title(self):
        if self.label:
            return self.label
        if self.kind == 'dir':
            home = os.path.expanduser('~')
            if self.path == home:
                return Path(home).name or 'Home'
            return os.path.basename(self.path.rstrip('/')) or 'Computer'
        if self.kind == 'remote':
            from urllib.parse import unquote, urlsplit
            p = urlsplit(self.uri)
            return unquote(os.path.basename(p.path.rstrip('/'))) or p.hostname or self.uri
        return {'trash': 'Trash', 'recent': 'Recents', 'network': 'Network', 'search': f'Search: {self.arg}',
                'tag': f'Tag: {self.arg}'}.get(self.kind, 'Files')

    @property
    def icon(self):
        if self.kind == 'dir':
            from .model import SPECIAL_DIRS
            home = os.path.expanduser('~')
            if self.path == home:
                return 'folder-home'
            if os.path.dirname(self.path) == home:
                return SPECIAL_DIRS.get(os.path.basename(self.path), 'folder')
            return 'folder'
        return {'trash': 'trash-full', 'recent': 'folder-recent', 'network': 'folder-network', 'remote': 'folder-network',
                'search': 'seek', 'tag': 'folder-tag'}.get(self.kind, 'folder')

    def parent(self):
        if self.kind == 'dir':
            p = os.path.dirname(self.path.rstrip('/'))
            return Loc.dir(p) if p and p != self.path else None
        if self.kind == 'remote':
            from gi.repository import Gio
            par = Gio.File.new_for_uri(self.uri).get_parent()
            return Loc.remote(par.get_uri()) if par is not None else Loc('network')
        if self.kind in ('search',) and self.root:
            return Loc.dir(self.root)
        return None

    def breadcrumbs(self):
        """[(label, Loc)] from the root to this location, for the path bar."""
        if self.kind == 'dir':
            parts = []
            home = os.path.expanduser('~')
            cur = self.path
            while True:
                parts.append((Loc.dir(cur).title if cur != '/' else 'Computer', Loc.dir(cur)))
                if cur == home or cur == '/':
                    break
                nxt = os.path.dirname(cur)
                if nxt == cur:
                    break
                cur = nxt
            parts.reverse()
            if parts and parts[0][1].path != '/' and parts[0][1].path != home:
                parts.insert(0, ('Computer', Loc.dir('/')))
            return parts
        if self.kind == 'remote':
            from urllib.parse import unquote, urlsplit
            p = urlsplit(self.uri)
            crumbs = [('Network', Loc('network')), (p.hostname or p.scheme, Loc.remote(f'{p.scheme}://{p.netloc}/'))]
            acc = f'{p.scheme}://{p.netloc}'
            for seg in [s for s in p.path.split('/') if s]:
                acc += '/' + seg
                crumbs.append((unquote(seg), Loc.remote(acc)))
            return crumbs
        return [(self.title, self)]
