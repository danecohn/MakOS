"""Files engine tests: temp directories only; trash runs in an isolated HOME subprocess."""
import io
import os
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/makos'))
ISOLATED = os.environ.get('MAKOS_FILES_ISOLATED') == '1'


class TmpCase(unittest.TestCase):
    def setUp(self):
        base = os.environ.get('HOME') if ISOLATED else None
        self._tmp = tempfile.TemporaryDirectory(dir=base)
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def write(self, rel, text='x'):
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p


class ModelTests(TmpCase):
    def test_listing_sort_and_kinds(self):
        from makos.files import model
        self.write('b.txt', 'bb')
        self.write('a10.txt')
        self.write('a2.txt')
        self.write('.hidden')
        (self.tmp / 'Folder').mkdir()
        entries = list(model.list_local(self.tmp))
        self.assertEqual({e.name for e in entries}, {'b.txt', 'a10.txt', 'a2.txt', 'Folder'})
        names = [e.name for e in model.sort_entries(entries)]
        self.assertEqual(names, ['Folder', 'a2.txt', 'a10.txt', 'b.txt'], 'natural order, folders first')
        names = [e.name for e in model.sort_entries(entries, 'size', reverse=True, folders_first=False)]
        self.assertEqual(names[0], 'b.txt')
        self.assertEqual(len(list(model.list_local(self.tmp, show_hidden=True))), 5)
        folder = next(e for e in entries if e.name == 'Folder')
        self.assertTrue(folder.is_dir)
        self.assertEqual(folder.icon, 'folder')

    def test_icons_by_type(self):
        from makos.files import model
        for name, icon in [('a.png', 'file-image'), ('a.mp3', 'file-audio'), ('a.mp4', 'file-video'), ('a.pdf', 'file-pdf'),
                           ('a.zip', 'file-archive'), ('a.py', 'file-code'), ('a.txt', 'file-text'), ('a.ods', 'file-spreadsheet'),
                           ('a.odt', 'file-document'), ('a.odp', 'file-presentation'), ('a.xyz123', 'file-generic')]:
            with self.subTest(name=name):
                mime = model.content_type(name)
                self.assertEqual(model.icon_for(mime, False, name), icon, mime)

    def test_symlinks_never_followed_and_broken_links_handled(self):
        from makos.files import model
        (self.tmp / 'real').mkdir()
        self.write('real/inner.txt')
        os.symlink(self.tmp, self.tmp / 'real' / 'loop')       # loop back to the parent
        os.symlink(self.tmp / 'nowhere', self.tmp / 'dangling')
        os.symlink(self.tmp / 'real', self.tmp / 'alias')
        entries = {e.name: e for e in model.list_local(self.tmp)}
        self.assertTrue(entries['dangling'].broken_link)
        self.assertEqual(entries['dangling'].kind, 'Broken alias')
        self.assertTrue(entries['alias'].is_dir and entries['alias'].is_symlink)
        self.assertFalse(entries['alias'].expandable, 'symlinked folders never expand')
        total, files, folders, complete = model.folder_size(self.tmp)
        self.assertTrue(complete)
        self.assertEqual(folders, 1, 'link loop is not traversed')

    def test_permission_errors_have_human_messages(self):
        from makos.files import model
        d = self.tmp / 'locked'
        d.mkdir()
        d.chmod(0)
        self.addCleanup(d.chmod, 0o700)
        if os.access(d, os.R_OK):
            self.skipTest('running with privileges that ignore permissions')
        with self.assertRaises(model.FolderError) as ctx:
            list(model.list_local(d))
        self.assertIn('permission', str(ctx.exception))
        with self.assertRaises(model.FolderError) as ctx:
            list(model.list_local(self.tmp / 'missing'))
        self.assertIn('no longer exists', str(ctx.exception))

    def test_large_directory_lists_quickly(self):
        from makos.files import model
        for i in range(20000):
            os.close(os.open(self.tmp / f'f{i:05d}.txt', os.O_CREAT | os.O_WRONLY))
        start = time.monotonic()
        entries = list(model.list_local(self.tmp))
        ordered = model.sort_entries(entries)
        elapsed = time.monotonic() - start
        self.assertEqual(len(ordered), 20000)
        self.assertLess(elapsed, 8, 'a 20k folder must list and sort in seconds, off the main thread')

    def test_names_and_formatting(self):
        from makos.files import model
        self.assertEqual(model.split_name('a.tar.gz'), ('a', '.tar.gz'))
        self.assertEqual(model.split_name('.bashrc'), ('.bashrc', ''))
        self.write('doc.txt')
        self.assertEqual(model.unique_name(self.tmp, 'doc.txt'), 'doc copy.txt')
        self.write('doc copy.txt')
        self.assertEqual(model.unique_name(self.tmp, 'doc.txt'), 'doc copy 2.txt')
        for bad in ('', '  ', '.', '..', 'a/b', 'a\0b', 'x' * 300):
            self.assertIsNotNone(model.valid_name(bad), repr(bad))
        self.assertIsNone(model.valid_name('Résumé 1.txt'))
        self.assertEqual(model.human_size(999), '999 bytes')
        self.assertEqual(model.human_size(1500), '1.5 KB')
        self.assertEqual(model.human_size(1), '1 byte')


