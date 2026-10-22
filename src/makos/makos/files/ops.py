"""Safe file operations on top of GIO with progress, cancel, conflicts and undo/redo.

Everything here is GTK-free. The engine runs jobs on worker threads and reports through an
injectable ``dispatch`` (GLib.idle_add in the app). Nothing is ever modified except by an
explicit call; "Replace" first moves the old item to the Trash so it can be undone.
"""
import errno
import itertools
import os
import shutil
import threading
import time
from pathlib import Path

from gi.repository import Gio, GLib

from . import model, trash as trashlib

NOFOLLOW = Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS
REPLACE, KEEP_BOTH, SKIP = 'replace', 'keep', 'skip'
HISTORY_LIMIT = 50
_IOE = Gio.IOErrorEnum


class OperationError(Exception):
    """User-facing failure of one item."""


class NeedsPermanentDelete(OperationError):
    pass


def gfile(x):
    if isinstance(x, Gio.File):
        return x
    x = os.fspath(x)
    return Gio.File.new_for_uri(x) if '://' in x else Gio.File.new_for_path(x)


def is_local(f):
    return f.get_path() is not None and f.is_native()


def display(f):
    try:
        return f.get_basename() or f.get_uri()
    except Exception:
        return str(f)


def gio_text(err, name=''):
    """Human text for a GLib.Error."""
    q = f'“{name}”' if name else 'the item'
    for code, text in [
        (_IOE.NOT_FOUND, f'{q} was not found. It may have been moved or the drive disconnected.'),
        (_IOE.PERMISSION_DENIED, f'You do not have permission to change {q}.'),
        (_IOE.EXISTS, f'An item named {q} already exists.'),
        (_IOE.NO_SPACE, 'There is not enough free space on the destination.'),
        (_IOE.READ_ONLY, 'The destination is read-only.'),
        (_IOE.IS_DIRECTORY, f'{q} is a folder and cannot be replaced by a file.'),
        (_IOE.NOT_DIRECTORY, f'{q} is not a folder.'),
        (_IOE.FILENAME_TOO_LONG, 'That name is too long.'),
        (_IOE.TIMED_OUT, 'The server did not respond in time.'),
        (_IOE.NOT_MOUNTED, 'The location is not connected. Open it from the sidebar first.'),
        (_IOE.HOST_NOT_FOUND, 'The server could not be found.'),
        (_IOE.NOT_SUPPORTED, f'This kind of item cannot be handled here: {q}.'),
        (_IOE.BUSY, f'{q} is busy.'),
        (_IOE.CANCELLED, 'Cancelled.'),
        (_IOE.WOULD_RECURSE, f'{q} must be copied item by item.'),
    ]:
        if err.matches(Gio.io_error_quark(), code):
            return text
    return err.message or str(err)


def exists(f):
    try:
        f.query_info('standard::type', NOFOLLOW, None)
        return True
    except GLib.Error as err:
        if err.matches(Gio.io_error_quark(), _IOE.NOT_FOUND):
            return False
        raise


def ftype(f):
    return f.query_info('standard::type', NOFOLLOW, None).get_file_type()


def children(f, cancel=None):
    en = f.enumerate_children('standard::name,standard::type', NOFOLLOW, cancel)
    try:
        while True:
            info = en.next_file(cancel)
            if info is None:
                break
            yield f.get_child(info.get_name()), info.get_file_type()
    finally:
        en.close(None)


def unique_child(parent, name, suffix=' copy'):
    stem, ext = model.split_name(name)
    cand, n = f'{stem}{suffix}{ext}', 2
    while exists(parent.get_child(cand)):
        cand = f'{stem}{suffix} {n}{ext}'
        n += 1
    return parent.get_child(cand)


def numbered_child(parent, name):
    """'untitled folder' -> 'untitled folder 2' -> ... first free sibling name."""
    stem, ext = model.split_name(name)
    cand, n = name, 2
    while exists(parent.get_child(cand)):
        cand = f'{stem} {n}{ext}'
        n += 1
    return parent.get_child(cand)


