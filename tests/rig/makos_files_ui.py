"""Files UI rig, runs inside makos_files_rig.sh: real GTK widgets under KWin with a private HOME."""
import os
import sys
import time
import threading
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
gi.require_version('Graphene', '1.0')
from gi.repository import Gtk, Gdk, Gio, GLib, Graphene

from makos import ui
from makos.files import Files, model, ops, search as fsearch, tags, trash as trashlib
from makos.files.location import Loc

OUT = Path(os.environ['MAKOS_RIG_SHOTS'])
HOME = Path.home()
PASSED = []


def spin(check, timeout=20, what='condition'):
    end = time.monotonic() + timeout
    ctx = GLib.MainContext.default()
    while time.monotonic() < end:
        while ctx.pending():
            ctx.iteration(False)
        if check():
            return
        time.sleep(.004)
    raise AssertionError('Timed out waiting for ' + what)


def settle(seconds=.3):
    end = time.monotonic() + seconds
    spin(lambda: time.monotonic() >= end, seconds + 2)


def shot(widget, name):
    settle(.25)
    w, h = widget.get_width(), widget.get_height()
    assert w > 0 and h > 0, f'{name}: widget has no size'
    paintable = Gtk.WidgetPaintable.new(widget)
    snap = Gtk.Snapshot()
    paintable.snapshot(snap, w, h)
    node = snap.to_node()
    renderer = widget.get_native().get_renderer()
    tex = renderer.render_texture(node, Graphene.Rect().init(0, 0, w, h))
    path = OUT / f'{name}.png'
    tex.save_to_png(str(path))
    print('SHOT', path.name, f'{w}x{h}')


def check(cond, message):
    if not cond:
        raise AssertionError(message)
    PASSED.append(message)
    print('PASS', message)


def make_fixtures():
    from PIL import Image, ImageDraw
    import zipfile
    import wave
    import struct
    import math
    d = HOME / 'Documents'
    (d / 'Projects/Alpha/src').mkdir(parents=True)
    (d / 'Projects/Beta').mkdir(parents=True)
    (HOME / 'Pictures').mkdir()
    (HOME / 'Downloads').mkdir()
    (HOME / 'Music').mkdir()
    (HOME / 'Desktop').mkdir()
    (d / 'Welcome.txt').write_text('A private rig document.\nSecond line mentions quarterly report numbers.\n')
    (d / 'Report 2026.md').write_text('# Quarterly report\n\nSome `code` and text.\n')
    (d / 'Projects/Alpha/src/main.py').write_text('#!/usr/bin/env python3\n# A comment\nimport os\n\ndef main(x):\n    """doc"""\n    return "value %d" % 42 if x else None\n\nclass Thing:\n    pass\n' * 3)
    (d / 'Projects/Alpha/notes.txt').write_text('alpha notes\n')
    (d / 'Projects/Beta/todo.txt').write_text('beta todo\n')
    for i, color in enumerate(['#3b8de0', '#5db84e', '#e0483d', '#ee9a2f']):
        im = Image.new('RGB', (640, 420), color)
        dr = ImageDraw.Draw(im)
        dr.ellipse((120, 60, 520, 360), fill='white')
        dr.text((280, 200), f'photo {i}', fill='black')
        im.save(HOME / 'Pictures' / f'photo-{i}.png')
    Image.new('RGB', (595, 842), 'white').save(d / 'Brochure.pdf')
    with zipfile.ZipFile(d / 'Bundle.zip', 'w') as z:
        z.writestr('readme.txt', 'hello')
        z.writestr('data/a.csv', 'a,b\n1,2\n')
    odt = d / 'Letter.odt'
    with zipfile.ZipFile(odt, 'w') as z:
        z.writestr('mimetype', 'application/vnd.oasis.opendocument.text', zipfile.ZIP_STORED)
        z.writestr('META-INF/manifest.xml', '<?xml version="1.0"?><manifest:manifest xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0" manifest:version="1.2"><manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/><manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/><manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/></manifest:manifest>')
        z.writestr('content.xml', '<?xml version="1.0"?><office:document-content xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" office:version="1.2"><office:body><office:text><text:p>Dear reader, this is the MakkOS rig letter.</text:p></office:text></office:body></office:document-content>')
        z.writestr('meta.xml', '<?xml version="1.0"?><office:document-meta xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:meta="urn:oasis:names:tc:opendocument:xmlns:meta:1.0" office:version="1.2"><office:meta><dc:title>Rig letter</dc:title><dc:creator>MakkOS</dc:creator><meta:document-statistic meta:page-count="1" meta:word-count="8"/></office:meta></office:document-meta>')
    with wave.open(str(HOME / 'Music/tone.wav'), 'w') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b''.join(struct.pack('<h', int(8000 * math.sin(i / 20))) for i in range(22050 * 2)))
    (d / 'empty-folder').mkdir()
    os.symlink(d / 'nowhere', d / 'broken-link')
    os.symlink(d / 'Projects', d / 'Projects alias')