class TagTests(TmpCase):
    def store(self):
        from makos.files import tags
        return tags.Store(tags.Sidecar(self.tmp / 'sidecar.json'), self.tmp / 'index.json')

    def test_tags_roundtrip_in_xattr_and_index(self):
        s = self.store()
        f = self.write('a.txt')
        s.set_tags(f, ['Red', 'Project X', 'red', 'a,b'])
        self.assertEqual(s.get_tags(f), ['Red', 'Project X', 'a b'])
        self.assertEqual(s.paths_for('red'), [str(f)])
        s.remove_tag(f, 'RED')
        self.assertEqual(s.get_tags(f), ['Project X', 'a b'])
        self.assertEqual(s.paths_for('Red'), [])
        s.set_comment(f, 'Hello — “comment”')
        self.assertEqual(s.get_comment(f), 'Hello — “comment”')
        self.assertIn('Project X', s.known_tags())

    def test_toggle_for_many_and_sidecar_fallback(self):
        from makos.files import tags
        s = self.store()
        a, b = self.write('a'), self.write('b')
        s.add_tag(a, 'Blue')
        self.assertTrue(s.toggle_tag([a, b], 'Blue'))       # not all had it -> add
        self.assertEqual(s.get_tags(b), ['Blue'])
        self.assertFalse(s.toggle_tag([a, b], 'Blue'))      # all had it -> remove
        self.assertEqual(s.get_tags(a), [])
        s.sidecar.set(tags.TAG_ATTR, a, 'Green')
        self.assertEqual(s.sidecar.get(tags.TAG_ATTR, a), 'Green')
        self.assertEqual(tags.colour_of('green'), tags.COLOURS['Green'])


