"""amerika-studio: command line for the Studio bridge, keys, budget and settings. Keys are read from stdin only."""
import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

from . import __version__, agent_link, common, control, keyring, projects
from .common import APPS, StudioError
from .usage import UsageLog


def out(obj):
    print(json.dumps(obj, indent=2, sort_keys=True))


def bridge_url():
    return f'http://127.0.0.1:{int(os.environ.get("AMERIKA_STUDIO_PORT", common.DEFAULT_PORT))}'


def bridge_ping(timeout=1.5):
    try:
        with urllib.request.urlopen(bridge_url() + '/v1/ping', timeout=timeout) as r:
            d = json.loads(r.read())
            return d.get('service') == 'amerika-studio-bridge'
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ensure_bridge():
    """Make sure the bridge is running. Prefers the systemd user unit, falls back to a detached process."""
    if not bridge_ping():
        started = None
        if shutil.which('systemctl') and not os.environ.get('AMERIKA_STUDIO_NO_SYSTEMD'):
            r = subprocess.run(['systemctl', '--user', 'start', 'amerika-studio-bridge.service'], capture_output=True, text=True)
            started = 'systemd' if r.returncode == 0 else None
        if not started:
            exe = shutil.which('amerika-studio-bridge')
            if not exe:
                raise StudioError('amerika-studio-bridge is not installed', 'not_installed')
            subprocess.Popen([exe], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                             start_new_session=True)
            started = 'process'
        for _ in range(40):
            if bridge_ping():
                break
            time.sleep(0.15)
        else:
            raise StudioError('the bridge did not start (see: journalctl --user -u amerika-studio-bridge)', 'bridge_down')


def cmd_ensure(args, paths):
    ensure_bridge()
    res = {'running': True, 'url': bridge_url(), 'token_file': str(paths.token)}
    out(res) if args.json else print(f'bridge running at {res["url"]}')
    return 0


def build_status(paths):
    s = common.load_settings(paths)
    log = UsageLog(paths)
    apps = {}
    for app in APPS:
        p = control.ping(app, paths)
        apps[app] = {'installed': control.installed(app), 'running': bool(p), 'ready': bool(p and p.get('ready', True))}
    keys = keyring.key_state(s)
    detail = keyring.detail(s)
    return {'version': __version__, 'bridge': bridge_ping(), 'model': s['model'], 'keys': keys,
            'shared_key': detail['shared'], 'agent_key_available': detail['agent_available'], 'reuse_agent_key': s['reuse_agent_key'],
            'overrides': detail['apps'], 'budget': {'daily_tokens': s['daily_budget_tokens'], 'used_today': log.tokens_today()},
            'agent_tools': s['agent_tools'], 'apps': apps, 'studio_root': str(paths.studio_root)}


def cmd_status(args, paths):
    st = build_status(paths)
    if args.json:
        out(st)
        return 0
    print(f'Studio {st["version"]}   bridge: {"running" if st["bridge"] else "stopped"}   model: {st["model"]}')
    for app in APPS:
        a = st['apps'][app]
        print(f'  {app:<7} installed={a["installed"]!s:<5} running={a["running"]!s:<5} key={"yes" if st["keys"][app] else "no"}')
    b = st['budget']
    print(f'  tokens today: {b["used_today"]:,} / {b["daily_tokens"]:,}   agent tools: {"on" if st["agent_tools"] else "off"}')
    return 0


def read_key():
    if sys.stdin.isatty():
        return getpass.getpass('Anthropic API key (input hidden): ')
    return sys.stdin.readline()


def cmd_key(args, paths):
    app = args.app
    if args.action == 'set':
        keyring.store(read_key(), app)
        print('Key saved in your keyring' + (f' for {app}' if app else '') + '.')
        return 0
    if args.action == 'clear':
        keyring.clear(app)
        print('Key removed' + (f' for {app}' if app else '') + '.')
        return 0
    s = common.load_settings(paths)
    st = {'shared': keyring.present(), 'agent_available': keyring.agent_present(), 'reuse_agent_key': s['reuse_agent_key'],
          'apps': {a: keyring.present(a) for a in APPS}}
    if args.json:
        out(st)
    else:
        print('shared key:', 'saved' if st['shared'] else 'not saved')
        for a in APPS:
            print(f'  {a}: {"own key saved" if st["apps"][a] else "uses shared key"}')
        print('Amerika Agent key reuse:', 'on' if s['reuse_agent_key'] else 'off', '(agent key found)' if st['agent_available'] else '')
    return 0