def delete_path(path, cancel=None):
    """Permanently delete a file, link or whole tree. Never follows symlinks."""
    f = gfile(path)
    t = ftype(f)
    if t == Gio.FileType.DIRECTORY:
        for child, _t in list(children(f, cancel)):
            delete_path(child, cancel)
        try:
            f.delete(cancel)
        except GLib.Error as err:
            if err.matches(Gio.io_error_quark(), _IOE.PERMISSION_DENIED) and is_local(f):
                os.chmod(f.get_path(), 0o700)
                f.delete(cancel)
            else:
                raise
    else:
        f.delete(cancel)


# ---------------------------------------------------------------- undo steps

class Step:
    """One reversible primitive. ``run`` performs it and returns the inverse step."""

    def run(self, job):
        raise NotImplementedError


class MoveStep(Step):
    def __init__(self, src, dst):
        self.src, self.dst = src, dst

    def run(self, job):
        s, d = gfile(self.src), gfile(self.dst)
        if exists(d):
            raise OperationError(f'“{display(d)}” already exists, so the item cannot be moved back.')
        try:
            d.get_parent().make_directory_with_parents(None)
        except GLib.Error:
            pass
        s.move(d, Gio.FileCopyFlags.ALL_METADATA | Gio.FileCopyFlags.NOFOLLOW_SYMLINKS, None, None, None)
        return MoveStep(self.dst, self.src)


class TrashStep(Step):
    def __init__(self, path):
        self.path = path

    def run(self, job):
        return trash_one(gfile(self.path))


class RestoreStep(Step):
    def __init__(self, orig, name, trash_dir):
        self.orig, self.name, self.trash_dir = orig, name, trash_dir

    def item(self):
        for it in trashlib.list_trash():
            if it.name == self.name and it.trash_dir == self.trash_dir:
                return it
        return None

    def run(self, job):
        it = self.item()
        if it is None:
            raise OperationError('The item is no longer in the Trash.')
        try:
            trashlib.restore(it, self.orig)
        except FileExistsError:
            raise OperationError(f'“{os.path.basename(self.orig)}” already exists at the original location.') from None
        return TrashStep(self.orig)


def trash_one(f):
    """Move a file to the Trash with GIO. Returns the RestoreStep (None if it cannot be located)."""
    started = time.time()
    path = f.get_path()
    try:
        f.trash(None)
    except GLib.Error as err:
        if err.matches(Gio.io_error_quark(), _IOE.NOT_SUPPORTED):
            raise NeedsPermanentDelete(f'“{display(f)}” cannot be moved to the Trash from this location.') from None
        raise OperationError(gio_text(err, display(f))) from None
    if path:
        found = trashlib.find_trashed(path, since=started)
        if found:
            return RestoreStep(path, found.name, found.trash_dir)
    return None


class Action:
    """An undoable user action: a list of steps and their human label."""

    def __init__(self, label, undo_steps, redo_steps=None):
        self.label = label
        self.undo_steps = list(undo_steps)
        self.redo_steps = list(redo_steps or [])

    def _run(self, steps, job):
        inverse = []
        for step in steps:
            if step is None:
                raise OperationError('This action can no longer be reversed.')
            inverse.append(step.run(job))
        return list(reversed(inverse))

    def undo(self, job):
        self.redo_steps = self._run(self.undo_steps, job)

    def redo(self, job):
        self.undo_steps = self._run(self.redo_steps, job)


# ---------------------------------------------------------------- jobs

_ids = itertools.count(1)


