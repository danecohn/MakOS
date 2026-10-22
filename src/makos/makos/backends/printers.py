"""Printers backend: CUPS through its command-line clients (`lpstat`, `lpoptions`, `lp`, `cancel`)."""
import re
from pathlib import Path

from . import sysutil

QUEUE_OK = re.compile(r'^[A-Za-z0-9_.@-]{1,127}$')
TESTPAGES = ('/usr/share/cups/data/testprint', '/usr/share/cups/data/default-testpage.pdf')


def available():
    return sysutil.have('lpstat') and sysutil.run(['lpstat', '-r']).out.startswith('scheduler is running')


def printers():
    default = None
    res = sysutil.run(['lpstat', '-d'])
    m = re.search(r'destination:\s*(\S+)', res.out)
    if m:
        default = m.group(1)
    uris = {}
    for line in sysutil.run(['lpstat', '-v']).out.splitlines():
        m = re.match(r'device for (\S+):\s*(.+)$', line)
        if m:
            uris[m.group(1)] = m.group(2)
    out = []
    text = sysutil.run(['lpstat', '-p']).out
    blocks = re.split(r'(?m)^(?=printer )', text)
    for block in blocks:
        m = re.match(r'printer (\S+) (is idle|now printing|disabled|is processing)[^\n]*', block)
        if not m:
            continue
        name, state = m.group(1), m.group(2)
        reasons = [ln.strip() for ln in block.splitlines()[1:] if ln.strip()]
        out.append({'name': name, 'state': 'printing' if 'printing' in state or 'processing' in state else ('disabled' if 'disabled' in state else 'idle'),
                    'default': name == default, 'uri': uris.get(name, ''), 'reason': reasons[0] if reasons else '',
                    'network': uris.get(name, '').startswith(('ipp', 'http', 'socket', 'lpd', 'dnssd'))})
    return out


def jobs():
    out = []
    for line in sysutil.run(['lpstat', '-o']).out.splitlines():
        m = re.match(r'(\S+)-(\d+)\s+(\S+)\s+(\d+)\s+(.*)$', line)
        if m:
            out.append({'queue': m.group(1), 'id': int(m.group(2)), 'user': m.group(3), 'size': int(m.group(4)), 'when': m.group(5)})
    return out


def _queue(name):
    if not QUEUE_OK.match(name or ''):
        raise ValueError('Invalid printer name.')
    return name


def set_default(name):
    return sysutil.run(['lpoptions', '-d', _queue(name)]).code == 0


def cancel_job(queue, job_id):
    return sysutil.run(['cancel', f'{_queue(queue)}-{int(job_id)}']).code == 0


def test_page(name):
    page = next((p for p in TESTPAGES if Path(p).exists()), None)
    if not page:
        return {'ok': False, 'error': 'No test page is installed.'}
    res = sysutil.run(['lp', '-d', _queue(name), page])
    return {'ok': res.code == 0, 'error': None if res.code == 0 else res.err[:200]}


def add_printer_command():
    """Guided: open the system printer tool (adding a queue needs administrator rights, which the tool asks for itself)."""
    for tool in ('system-config-printer', 'kcmshell6'):
        if sysutil.have(tool):
            return [tool] if tool == 'system-config-printer' else [tool, 'kcm_printer_manager']
    return ['xdg-open', 'http://localhost:631/admin']