def cmd_budget(args, paths):
    s = common.load_settings(paths)
    if args.set is not None:
        if args.set < 0:
            raise StudioError('budget must be 0 (unlimited) or a positive number of tokens', 'bad_budget')
        s['daily_budget_tokens'] = args.set
        s = common.save_settings(s, paths)
    log = UsageLog(paths)
    res = {'daily_tokens': s['daily_budget_tokens'], 'used_today': log.tokens_today(), 'last_days': log.summary()}
    out(res) if args.json else print(f'{res["used_today"]:,} of {res["daily_tokens"]:,} tokens used today (0 = unlimited)')
    return 0


def parse_bool(text):
    t = str(text).strip().lower()
    if t in ('1', 'true', 'on', 'yes'):
        return True
    if t in ('0', 'false', 'off', 'no'):
        return False
    raise StudioError(f'expected on/off, got {text!r}', 'bad_value')


def cmd_config(args, paths):
    s = common.load_settings(paths)
    if args.key == 'model':
        if args.value:
            if args.value not in common.MODEL_IDS:
                raise StudioError(f'unknown model; choose one of {", ".join(common.MODEL_IDS)}', 'bad_model')
            s['model'] = args.value
            s = common.save_settings(s, paths)
        print(s['model'])
    elif args.key == 'reuse-agent-key':
        if args.value:
            s['reuse_agent_key'] = parse_bool(args.value)
            s = common.save_settings(s, paths)
        print('on' if s['reuse_agent_key'] else 'off')
    elif args.key == 'agent-tools':
        if args.value:
            print(agent_link.set_agent_tools(parse_bool(args.value), paths))
        else:
            print('on' if s['agent_tools'] else 'off')
    elif args.key == 'override':
        if not args.app:
            raise StudioError('--app is required for override', 'bad_app')
        common.check_app(args.app)
        if args.value:
            s['override'][args.app] = parse_bool(args.value)
            s = common.save_settings(s, paths)
        print('on' if s['override'][args.app] else 'off')
    return 0


def cmd_new_game(args, paths):
    res = projects.new_game(args.name, paths)
    out(res) if args.json else print('created', res['slug'], 'in', paths.studio_root)
    return 0


def build_parser():
    p = argparse.ArgumentParser(prog='amerika-studio', description='Studio bridge, keys and settings')
    p.add_argument('--version', action='version', version=__version__)
    sub = p.add_subparsers(dest='cmd', required=True)
    e = sub.add_parser('ensure', help='start the bridge if it is not running')
    e.add_argument('--json', action='store_true')
    s = sub.add_parser('status', help='bridge, keys, apps, budget')
    s.add_argument('--json', action='store_true')
    k = sub.add_parser('key', help='set | clear | status (key on stdin only)')
    k.add_argument('action', choices=['set', 'clear', 'status'])
    k.add_argument('--app', choices=APPS, help='per-app override instead of the shared key')
    k.add_argument('--json', action='store_true')
    b = sub.add_parser('budget', help='show or set the daily token budget')
    b.add_argument('--set', type=int, metavar='TOKENS')
    b.add_argument('--json', action='store_true')
    c = sub.add_parser('config', help='get/set model, reuse-agent-key, agent-tools, override')
    c.add_argument('key', choices=['model', 'reuse-agent-key', 'agent-tools', 'override'])
    c.add_argument('value', nargs='?')
    c.add_argument('--app', choices=APPS)
    n = sub.add_parser('new-game', help='create the ~/Studio folders for a new game')
    n.add_argument('name')
    n.add_argument('--json', action='store_true')
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    paths = common.Paths()
    handlers = {'ensure': cmd_ensure, 'status': cmd_status, 'key': cmd_key, 'budget': cmd_budget, 'config': cmd_config,
                'new-game': cmd_new_game}
    try:
        return handlers[args.cmd](args, paths)
    except StudioError as e:
        print(f'amerika-studio: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