class Job:
    def __init__(self, kind, sources=(), dest=None, label='', **opts):
        self.id = next(_ids)
        self.kind = kind
        self.sources = [gfile(s) for s in sources]
        self.dest = gfile(dest) if dest is not None else None
        self.opts = opts
        self.label = label or kind.title()
        self.cancellable = Gio.Cancellable()
        self.state = 'queued'
        self.total_bytes = self.done_bytes = 0
        self.total_items = self.done_items = 0
        self.current = ''
        self.errors = []
        self.results = []          # resulting paths/URIs, for selecting after completion
        self.skipped = 0
        self.policy = opts.get('policy')   # preset conflict resolution
        self.undo_steps = []
        self.redo_steps = []
        self.undoable = True
        self.started = 0.0
        self.finished = 0.0
        self.listeners = []
        self._last_notify = 0.0
        self.undo_label = ''

    # cancellation
    def cancel(self):
        self.cancellable.cancel()

    @property
    def cancelled(self):
        return self.cancellable.is_cancelled()

    def check(self):
        if self.cancelled:
            raise model.Cancelled()

    @property
    def fraction(self):
        if self.total_bytes > 0:
            return min(1.0, self.done_bytes / self.total_bytes)
        if self.total_items > 0:
            return min(1.0, self.done_items / self.total_items)
        return 0.0

    def notify(self, force=False):
        now = time.monotonic()
        if force or now - self._last_notify >= 0.06:
            self._last_notify = now
            for fn in list(self.listeners):
                fn(self)

    def fail(self, name, text):
        self.errors.append(f'{name}: {text}')