class ArchiveTests(TmpCase):
    def test_zip_and_tar_roundtrip_preserves_content_and_mode(self):
        from makos.files import archive
        self.write('src/a.txt', 'alpha')
        self.write('src/sub/b.txt', 'beta')
        (self.tmp / 'src/run.sh').write_text('#!/bin/sh\n')
        (self.tmp / 'src/run.sh').chmod(0o755)
        os.symlink('a.txt', self.tmp / 'src/link')
        for fmt in archive.FORMATS:
            with self.subTest(fmt=fmt):
                out = archive.compress([str(self.tmp / 'src')], str(self.tmp / ('out' + archive.SUFFIX[fmt])), fmt)
                entries, total, trunc = archive.list_archive(out)
                names = {e[0].rstrip('/') for e in entries}
                self.assertIn('src/sub/b.txt', names)
                dest = archive.extract(out, str(self.tmp / ('x' + fmt)))
                self.assertEqual((Path(dest) / 'sub/b.txt').read_text(), 'beta', 'single top folder is unwrapped')
                self.assertTrue(os.access(Path(dest) / 'run.sh', os.X_OK))
                self.assertTrue((Path(dest) / 'link').is_symlink())

    def test_malicious_zip_is_rejected_without_writing_outside(self):
        from makos.files import archive
        evil = self.tmp / 'evil.zip'
        with zipfile.ZipFile(evil, 'w') as zf:
            zf.writestr('ok.txt', 'fine')
            zf.writestr('../escape.txt', 'bad')
        with self.assertRaises(archive.ArchiveError):
            archive.extract(str(evil), str(self.tmp / 'out'))
        self.assertFalse((self.tmp / 'escape.txt').exists())
        self.assertFalse((self.tmp / 'out').exists(), 'nothing is left behind after rejection')
        self.assertEqual([p.name for p in self.tmp.iterdir() if 'makos-part' in p.name], [])

    def test_symlink_escape_and_absolute_paths(self):
        from makos.files import archive
        evil = self.tmp / 'evil.zip'
        with zipfile.ZipFile(evil, 'w') as zf:
            zi = zipfile.ZipInfo('lnk')
            zi.external_attr = (stat.S_IFLNK | 0o777) << 16
            zf.writestr(zi, '/etc')
            zf.writestr('lnk/passwd', 'x')
        dest = archive.extract(str(evil), str(self.tmp / 'o1'))
        self.assertFalse((Path(dest) / 'lnk').is_symlink(), 'absolute symlink is dropped, so nothing is written through it')
        self.assertFalse(os.path.exists('/etc/passwd.makos-test'))
        tar = self.tmp / 'evil.tar'
        with tarfile.open(tar, 'w') as tf:
            info = tarfile.TarInfo('/abs.txt')
            info.size = 1
            tf.addfile(info, io.BytesIO(b'x'))
        with self.assertRaises(archive.ArchiveError):
            archive.extract(str(tar), str(self.tmp / 'o2'))
        tar2 = self.tmp / 'link.tar'
        with tarfile.open(tar2, 'w') as tf:
            info = tarfile.TarInfo('out')
            info.type = tarfile.SYMTYPE
            info.linkname = '../../etc'
            tf.addfile(info)
            info = tarfile.TarInfo('good.txt')
            info.size = 2
            tf.addfile(info, io.BytesIO(b'ok'))
        dest = archive.extract(str(tar2), str(self.tmp / 'o3'))
        self.assertTrue((Path(dest) / 'good.txt').exists())
        self.assertFalse((Path(dest) / 'out').exists(), 'escaping symlink is dropped')

    def test_cancel_removes_partial_output(self):
        from makos.files import archive, model
        self.write('big/a.txt', 'a' * 1000)
        out = archive.compress([str(self.tmp / 'big')], str(self.tmp / 'big.zip'))
        with self.assertRaises(model.Cancelled):
            archive.extract(out, str(self.tmp / 'dest'), cancel=lambda: True)
        self.assertFalse((self.tmp / 'dest').exists())
        with self.assertRaises(model.Cancelled):
            archive.compress([str(self.tmp / 'big')], str(self.tmp / 'c.zip'), cancel=lambda: True)
        self.assertFalse((self.tmp / 'c.zip').exists())
        self.assertFalse((self.tmp / 'c.zip.part').exists())


class SearchTests(TmpCase):
    def test_search_scores_bounds_and_symlinks(self):
        from makos.files import search
        self.write('Documents/Report 2026.txt', 'quarterly numbers')
        self.write('Documents/notes.md', 'the Report is elsewhere\nsecond line')
        self.write('Documents/.hidden/report-secret.txt')
        self.write('Other/report.txt')
        os.symlink(self.tmp / 'Other', self.tmp / 'Documents/linkdir')
        hits = search.search('report', [self.tmp])
        names = [h.name for h in hits]
        self.assertIn('Report 2026.txt', names)
        self.assertIn('report.txt', names)
        self.assertNotIn('report-secret.txt', names, 'hidden folders are not searched')
        self.assertEqual(len([h for h in hits if h.name == 'report.txt']), 1, 'symlinked folders are not followed')
        content = search.search('second line', [self.tmp], contents=True)
        self.assertEqual([h.name for h in content], ['notes.md'])
        self.assertEqual(len(search.search('report', [self.tmp], limit=1)), 1)
        self.assertEqual(search.search('r', [self.tmp]), [], 'one-letter queries are refused')
        kind = search.search('report', [self.tmp], kinds={'folder'})
        self.assertEqual(kind, [])

    def test_async_search_and_cancel(self):
        from makos.files import search
        self.write('a/findme.txt')
        got, done = [], []
        handle = search.search_async('findme', lambda hit: got.append(hit), lambda: done.append(1), roots=[self.tmp])
        handle.join(5)
        self.assertEqual([h.name for h in got], ['findme.txt'])
        self.assertTrue(done)
        handle = search.search_async('findme', lambda hit: None, None, roots=[self.tmp])
        handle.cancel()
        handle.join(5)


