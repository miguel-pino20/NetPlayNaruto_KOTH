"""Local, flushed JSON-lines logs for comparing D.O.N sessions across PCs."""
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import sys
import time
import traceback
from datetime import datetime, timezone
from uuid import uuid4
from release_info import VERSION


class SessionLog:
    def __init__(self, directory, config):
        slug = 'digimon' if config.get('game') in ('digimon', 'digimon-rumble-arena-2') else 'don'
        directory = Path(directory)/'logs'/slug
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
        self.path = directory/f'{slug.upper()}-{stamp}-{uuid4().hex[:8]}.jsonl'
        self.started = time.monotonic()
        self.secrets = []
        self.closed = False
        self.handler = RotatingFileHandler(self.path, maxBytes=5*1024*1024, backupCount=2, encoding='utf-8')
        self.handler.setFormatter(logging.Formatter('%(message)s'))
        root = Path(__file__).resolve().parent
        hashes = {}
        for name in ('don_diagnostics.py', 'don_online.py', 'don_core.py', 'node.py', 'pine.py',
                     'don_routing.py', 'multiplayer_client.py', 'digimon_core.py', 'game_adapters.py'):
            try:
                hashes[name] = hashlib.sha256((root/name).read_bytes()).hexdigest()
            except OSError:
                pass
        self.write('session_start', {'schema': 1, 'launcher_version': VERSION,
            'pid': os.getpid(), 'python': sys.version,
            'platform': platform.platform(), 'sources': hashes,
            'config': {k: config[k] for k in ('game', 'role', 'players', 'address', 'port', 'pine_slot', 'state_dir', 'url')
                       if k in config}})

    def protect(self, secret):
        if isinstance(secret, str) and secret:
            self.secrets.append(secret)

    def write(self, event, data):
        record = {'utc': datetime.now(timezone.utc).isoformat(timespec='milliseconds'),
                  'elapsed_s': round(time.monotonic()-self.started, 3), 'event': event, 'data': data}
        line = json.dumps(record, ensure_ascii=False, default=str)
        for secret in self.secrets:
            line = line.replace(secret, '[REDACTED]')
        # Handler.handle serializes concurrent heartbeat/transport writes and
        # StreamHandler flushes every record, including the last error.
        self.handler.acquire()
        try:
            if not self.closed:
                self.handler.handle(logging.LogRecord('don-session', logging.INFO, '', 0, line, (), None))
        finally:
            self.handler.release()

    def exception(self, stage):
        self.write('exception', {'stage': stage, 'traceback': traceback.format_exc()})

    def close(self):
        self.handler.acquire()
        try:
            self.closed = True
            self.handler.close()
        finally:
            self.handler.release()