class Engine:
    """Runs jobs, keeps undo/redo history.

    ``dispatch(fn)`` is used to deliver callbacks on the UI thread; ``ask(job, src, dst, dst_is_dir)`` is
    called on the worker thread for conflicts and returns ``(resolution, apply_to_all)``.
    """

    def __init__(self, dispatch=None, ask=None, sync=False):
        self.dispatch = dispatch or (lambda fn: fn())
        self.ask = ask
        self.sync = sync
        self.history = []
        self.future = []
        self.jobs = []
        self.on_job_added = None
        self.on_job_done = None
        self.on_history = None
        self._lock = threading.RLock()
        self._serial = threading.Lock()    # one disk-modifying job at a time keeps undo coherent

    # -- history
    @property
    def can_undo(self):
        return bool(self.history)

    @property
    def can_redo(self):
        return bool(self.future)

    @property
    def undo_label(self):
        return self.history[-1].label if self.history else ''

    @property
    def redo_label(self):
        return self.future[-1].label if self.future else ''

    def _push(self, action):
        with self._lock:
            self.history.append(action)
            del self.history[:-HISTORY_LIMIT]
            self.future.clear()
        self._changed()

    def _changed(self):
        if self.on_history:
            self.dispatch(self.on_history)

    # -- running
    def submit(self, job, body):
        job.state = 'queued'
        self.jobs.append(job)
        if self.on_job_added:
            self.dispatch(lambda: self.on_job_added(job))
        if self.sync:
            self._run(job, body)
        else:
            threading.Thread(target=self._run, args=(job, body), daemon=True, name=f'makos-files-{job.kind}').start()
        return job

    def _run(self, job, body):
        with self._serial:
            job.state = 'running'
            job.started = time.monotonic()
            job.notify(True)
            try:
                job.check()
                body(job)
                job.state = 'cancelled' if job.cancelled else ('failed' if job.errors and not job.results and not job.done_items else 'done')
            except model.Cancelled:
                job.state = 'cancelled'
            except OperationError as exc:
                job.fail('', str(exc))
                job.state = 'failed'
            except GLib.Error as err:
                job.fail('', gio_text(err))
                job.state = 'failed'
            except OSError as exc:
                job.fail('', model.human_error(exc))
                job.state = 'failed'
            except Exception as exc:  # last resort: report, never crash the shell
                job.fail('', f'Unexpected problem: {exc}')
                job.state = 'failed'
            job.finished = time.monotonic()
            if job.undo_steps and job.undoable and job.state in ('done', 'cancelled'):
                self._push(Action(job.undo_label or job.label, job.undo_steps, job.redo_steps))
            job.notify(True)
            if self.on_job_done:
                self.dispatch(lambda: self.on_job_done(job))

    # -- API (each returns the Job)
    def copy(self, sources, dest, policy=None):
        job = Job('copy', sources, dest, 'Copy', policy=policy)
        job.undo_label = 'Copy'
        return self.submit(job, lambda j: _transfer(self, j, move=False))

    def move(self, sources, dest, policy=None):
        job = Job('move', sources, dest, 'Move', policy=policy)
        job.undo_label = 'Move'
        return self.submit(job, lambda j: _transfer(self, j, move=True))

    def duplicate(self, sources):
        sources = [gfile(s) for s in sources]
        job = Job('duplicate', sources, None, 'Duplicate')
        job.undo_label = 'Duplicate'
        return self.submit(job, lambda j: _transfer(self, j, move=False, duplicate=True))

    def rename(self, path, new_name):
        job = Job('rename', [path], None, 'Rename', new_name=new_name)
        job.undo_label = 'Rename'
        return self.submit(job, lambda j: _rename(self, j))

    def new_folder(self, parent, name='untitled folder'):
        job = Job('new-folder', [], parent, 'New Folder', name=name)
        job.undo_label = 'New Folder'
        return self.submit(job, lambda j: _create(j, folder=True))

    def new_file(self, parent, name='untitled'):
        job = Job('new-file', [], parent, 'New File', name=name)
        job.undo_label = 'New File'
        return self.submit(job, lambda j: _create(j, folder=False))

    def trash(self, paths):
        job = Job('trash', paths, None, 'Move to Trash')
        job.undo_label = 'Move to Trash'
        return self.submit(job, _trash)

    def restore(self, items):
        job = Job('restore', [], None, 'Put Back', items=list(items))
        job.undo_label = 'Put Back'
        return self.submit(job, _restore)

    def delete(self, paths):
        job = Job('delete', paths, None, 'Delete')
        job.undoable = False
        return self.submit(job, _delete)

    def empty_trash(self):
        job = Job('empty-trash', [], None, 'Empty Trash')
        job.undoable = False
        return self.submit(job, _empty_trash)

    def compress(self, paths, dest_dir, fmt='zip', name=None):
        job = Job('compress', paths, dest_dir, 'Compress', fmt=fmt, name=name)
        job.undo_label = 'Compress'
        return self.submit(job, _compress)

    def extract(self, archive, dest_dir=None):
        job = Job('extract', [archive], dest_dir, 'Extract')
        job.undo_label = 'Extract'
        return self.submit(job, _extract)

    def undo(self):
        return self._history_job('undo')

    def redo(self):
        return self._history_job('redo')

    def _history_job(self, which):
        with self._lock:
            stack = self.history if which == 'undo' else self.future
            if not stack:
                return None
            action = stack.pop()
        job = Job(which, [], None, f'{which.title()} {action.label}')
        job.undoable = False

        def body(j):
            try:
                getattr(action, which)(j)
            except Exception:
                with self._lock:   # keep the action so the user can retry once the cause is fixed
                    stack.append(action)
                self._changed()
                raise
            with self._lock:
                (self.future if which == 'undo' else self.history).append(action)
            j.done_items = 1
            self._changed()
        return self.submit(job, body)


# ---------------------------------------------------------------- job bodies

