"""Seek: calculator, conversions, providers, the FTS5 fallback index (exclusions, inotify), LocalSearch, Quick Look hook."""
import os
import socket
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src/makos'))
sys.path.insert(0, str(ROOT / 'tests'))
from fakesys import FakeSystem, Result  # noqa: E402
from makos.backends import sysutil  # noqa: E402
from makos.seek import engine, index, providers, units  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'home'
        self.home.mkdir()
        self.env = mock.patch.dict(os.environ, {'HOME': str(self.home), 'XDG_DATA_HOME': str(self.home / '.local/share')})
        self.env.start()
        self.fake = FakeSystem()
        sysutil.set_runner(self.fake, self.fake.which)

    def tearDown(self):
        providers._probe.update(at=0.0, ok=False)
        sysutil.set_runner(None)
        self.env.stop()
        self.tmp.cleanup()

    def make(self, rel, text='x'):
        p = self.home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p


class CalcTests(unittest.TestCase):
    def test_calculator_is_safe(self):
        self.assertEqual(units.calculate('(15 + 5) * 3 / 2'), '30')
        self.assertEqual(units.calculate('2^3 × 2'), '16')
        for text in ['__import__("os").system("true")', '(1).__class__', '2**999999', '9**9**9', '[1]*100', '(1+2j)', 'True', '1/0', '1e200', 'abs(-1)', 'x']:
            with self.subTest(text=text), self.assertRaises((ValueError, SyntaxError, ZeroDivisionError, OverflowError)):
                units.calculate(text)

    def test_conversions_across_dimensions(self):
        cases = {'1 mi to km': '1.609344 km', '5 ft in cm': '152.4 cm', '2 kg to g': '2000 g', '2 lb to kg': '0.90718474 kg', '1 gal to l': '3.785411784 l',
                 '100 f to c': '37.77777778 c', '0 c to k': '273.15 k', '-40 c to f': '-40 f', '60 mph to km/h': '96.56064 km/h',
                 '10 km/h to m/s': '2.777777778 m/s', '1 gib to mb': '1073.741824 mb', '3 gb to mb': '3000 mb', '5 min to s': '300 s'}
        for text, want in cases.items():
            self.assertEqual(units.convert(text), want, text)
        for text in ('1 m to kg', '5 c to m', 'hello', '1 usd to eur', '10 euros in dollars', '-300 c to k'):
            self.assertIsNone(units.convert(text), text)

    def test_is_expression(self):
        self.assertTrue(units.is_expression('2+2'))
        self.assertFalse(units.is_expression('report 2'))
        self.assertFalse(units.is_expression('-5'))