class ShortcutTests(unittest.TestCase):
    def test_primary_and_super_mirror(self):
        import gi
        gi.require_version('Gdk', '4.0')
        from gi.repository import Gdk
        from makos.files import shortcuts
        C, S = Gdk.ModifierType.CONTROL_MASK, Gdk.ModifierType.SUPER_MASK
        for mod in (C, S):
            self.assertEqual(shortcuts.resolve(Gdk.KEY_c, mod), 'copy')
            self.assertEqual(shortcuts.resolve(Gdk.KEY_v, mod), 'paste')
            self.assertEqual(shortcuts.resolve(Gdk.KEY_x, mod), 'cut')
            self.assertEqual(shortcuts.resolve(Gdk.KEY_BackSpace, mod), 'trash')
            self.assertEqual(shortcuts.resolve(Gdk.KEY_i, mod), 'info')
            self.assertEqual(shortcuts.resolve(Gdk.KEY_Down, mod), 'open')
            self.assertEqual(shortcuts.resolve(Gdk.KEY_Up, mod), 'parent')
        self.assertEqual(shortcuts.resolve(Gdk.KEY_space, Gdk.ModifierType(0)), 'quicklook')
        self.assertEqual(shortcuts.resolve(Gdk.KEY_z, C | Gdk.ModifierType.SHIFT_MASK), 'redo')
        self.assertEqual(shortcuts.resolve(Gdk.KEY_z, C), 'undo')
        self.assertEqual(shortcuts.resolve(Gdk.KEY_n, C | Gdk.ModifierType.SHIFT_MASK), 'new-folder')
        self.assertEqual(shortcuts.resolve(Gdk.KEY_Delete, Gdk.ModifierType.SHIFT_MASK), 'delete')
        self.assertIsNone(shortcuts.resolve(Gdk.KEY_c, C | Gdk.ModifierType.ALT_MASK))
        self.assertIsNone(shortcuts.resolve(Gdk.KEY_q, Gdk.ModifierType(0)))