def _scan(job, files):
    """Count bytes/items for progress. Never follows symlinks."""
    for f in files:
        job.check()
        try:
            t = ftype(f)
        except GLib.Error:
            continue
        job.total_items += 1
        if t == Gio.FileType.DIRECTORY:
            if is_local(f):
                for root, dirs, names in os.walk(f.get_path(), followlinks=False, onerror=lambda e: None):
                    job.check()
                    job.total_items += len(dirs) + len(names)
                    for n in names:
                        try:
                            job.total_bytes += os.lstat(os.path.join(root, n)).st_size
                        except OSError:
                            pass
            else:
                try:
                    stack = [f]
                    while stack:
                        d = stack.pop()
                        for c, ct in children(d, job.cancellable):
                            job.total_items += 1
                            if ct == Gio.FileType.DIRECTORY:
                                stack.append(c)
                            else:
                                job.total_bytes += c.query_info('standard::size', NOFOLLOW, None).get_size()
                except GLib.Error:
                    pass
        else:
            try:
                job.total_bytes += f.query_info('standard::size', NOFOLLOW, None).get_size()
            except GLib.Error:
                pass


def _check_space(job, dest, move):
    if not is_local(dest) or job.total_bytes <= 0:
        return
    try:
        free = shutil.disk_usage(dest.get_path()).free
    except OSError:
        return
    if job.total_bytes > free:
        raise OperationError(f'There is not enough free space on the destination: {model.human_size(job.total_bytes)} '
                             f'needed, {model.human_size(free)} available.')


def _inside(child, parent):
    if child.equal(parent) or child.has_prefix(parent):
        return True
    if is_local(child) and is_local(parent):
        c, p = os.path.realpath(child.get_path()), os.path.realpath(parent.get_path())
        return c == p or c.startswith(p.rstrip('/') + '/')
    return False


def _resolve(engine, job, src, dst):
    if job.policy in (REPLACE, KEEP_BOTH, SKIP):
        return job.policy
    if engine.ask is None:
        return KEEP_BOTH
    res, every = engine.ask(job, src, dst)
    job.check()
    if every:
        job.policy = res
    return res


def _transfer(engine, job, move, duplicate=False):
    sources = job.sources
    if not duplicate and job.dest is None:
        raise OperationError('Choose a destination folder.')
    if job.dest is not None:
        try:
            if ftype(job.dest) != Gio.FileType.DIRECTORY:
                raise OperationError('The destination is not a folder.')
        except GLib.Error as err:
            raise OperationError(gio_text(err, display(job.dest))) from None
    job.current = 'Preparing…'
    job.notify(True)
    _scan(job, sources)
    if job.dest is not None and not (move and all(is_local(s) for s in sources) and _same_fs(sources, job.dest)):
        _check_space(job, job.dest, move)
    undo, redo = [], []
    for src in sources:
        job.check()
        name = display(src)
        dest_dir = job.dest if job.dest is not None else src.get_parent()
        if dest_dir is None:
            job.fail(name, 'This item has no parent folder.')
            continue
        try:
            if ftype(src) == Gio.FileType.DIRECTORY and _inside(dest_dir, src) and not duplicate:
                job.fail(name, f'“{name}” cannot be {"moved" if move else "copied"} into itself.')
                continue
            made = _transfer_item(engine, job, src, dest_dir, name, move, duplicate, undo)
        except model.Cancelled:
            raise
        except OperationError as exc:
            job.fail(name, str(exc))
            continue
        except GLib.Error as err:
            if err.matches(Gio.io_error_quark(), _IOE.CANCELLED):
                raise model.Cancelled()
            job.fail(name, gio_text(err, name))
            if err.matches(Gio.io_error_quark(), _IOE.NO_SPACE):
                break
            continue
        if made is not None:
            job.results.append(made.get_uri() if not is_local(made) else made.get_path())
        job.done_items += 1
        job.notify()
    job.undo_steps = list(reversed(undo))
    job.redo_steps = []
    # copy: undo = trash the created items; their redo restores them. move: undo = move back.
    job.notify(True)


def _same_fs(sources, dest):
    try:
        d = os.stat(dest.get_path()).st_dev
        return all(os.lstat(s.get_path()).st_dev == d for s in sources)
    except OSError:
        return False


