"""Metadata-only usage log (~/.local/state/amerika-studio/usage.jsonl): time, app, model, token counts. Never prompts or
responses. Also answers "how many tokens today" for the daily budget guard."""
import json
import os
import threading
import time

from .common import Paths, ensure_private_dir

MAX_BYTES = 5 * 1024 * 1024


class UsageLog:
    def __init__(self, paths=None):
        self.paths = paths or Paths()
        self._lock = threading.Lock()
        self._day = None
        self._tokens = 0

    def _scan(self, day):
        total = 0
        try:
            with open(self.paths.usage, encoding='utf-8') as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if str(row.get('t', ''))[:10] == day:
                        total += int(row.get('in', 0)) + int(row.get('out', 0))
        except OSError:
            pass
        return total

    def tokens_today(self):
        day = time.strftime('%Y-%m-%d')
        with self._lock:
            if self._day != day:
                self._day, self._tokens = day, self._scan(day)
            return self._tokens

    def record(self, app, model, tokens_in, tokens_out, status=200):
        day = time.strftime('%Y-%m-%d')
        row = {'t': time.strftime('%Y-%m-%dT%H:%M:%S'), 'app': app, 'model': model,
               'in': int(tokens_in or 0), 'out': int(tokens_out or 0), 'status': status}
        with self._lock:
            if self._day != day:
                self._day, self._tokens = day, self._scan(day)
            ensure_private_dir(self.paths.state_dir)
            try:
                if os.path.getsize(self.paths.usage) > MAX_BYTES:
                    os.replace(self.paths.usage, str(self.paths.usage) + '.1')
            except OSError:
                pass
            fd = os.open(self.paths.usage, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            with os.fdopen(fd, 'a', encoding='utf-8') as fh:
                fh.write(json.dumps(row) + '\n')
            self._tokens += row['in'] + row['out']
        return row

    def summary(self, days=7):
        by_day = {}
        try:
            with open(self.paths.usage, encoding='utf-8') as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    d = by_day.setdefault(str(row.get('t', ''))[:10], {'in': 0, 'out': 0, 'calls': 0})
                    d['in'] += int(row.get('in', 0))
                    d['out'] += int(row.get('out', 0))
                    d['calls'] += 1
        except OSError:
            pass
        return dict(sorted(by_day.items())[-days:])
