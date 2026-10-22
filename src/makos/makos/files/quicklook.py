"""Quick Look: a floating, bounded preview panel (Space). Previews never execute content."""
import os
import threading

import gi

gi.require_version('Gtk', '4.0')
gi.require_version('Gdk', '4.0')
from gi.repository import Gdk, Gio, GLib, Gtk, Pango

from .. import ui
from . import archive, content, model, panes, widgets

MAX_SPANS = 5000


class QuickLook:
    def __init__(self, app, parent=None, step=None, open_cb=None):
        self.app, self.parent, self.step, self.open_cb = app, parent, step, open_cb
        self.win = None
        self.entry = None
        self.gen = 0
        self.media = None
        self.pdf_state = None

    # -- window
    def visible(self):
        return self.win is not None and self.win.get_visible()

    def toggle(self, entry):
        if self.visible():
            self.close()
        else:
            self.show(entry)

    def close(self):
        self._stop_media()
        if self.win is not None:
            self.win.hide()
        self.gen += 1

    def _ensure(self):
        if self.win is not None:
            return
        w = ui.window(self.app, 'Quick Look', 780, 580)
        if self.parent is not None:
            w.set_transient_for(self.parent)
        w.add_css_class('quicklook')
        w.set_hide_on_close(True)
        outer = ui.box(True, 0)
        self.stack = Gtk.Stack(hexpand=True, vexpand=True, hhomogeneous=False, vhomogeneous=False, transition_type=Gtk.StackTransitionType.CROSSFADE, transition_duration=120)
        outer.append(self.stack)
        foot = ui.box(spacing=8, css='ql-foot')
        self.prev_btn = ui.button('‹', lambda: self._step(-1))
        self.next_btn = ui.button('›', lambda: self._step(1))
        self.caption = Gtk.Label(xalign=0.5, hexpand=True, ellipsize=Pango.EllipsizeMode.MIDDLE, css_classes=['subtitle'])
        self.open_btn = ui.button('Open', self._open, 'suggested-action')
        for wdg in (self.prev_btn, self.caption, self.next_btn, self.open_btn):
            foot.append(wdg)
        outer.append(foot)
        w.set_child(outer)
        keys = Gtk.EventControllerKey()
        keys.connect('key-pressed', self._key)
        w.add_controller(keys)
        w.connect('close-request', lambda *_: (self.close(), True)[1])
        self.win = w
        self._counter = 0

    def _key(self, _c, key, _code, state):
        if key in (Gdk.KEY_Escape, Gdk.KEY_space):
            if self.pdf_state is None or key == Gdk.KEY_Escape or not isinstance(self.win.get_focus(), Gtk.Button):
                self.close()
                return True
        if key in (Gdk.KEY_Left, Gdk.KEY_Up) and not self.media:
            self._step(-1)
            return True
        if key in (Gdk.KEY_Right, Gdk.KEY_Down) and not self.media:
            self._step(1)
            return True
        return False

    def _step(self, delta):
        if self.step:
            self.step(delta)

    def _open(self):
        if self.entry is not None and self.open_cb:
            self.open_cb(self.entry)

    def _stop_media(self):
        if self.media is not None:
            try:
                self.media.set_playing(False)
            except Exception:
                pass
            self.media = None

    # -- content
    def show(self, entry, siblings=0):
        self._ensure()
        self._stop_media()
        self.pdf_state = None
        self.gen += 1
        gen = self.gen
        self.entry = entry
        self.win._title.set_text('Quick Look  —  ' + entry.name)
        self.caption.set_text(f'{entry.name}  ·  {entry.kind}' + (f'  ·  {model.human_size(entry.size)}' if not entry.is_dir else ''))
        self.prev_btn.set_visible(self.step is not None)
        self.next_btn.set_visible(self.step is not None)
        self.open_btn.set_label('Open Folder' if entry.is_dir else 'Open')
        content_page = self._build(entry, gen)
        page = Gtk.ScrolledWindow(hexpand=True, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        page.set_child(content_page)
        self._counter += 1
        name = f'p{self._counter}'
        self.stack.add_named(page, name)
        self.stack.set_visible_child_name(name)
        old = [c for c in self._children() if c is not page]
        GLib.timeout_add(300, lambda: [self.stack.remove(c) for c in old if c.get_parent() is self.stack] and False)
        self.win.present()

    def _children(self):
        out, c = [], self.stack.get_first_child()
        while c:
            out.append(c)
            c = c.get_next_sibling()
        return out

    def _busy(self, text):
        box = ui.box(True, 12)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        sp = Gtk.Spinner(spinning=True)
        sp.set_size_request(32, 32)
        box.append(sp)
        box.append(Gtk.Label(label=text, css_classes=['subtitle']))
        return box

    def _message(self, entry, text):
        box = ui.box(True, 12)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        box.append(widgets.make_icon(entry.icon, 96))
        box.append(Gtk.Label(label=entry.name, css_classes=['sheet-title']))
        box.append(Gtk.Label(label=text, wrap=True, max_width_chars=50, css_classes=['subtitle'], justify=Gtk.Justification.CENTER))
        return box

    def _metadata_page(self, entry, note=None):
        box = ui.box(True, 14)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)
        pane = panes.PreviewPane(size=300, snippet=False)
        pane.show(entry)
        box.append(pane)
        if note:
            box.append(Gtk.Label(label=note, wrap=True, max_width_chars=60, css_classes=['subtitle'], justify=Gtk.Justification.CENTER))
        return box

    def _swap(self, holder, gen, widget):
        """Replace the placeholder child of ``holder`` if this preview is still current."""
        if gen != self.gen or holder.get_parent() is None:
            return False
        child = holder.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            holder.remove(child)
            child = nxt
        holder.append(widget)
        return False

    def _build(self, entry, gen):
        holder = ui.box(True, 0)
        holder.set_vexpand(True)
        holder.set_hexpand(True)
        if not entry.path:
            holder.append(self._metadata_page(entry, 'This item is on a server. Open it to preview.') if not entry.is_dir else
                          self._message(entry, 'Network folder'))
            return holder
        kind = content.classify(entry.path)
        try:
            if kind == 'folder':
                holder.append(self._busy('Measuring folder…'))
                self._folder(entry, gen, holder)
            elif kind == 'image':
                holder.append(self._busy('Loading image…'))
                self._image(entry, gen, holder)
            elif kind == 'text':
                holder.append(self._busy('Reading…'))
                self._text(entry, gen, holder)
            elif kind == 'pdf':
                holder.append(self._busy('Rendering PDF…'))
                self._pdf(entry, gen, holder)
            elif kind in ('audio', 'video'):
                holder.append(self._media(entry, kind))
            elif kind == 'office':
                holder.append(self._busy('Preparing document preview…'))
                self._office(entry, gen, holder)
            elif kind == 'archive':
                holder.append(self._busy('Reading archive…'))
                self._archive(entry, gen, holder)
            else:
                holder.append(self._metadata_page(entry))
        except Exception as exc:  # a preview must never break the file window
            holder.append(self._message(entry, f'No preview available ({exc}).'))
        return holder

    def _thread(self, fn):
        threading.Thread(target=fn, daemon=True, name='makos-quicklook').start()

    # folder
    def _folder(self, entry, gen, holder):
        def work():
            n = model.count_children(entry.path)
            total, files, folders, complete = model.folder_size(entry.path, max_items=400000)
            GLib.idle_add(done, n, total, files, folders, complete)

        def done(n, total, files, folders, complete):
            box = ui.box(True, 10)
            box.set_valign(Gtk.Align.CENTER)
            box.set_halign(Gtk.Align.CENTER)
            box.append(widgets.make_icon(entry.icon, 128))
            box.append(Gtk.Label(label=entry.name, css_classes=['sheet-title']))
            if n is None:
                text = 'This folder cannot be read.'
            else:
                text = (f'{n} item' + ('' if n == 1 else 's') + f'  ·  {model.human_size(total)}'
                        + ('' if complete else ' or more') + f'\n{files} files in {folders} subfolders')
            box.append(Gtk.Label(label=text, css_classes=['subtitle'], justify=Gtk.Justification.CENTER))
            self._swap(holder, gen, box)
            return False
        self._thread(work)

    # image
    def _image(self, entry, gen, holder):
        def work():
            pb = content.pixbuf_thumbnail(entry.path, 2200) if entry.size < content.IMAGE_LIMIT else None
            tex = Gdk.Texture.new_for_pixbuf(pb) if pb else None
            info = content.image_info(entry.path)
            GLib.idle_add(done, tex, info)

        def done(tex, info):
            if tex is None:
                self._swap(holder, gen, self._metadata_page(entry, 'This image cannot be shown (damaged, unsupported or very large).'))
                return False
            pic = Gtk.Picture.new_for_paintable(tex)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_can_shrink(True)
            pic.add_css_class('ql-picture')
            if info:
                self.caption.set_text(f'{entry.name}  ·  {info[1]} × {info[2]}  ·  {info[0]}  ·  {model.human_size(entry.size)}')
            self._swap(holder, gen, pic)
            return False
        self._thread(work)

    # text
    def _text(self, entry, gen, holder):
        def work():
            try:
                text, truncated = content.read_text(entry.path)
            except OSError as exc:
                GLib.idle_add(fail, model.human_error(exc, entry.name))
                return
            lang = content.language_for(entry.name)
            spans = content.highlight_spans(text, lang)[:MAX_SPANS] if lang else []
            GLib.idle_add(done, text, truncated, spans)

        def fail(msg):
            self._swap(holder, gen, self._message(entry, msg))
            return False

        def done(text, truncated, spans):
            view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.NONE,
                                left_margin=14, right_margin=14, top_margin=12, bottom_margin=12)
            view.add_css_class('ql-text')
            buf = view.get_buffer()
            buf.set_text(text)
            styles = {'comment': '#6f8196', 'string': '#2a7a4f', 'number': '#a2541c', 'keyword': '#2f5fa8'}
            for name, color in styles.items():
                tag = buf.create_tag(name, foreground=color)
                if name == 'keyword':
                    tag.set_property('weight', Pango.Weight.BOLD)
            for start, end, name in spans:
                buf.apply_tag_by_name(name, buf.get_iter_at_offset(start), buf.get_iter_at_offset(end))
            box = ui.box(True, 0)
            box.append(ui.scroll(view))
            if truncated:
                box.append(Gtk.Label(label=f'Showing the first {content.TEXT_LIMIT // 1024} KB of {model.human_size(entry.size)}.',
                                     css_classes=['statusbar'], xalign=0))
            self._swap(holder, gen, box)
            return False
        self._thread(work)

    # pdf
    def _pdf(self, entry, gen, holder):
        state = {'page': 1, 'pages': 0, 'busy': False}
        self.pdf_state = state

        def work_info():
            pages = content.pdf_pages(entry.path)
            GLib.idle_add(start, pages)

        def start(pages):
            if gen != self.gen:
                return False
            if not pages:
                self._swap(holder, gen, self._metadata_page(entry, 'This PDF cannot be rendered here (poppler-utils missing, encrypted or damaged).'))
                return False
            state['pages'] = pages
            box = ui.box(True, 0)
            self.pdf_pic = Gtk.Picture(content_fit=Gtk.ContentFit.CONTAIN, can_shrink=True)
            self.pdf_pic.add_css_class('ql-picture')
            box.append(self.pdf_pic)
            bar = ui.box(spacing=8, css='ql-foot')
            bar.set_halign(Gtk.Align.CENTER)
            self.pdf_label = Gtk.Label()
            bar.append(ui.button('Previous Page', lambda: goto(state['page'] - 1)))
            bar.append(self.pdf_label)
            bar.append(ui.button('Next Page', lambda: goto(state['page'] + 1)))
            box.append(bar)
            self._swap(holder, gen, box)
            goto(1)
            return False

        def goto(page):
            page = max(1, min(state['pages'], page))
            state['page'] = page
            self.pdf_label.set_text(f'Page {page} of {state["pages"]}')

            def render():
                try:
                    data = content.pdf_page_png(entry.path, page, 1100)
                except TimeoutError:
                    data = None
                tex = panes.texture_from_bytes(data) if data else None
                GLib.idle_add(show, tex, page)

            def show(tex, page_no):
                if gen == self.gen and page_no == state['page']:
                    if tex is not None:
                        self.pdf_pic.set_paintable(tex)
                    else:
                        self.pdf_label.set_text(f'Page {page_no} could not be rendered (time limit).')
                return False
            self._thread(render)
        self._thread(work_info)

    # media
    def _media(self, entry, kind):
        box = ui.box(True, 0)
        try:
            media = Gtk.MediaFile.new_for_filename(entry.path)
        except Exception:
            media = None
        if media is None:
            return self._metadata_page(entry, 'No media backend is installed, so this file cannot be played here.')
        video = Gtk.Video()
        video.set_autoplay(False)
        video.set_loop(False)
        video.set_media_stream(media)
        video.set_vexpand(True)
        video.add_css_class('ql-video')
        self.media = media
        if kind == 'audio':
            top = ui.box(True, 8)
            top.set_valign(Gtk.Align.CENTER)
            top.set_vexpand(True)
            top.append(widgets.make_icon(entry.icon, 160))
            rows = content.media_info(entry.path)
            if rows:
                top.append(Gtk.Label(label='  ·  '.join(f'{k}: {v}' for k, v in rows), css_classes=['subtitle']))
            box.append(top)
            video.set_vexpand(False)
        box.append(video)
        err = Gtk.Label(xalign=0, css_classes=['error-label'])
        box.append(err)

        def check(*_):
            e = media.get_error()
            if e is not None:
                err.set_text('This file cannot be played: ' + e.message)
        media.connect('notify::error', check)
        return box

    # office / documents
    def _office(self, entry, gen, holder):
        def work():
            data = None
            try:
                data = content.office_thumbnail(entry.path)
            except Exception:
                data = None
            rows = content.metadata_rows(entry.path)
            tex = panes.texture_from_bytes(data) if data else None
            GLib.idle_add(done, tex, rows)

        def done(tex, rows):
            if tex is None:
                note = ('No preview could be created. LibreOffice may be missing or the document took too long; '
                        'the information above comes from the file itself.')
                self._swap(holder, gen, self._metadata_page(entry, note))
                return False
            box = ui.box(True, 0)
            pic = Gtk.Picture.new_for_paintable(tex)
            pic.set_content_fit(Gtk.ContentFit.CONTAIN)
            pic.set_can_shrink(True)
            pic.add_css_class('ql-picture')
            box.append(pic)
            meta = '  ·  '.join(f'{k}: {v}' for k, v in rows if k in ('Title', 'Author', 'Pages', 'Words'))
            if meta:
                box.append(Gtk.Label(label=meta, css_classes=['statusbar'], xalign=0))
            self._swap(holder, gen, box)
            return False
        self._thread(work)

    # archives
    def _archive(self, entry, gen, holder):
        def work():
            try:
                entries, total, trunc = archive.list_archive(entry.path)
            except archive.ArchiveError as exc:
                GLib.idle_add(fail, str(exc))
                return
            GLib.idle_add(done, entries, total, trunc)

        def fail(msg):
            self._swap(holder, gen, self._message(entry, msg))
            return False

        def done(entries, total, trunc):
            lines = [f'{"" if d else model.human_size(s):>10}   {n}' for n, s, d in entries]
            view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True, left_margin=14, top_margin=12)
            view.get_buffer().set_text('\n'.join(lines))
            box = ui.box(True, 0)
            box.append(ui.scroll(view))
            box.append(Gtk.Label(label=f'{total} items' + (' (list shortened)' if trunc else '') +
                                 '  ·  Archives are listed, never extracted by preview.', css_classes=['statusbar'], xalign=0))
            self._swap(holder, gen, box)
            return False
        self._thread(work)