@unittest.skipUnless(ISOLATED, 'runs in the isolated subprocess below')
class OpsCases(TmpCase):
    def engine(self, policy=None):
        from makos.files import ops
        asked = []

        def ask(job, src, dst):
            asked.append((ops.display(src), ops.display(dst)))
            return (policy or ops.KEEP_BOTH), False
        eng = ops.Engine(ask=ask, sync=True)
        eng.asked = asked
        return eng

    def test_copy_move_duplicate_rename_new_folder_with_undo(self):
        eng = self.engine()
        src = self.write('a/one.txt', '1')
        (self.tmp / 'dest').mkdir()
        job = eng.copy([src], self.tmp / 'dest')
        self.assertEqual(job.state, 'done')
        self.assertEqual((self.tmp / 'dest/one.txt').read_text(), '1')
        self.assertTrue(src.exists())
        job = eng.duplicate([src])
        self.assertTrue((self.tmp / 'a/one copy.txt').exists())
        eng.undo()
        self.assertFalse((self.tmp / 'a/one copy.txt').exists())
        eng.redo()
        self.assertTrue((self.tmp / 'a/one copy.txt').exists(), 'redo restores the duplicate')
        job = eng.move([src], self.tmp / 'dest', policy='keep')
        self.assertEqual(sorted(p.name for p in (self.tmp / 'dest').iterdir()), ['one copy.txt', 'one.txt'])
        eng.undo()
        self.assertTrue(src.exists(), 'undo move puts the file back')
        job = eng.rename(src, 'renamed.txt')
        self.assertEqual(job.state, 'done')
        self.assertTrue((self.tmp / 'a/renamed.txt').exists())
        job = eng.rename(self.tmp / 'a/renamed.txt', 'one copy.txt')
        self.assertEqual(job.state, 'failed', 'rename never overwrites')
        self.assertIn('already exists', job.errors[0])
        job = eng.new_folder(self.tmp / 'a')
        self.assertTrue((self.tmp / 'a/untitled folder').is_dir())
        job = eng.new_folder(self.tmp / 'a')
        self.assertTrue((self.tmp / 'a/untitled folder 2').is_dir())
        self.assertEqual(eng.rename(self.tmp / 'a/renamed.txt', 'bad/name').state, 'failed')

    def test_conflicts_replace_keep_skip(self):
        from makos.files import ops
        a = self.write('src/f.txt', 'new')
        self.write('dst/f.txt', 'old')
        eng = self.engine(ops.SKIP)
        eng.copy([a], self.tmp / 'dst')
        self.assertEqual((self.tmp / 'dst/f.txt').read_text(), 'old')
        self.assertEqual(eng.asked, [('f.txt', 'f.txt')])
        eng = self.engine(ops.KEEP_BOTH)
        eng.copy([a], self.tmp / 'dst')
        self.assertEqual((self.tmp / 'dst/f copy.txt').read_text(), 'new')
        self.assertEqual((self.tmp / 'dst/f.txt').read_text(), 'old')
        eng = self.engine(ops.REPLACE)
        job = eng.copy([a], self.tmp / 'dst')
        self.assertEqual((self.tmp / 'dst/f.txt').read_text(), 'new')
        eng.undo()
        self.assertEqual((self.tmp / 'dst/f.txt').read_text(), 'old', 'undo of Replace brings the old file back from the Trash')

    def test_replace_policy_apply_to_all(self):
        from makos.files import ops
        a, b = self.write('src/a.txt', 'A'), self.write('src/b.txt', 'B')
        self.write('dst/a.txt', 'oa')
        self.write('dst/b.txt', 'ob')
        calls = []
        eng = ops.Engine(ask=lambda j, s, d: (calls.append(1), (ops.REPLACE, True))[1], sync=True)
        eng.copy([a, b], self.tmp / 'dst')
        self.assertEqual(len(calls), 1, 'apply to all asks once')
        self.assertEqual((self.tmp / 'dst/b.txt').read_text(), 'B')

    def test_folder_copy_move_and_into_itself(self):
        eng = self.engine()
        self.write('tree/x/y/z.txt', 'deep')
        os.symlink('x', self.tmp / 'tree/ln')
        (self.tmp / 'out').mkdir()
        job = eng.copy([self.tmp / 'tree'], self.tmp / 'out')
        self.assertEqual((self.tmp / 'out/tree/x/y/z.txt').read_text(), 'deep')
        self.assertTrue((self.tmp / 'out/tree/ln').is_symlink(), 'symlinks are copied as links')
        job = eng.copy([self.tmp / 'tree'], self.tmp / 'tree/x')
        self.assertTrue(job.errors and 'into itself' in job.errors[0])
        self.assertFalse((self.tmp / 'tree/x/tree').exists())
        job = eng.move([self.tmp / 'tree'], self.tmp / 'tree')
        self.assertTrue(job.errors)
        job = eng.move([self.tmp / 'out/tree'], self.tmp)
        self.assertEqual(job.state, 'done')
        self.assertTrue((self.tmp / 'tree copy/x/y/z.txt').is_file(), 'keep-both naming')

    def test_trash_restore_undo_and_empty(self):
        from makos.files import trash
        eng = self.engine()
        f = self.write('docs/gone.txt', 'bye')
        d = self.write('docs/folder/inner.txt', 'in').parent
        job = eng.trash([f, d])
        self.assertEqual(job.state, 'done', job.errors)
        self.assertFalse(f.exists() or d.exists())
        items = {t.name: t for t in trash.list_trash()}
        self.assertIn('gone.txt', items)
        self.assertEqual(items['gone.txt'].orig, str(f))
        eng.undo()
        self.assertEqual(f.read_text(), 'bye')
        self.assertTrue((d / 'inner.txt').exists())
        eng.redo()
        self.assertFalse(f.exists())
        self.assertFalse(trash.is_empty())
        # "Put Back" from the Trash view, with the original name already taken
        self.write('docs/gone.txt', 'new occupant')
        item = [t for t in trash.list_trash() if t.name == 'gone.txt'][0]
        job = eng.restore([item])
        self.assertEqual(f.read_text(), 'new occupant')
        self.assertEqual(len(job.results), 1)
        self.assertTrue(os.path.exists(job.results[0]) and job.results[0] != str(f))
        job = eng.empty_trash()
        self.assertEqual(job.state, 'done')
        self.assertTrue(trash.is_empty())

    def test_permanent_delete_never_follows_links(self):
        eng = self.engine()
        outside = self.write('outside/keep.txt', 'keep')
        self.write('victim/a.txt')
        os.symlink(self.tmp / 'outside', self.tmp / 'victim/link')
        job = eng.delete([self.tmp / 'victim'])
        self.assertEqual(job.state, 'done')
        self.assertFalse((self.tmp / 'victim').exists())
        self.assertTrue(outside.exists(), 'symlink target must survive')

    def test_cancel_stops_job_and_reports(self):
        from makos.files import ops
        for i in range(30):
            self.write(f'big/f{i}.txt', 'x' * 100)
        eng = ops.Engine(sync=True)
        job = ops.Job('copy', [self.tmp / 'big'], self.tmp)
        job.cancel()
        eng.submit(job, lambda j: ops._transfer(eng, j, False))
        self.assertEqual(job.state, 'cancelled')
        self.assertFalse((self.tmp / 'big copy').exists() and len(list((self.tmp / 'big copy').iterdir())) == 30)

    def test_compress_extract_jobs_with_undo(self):
        eng = self.engine()
        self.write('pack/one.txt', '1')
        self.write('pack/two.txt', '2')
        job = eng.compress([self.tmp / 'pack'], self.tmp)
        self.assertEqual(job.state, 'done', job.errors)
        archive_path = Path(job.results[0])
        self.assertEqual(archive_path.name, 'pack.zip')
        job = eng.extract(archive_path)
        self.assertEqual(job.state, 'done', job.errors)
        self.assertEqual(Path(job.results[0]).name, 'pack 2')
        self.assertEqual((Path(job.results[0]) / 'one.txt').read_text(), '1')
        eng.undo()
        self.assertFalse(Path(job.results[0]).exists())

    def test_unreadable_source_reports_and_continues(self):
        eng = self.engine()
        good = self.write('src/good.txt', 'ok')
        bad = self.write('src/bad.txt', 'no')
        bad.chmod(0)
        self.addCleanup(bad.chmod, 0o600)
        (self.tmp / 'dst').mkdir()
        job = eng.copy([bad, good], self.tmp / 'dst')
        if os.access(bad, os.R_OK):
            self.skipTest('privileged user ignores permissions')
        self.assertEqual((self.tmp / 'dst/good.txt').read_text(), 'ok')
        self.assertTrue(any('permission' in e for e in job.errors), job.errors)

    def test_missing_source_is_reported(self):
        eng = self.engine()
        (self.tmp / 'dst').mkdir()
        job = eng.copy([self.tmp / 'ghost.txt'], self.tmp / 'dst')
        self.assertEqual(job.done_items, 0)


class OpsIsolated(unittest.TestCase):
    def test_ops_in_isolated_home(self):
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, MAKOS_FILES_ISOLATED='1', HOME=home, XDG_DATA_HOME=home + '/data',
                       XDG_CONFIG_HOME=home + '/config', XDG_STATE_HOME=home + '/state', XDG_CACHE_HOME=home + '/cache',
                       PYTHONPATH=str(ROOT / 'src/makos'))
            os.makedirs(home + '/data')
            proc = subprocess.run([sys.executable, '-m', 'unittest', 'tests.test_makos_files.OpsCases', '-q'],
                                  cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
            self.assertEqual(proc.returncode, 0, proc.stderr[-4000:])


if __name__ == '__main__':
    unittest.main()
