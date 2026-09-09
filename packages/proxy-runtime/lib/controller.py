"""Local proxy routing, persistent state, and user-service control."""
import fcntl
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from settings import load_settings

ENDPOINT = 'http://127.0.0.1:18080'
NO_PROXY = 'localhost,127.0.0.1,::1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,.nav.gov.hu'
EXPORTS = dict(HTTP_PROXY=ENDPOINT, HTTPS_PROXY=ENDPOINT, http_proxy=ENDPOINT,
               https_proxy=ENDPOINT, NO_PROXY=NO_PROXY, no_proxy=NO_PROXY)
DEFAULT = dict(PROXY_MODE='auto', PROXY_DETECTED='unknown', PROXY_EFFECTIVE='off',
               PROXY_SUCCESS_COUNT='0', PROXY_FAILURE_COUNT='0')


def atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError('Unsafe state file: ' + str(path))
    if path.exists() and path.read_text() == text:
        return
    descriptor, temporary = tempfile.mkstemp(prefix='.' + path.name, dir=path.parent)
    try:
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_state(path, pending=False):
    if path.is_symlink():
        raise ValueError('Unsafe state symlink')
    if not path.exists():
        return None if pending else DEFAULT.copy()
    state = {}
    for line in path.read_text().splitlines():
        # Read shell exports as data; never source or execute them.
        if line.startswith('export '):
            fields = shlex.split(line)
            if len(fields) != 2 or '=' not in fields[1]:
                raise ValueError('Invalid proxy export')
            key, value = fields[1].split('=', 1)
            if key not in EXPORTS:
                raise ValueError('Unknown proxy export')
            if value != EXPORTS[key]:
                raise ValueError('Unexpected proxy endpoint')
            continue
        key, separator, value = line.partition('=')
        if not separator or key in state:
            raise ValueError('Invalid proxy state')
        state[key] = value
    route = 'PROXY_TARGET' if pending else 'PROXY_EFFECTIVE'
    expected = (set(DEFAULT) - {'PROXY_EFFECTIVE'}) | {route}
    if set(state) != expected or state['PROXY_MODE'] not in ('auto', 'force-on', 'force-off') or state['PROXY_DETECTED'] not in ('on', 'off', 'unknown') or state[route] not in ('on', 'off'):
        raise ValueError('Invalid proxy state fields')
    for key in ('PROXY_SUCCESS_COUNT', 'PROXY_FAILURE_COUNT'):
        if not state[key].isascii() or not state[key].isdigit():
            raise ValueError('Invalid proxy counter')
    if pending:
        if state['PROXY_MODE'] != 'auto' and state['PROXY_MODE'] != 'force-' + state[route]:
            raise ValueError('Inconsistent pending route')
        state['PROXY_EFFECTIVE'] = state.pop('PROXY_TARGET')
    return state