def _transfer_item(engine, job, src, dest_dir, name, move, duplicate, undo):
    """Copy/move one top-level item. Appends undo steps (in forward order). Returns the final Gio.File or None."""
    dst = dest_dir.get_child(name)
    if exists(dst):
        same = src.equal(dst)
        if same or duplicate:
            if move and same:
                return dst                     # moving onto itself is a no-op
            dst = unique_child(dest_dir, name)  # duplicate / copy into own folder
        else:
            res = _resolve(engine, job, src, dst)
            if res == SKIP:
                job.skipped += 1
                return None
            if res == KEEP_BOTH:
                dst = unique_child(dest_dir, name)
            elif res == REPLACE:
                return _replace(engine, job, src, dst, move, undo)
    return _put(job, src, dst, move, undo)


def _replace(engine, job, src, dst, move, undo):
    st, dt = ftype(src), ftype(dst)
    if st == Gio.FileType.DIRECTORY and dt == Gio.FileType.DIRECTORY:
        return _merge(engine, job, src, dst, move, undo)
    # Move the old item to the Trash so Replace can be undone; otherwise overwrite directly.
    restore = None
    if dt == Gio.FileType.DIRECTORY:
        raise OperationError(f'“{display(dst)}” is a folder; it cannot be replaced by a file.')
    try:
        restore = trash_one(dst)
    except NeedsPermanentDelete:
        restore = None
    except OperationError:
        restore = None
    if restore is not None:
        undo.append(restore)       # forward order [restore-old, undo-put]; reversed at the end => put first, then old
    return _put(job, src, dst, move, undo, overwrite=restore is None)


def _merge(engine, job, src, dst, move, undo):
    """Replace folder = merge: files with the same name go through conflict handling again."""
    for child, ct in list(children(src, job.cancellable)):
        job.check()
        name = display(child)
        try:
            _transfer_item(engine, job, child, dst, name, move, False, undo)
        except OperationError as exc:
            job.fail(name, str(exc))
        except GLib.Error as err:
            if err.matches(Gio.io_error_quark(), _IOE.CANCELLED):
                raise model.Cancelled()
            job.fail(name, gio_text(err, name))
    if move:
        try:
            src.delete(None)    # only succeeds if emptied; leftovers (skipped items) stay put
        except GLib.Error:
            pass
    return dst


def _progress_cb(job, base):
    def cb(current, total, _data=None):
        job.done_bytes = base + current
        job.notify()
    return cb


def _put(job, src, dst, move, undo, overwrite=False):
    """Create ``dst`` from ``src`` (which must not exist unless overwrite)."""
    job.check()
    job.current = display(src)
    t = ftype(src)
    flags = Gio.FileCopyFlags.ALL_METADATA | Gio.FileCopyFlags.NOFOLLOW_SYMLINKS
    if overwrite:
        flags |= Gio.FileCopyFlags.OVERWRITE
    if t == Gio.FileType.DIRECTORY:
        if move:
            try:
                src.move(dst, flags, job.cancellable, None, None)
                undo.append(MoveStep(dst.get_uri() if not is_local(dst) else dst.get_path(),
                                     src.get_uri() if not is_local(src) else src.get_path()))
                job.done_bytes = job.total_bytes
                return dst
            except GLib.Error as err:
                if not (err.matches(Gio.io_error_quark(), _IOE.WOULD_RECURSE) or err.matches(Gio.io_error_quark(), _IOE.NOT_SUPPORTED)):
                    raise
        before = len(job.errors)
        dst.make_directory(job.cancellable)
        _copy_dir_contents(job, src, dst, move)
        try:
            src.copy_attributes(dst, Gio.FileCopyFlags.ALL_METADATA, None)
        except GLib.Error:
            pass
        if move and len(job.errors) == before:
            try:
                delete_path(src)
            except GLib.Error as err:
                job.fail(display(src), 'Copied, but the original could not be removed: ' + gio_text(err))
        _record_created(undo, move, src, dst)
        return dst
    base = job.done_bytes
    cb = _progress_cb(job, base)
    if move:
        try:
            src.move(dst, flags, job.cancellable, cb, None)
            undo.append(MoveStep(dst.get_uri() if not is_local(dst) else dst.get_path(),
                                 src.get_uri() if not is_local(src) else src.get_path()))
            job.done_bytes = base + _size(dst)
            return dst
        except GLib.Error:
            raise
    src.copy(dst, flags, job.cancellable, cb, None)
    job.done_bytes = base + _size(dst)
    _record_created(undo, False, src, dst)
    return dst


