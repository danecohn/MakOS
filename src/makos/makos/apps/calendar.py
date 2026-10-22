"""Calendar: local events stored one-per-file as RFC 5545 .ics, recurrence and display alarms."""
import calendar as pycal
import datetime as dt
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, Gio, GLib
from .. import ui
from .base import AppWindow, data_dir, atomic_write, notify

FREQS = ('DAILY', 'WEEKLY', 'MONTHLY', 'YEARLY')
DAYS = ('MO', 'TU', 'WE', 'TH', 'FR', 'SA', 'SU')


@dataclass
class Event:
    summary: str
    start: dt.datetime
    end: dt.datetime
    all_day: bool = False
    location: str = ''
    description: str = ''
    rrule: str = ''
    alarm_minutes: int = -1  # -1 = none
    uid: str = field(default_factory=lambda: uuid.uuid4().hex + '@makos.local')

    @property
    def filename(self):
        return re.sub(r'[^A-Za-z0-9._-]', '_', self.uid.split('@')[0]) + '.ics'


# ---------------------------------------------------------------- iCalendar text
def esc(text):
    return text.replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\r\n', '\n').replace('\n', '\\n')


def unesc(text):
    out, i = [], 0
    while i < len(text):
        if text[i] == '\\' and i + 1 < len(text):
            out.append('\n' if text[i + 1] in 'nN' else text[i + 1])
            i += 2
        else:
            out.append(text[i])
            i += 1
    return ''.join(out)


def fold(line):
    raw = line.encode('utf-8')
    if len(raw) <= 75:
        return line
    parts, current = [], ''
    for ch in line:
        if len((current + ch).encode('utf-8')) > (75 if not parts else 74):
            parts.append(current)
            current = ch
        else:
            current += ch
    parts.append(current)
    return '\r\n '.join(parts)


def to_ics(event):
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//MakOS//Calendar//EN', 'BEGIN:VEVENT', 'UID:' + event.uid, 'DTSTAMP:' + stamp]
    if event.all_day:
        lines += ['DTSTART;VALUE=DATE:' + event.start.strftime('%Y%m%d'), 'DTEND;VALUE=DATE:' + (event.end if event.end > event.start else event.start + dt.timedelta(days=1)).strftime('%Y%m%d')]
    else:
        lines += ['DTSTART:' + event.start.strftime('%Y%m%dT%H%M%S'), 'DTEND:' + event.end.strftime('%Y%m%dT%H%M%S')]
    lines.append('SUMMARY:' + esc(event.summary))
    for key, value in (('LOCATION', event.location), ('DESCRIPTION', event.description)):
        if value:
            lines.append(f'{key}:{esc(value)}')
    if event.rrule:
        lines.append('RRULE:' + event.rrule)
    if event.alarm_minutes >= 0:
        lines += ['BEGIN:VALARM', 'ACTION:DISPLAY', 'DESCRIPTION:' + esc(event.summary), f'TRIGGER:-PT{event.alarm_minutes}M', 'END:VALARM']
    lines += ['END:VEVENT', 'END:VCALENDAR']
    return '\r\n'.join(fold(l) for l in lines) + '\r\n'


def _parse_time(key, value):
    value = value.strip()
    if 'VALUE=DATE' in key or re.fullmatch(r'\d{8}', value):
        return dt.datetime.strptime(value[:8], '%Y%m%d'), True
    when = dt.datetime.strptime(value.rstrip('Z')[:15], '%Y%m%dT%H%M%S')
    if value.endswith('Z'):
        when = when.replace(tzinfo=dt.timezone.utc).astimezone().replace(tzinfo=None)
    return when, False


def _trigger_minutes(value):
    m = re.fullmatch(r'-P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?', value.strip())
    if not m or not any(m.groups()):
        return None
    d, h, mi, s = (int(g or 0) for g in m.groups())
    return d * 1440 + h * 60 + mi + s // 60


