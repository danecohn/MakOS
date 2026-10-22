"""Widget bodies for the layer. Each builder takes a context (data, save(), alive()) and returns a Gtk widget.

Timers stop as soon as the layer is closed (alive() turns false), so a hidden layer costs nothing.
"""
import datetime as dt
import threading
import time
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk, GLib
from .. import ui
from . import units, weather
from .store import MAX_NOTE


def label(text='', css=None, xalign=0.5):
    return Gtk.Label(label=text, xalign=xalign, css_classes=[css] if css else [])


def every(ctx, seconds, fn):
    fn()
    GLib.timeout_add_seconds(seconds, lambda: (fn(), True)[1] if ctx.alive() else False)


def clock(ctx):
    col = ui.box(True, 2)
    big, day = label('', 'widget-big'), label('')
    col.append(big)
    col.append(day)

    def tick():
        now = dt.datetime.now()
        big.set_text(now.strftime('%H:%M'))
        day.set_text(now.strftime('%A, %B %d'))
    every(ctx, 5, tick)
    col.set_size_request(220, -1)
    return col


def worldclock(ctx):
    col = ui.box(True, 4)
    rows = []
    from zoneinfo import ZoneInfo
    for z in ctx.data['zones']:
        line = ui.box(spacing=10)
        name, when = label(z['label'] or z['tz'], xalign=0), label('', xalign=1)
        name.set_hexpand(True)
        line.append(name)
        line.append(when)
        col.append(line)
        try:
            rows.append((when, ZoneInfo(z['tz'])))
        except Exception:  # an unknown zone name shows a dash rather than failing the layer
            when.set_text('—')

    def tick():
        now = dt.datetime.now(dt.timezone.utc)
        for w, tz in rows:
            w.set_text(now.astimezone(tz).strftime('%H:%M  %a'))
    every(ctx, 10, tick)
    col.set_size_request(240, -1)
    return col


def calendar(ctx):
    from ..apps.calendar import CalendarStore
    col = ui.box(True, 6)
    cal = Gtk.Calendar()
    upcoming = label('', 'hint', 0)
    upcoming.set_wrap(True)
    col.append(cal)
    col.append(upcoming)

    def refresh(*_):
        try:
            found = CalendarStore().on_day(dt.date.today())
        except OSError:
            found = []
        upcoming.set_text('Today: ' + ('; '.join(f"{'' if e.all_day else s.strftime('%H:%M') + ' '}{e.summary}" for s, e in found[:3]) or 'no events'))
    every(ctx, 300, refresh)
    return col


def sysmon(ctx):
    from ..apps import activity
    sampler = activity.Sampler()
    col = ui.box(True, 4)
    cpu_l, mem_l, extra = label('', xalign=0), label('', xalign=0), label('', 'hint', 0)
    cpu_bar, mem_bar = Gtk.LevelBar(min_value=0, max_value=100, css_classes=['meter']), Gtk.LevelBar(min_value=0, max_value=100, css_classes=['meter'])
    for w in (cpu_l, cpu_bar, mem_l, mem_bar, extra):
        col.append(w)
    sampler.cpu()

    def tick():
        cpu, _cores = sampler.cpu()
        mem = activity.memory()
        pct = 100 * mem['used'] / mem['total'] if mem['total'] else 0
        cpu_l.set_text(f'CPU  {cpu:.0f}%')
        cpu_bar.set_value(cpu)
        mem_l.set_text(f'Memory  {pct:.0f}%')
        mem_bar.set_value(pct)
        e = activity.energy()
        extra.set_text((f"Battery {e['battery']}% {e['status']}" if e['battery'] is not None else 'No battery') + (f"   {e['watts']:.1f} W" if e['watts'] is not None else ''))
    every(ctx, 3, tick)
    col.set_size_request(230, -1)
    return col


def calculator(ctx):
    from ..apps import calculator as calc
    col = ui.box(True, 6)
    entry = Gtk.Entry(placeholder_text='2 + 2 × 8')
    result = label('0', 'widget-big')
    result.set_xalign(1)

    def go(*_):
        try:
            result.set_text(calc.format_value(calc.evaluate(entry.get_text())))
        except ZeroDivisionError:
            result.set_text('÷0')
        except (ValueError, SyntaxError, OverflowError, TypeError):
            result.set_text('?')
    entry.connect('activate', go)
    entry.connect('changed', go)
    col.append(entry)
    col.append(result)
    col.set_size_request(240, -1)
    return col


def notes(ctx):
    view = Gtk.TextView(wrap_mode=Gtk.WrapMode.WORD_CHAR, left_margin=6, right_margin=6, top_margin=6)
    view.get_buffer().set_text(ctx.data['notes'])
    pending = [0]

    def flush():
        pending[0] = 0
        buf = view.get_buffer()
        ctx.data['notes'] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)[:MAX_NOTE]
        ctx.save()
        return False

    def changed(*_):
        if pending[0]:
            GLib.source_remove(pending[0])
        pending[0] = GLib.timeout_add(800, flush)
    view.get_buffer().connect('changed', changed)
    scroller = ui.scroll(view, 240, 150)
    scroller.set_hexpand(False)
    scroller.set_vexpand(False)
    return scroller