def _size(f):
    try:
        return f.query_info('standard::size', NOFOLLOW, None).get_size()
    except GLib.Error:
        return 0


def _record_created(undo, move, src, dst):
    if move:
        undo.append(MoveStep(dst.get_uri() if not is_local(dst) else dst.get_path(),
                             src.get_uri() if not is_local(src) else src.get_path()))
    else:
        undo.append(TrashStep(dst.get_path() if is_local(dst) else dst.get_uri()))


def _copy_dir_contents(job, src, dst, move):
    for child, ct in list(children(src, job.cancellable)):
        job.check()
        target = dst.get_child(display(child))
        job.current = display(child)
        try:
            if ct == Gio.FileType.DIRECTORY:
                target.make_directory(job.cancellable)
                _copy_dir_contents(job, child, target, move)
                try:
                    child.copy_attributes(target, Gio.FileCopyFlags.ALL_METADATA, None)
                except GLib.Error:
                    pass
            else:
                base = job.done_bytes
                child.copy(target, Gio.FileCopyFlags.ALL_METADATA | Gio.FileCopyFlags.NOFOLLOW_SYMLINKS,
                           job.cancellable, _progress_cb(job, base), None)
                job.done_bytes = base + _size(target)
            job.done_items += 1
        except model.Cancelled:
            raise
        except GLib.Error as err:
            if err.matches(Gio.io_error_quark(), _IOE.CANCELLED):
                raise model.Cancelled()
            job.fail(display(child), gio_text(err, display(child)))
            if err.matches(Gio.io_error_quark(), _IOE.NO_SPACE):
                raise OperationError(gio_text(err))
        job.notify()


def _rename(engine, job):
    src = job.sources[0]
    new = job.opts['new_name']
    problem = model.valid_name(new)
    if problem:
        raise OperationError(problem)
    parent = src.get_parent()
    dst = parent.get_child(new)
    if display(src) == new:
        return
    if exists(dst):
        # A case-only rename on a case-insensitive filesystem would match itself; real clashes fail.
        raise OperationError(f'An item named “{new}” already exists in this folder.')
    try:
        src.move(dst, Gio.FileCopyFlags.NOFOLLOW_SYMLINKS | Gio.FileCopyFlags.ALL_METADATA, None, None, None)
    except GLib.Error as err:
        raise OperationError(gio_text(err, display(src))) from None
    job.results.append(dst.get_path() or dst.get_uri())
    job.done_items = 1
    job.undo_steps = [MoveStep(dst.get_path() or dst.get_uri(), src.get_path() or src.get_uri())]
    try:
        from . import tags
        if is_local(src):
            tags.STORE.rename_in_index(src.get_path(), dst.get_path())
    except Exception:
        pass


def _create(job, folder):
    parent = job.dest
    base = job.opts['name']
    target = numbered_child(parent, base)
    try:
        if folder:
            target.make_directory(None)
        else:
            target.create(Gio.FileCreateFlags.NONE, None).close(None)
    except GLib.Error as err:
        raise OperationError(gio_text(err, display(target))) from None
    job.results.append(target.get_path() or target.get_uri())
    job.done_items = 1
    path = target.get_path() or target.get_uri()
    job.undo_steps = [TrashStep(path)]