def wait_loaded(files, tab=None, count=None):
    tab = tab or files.current
    spin(lambda: not tab.loading and (count is None or tab.store.get_n_items() == count), 30, 'listing')
    settle(.3)


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id='org.makos.FilesRig')

    def do_activate(self):
        self.hold()
        ui.install_theme()
        GLib.idle_add(self.run_rig)

    def run_rig(self):
        try:
            run(self)
            print('RIG-DONE')
        except Exception:
            import traceback
            traceback.print_exc()
            self.exit_code = 1
        finally:
            self.release()
            self.quit()
        return False


def run(app):
    make_fixtures()
    t0 = time.monotonic()
    files = Files(app, HOME / 'Documents')
    wait_loaded(files)
    tab = files.current
    names = [tab.store.get_item(i).entry.name for i in range(tab.store.get_n_items())]
    check(names[:3] == ['empty-folder', 'Projects', 'Projects alias'], f'folders first, natural order: {names[:4]}')
    check('broken-link' in names, 'broken symlink is listed, not fatal')
    check(files.path.name == 'Documents', 'Files.path API')
    files.win.set_default_size(1180, 760)
    settle(.5)
    shot(files.win, '01-icon-view')

    # --- views
    files.view('list')
    settle(.5)
    check(tab.view.mode == 'list', 'list view active')
    lv = tab.view
    # expand a folder row
    pos = next(i for i in range(lv.tree.get_n_items()) if lv.tree.get_item(i).get_item().entry.name == 'Projects')
    row = lv.tree.get_row(pos)
    row.set_expanded(True)
    spin(lambda: lv.tree.get_n_items() > tab.store.get_n_items(), 10, 'expanded children')
    check(lv.tree.get_n_items() == tab.store.get_n_items() + 2, 'expanding Projects shows Alpha and Beta')
    alias_pos = next(i for i in range(lv.tree.get_n_items()) if lv.tree.get_item(i).get_item().entry.name == 'Projects alias')
    check(not lv.tree.get_row(alias_pos).is_expandable(), 'symlinked folder is not expandable (no loops)')
    tab.sort_changed('size', True)
    settle(.6)
    check(tab.store.get_item(0).entry.is_dir, 'folders stay on top when sorting by size')
    sizes = [tab.store.get_item(i).entry.size for i in range(tab.store.get_n_items()) if not tab.store.get_item(i).entry.is_dir]
    check(sizes == sorted(sizes, reverse=True), 'size sort descending')
    tab.sort_changed('name', False)
    settle(.5)
    shot(files.win, '02-list-view')

    files.view('columns')
    settle(.6)
    cv = tab.view
    check(cv.mode == 'columns', 'column view active')
    cv.show_path(str(HOME / 'Documents/Projects/Alpha'))
    spin(lambda: len(cv.columns) >= 4 and all(c.store.get_n_items() for c in cv.columns[:3]), 10, 'columns')
    settle(.4)
    src_col = cv.columns[-1]
    check(len(cv.columns) >= 4, f'column stack has {len(cv.columns)} columns')
    pos = next(i for i in range(src_col.store.get_n_items()) if src_col.store.get_item(i).entry.name == 'src')
    src_col.sel.set_selected(pos)
    spin(lambda: len(cv.columns) >= 5, 10, 'src column')
    settle(.4)
    last = cv.columns[-1]
    spin(lambda: last.store.get_n_items() > 0, 10, 'main.py listed')
    last.sel.set_selected(0)
    settle(.8)
    check(cv.preview is not None, 'selecting a file adds the preview column')
    check(files.current.loc.path.endswith('Alpha/src'), 'location follows the column stack')
    shot(files.win, '03-column-view')

    files.view('cover')
    tab.navigate(Loc.dir(HOME / 'Pictures'), push=False)
    wait_loaded(files)
    settle(1.2)
    check(tab.view.mode == 'cover', 'cover view active')
    shot(files.win, '04-cover-view')

    files.view('icons')
    tab.navigate(Loc.dir(HOME / 'Pictures'), push=False)
    wait_loaded(files)
    settle(1.0)
    shot(files.win, '05-icon-view-thumbnails')
    tab.navigate(Loc.dir(HOME / 'Documents'), push=False)
    wait_loaded(files)

    # --- Quick Look on every type
    def ql(name, wait=1.0):
        item = next(tab.store.get_item(i) for i in range(tab.store.get_n_items()) if tab.store.get_item(i).entry.name == name)
        tab.view.select_items([item])
        settle(.2)
        files.quicklook.close()
        files.quicklook.show(item.entry)
        settle(wait)
        return item.entry
    ql('Welcome.txt')
    shot(files.quicklook.win, '10-quicklook-text')
    tab.navigate(Loc.dir(HOME / 'Documents/Projects/Alpha/src'), push=False)
    wait_loaded(files)
    ql('main.py')
    shot(files.quicklook.win, '11-quicklook-code')
    tab.navigate(Loc.dir(HOME / 'Pictures'), push=False)
    wait_loaded(files)
    ql('photo-1.png')
    shot(files.quicklook.win, '12-quicklook-image')
    tab.navigate(Loc.dir(HOME / 'Documents'), push=False)
    wait_loaded(files)
    ql('Brochure.pdf', 2.0)
    shot(files.quicklook.win, '13-quicklook-pdf')
    ql('Letter.odt', 6.0)
    shot(files.quicklook.win, '14-quicklook-office')
    ql('Bundle.zip')
    shot(files.quicklook.win, '15-quicklook-archive')
    ql('Projects')
    settle(1.0)
    shot(files.quicklook.win, '16-quicklook-folder')
    ql('broken-link')
    shot(files.quicklook.win, '17-quicklook-fallback')
    tab.navigate(Loc.dir(HOME / 'Music'), push=False)
    wait_loaded(files)
    ql('tone.wav', 1.5)
    shot(files.quicklook.win, '18-quicklook-audio')
    files.quicklook.close()
    tab.navigate(Loc.dir(HOME / 'Documents'), push=False)
    wait_loaded(files)

    # --- operations through the real window
    before = tab.store.get_n_items()
    files.new_folder()
    spin(lambda: tab.store.get_n_items() == before + 1, 10, 'new folder appears')
    settle(.5)
    item = tab.selected_items()[0]
    check(item.entry.name == 'untitled folder', 'new folder selected after creation')
    cell = tab.view.bound.get(id(item))
    check(cell is not None and cell.stack.get_visible_child_name() == 'entry', 'inline rename entry is open')
    shot(files.win, '20-inline-rename')
    cell.entry.set_text('Archive Box')
    cell.entry.emit('activate')
    spin(lambda: (HOME / 'Documents/Archive Box').is_dir(), 10, 'rename applied')
    settle(.5)
    check(any(tab.store.get_item(i).entry.name == 'Archive Box' for i in range(tab.store.get_n_items())), 'renamed folder appears in list')

    sel_item = next(tab.store.get_item(i) for i in range(tab.store.get_n_items()) if tab.store.get_item(i).entry.name == 'Welcome.txt')
    tab.view.select_items([sel_item])
    files.do_action('copy')
    settle(.3)
    folder_item = next(tab.store.get_item(i) for i in range(tab.store.get_n_items()) if tab.store.get_item(i).entry.name == 'Archive Box')
    tab.view.select_items([folder_item])
    files.do_action('paste')
    spin(lambda: (HOME / 'Documents/Archive Box/Welcome.txt').exists(), 10, 'paste into folder')
    check(True, 'clipboard copy/paste into selected folder works')
    # cut & paste (move)
    tab.view.select_items([sel_item])
    files.do_action('cut')
    settle(.2)
    tab.view.select_items([folder_item])
    files.do_action('paste')
    # the cut/paste target already holds Welcome.txt: the real conflict sheet appears and blocks the worker
    from makos.files import sheets
    def click(widget, label):
        c = widget.get_first_child()
        while c:
            if isinstance(c, Gtk.Button) and c.get_label() == label:
                c.emit('clicked')
                return True
            if click(c, label):
                return True
            c = c.get_next_sibling()
        return False
    spin(lambda: any(isinstance(w, Gtk.Window) and w.get_title() == 'Item already exists' for w in Gtk.Window.list_toplevels()), 10, 'conflict sheet')
    sheet = next(w for w in Gtk.Window.list_toplevels() if w.get_title() == 'Item already exists')
    shot(sheet, '22-conflict-sheet')
    check(click(sheet.get_child(), 'Keep Both'), 'Keep Both button found')
    spin(lambda: (HOME / 'Documents/Archive Box/Welcome copy.txt').exists() and not (HOME / 'Documents/Welcome.txt').exists(), 10, 'moved with Keep Both')
    check(True, 'conflict sheet answered Keep Both: cut/paste moved the file as "Welcome copy.txt"')
    files.engine.undo()
    spin(lambda: (HOME / 'Documents/Welcome.txt').exists(), 10, 'undo move')
    check(not (HOME / 'Documents/Archive Box/Welcome copy.txt').exists(), 'undo of the move restores the original location')
    settle(.8)
    shot(files.win, '21-after-paste')

    # trash + undo through the engine with real window refresh
    target = HOME / 'Documents/Report 2026.md'
    it = next(tab.store.get_item(i) for i in range(tab.store.get_n_items()) if tab.store.get_item(i).entry.name == 'Report 2026.md')
    tab.view.select_items([it])
    files.do_action('trash')
    settle(1.5)
    print('JOBS', [(j.kind, j.state, j.errors, [str(x.get_path()) for x in j.sources]) for j in files.engine.jobs][-3:], 'selected', [i.entry.name for i in tab.selected_items()])
    spin(lambda: not target.exists(), 10, 'trashed')
    settle(.5)
    check(not any(tab.store.get_item(i).entry.name == 'Report 2026.md' for i in range(tab.store.get_n_items())), 'trashed item leaves the list')
    check(not trashlib.is_empty(), 'item is in the Trash')
    files.open_location(Loc('trash'))
    wait_loaded(files)
    check(tab.store.get_n_items() >= 1, 'Trash view lists items')
    shot(files.win, '23-trash-view')
    files.open_location(Loc.dir(HOME / 'Documents'))
    wait_loaded(files)
    files.undo()
    spin(lambda: target.exists(), 10, 'undo trash')
    settle(.8)
    check(any(tab.store.get_item(i).entry.name == 'Report 2026.md' for i in range(tab.store.get_n_items())), 'undo brings the item back into the list')

    # progress sheet (forced visible)
    big = HOME / 'Downloads/big.bin'
    with open(big, 'wb') as f:
        f.truncate(300 * 1024 * 1024)
    job = ops.Job('copy', [big], HOME / 'Documents')
    pj = sheets.ProgressSheet(files, job, delay=1)
    job.state = 'running'
    job.total_bytes, job.done_bytes, job.current = 300 * 1024 * 1024, 120 * 1024 * 1024, 'big.bin'
    spin(lambda: pj.win is not None, 5, 'progress sheet')
    pj._update()
    shot(pj.win, '24-progress-sheet')
    job.state = 'cancelled'
    pj._update()
    big.unlink()

    # Get Info
    it = next(tab.store.get_item(i) for i in range(tab.store.get_n_items()) if tab.store.get_item(i).entry.name == 'Projects')
    tab.view.select_items([it])
    files.do_action('info')
    spin(lambda: any(isinstance(w, Gtk.Window) and (w.get_title() or '').endswith('Info') for w in Gtk.Window.list_toplevels()), 10, 'info window')
    settle(1.0)
    info = next(w for w in Gtk.Window.list_toplevels() if (w.get_title() or '').endswith('Info'))
    shot(info, '25-get-info')
    info.close()

    # tags
    wt = HOME / 'Documents/Welcome.txt'
    wt = next((p for p in (HOME / 'Documents/Archive Box/Welcome.txt', wt) if p.exists()))
    tags.STORE.set_tags(wt, ['Red', 'Blue', 'Project X'])
    check(tags.STORE.get_tags(wt) == ['Red', 'Blue', 'Project X'], 'tags stored in user.xdg.tags')
    check(os.getxattr(wt, 'user.xdg.tags') == b'Red,Blue,Project X', 'xattr is the freedesktop tag attribute')
    files.sidebar.refresh()
    files.open_location(Loc('tag', arg='Red'))
    wait_loaded(files)
    check(tab.store.get_n_items() == 1, 'Tags sidebar location lists tagged files')
    shot(files.win, '26-tag-view')
    files.open_location(Loc.dir(HOME / 'Documents/Archive Box'))
    wait_loaded(files)
    settle(.5)
    shot(files.win, '27-tag-dots')

    # context menu
    files.open_location(Loc.dir(HOME / 'Documents'))
    wait_loaded(files)
    files.view('list')
    settle(.5)
    it = next(tab.store.get_item(i) for i in range(tab.store.get_n_items()) if tab.store.get_item(i).entry.name == 'Bundle.zip')
    tab.view.select_items([it])
    from makos.files.widgets import popup_menu
    pop = popup_menu(tab.view.cv, 300, 200, files.selection_rows(tab.selected_entries(), tab))
    settle(.6)
    shot(pop, '28-context-menu')
    pop.popdown()
    settle(.3)

    # search
    files.search.set_text('report')
    spin(lambda: tab.loc.kind == 'search' and not tab.loading, 15, 'search finished')
    settle(.5)
    names = sorted(tab.store.get_item(i).entry.name for i in range(tab.store.get_n_items()))
    check('Report 2026.md' in names, f'folder search finds files: {names}')
    shot(files.win, '29-search-results')
    files.end_search()
    spin(lambda: tab.loc.kind == 'dir', 10, 'search closed')
    hits = fsearch.search('welcome', [HOME])
    check(any(h.name == 'Welcome.txt' for h in hits), 'files.search API (Seek) returns hits')

    # DnD handlers (the same code the GTK drag-and-drop signals call)
    wait_loaded(files)
    box = next(tab.store.get_item(i) for i in range(tab.store.get_n_items()) if tab.store.get_item(i).entry.name == 'empty-folder')
    f = HOME / 'Pictures/photo-0.png'
    ok = tab.drop([str(f)], box, True)    # Ctrl held => copy
    spin(lambda: (HOME / 'Documents/empty-folder/photo-0.png').exists(), 10, 'drop copy')
    check(f.exists(), 'drop with Ctrl copies')
    ok = tab.drop([str(HOME / 'Pictures/photo-1.png')], box, False)   # same filesystem => move
    spin(lambda: (HOME / 'Documents/empty-folder/photo-1.png').exists(), 10, 'drop move')
    check(not (HOME / 'Pictures/photo-1.png').exists(), 'drop on same volume moves')
    from makos.files import dnd
    prov = dnd.provider_for([str(f)])
    check('text/uri-list' in prov.ref_formats().to_string() or 'GdkFileList' in prov.ref_formats().to_string(), 'drag source offers a uri list')

    # compress / extract
    it = next(tab.store.get_item(i) for i in range(tab.store.get_n_items()) if tab.store.get_item(i).entry.name == 'Projects')
    tab.view.select_items([it])
    files.compress_selection('zip')
    spin(lambda: (HOME / 'Documents/Projects.zip').exists(), 10, 'compress')
    check(True, 'compress selection creates Projects.zip')

    # network sidebar + devices render
    files.sidebar.refresh()
    settle(.4)
    shot(files.win, '30-final-window')

    # tabs
    files.new_tab(Loc.dir(HOME / 'Music'))
    wait_loaded(files)
    check(files.tabs.get_n_pages() == 2, 'second tab opened')
    files.tabs.set_current_page(0)
    settle(.2)
    check(files.current.loc.path == str(HOME / 'Documents'), 'tab restores its own location')
    shot(files.win, '31-tabs')

    # large directory responsiveness (30k files)
    big_dir = HOME / 'Big'
    big_dir.mkdir()
    for i in range(30000):
        os.close(os.open(big_dir / f'file-{i:06d}.dat', os.O_CREAT | os.O_WRONLY))
    gaps = []
    last = [time.monotonic()]

    def beat():
        now = time.monotonic()
        gaps.append(now - last[0])
        last[0] = now
        return True
    GLib.timeout_add(10, beat)
    files.view('icons')
    t1 = time.monotonic()
    files.open_location(Loc.dir(big_dir))
    wait_loaded(files, count=30000)
    elapsed = time.monotonic() - t1
    worst = max(gaps[1:] or [0])
    print(f'BIGDIR 30000 items listed in {elapsed:.2f}s, worst main-thread gap {worst * 1000:.0f} ms')
    check(elapsed < 20, f'30k folder lists in {elapsed:.1f}s')
    check(worst < 1.5, f'main thread never stalls more than {worst * 1000:.0f} ms while loading 30k files')
    shot(files.win, '32-big-folder')
    files.view('list')
    settle(.5)
    t1 = time.monotonic()
    tab.sort_changed('size', False)
    spin(lambda: True, 1)
    settle(1.5)
    print(f'BIGDIR resort ok in {time.monotonic() - t1:.2f}s')

    # permission error handling
    locked = HOME / 'locked'
    locked.mkdir()
    locked.chmod(0)
    files.open_location(Loc.dir(HOME))
    wait_loaded(files)
    files.activate_entry(model.stat_entry(locked), tab)
    wait_loaded(files)
    check('permission' in tab.banner.get_text(), f'unreadable folder shows a human message: {tab.banner.get_text()!r}')
    shot(files.win, '33-permission-error')
    locked.chmod(0o700)
    files.win.close()
    print(f'RIG total {time.monotonic() - t0:.1f}s, {len(PASSED)} checks')


if __name__ == '__main__':
    app = App()
    app.exit_code = 0
    code = app.run([sys.argv[0]])
    sys.exit(code or app.exit_code)