def parse_ics(text):
    lines = []
    for raw in text.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
        if raw[:1] in (' ', '\t') and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    events, current, in_alarm = [], None, False
    for line in lines:
        if ':' not in line:
            continue
        key, value = line.split(':', 1)
        name = key.split(';')[0].upper()
        if name == 'BEGIN' and value == 'VEVENT':
            current, in_alarm = {'alarm': -1}, False
        elif name == 'BEGIN' and value == 'VALARM':
            in_alarm = True
        elif name == 'END' and value == 'VALARM':
            in_alarm = False
        elif name == 'END' and value == 'VEVENT' and current is not None:
            if 'start' in current:
                start, all_day = current['start']
                end = current.get('end', (start + dt.timedelta(days=1), True))[0] if all_day else current.get('end', (start + dt.timedelta(hours=1), False))[0]
                events.append(Event(current.get('summary', ''), start, end, all_day, current.get('location', ''), current.get('description', ''),
                                    current.get('rrule', ''), current['alarm'], current.get('uid') or uuid.uuid4().hex + '@makos.local'))
            current = None
        elif current is not None:
            try:
                if in_alarm:
                    if name == 'TRIGGER':
                        minutes = _trigger_minutes(value)
                        if minutes is not None:
                            current['alarm'] = minutes
                elif name == 'DTSTART':
                    current['start'] = _parse_time(key, value)
                elif name == 'DTEND':
                    current['end'] = _parse_time(key, value)
                elif name in ('SUMMARY', 'LOCATION', 'DESCRIPTION'):
                    current[name.lower()] = unesc(value)
                elif name in ('UID', 'RRULE'):
                    current[name.lower()] = value
            except ValueError:
                current = None
    return events


# ---------------------------------------------------------------- recurrence and alarms
def parse_rrule(rule):
    parts = dict(p.split('=', 1) for p in rule.split(';') if '=' in p)
    freq = parts.get('FREQ', '')
    if freq not in FREQS:
        return None
    try:
        interval = max(1, int(parts.get('INTERVAL', 1)))
        count = int(parts['COUNT']) if 'COUNT' in parts else None
    except ValueError:
        return None
    until = None
    if 'UNTIL' in parts:
        try:
            until = dt.datetime.strptime(parts['UNTIL'][:8], '%Y%m%d') + dt.timedelta(days=1)
        except ValueError:
            return None
    byday = [DAYS.index(d[-2:]) for d in parts.get('BYDAY', '').split(',') if d[-2:] in DAYS]
    return freq, interval, count, until, byday


def occurrences(event, begin, finish, limit=2000):
    """Start datetimes of event instances overlapping [begin, finish)."""
    length = event.end - event.start
    rule = parse_rrule(event.rrule) if event.rrule else None
    out = []
    if not rule:
        if event.start < finish and event.start + max(length, dt.timedelta(seconds=1)) > begin:
            out.append(event.start)
        return out
    freq, interval, count, until, byday = rule
    produced, n = 0, 0
    day0 = event.start
    while n < 20000 and produced < limit:
        if freq == 'DAILY':
            cands = [day0 + dt.timedelta(days=interval * n)]
        elif freq == 'WEEKLY':
            monday = day0 - dt.timedelta(days=day0.weekday()) + dt.timedelta(weeks=interval * n)
            cands = [monday + dt.timedelta(days=d) for d in sorted(byday or [day0.weekday()])]
        elif freq == 'MONTHLY':
            month = day0.month - 1 + interval * n
            year, mon = day0.year + month // 12, month % 12 + 1
            if day0.day > pycal.monthrange(year, mon)[1]:
                n += 1
                continue
            cands = [day0.replace(year=year, month=mon)]
        else:
            year = day0.year + interval * n
            try:
                cands = [day0.replace(year=year)]
            except ValueError:
                n += 1
                continue
        n += 1
        for c in cands:
            if c < event.start:
                continue
            if until and c >= until or (count is not None and produced >= count):
                return out
            produced += 1
            if c + max(length, dt.timedelta(seconds=1)) > begin and c < finish:
                out.append(c)
        if cands and cands[0] >= finish:
            break
    return out


def due_alarms(events, after, until):
    """(event, occurrence start) whose alarm time lies in (after, until]."""
    out = []
    for e in events:
        if e.alarm_minutes < 0:
            continue
        lead = dt.timedelta(minutes=e.alarm_minutes)
        for start in occurrences(e, after + lead, until + lead + dt.timedelta(seconds=1)):
            if after < start - lead <= until:
                out.append((e, start))
    return out


class CalendarStore:
    def __init__(self, root=None):
        self.root = Path(root) if root else data_dir('calendar')
        self.root.mkdir(parents=True, exist_ok=True)

    def all(self):
        events = []
        for p in sorted(self.root.glob('*.ics')):
            try:
                events += parse_ics(p.read_text(encoding='utf-8', errors='replace'))
            except OSError:
                pass
        return events

    def save(self, event):
        atomic_write(self.root / event.filename, to_ics(event), 0o600)

    def remove(self, event):
        """Moves the file to .deleted/ so a mistaken delete can be recovered by hand."""
        src = self.root / event.filename
        if src.exists():
            (self.root / '.deleted').mkdir(exist_ok=True)
            src.replace(self.root / '.deleted' / event.filename)

    def on_day(self, day):
        begin = dt.datetime.combine(day, dt.time())
        found = []
        for e in self.all():
            for start in occurrences(e, begin, begin + dt.timedelta(days=1)):
                found.append((start, e))
        return sorted(found, key=lambda t: (not t[1].all_day, t[0]))


