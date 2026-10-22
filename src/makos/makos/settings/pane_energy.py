"""Energy Saver: power profile, battery health, lid action and charge limit (privileged parts through the polkit helper)."""
from ..backends import powermgmt
from . import widgets as W


def build(col, ctx):
    def load():
        return {'battery': powermgmt.battery(), 'profiles': powermgmt.profiles(), 'threshold': powermgmt.threshold(),
                'lid': powermgmt.lid_action(), 'powerdevil': powermgmt.powerdevil_running()}

    def render(box, info):
        s = W.section(box, 'Battery')
        b = info['battery']
        if not b:
            W.note(s, 'No battery was found: this computer runs on mains power.')
        else:
            line = f"{b['percent']} %, {b['state']}"
            if b['state'] == 'discharging' and b['time_to_empty']:
                line += f", about {powermgmt.duration(b['time_to_empty'])} left"
            if b['state'] == 'charging' and b['time_to_full']:
                line += f", {powermgmt.duration(b['time_to_full'])} until full"
            W.note(s, line, 'title-label')
            W.note(s, 'Battery health: ' + (f"{b['health']} % of design capacity" if b['health'] else 'not reported by this battery'))
            th = info['threshold']
            if th['supported']:
                W.scale_row(s, 'Charge limit', 50, 100, 5, th['value'], lambda v: ctx.do(powermgmt.set_threshold, round(v), ok='Charge limit set.'),
                            fmt=lambda v: f'{int(v)} %', hint='Needs your administrator password through the system authentication dialog.')
            else:
                W.note(s, 'This computer does not offer a charge limit.')
        s = W.section(box, 'Performance')
        prof = info['profiles']
        if prof['available']:
            W.choice_row(s, 'Power profile', [(n, t) for n, t in powermgmt.PROFILES if n in prof['available']], prof['current'],
                         lambda v: ctx.do(powermgmt.set_profile, v, ok='Power profile changed.'))
        else:
            W.unavailable(s, 'The power profiles service (power-profiles-daemon) is not available.')
        s = W.section(box, 'When the lid closes')
        W.choice_row(s, 'Closing the lid', powermgmt.LID_CHOICES, info['lid'] or 'suspend',
                     lambda v: ctx.do(powermgmt.set_lid_action, v, ok='Lid action saved (applies after logind reloads or at the next boot).'),
                     hint='Writes one logind drop-in file after you authenticate. Delete /etc/systemd/logind.conf.d/50-makos-lid.conf to undo it.')
        s = W.section(box, 'Idle')
        if info['powerdevil']:
            opts = powermgmt.power_options('AC')
            W.choice_row(s, 'When idle', powermgmt.ACTIONS, opts['idle_action'], lambda v: ctx.do(powermgmt.set_power_options, 'AC', idle_action=v, ok='Saved.'))
            W.scale_row(s, 'Turn the display off after', 1, 60, 1, opts['screen_off_minutes'],
                        lambda v: ctx.do(powermgmt.set_power_options, 'AC', screen_off_minutes=round(v), ok='Saved.'), fmt=lambda v: f'{int(v)} min')
        else:
            W.unavailable(s, 'Idle sleep and display-off timing is not available: the power management service (powerdevil) is not running in this session. The screen lock timer is in Security.')
    W.loading(col, load, render)