class ProviderTests(Base):
    def test_apps_and_panes(self):
        self.assertEqual(providers.applications('term')[0].title, 'Terminal')
        self.assertEqual(providers.applications('term')[0].action, ('launch', 'terminal'))
        for forbidden in ('Konsole', 'Ptyxis', 'Amerika'):
            self.assertFalse(providers.applications(forbidden))
        panes = providers.settings_panes('night shift')
        self.assertEqual(panes[0].title, 'Displays')
        self.assertEqual(panes[0].action, ('pane', 'displays'))
        self.assertEqual(providers.settings_panes('wi-fi')[0].title, 'Network')
        self.assertEqual(providers.settings_panes('x'), [])

    def test_web_shortcut_builds_a_quoted_url_and_never_fetches(self):
        with mock.patch.object(socket, 'socket', side_effect=AssertionError('network used')):
            r = providers.web('a&b c=d', 'duckduckgo')[0]
            self.assertEqual(r.action, ('url', 'https://duckduckgo.com/?q=a%26b+c%3Dd'))
            self.assertEqual(providers.web('x', 'duckduckgo'), [])
            self.assertIn('wikipedia', providers.web('cats', 'wikipedia')[0].action[1])
            self.assertIn('duckduckgo', providers.web('cats', 'evil')[0].action[1])
            engine.Engine(self.home, settings={}).fast('2+2')
            engine.Engine(self.home, settings={}).slow('report')

    def test_vcard_parsing_and_contacts(self):
        text = ('BEGIN:VCARD\r\nVERSION:3.0\r\nFN:Ada Lovelace\r\nORG:Analytical Engines;Research\r\nEMAIL;TYPE=work:ada@example.com\r\n'
                'TEL:+44 20 7946 0000\r\nNOTE:folded\r\n line\r\nEND:VCARD\r\nBEGIN:VCARD\r\nN:Babbage;Charles;;;\r\nEMAIL:cb@example.com\r\nEND:VCARD\r\n')
        people = providers.parse_vcard(text)
        self.assertEqual([p['name'] for p in people], ['Ada Lovelace', 'Charles Babbage'])
        self.assertEqual(people[0]['emails'], ['ada@example.com'])
        found = providers.contacts('lovelace', people)
        self.assertEqual(found[0].group, 'Contacts')
        self.assertEqual(found[0].action, ('copy', 'ada@example.com'))
        self.assertEqual(providers.contacts('a', people), [])

    def test_contacts_from_vcard_folder_and_evolution_database_read_only(self):
        self.make('.local/share/contacts/ada.vcf', 'BEGIN:VCARD\nFN:Ada Folder\nEND:VCARD\n')
        db = self.home / '.local/share/evolution/addressbook/system/contacts.db'
        db.parent.mkdir(parents=True)
        con = sqlite3.connect(db)
        con.execute('create table folder_contacts(uid text, vcard text)')
        con.execute('insert into folder_contacts values(?,?)', ('1', 'BEGIN:VCARD\nFN:Grace Hopper\nEND:VCARD\n'))
        con.commit()
        con.close()
        names = [p['name'] for p in providers.load_contacts(self.home)]
        self.assertEqual(sorted(names), ['Ada Folder', 'Grace Hopper'])
        self.assertEqual(providers.load_contacts(self.home / 'nowhere'), [])

    def test_dictionary_is_offline_and_honest_when_absent(self):
        self.fake.tools -= {'wn', 'dict'}
        self.assertIsNone(providers.dictionary_backend())
        self.assertEqual(providers.dictionary('define serendipity'), [])
        self.fake.tools.add('wn')
        self.fake.do_wn = lambda a, env: '\nOverview of noun serendipity\n\n1. serendipity -- (good luck in making unexpected finds)\n'
        r = providers.dictionary('define serendipity')[0]
        self.assertEqual((r.group, r.title), ('Dictionary', 'serendipity'))
        self.assertIn('good luck', r.subtitle)
        self.assertEqual(self.fake.ran('wn')[-1], ['wn', 'serendipity', '-over'])  # never a shell string
        self.assertEqual(providers.dictionary('define x; rm -rf'), [])
        self.assertEqual(providers.dictionary('two words here'), [])

    def test_recent_files(self):
        f = self.make('Documents/plan.txt')
        hidden = self.make('.ssh/id_rsa')
        xbel = self.home / 'recent.xbel'
        xbel.write_text(f'<?xml version="1.0"?><xbel version="1.0"><bookmark href="file://{f}" modified="2026-10-22T10:00:00Z"/>'
                        f'<bookmark href="file://{hidden}" modified="2026-10-22T11:00:00Z"/><bookmark href="https://example.com/x"/>'
                        f'<bookmark href="file:///nonexistent/gone.txt"/></xbel>')
        with mock.patch.object(Path, 'home', return_value=self.home):
            got = providers.recent_files('', xbel=xbel)
            self.assertEqual([r.title for r in got], ['plan.txt'])
            self.assertEqual(providers.recent_files('zzz', xbel=xbel), [])
        self.assertEqual(providers.recent_files('', xbel=self.home / 'missing.xbel'), [])