MENU = [('File', [('New Event…', 'new_event', '<Primary>n'), None, ('Close', 'close', '<Primary>w')]),
        ('View', [('Today', 'today', '<Primary>t'), ('Previous Month', 'prev', '<Primary>Left'), ('Next Month', 'next', '<Primary>Right')])]
REPEATS = [('Never', ''), ('Daily', 'FREQ=DAILY'), ('Weekly', 'FREQ=WEEKLY'), ('Monthly', 'FREQ=MONTHLY'), ('Yearly', 'FREQ=YEARLY')]
ALARMS = [('None', -1), ('At time of event', 0), ('5 minutes before', 5), ('15 minutes before', 15), ('1 hour before', 60), ('1 day before', 1440)]


class Calendar:
    def __init__(self, app, store=None):
        self.store = store or CalendarStore()
        today = dt.date.today()
        self.year, self.month, self.selected = today.year, today.month, today
        self.last_check = dt.datetime.now()
        self.aw = AppWindow(app, 'Calendar', 940, 640, MENU)
        self.win = self.aw.win
        for name, fn in (('new_event', lambda: self.edit(None)), ('close', self.win.close), ('today', self.go_today), ('prev', lambda: self.shift(-1)), ('next', lambda: self.shift(1))):
            self.aw.action(name, fn)
        top = ui.box(spacing=6, css='metal-toolbar')
        self.title = Gtk.Label(label='', hexpand=True, css_classes=['hero'])
        top.append(ui.button('‹', lambda: self.shift(-1)))
        top.append(self.title)
        top.append(ui.button('›', lambda: self.shift(1)))
        top.append(ui.button('Today', self.go_today))
        top.append(ui.button('New Event', lambda: self.edit(None), 'suggested-action'))
        self.grid = Gtk.Grid(column_homogeneous=True, row_homogeneous=False, column_spacing=2, row_spacing=2, hexpand=True, vexpand=True)
        side = ui.box(True, 6, 'sheet')
        side.set_size_request(280, -1)
        self.day_title = Gtk.Label(label='', xalign=0, css_classes=['title-label'])
        self.day_list = ui.box(True, 4)
        side.append(self.day_title)
        side.append(ui.scroll(self.day_list))
        row = ui.box()
        mainbox = ui.box(True, 6, 'sheet')
        mainbox.set_hexpand(True)
        mainbox.append(self.grid)
        row.append(mainbox)
        row.append(side)
        self.aw.body.append(top)
        self.aw.body.append(row)
        GLib.timeout_add_seconds(20, self.tick_alarms)
        self.render()

    def go_today(self):
        t = dt.date.today()
        self.year, self.month, self.selected = t.year, t.month, t
        self.render()

    def shift(self, step):
        m = self.month - 1 + step
        self.year, self.month = self.year + m // 12, m % 12 + 1
        self.render()

    def render(self):
        ui.clear(self.grid)
        self.title.set_text(dt.date(self.year, self.month, 1).strftime('%B %Y'))
        for i, name in enumerate(pycal.day_abbr):
            self.grid.attach(Gtk.Label(label=name, css_classes=['section-title']), i, 0, 1, 1)
        weeks = pycal.Calendar(firstweekday=0).monthdatescalendar(self.year, self.month)
        first = dt.datetime.combine(weeks[0][0], dt.time())
        events = self.store.all()
        for r, week in enumerate(weeks):
            for c, day in enumerate(week):
                begin = dt.datetime.combine(day, dt.time())
                titles = [e.summary for e in events if occurrences(e, begin, begin + dt.timedelta(days=1))][:3]
                col = ui.box(True, 1)
                col.append(Gtk.Label(label=str(day.day), xalign=0, css_classes=['title-label'] if day == dt.date.today() else []))
                for t in titles:
                    col.append(Gtk.Label(label='• ' + t, xalign=0, ellipsize=3, css_classes=['hint']))
                b = Gtk.Button(css_classes=['tile'] + (['selected'] if day == self.selected else []) + (['dim'] if day.month != self.month else []))
                b.set_child(col)
                b.set_size_request(80, 72)
                b.set_hexpand(True)
                b.set_vexpand(True)
                if day.month != self.month:
                    b.set_opacity(.55)
                b.connect('clicked', lambda _b, d=day: self.select(d))
                self.grid.attach(b, c, r + 1, 1, 1)
        self.show_day()

    def select(self, day):
        self.selected = day
        self.render()

    def show_day(self):
        ui.clear(self.day_list)
        self.day_title.set_text(self.selected.strftime('%A, %B %d'))
        found = self.store.on_day(self.selected)
        for start, event in found:
            when = 'All day' if event.all_day else start.strftime('%H:%M') + ' – ' + (start + (event.end - event.start)).strftime('%H:%M')
            b = Gtk.Button(css_classes=['tile'])
            col = ui.box(True, 1)
            col.append(Gtk.Label(label=event.summary or '(No title)', xalign=0, css_classes=['title-label']))
            col.append(Gtk.Label(label=when + ('   ↻' if event.rrule else '') + ('   🔔' if event.alarm_minutes >= 0 else ''), xalign=0, css_classes=['hint']))
            b.set_child(col)
            b.connect('clicked', lambda _b, e=event: self.edit(e))
            self.day_list.append(b)
        if not found:
            self.day_list.append(Gtk.Label(label='No events', css_classes=['hint']))
        self.aw.say(f'{len(self.store.all())} events stored locally as .ics in {self.store.root}')

    def edit(self, event):
        new = event is None
        day = self.selected
        event = event or Event('', dt.datetime.combine(day, dt.time(9)), dt.datetime.combine(day, dt.time(10)))
        d = Gtk.Window(title='Event', transient_for=self.win, modal=True, default_width=380)
        col = ui.box(True, 8, 'sheet')
        title = Gtk.Entry(text=event.summary, placeholder_text='Title')
        date = Gtk.Entry(text=event.start.strftime('%Y-%m-%d'))
        start = Gtk.Entry(text=event.start.strftime('%H:%M'), width_chars=6)
        end = Gtk.Entry(text=event.end.strftime('%H:%M') if not event.all_day else '10:00', width_chars=6)
        allday = Gtk.CheckButton(label='All day', active=event.all_day)
        loc = Gtk.Entry(text=event.location, placeholder_text='Location')
        notes = Gtk.Entry(text=event.description, placeholder_text='Notes')
        repeat = Gtk.DropDown.new_from_strings([r[0] for r in REPEATS])
        alarm = Gtk.DropDown.new_from_strings([a[0] for a in ALARMS])
        base_rule = event.rrule.split(';')[0] if event.rrule else ''
        repeat.set_selected(next((i for i, r in enumerate(REPEATS) if r[1] == base_rule), 0))
        alarm.set_selected(next((i for i, a in enumerate(ALARMS) if a[1] == event.alarm_minutes), 0))
        err = Gtk.Label(label='', css_classes=['error-text'])
        times = ui.box(spacing=6)
        for w in (date, start, Gtk.Label(label='to'), end, allday):
            times.append(w)
        for label, w in (('', title), ('', times), ('', loc), ('', notes), ('Repeat', repeat), ('Alert', alarm), ('', err)):
            if label:
                col.append(Gtk.Label(label=label, xalign=0, css_classes=['section-title']))
            col.append(w)

        def commit(*_):
            try:
                begin = dt.datetime.strptime(date.get_text().strip() + ' ' + (start.get_text().strip() if not allday.get_active() else '00:00'), '%Y-%m-%d %H:%M')
                finish = dt.datetime.combine(begin.date(), dt.datetime.strptime(end.get_text().strip(), '%H:%M').time()) if not allday.get_active() else begin + dt.timedelta(days=1)
            except ValueError:
                err.set_text('Use dates as YYYY-MM-DD and times as HH:MM.')
                return
            if finish <= begin and not allday.get_active():
                err.set_text('The event must end after it starts.')
                return
            event.summary, event.start, event.end, event.all_day = title.get_text().strip(), begin, finish, allday.get_active()
            event.location, event.description = loc.get_text(), notes.get_text()
            event.rrule = REPEATS[repeat.get_selected()][1]
            event.alarm_minutes = ALARMS[alarm.get_selected()][1]
            self.store.save(event)
            d.destroy()
            self.selected = begin.date()
            self.year, self.month = begin.year, begin.month
            self.render()
        buttons = ui.box(spacing=8)
        buttons.append(ui.button('Cancel', d.destroy))
        if not new:
            buttons.append(ui.button('Delete', lambda: (self.store.remove(event), d.destroy(), self.render())))
        buttons.append(ui.button('Save', commit, 'suggested-action'))
        col.append(buttons)
        d.set_child(col)
        d.present()

    def tick_alarms(self):
        now = dt.datetime.now()
        for event, start in due_alarms(self.store.all(), self.last_check, now):
            notify(event.summary or 'Event', start.strftime('%H:%M') + (' ' + event.location if event.location else ''))
        self.last_check = now
        return self.win.get_visible()


def open_window(app, path=None):
    c = Calendar(app)
    c.aw.present()
    return c
