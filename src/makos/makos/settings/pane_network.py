"""Network (NetworkManager): Wi-Fi join/forget, VPN import, proxy. Passwords are never typed into Settings or stored by MakkOS:
new secured networks are joined by `nmcli --ask` in a terminal window, or in the system network editor."""
import gi

gi.require_version('Gtk', '4.0')
from gi.repository import Gio, GLib, Gtk

from .. import ui
from ..backends import accounts, netman, sysutil
from . import widgets as W


def terminal_join_command(ssid):
    """argv that opens a terminal running nmcli, which asks for the Wi-Fi password itself. The SSID is validated first."""
    ssid = netman.check_ssid(ssid)
    for term, args in (('ptyxis', ['--new-window', '--']), ('konsole', ['-e']), ('x-terminal-emulator', ['-e'])):
        if sysutil.have(term):
            return [term] + args + ['nmcli', '--ask', 'device', 'wifi', 'connect', ssid]
    return None


def build(col, ctx):
    holder = ui.box(True, 12)
    col.append(holder)

    def load():
        st = netman.status()
        if not st['available']:
            return None
        return {'status': st, 'wifi': netman.wifi_list() if st['wifi_enabled'] else [], 'vpns': netman.vpns(), 'proxy': netman.proxy_get(),
                'wired': netman.wired()}

    def reload(_r=None):
        ui.clear(holder)
        W.loading(holder, load, render)

    def join(net):
        if net['saved'] or not net['secured']:
            ctx.do(netman.join, net['ssid'], ok=f"Connected to {net['ssid']}.", done=reload)
            return
        argv = terminal_join_command(net['ssid'])
        if argv and ctx.terminal(argv):
            ctx.flash('Enter the Wi-Fi password in the terminal window; Settings never sees it.')
        else:
            ctx.flash('No terminal was found. Use the system network editor (nm-connection-editor) to join this network.', True)

    def render(box, info):
        if info is None:
            W.unavailable(box, 'NetworkManager is not available.')
            return
        st = info['status']
        s = W.section(box, 'Wi-Fi')
        W.note(s, ('Connected to ' + st['connection']) if st['connection'] else 'Not connected.')
        W.switch_row(s, 'Wi-Fi', st['wifi_enabled'], lambda v: ctx.do(netman.set_wifi, v, ok='Wi-Fi ' + ('on.' if v else 'off.'), done=reload))
        for net in info['wifi'][:25]:
            line = ui.box(spacing=10)
            label = net['ssid'] + ('  🔒' if net['secured'] else '') + ('  ✓' if net['connected'] else '')
            text = ui.box(True, 1)
            text.set_hexpand(True)
            text.append(Gtk.Label(label=label, xalign=0))
            text.append(Gtk.Label(label=f"{net['signal']} % • {net['kind']}" + (' • saved' if net['saved'] else ''), xalign=0, css_classes=['subtitle']))
            line.append(text)
            if not net['connected']:
                line.append(ui.button('Join', lambda n=net: join(n)))
            if net['saved']:
                uuid = next((c['uuid'] for c in netman.connections() if c['name'] == net['ssid']), None)
                if uuid:
                    line.append(ui.button('Forget', lambda u=uuid: ctx.do(netman.forget, u, ok='Network forgotten.', done=reload)))
            s.append(line)
        W.button_row(s, '', 'Scan Again', lambda: ctx.do(netman.scan, ok='Scanning…', done=reload))

        s = W.section(box, 'Ethernet')
        if info['wired']:
            for w in info['wired']:
                W.note(s, f"{w.get('device', 'Wired')}: {w.get('state', '')}")
        else:
            W.note(s, 'No wired network adapter.')

        s = W.section(box, 'VPN')
        for v in info['vpns']:
            line = ui.box(spacing=10)
            line.append(Gtk.Label(label=v['name'] + ('  (on)' if v['active'] else ''), xalign=0, hexpand=True))
            line.append(ui.button('Turn Off' if v['active'] else 'Turn On', lambda v=v: ctx.do(netman.vpn_toggle, v['uuid'], not v['active'], ok='VPN changed.', done=reload)))
            line.append(ui.button('Remove', lambda v=v: ctx.do(netman.forget, v['uuid'], ok='VPN removed.', done=reload)))
            s.append(line)
        if not info['vpns']:
            W.note(s, 'No VPN profiles.')

        def pick():
            dialog = Gtk.FileDialog(title='Import a VPN profile (.conf WireGuard or .ovpn OpenVPN)')

            def picked(dlg, result):
                try:
                    f = dlg.open_finish(result)
                except GLib.Error:
                    return
                if f and f.get_path():
                    ctx.do(netman.vpn_import, f.get_path(), ok='VPN profile imported.', done=reload)
            dialog.open(ctx.window, None, picked)
        W.button_row(s, '', 'Import VPN Profile…', pick, hint='Credentials in the profile are stored by NetworkManager, not by MakkOS.')

        s = W.section(box, 'Proxy')
        px = info['proxy']
        mode = Gtk.DropDown.new_from_strings(['None', 'Manual', 'Automatic (script)'])
        modes = ['none', 'manual', 'auto']
        mode.set_selected(modes.index(px['mode']) if px['mode'] in modes else 0)
        W.row(s, 'Proxy', mode)
        host = Gtk.Entry(text=px['http_host'], placeholder_text='Host', width_chars=22)
        port = Gtk.Entry(text=str(px['http_port'] or ''), placeholder_text='Port', width_chars=6)
        pac = Gtk.Entry(text=px['pac_url'], placeholder_text='https://…/proxy.pac', width_chars=30)
        hp = ui.box(spacing=6)
        hp.append(host)
        hp.append(port)
        W.row(s, 'Web proxy (manual)', hp)
        W.row(s, 'Script address (automatic)', pac)

        def apply_proxy():
            m = modes[mode.get_selected()]
            try:
                ctx.do(netman.proxy_set, m, host.get_text().strip(), int(port.get_text() or 0), pac_url=pac.get_text().strip(), ok='Proxy saved.')
            except ValueError:
                ctx.flash('Enter a valid port number.', True)
        W.button_row(s, '', 'Apply Proxy', apply_proxy)
    reload()