class IndexTests(Base):
    def make_tree(self):
        self.make('Documents/Report final.txt', 'quarterly budget numbers')
        self.make('Documents/sub/notes.md', '# Budget plan')
        self.make('Documents/.hidden/secret.txt', 'budget')
        self.make('Documents/id_rsa', 'KEY budget')
        self.make('Documents/server.pem', 'budget')
        self.make('Documents/.env', 'budget=1')
        self.make('Desktop/todo.txt', 'buy milk and budget')
        self.make('Music/song budget.mp3', '')
        self.make('Elsewhere/budget.txt', 'not a root')
        for secret in ('.ssh/config', '.gnupg/key', '.claude/history', '.codex/auth', '.openclaw/x', '.mozilla/firefox/places.sqlite', '.config/chromium/Default/Login Data',
                       'snap/firefox/common/.mozilla/x'):
            self.make(secret, 'budget')
        ix = index.Index(self.home / 'ix.sqlite')
        self.addCleanup(ix.close)
        return ix

    def test_only_safe_user_files_are_indexed(self):
        ix = self.make_tree()
        ix.scan(index.default_roots(self.home), home=self.home)
        names = sorted(r['name'] for r in ix.search('budget'))
        self.assertEqual(names, ['Report final.txt', 'notes.md', 'song budget.mp3', 'todo.txt'])
        paths = ' '.join(r[0] for r in ix.db.execute('select path from files'))
        for bad in ('.ssh', '.gnupg', '.claude', '.codex', '.openclaw', '.mozilla', 'chromium', 'id_rsa', '.pem', '.env', '.hidden', 'Elsewhere'):
            self.assertNotIn(bad, paths)

    def test_secret_directories_are_excluded_even_when_used_as_a_root(self):
        ix = self.make_tree()
        ix.scan([self.home / '.ssh', self.home / '.claude', self.home / '.codex', self.home / '.openclaw', self.home / '.gnupg', self.home / '.mozilla'], home=self.home)
        self.assertEqual(ix.count(), 0)
        for rel in ('.ssh', '.gnupg', '.claude', '.codex', '.openclaw', '.mozilla/firefox', '.config/google-chrome/Default', 'snap/firefox/common'):
            self.assertTrue(index.is_excluded(self.home / rel, self.home), rel)
        self.assertFalse(index.is_excluded(self.home / 'Documents/a.txt', self.home))

    def test_symlinks_and_user_exclusions(self):
        ix = self.make_tree()
        (self.home / 'Documents/link').symlink_to(self.home / '.ssh', target_is_directory=True)
        (self.home / 'Documents/filelink.txt').symlink_to(self.home / '.ssh/config')
        ix.scan(index.default_roots(self.home), home=self.home, exclusions=[str(self.home / 'Desktop')])
        names = [r['name'] for r in ix.search('budget')]
        self.assertNotIn('config', names)
        self.assertNotIn('filelink.txt', names)
        self.assertNotIn('todo.txt', names)  # user exclusion
        self.assertIn('notes.md', names)

    def test_search_is_prefix_name_first_and_injection_safe(self):
        ix = self.make_tree()
        ix.scan(index.default_roots(self.home), home=self.home)
        self.assertEqual(ix.search('rep fin')[0]['name'], 'Report final.txt')
        self.assertEqual(ix.search('quart')[0]['name'], 'Report final.txt')
        for nasty in ('"', 'budget"', 'NEAR(a b)', 'a OR', '*', "x' ; drop table files; --", '(', 'name:budget', ''):
            ix.search(nasty)  # must not raise
        self.assertEqual(ix.count(), 4)
        self.assertEqual(index.fts_query('a "b" (c)'), '"a"* "b"* "c"*')
        self.assertIsNone(index.fts_query('!!!'))

    def test_rescan_removes_vanished_files_and_updates_changes(self):
        ix = self.make_tree()
        ix.scan(index.default_roots(self.home), home=self.home)
        (self.home / 'Documents/Report final.txt').unlink()
        self.make('Documents/new thing.txt', 'brand new')
        changed = ix.scan(index.default_roots(self.home), home=self.home)
        self.assertGreaterEqual(changed, 2)
        self.assertEqual(ix.search('quarterly'), [])
        self.assertEqual(ix.search('brand')[0]['name'], 'new thing.txt')

    def test_watcher_follows_changes_with_inotify(self):
        self.make('Documents/seed.txt', 'seed')
        ix = index.Index(self.home / 'ix.sqlite')
        self.addCleanup(ix.close)
        ix.scan(index.default_roots(self.home), home=self.home)
        try:
            w = index.Watcher(ix, index.default_roots(self.home), home=self.home)
        except OSError:
            self.skipTest('inotify unavailable')
        self.addCleanup(w.close)
        self.make('Documents/fresh file.txt', 'zebra')
        (self.home / 'Documents/.dotfile').write_text('zebra')
        self.make('Documents/newdir/inner.txt', 'zebra inner')
        for _ in range(6):
            w.step(0.3)
        names = sorted(r['name'] for r in ix.search('zebra'))
        self.assertEqual(names, ['fresh file.txt', 'inner.txt'])
        (self.home / 'Documents/fresh file.txt').unlink()
        for _ in range(3):
            w.step(0.3)
        self.assertEqual([r['name'] for r in ix.search('zebra')], ['inner.txt'])

    def test_indexer_process_helpers(self):
        index.lower_priority.__call__  # callable
        with mock.patch('subprocess.Popen') as popen:
            index.spawn()
        argv, kwargs = popen.call_args[0][0], popen.call_args[1]
        self.assertEqual(argv[1:], ['-m', 'makos.seek.index'])
        self.assertNotIn('LD_PRELOAD', kwargs['env'])
        self.assertIn('src/makos', kwargs['env']['PYTHONPATH'])
        self.assertIn(self.home.name, str(index.default_roots(self.home)[0]))
        self.assertEqual([r.name for r in index.default_roots(self.home)], list(index.ROOT_NAMES))