def _trash(job):
    job.total_items = len(job.sources)
    undo = []
    permanent = []
    for src in job.sources:
        job.check()
        job.current = display(src)
        try:
            if not exists(src):
                job.fail(display(src), 'The item no longer exists.')
                continue
            step = trash_one(src)
            undo.append(step)
            job.done_items += 1
        except NeedsPermanentDelete as exc:
            permanent.append(src)
            job.fail(display(src), str(exc))
        except OperationError as exc:
            job.fail(display(src), str(exc))
        except GLib.Error as err:
            job.fail(display(src), gio_text(err, display(src)))
        job.notify()
    job.opts['permanent_candidates'] = permanent
    job.undo_steps = list(reversed([s if s is not None else _Irreversible() for s in undo]))


class _Irreversible(Step):
    def run(self, job):
        raise OperationError('This item can no longer be located in the Trash.')


def _restore(job):
    items = job.opts['items']
    job.total_items = len(items)
    undo = []
    for it in items:
        job.check()
        try:
            target = it.orig
            if not target:
                raise OperationError('The original location of this item is unknown.')
            if os.path.lexists(target):
                parent = Gio.File.new_for_path(os.path.dirname(target))
                target = unique_child(parent, os.path.basename(target), ' restored').get_path()
            trashlib.restore(it, target)
            undo.append(TrashStep(target))
            job.results.append(target)
            job.done_items += 1
        except OperationError as exc:
            job.fail(it.name, str(exc))
        except OSError as exc:
            job.fail(it.name, model.human_error(exc, it.name))
        job.notify()
    job.undo_steps = list(reversed(undo))


def _delete(job):
    job.total_items = len(job.sources)
    for src in job.sources:
        job.check()
        job.current = display(src)
        try:
            delete_path(src, job.cancellable)
            job.done_items += 1
        except GLib.Error as err:
            if err.matches(Gio.io_error_quark(), _IOE.CANCELLED):
                raise model.Cancelled()
            job.fail(display(src), gio_text(err, display(src)))
        job.notify()


def _empty_trash(job):
    items = trashlib.list_trash()
    job.total_items = len(items)
    for it in items:
        job.check()
        job.current = it.name
        try:
            trashlib.delete_item(it)
            job.done_items += 1
        except Exception as exc:
            job.fail(it.name, getattr(exc, 'message', None) or str(exc))
        job.notify()
    if not job.cancelled:
        trashlib.empty()      # sweeps orphaned .trashinfo files


def _compress(job):
    from . import archive
    dest_dir = job.dest
    sources = [s.get_path() for s in job.sources if is_local(s)]
    if not sources:
        raise OperationError('Only local items can be compressed.')
    fmt = job.opts.get('fmt', 'zip')
    suffix = archive.SUFFIX[fmt]
    if job.opts.get('name'):
        base = job.opts['name']
    elif len(sources) == 1:
        base = os.path.basename(sources[0]) + suffix
    else:
        base = 'Archive' + suffix
    target = numbered_child(dest_dir, base)
    _scan(job, job.sources)
    out = archive.compress(sources, target.get_path(), fmt, progress=lambda n: _bump(job, n, target.get_path()),
                           cancel=job.cancellable.is_cancelled)
    job.results.append(out)
    job.done_items = job.total_items
    job.undo_steps = [TrashStep(out)]


def _bump(job, nbytes, current):
    job.done_bytes += nbytes
    job.current = os.path.basename(current)
    job.notify()


def _extract(job):
    from . import archive
    src = job.sources[0]
    if not is_local(src):
        raise OperationError('Only local archives can be extracted.')
    dest_dir = job.dest or src.get_parent()
    path = src.get_path()
    stem = archive.strip_suffix(os.path.basename(path))
    target = numbered_child(dest_dir, stem)
    try:
        out = archive.extract(path, target.get_path(), progress=lambda n, name: _bump(job, n, name),
                              cancel=job.cancellable.is_cancelled)
    except archive.ArchiveError as exc:
        raise OperationError(str(exc)) from None
    job.results.append(out)
    job.done_items = 1
    job.undo_steps = [TrashStep(out)]