class Controller:
    def __init__(self, root):
        self.root = Path(root)
        self.home = Path.home()
        self.state_path = self.home / '.cache/.proxy-state'
        self.pending_path = self.home / '.cache/.proxy-state.pending'
        self.config_path = self.home / '.config/haproxy/proxy.cfg'

    def ctl(self, *args, check=True):
        return subprocess.run(['/usr/bin/systemctl', '--user', *args], text=True, capture_output=True, check=check)

    def render(self, route):
        host, port = load_settings(self.root / 'config/proxy.yaml')
        backend = f'  server corporate {host}:{port} resolvers wsl resolve-prefer ipv4 init-addr libc,none' if route == 'on' else '  server direct 127.0.0.1:18081'
        return '''global
  nbthread 1
  maxconn 512
  log stdout format raw local0 notice
defaults
  mode tcp
  log global
  timeout connect 5s
  timeout client 1h
  timeout server 1h
  timeout client-fin 30s
  timeout server-fin 30s
resolvers wsl
  parse-resolv-conf
  resolve_retries 3
  timeout resolve 1s
  timeout retry 1s
  hold valid 10s
frontend local_proxy
  bind 127.0.0.1:18080
  bind 192.168.20.5:18080
  acl allowed_client src 127.0.0.1/32 192.168.20.0/24 172.30.0.0/24
  tcp-request connection reject if !allowed_client
  default_backend selected_route
backend selected_route
''' + backend + '\n'

    def save(self, state, pending=False):
        values = state.copy()
        if pending:
            values['PROXY_TARGET'] = values.pop('PROXY_EFFECTIVE')
        text = ''.join(f'{key}={value}\n' for key, value in values.items())
        if not pending:
            text += ''.join(f'export {key}={shlex.quote(value)}\n' for key, value in EXPORTS.items())
        atomic_write(self.pending_path if pending else self.state_path, text)

    def reload(self):
        before = self.ctl('show', '--property=MainPID', '--value', 'proxy-endpoint.service').stdout.strip()
        if not before.isdigit() or int(before) == 0:
            raise RuntimeError('Proxy endpoint is not running')
        self.ctl('reload', 'proxy-endpoint.service')
        after = self.ctl('show', '--property=MainPID', '--value', 'proxy-endpoint.service').stdout.strip()
        if before != after:
            raise RuntimeError('Proxy master changed during reload')
        with socket.create_connection(('127.0.0.1', 18080), timeout=2):
            pass

    def restore_route(self, state):
        atomic_write(self.config_path, self.render(state['PROXY_EFFECTIVE']))
        try:
            self.reload()
        except (OSError, RuntimeError, subprocess.CalledProcessError):
            self.ctl('restart', '--no-block', 'proxy-endpoint.service')

    def apply(self, old, new):
        candidate = self.render(new['PROXY_EFFECTIVE'])
        if self.config_path.is_symlink():
            raise ValueError('Unsafe HAProxy configuration')
        if old['PROXY_EFFECTIVE'] == new['PROXY_EFFECTIVE'] and self.config_path.exists() and self.config_path.read_text() == candidate:
            self.save(new)
        else:
            self.save(new, pending=True)
            try:
                atomic_write(self.config_path, candidate)
                self.reload()
                self.save(new)
            except BaseException:
                self.restore_route(old)
                raise
        self.pending_path.unlink(missing_ok=True)

    def change(self, command):
        # Validate the current YAML before altering state or contacting services.
        host, port = load_settings(self.root / 'config/proxy.yaml')
        old = read_state(self.state_path)
        pending = read_state(self.pending_path, pending=True)
        new = old.copy()
        if command == 'render-config':
            atomic_write(self.config_path, self.render(old['PROXY_EFFECTIVE']))
            return
        if command == 'auto':
            if not self.config_path.exists() or self.config_path.read_text() != self.render(old['PROXY_EFFECTIVE']):
                self.restore_route(old)
            new['PROXY_MODE'] = 'auto'
            self.save(new)
            self.pending_path.unlink(missing_ok=True)
            return
        if command in ('on', 'off', 'toggle'):
            route = command if command != 'toggle' else ('off' if old['PROXY_EFFECTIVE'] == 'on' else 'on')
            new.update(PROXY_MODE='force-' + route, PROXY_EFFECTIVE=route)
        elif pending:
            new = pending
        else:
            try:
                with socket.create_connection((host, port), timeout=2):
                    pass
                success = True
            except OSError:
                success = False
            new['PROXY_SUCCESS_COUNT'] = str(min(int(old['PROXY_SUCCESS_COUNT']) + 1, 2)) if success else '0'
            new['PROXY_FAILURE_COUNT'] = '0' if success else str(min(int(old['PROXY_FAILURE_COUNT']) + 1, 3))
            if int(new['PROXY_SUCCESS_COUNT']) >= 2:
                new['PROXY_DETECTED'] = 'on'
            if int(new['PROXY_FAILURE_COUNT']) >= 3:
                new['PROXY_DETECTED'] = 'off'
            if new['PROXY_MODE'] == 'auto' and new['PROXY_DETECTED'] != 'unknown':
                new['PROXY_EFFECTIVE'] = new['PROXY_DETECTED']
        self.apply(old, new)

    def locked_change(self, command):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with open(str(self.state_path) + '.lock', 'a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.change(command)

    def status(self):
        state = read_state(self.state_path)
        pending = read_state(self.pending_path, pending=True)
        service = self.ctl('is-active', 'proxy-endpoint.service', check=False).stdout.strip() or 'unavailable'
        values = dict(mode=state['PROXY_MODE'], detected=state['PROXY_DETECTED'], route=state['PROXY_EFFECTIVE'],
                      effective=state['PROXY_EFFECTIVE'], successes=state['PROXY_SUCCESS_COUNT'], failures=state['PROXY_FAILURE_COUNT'],
                      pending=pending['PROXY_EFFECTIVE'] if pending else 'none', service=service,
                      **{'host-endpoint': ENDPOINT, 'docker-endpoint': 'http://192.168.20.5:18080'})
        print('\n'.join(f'{key}: {value}' for key, value in values.items()))


def main(root):
    command = sys.argv[1] if len(sys.argv) > 1 else 'status'
    controller = Controller(root)
    if command in ('help', '--help', '-h'):
        print('Usage: proxy {status|on|off|auto|toggle|check|monitor|start|stop|render-config|state-file}')
    elif command == 'state-file':
        print(controller.state_path)
    elif command == 'status':
        controller.status()
    elif command in ('start', 'stop'):
        controller.ctl(command, 'proxy-monitor.service')
    elif command == '__reload-haproxy':
        from operations import reload_haproxy
        sys.argv.pop(1)
        reload_haproxy()
    elif command == 'monitor':
        while True:
            try:
                controller.locked_change('check')
            except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
                print(f'[proxy] check failed: {error}', file=sys.stderr, flush=True)
            time.sleep(5)
    elif command in ('on', 'off', 'auto', 'toggle', 'check', 'render-config'):
        controller.locked_change(command)
    else:
        raise ValueError('Unknown proxy command: ' + command)