class FilesSearchTests(Base):
    def test_localsearch_query_is_parameterised_filtered_and_falls_back(self):
        good = self.make('Documents/good.txt')
        secret = self.make('.ssh/id_rsa')
        calls = []

        def tinysparql(a, env):
            calls.append(a)
            return f'Results:\n  file://{good}\n  file://{secret}\n  file:///nonexistent/gone.txt\n'
        self.fake.do_tinysparql = tinysparql
        providers._probe.update(at=0.0, ok=False)
        got = providers.localsearch('good "evil" (x)', self.home)
        self.assertEqual([r.title for r in got], ['good.txt'])
        a = calls[-1]
        self.assertIn('-b', a)
        self.assertNotIn('evil', a[a.index('-q') + 1])  # the term is a query parameter, never SPARQL text
        self.assertTrue(any(x.startswith('q:string:') and 'evil' in x for x in a))
        self.assertIn('~q', a[a.index('-q') + 1])
        providers._probe.update(at=0.0, ok=False)
        self.fake.do_tinysparql = lambda a, env: Result(1, '', 'Could not activate')
        self.assertEqual(providers.localsearch('good', self.home), [])  # service down: caller falls back
        self.fake.tools.discard('tinysparql')
        self.assertEqual(providers.localsearch('good', self.home), [])

    def test_engine_falls_back_from_localsearch_to_index_to_walk(self):
        self.make('Documents/Budget 2026.txt', 'numbers')
        db = self.home / 'ix.sqlite'
        e = engine.Engine(self.home, db=db, settings={})
        self.addCleanup(e.close)
        self.assertEqual(e.slow('budget')[0].title, 'Budget 2026.txt')  # basic walk (index empty)
        self.assertEqual(e.status()['files'], 'index')
        e.index().scan(index.default_roots(self.home), home=self.home)
        self.assertEqual(e.slow('numbers')[0].group, 'Files')  # body text is only found through the index
        self.assertEqual(e.slow('numbers')[0].preview.strip(), 'numbers')
        providers._probe.update(at=0.0, ok=False)
        self.fake.do_tinysparql = lambda a, env: f'file://{self.home}/Documents/Budget 2026.txt'.replace(' ', '%20')
        self.assertEqual(e.status()['files'], 'LocalSearch')
        self.assertEqual(e.slow('budget')[0].score, 55)

    def test_engine_groups_orders_and_caps(self):
        self.make('Documents/term paper.txt')
        e = engine.Engine(self.home, db=self.home / 'ix.sqlite', settings={})
        self.addCleanup(e.close)
        res = e.fast('term') + e.web('term') + e.slow('term')
        groups = [g for g, _ in engine.grouped(res)]
        self.assertEqual(groups, ['Applications', 'Files', 'Web'])
        calc = engine.grouped(e.fast('12*12'))
        self.assertEqual(calc[0][0], 'Calculator')
        self.assertEqual(calc[0][1][0].title, '144')
        conv = engine.grouped(e.fast('1 mi to km'))
        self.assertEqual(conv[0][0], 'Conversion')
        dup = providers.Result('Files', 'a', action=('open', '/x'))
        self.assertEqual(len(engine.grouped([dup, dup])[0][1]), 1)
        many = [providers.Result('Files', str(i), action=('open', str(i)), score=i) for i in range(30)]
        self.assertEqual(len(engine.grouped(many)[0][1]), engine.PER_GROUP['Files'])
        self.assertEqual(e.fast(''), [])
        self.assertTrue(all(r.group == 'Applications' for r in e.fast('term', applications_only=True)))

    def test_empty_state_shows_recents_not_everything(self):
        e = engine.Engine(self.home, db=self.home / 'ix.sqlite', settings={})
        self.addCleanup(e.close)
        self.assertEqual(e.recents(), [])