def converter(ctx):
    col = ui.box(True, 6)
    category = Gtk.DropDown.new_from_strings(units.CATEGORIES)
    a_entry, b_label = Gtk.Entry(text='1', width_chars=8), label('', xalign=0)
    a_unit, b_unit = Gtk.DropDown(), Gtk.DropDown()
    state = {'cat': units.CATEGORIES[0]}

    def fill(*_):
        state['cat'] = units.CATEGORIES[category.get_selected()]
        names = Gtk.StringList.new(units.units(state['cat']))
        a_unit.set_model(names)
        b_unit.set_model(Gtk.StringList.new(units.units(state['cat'])))
        b_unit.set_selected(min(1, len(units.units(state['cat'])) - 1))
        update()

    def update(*_):
        names = units.units(state['cat'])
        try:
            v = units.convert(float(a_entry.get_text().replace(',', '.')), names[a_unit.get_selected()], names[b_unit.get_selected()], state['cat'])
            b_label.set_text('= ' + units.fmt(v))
        except (ValueError, IndexError):
            b_label.set_text('= ?')
    category.connect('notify::selected', fill)
    for w in (a_unit, b_unit):
        w.connect('notify::selected', update)
    a_entry.connect('changed', update)
    row1, row2 = ui.box(spacing=6), ui.box(spacing=6)
    row1.append(a_entry)
    row1.append(a_unit)
    row2.append(b_label)
    row2.append(b_unit)
    for w in (category, row1, row2):
        col.append(w)
    fill()
    return col


def weather_card(ctx):
    col = ui.box(True, 4)
    wx = ctx.data['weather']
    big, desc, note = label('', 'widget-big'), label(''), label('', 'hint')
    note.set_wrap(True)
    switch = Gtk.Switch(active=wx['enabled'], halign=Gtk.Align.START)
    place = Gtk.Entry(placeholder_text='Place name (label only)', text=wx['label'])
    lat = Gtk.Entry(placeholder_text='Latitude', text='' if wx['latitude'] is None else str(wx['latitude']), width_chars=9)
    lon = Gtk.Entry(placeholder_text='Longitude', text='' if wx['longitude'] is None else str(wx['longitude']), width_chars=9)
    coords = ui.box(spacing=6)
    coords.append(lat)
    coords.append(lon)
    toggle = ui.box(spacing=8)
    toggle.append(Gtk.Label(label='Fetch weather online'))
    toggle.append(switch)
    for w in (big, desc, note, place, coords, toggle):
        col.append(w)

    def show():
        last = ctx.data['weather'].get('last')
        if last:
            big.set_text(f"{last['temp_c']:.0f}°C")
            desc.set_text(f"{ctx.data['weather']['label'] or 'Here'}: {last['text']}, wind {last['wind_kmh']:.0f} km/h")
            note.set_text('As of ' + time.strftime('%H:%M', time.localtime(last['fetched'])) + (' (saved)' if not ctx.data['weather']['enabled'] else ''))
        else:
            big.set_text('--')
            desc.set_text('Weather is off')
            note.set_text('Enter your coordinates and turn the switch on. Only then does this widget contact open-meteo.com (latitude and longitude are sent).')

    def fetch():
        w = ctx.data['weather']
        if not w['enabled']:
            return

        def work():
            try:
                result = weather.fetch(w['latitude'], w['longitude'])
            except (OSError, ValueError):
                result = None

            def done():
                if result:
                    w['last'] = result
                    ctx.save()
                else:
                    note.set_text('Could not reach the weather service; showing saved data.')
                show() if result else None
                return False
            GLib.idle_add(done)
        threading.Thread(target=work, daemon=True).start()

    def apply(*_):
        try:
            la, lo = float(lat.get_text().replace(',', '.')), float(lon.get_text().replace(',', '.'))
        except ValueError:
            la = lo = None
        w = ctx.data['weather']
        w['label'] = place.get_text()[:60]
        w['latitude'], w['longitude'] = la, lo
        w['enabled'] = switch.get_active() and la is not None and -90 <= la <= 90 and -180 <= lo <= 180
        if switch.get_active() and not w['enabled']:
            switch.set_active(False)
            note.set_text('Enter valid coordinates first (latitude -90..90, longitude -180..180).')
        ctx.save()
        show()
        fetch()
    switch.connect('notify::active', apply)
    place.connect('activate', apply)
    lat.connect('activate', apply)
    lon.connect('activate', apply)
    show()
    if wx['enabled']:
        last = wx.get('last')
        if not last or time.time() - last.get('fetched', 0) > 1800:
            fetch()
        every(ctx, 1800, lambda: None if not ctx.alive() else (fetch() if time.time() - (ctx.data['weather'].get('last') or {}).get('fetched', 0) > 1700 else None))
    col.set_size_request(250, -1)
    return col


BUILDERS = {'clock': clock, 'weather': weather_card, 'calculator': calculator, 'notes': notes, 'converter': converter, 'calendar': calendar, 'sysmon': sysmon, 'worldclock': worldclock}