class FilesApiTests(Base):
    def fake_module(self, hits=None, error=None):
        mod = types.ModuleType('makos.files.search')
        calls = []

        def search(text, roots=None, limit=100, **kw):
            calls.append((text, roots, limit))
            if error:
                raise error
            return hits or []
        mod.search = search
        pkg = types.ModuleType('makos.files')
        pkg.search = mod
        return {'makos.files': pkg, 'makos.files.search': mod}, calls

    def test_files_package_search_is_used_for_filters_and_as_fallback(self):
        good = self.make('Documents/photo.png')
        secret = self.make('.ssh/key.png')
        hit = lambda p: types.SimpleNamespace(path=str(p), name=Path(p).name, is_dir=False, snippet='')  # noqa: E731
        mods, calls = self.fake_module([hit(good), hit(secret), types.SimpleNamespace(path=str(self.home / 'Documents'), name='Documents', is_dir=True, snippet='')])
        e = engine.Engine(self.home, db=self.home / 'ix.sqlite', settings={})
        self.addCleanup(e.close)
        with mock.patch.dict(sys.modules, mods), mock.patch.object(Path, 'home', return_value=self.home):
            res = e.slow('kind:image sunset')
            self.assertEqual([r.title for r in res if r.group == 'Files'], ['photo.png'])
            self.assertEqual(calls[0][0], 'kind:image sunset')
            self.assertTrue(all(str(self.home) in r for r in calls[0][1]))
        mods, calls = self.fake_module(error=RuntimeError('changed API'))
        with mock.patch.dict(sys.modules, mods):
            self.assertEqual(providers.files_api('x', [self.home]), [])  # failures never reach the user


class QuickLookTests(Base):
    def test_quicklook_calls_the_files_package_defensively(self):
        from makos.seek import panel
        f = self.make('Documents/a.txt')
        shell = object()
        seen = []
        files = types.ModuleType('makos.files')
        files.preview = lambda app, path: seen.append((app, path))
        with mock.patch.dict(sys.modules, {'makos.files': files}), mock.patch.object(Path, 'home', return_value=self.home):
            self.assertTrue(panel.quicklook(shell, str(f)))
            self.assertEqual(seen, [(shell, str(f))])
            files.preview = mock.Mock(side_effect=RuntimeError('boom'))
            self.assertFalse(panel.quicklook(shell, str(f)))  # a failing previewer never breaks Seek
            del files.preview
            self.assertFalse(panel.quicklook(shell, str(f)))  # an older Files package without the API
            files.preview = lambda *a: seen.append('x')
            self.assertFalse(panel.quicklook(shell, str(self.home / '.ssh/id_rsa')))  # secrets are never handed to a previewer


class CompatTests(Base):
    def test_old_search_facade_still_works(self):
        from makos import search
        self.make('Documents/Report.txt')
        self.make('Documents/.hidden/Report-secret.txt')
        self.assertEqual(search.documents('report', self.home), [self.home / 'Documents/Report.txt'])
        self.assertEqual(search.documents('r', self.home), [])
        self.assertEqual(search.convert('1 mi to km'), '1.609344 km')
        self.assertEqual(search.calculate('(15 + 5) * 3 / 2'), '30')
        self.assertTrue(search.applications('files'))


if __name__ == '__main__':
    unittest.main()
