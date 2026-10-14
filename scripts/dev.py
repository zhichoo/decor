#!/usr/bin/env python3
"""Manage the local unified application and its persistent PostgreSQL database."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'
CONFIG = ROOT / 'backend' / 'config.local.json'
ENV_FILE = ROOT / '.env'
PYTHON = ROOT / '.venv' / 'bin' / 'python'
STATE = RUNTIME / 'app.json'
CONTAINER = 'decor-postgres'
TABLES = {'sources', 'videos', 'claims', 'extraction_runs'}


def run(args, **kwargs):
    return subprocess.run([str(a) for a in args], cwd=ROOT, check=True, **kwargs)


def save_private(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        stream.write(text)
    path.chmod(0o600)


def configure():
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    RUNTIME.chmod(0o700)
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                values[key.strip()] = value.strip()
    values.setdefault('POSTGRES_PASSWORD', secrets.token_urlsafe(32))
    values.setdefault('DECOR_DB_PORT', '15439')
    db_port = int(values['DECOR_DB_PORT'])
    save_private(ENV_FILE, '\n'.join(f'{key}={value}' for key, value in values.items()) + '\n')
    config = json.loads(CONFIG.read_text()) if CONFIG.exists() else {}
    config['DATABASE_URL'] = (
        f'host=127.0.0.1 port={db_port} dbname=decor user=decor '
        f'password={values["POSTGRES_PASSWORD"]} sslmode=disable connect_timeout=5'
    )
    config.setdefault('ADMIN_PASSWORD', secrets.token_urlsafe(18))
    config.setdefault('PORT', '4189')
    save_private(CONFIG, json.dumps(config, ensure_ascii=False, indent=2) + '\n')
    return config


def compose(*args, **kwargs):
    return run(['docker', 'compose', '--project-name', 'decor', '--env-file', ENV_FILE,
                '-f', ROOT / 'compose.yaml', *args], **kwargs)


def database_up():
    compose('up', '-d', '--wait', '--wait-timeout', '45', 'db')


def database_sql(sql):
    return run(['docker', 'exec', CONTAINER, 'psql', '-U', 'decor', '-d', 'decor',
                '-X', '-v', 'ON_ERROR_STOP=1', '-At', '-c', sql],
               capture_output=True, text=True).stdout.strip()


def existing_tables():
    rows = database_sql("SELECT tablename FROM pg_tables WHERE schemaname='public'")
    return set(rows.splitlines()) if rows else set()


def python_ready():
    created = not PYTHON.exists()
    if created:
        uv = shutil.which('uv')
        if uv:
            run([uv, 'venv', '--python', '3.12', ROOT / '.venv'])
        else:
            run([sys.executable, '-m', 'venv', ROOT / '.venv'])
    requirements = ROOT / 'backend' / 'requirements.txt'
    marker = RUNTIME / 'installed-requirements.txt'
    text = 'install-with-dependencies-v1\n' + requirements.read_text()
    if created or not marker.exists() or marker.read_text() != text:
        uv = shutil.which('uv')
        if uv:
            run([uv, 'pip', 'install', '--python', PYTHON, '-r', requirements])
        else:
            run([PYTHON, '-m', 'pip', 'install', '-r', requirements])
        marker.write_text(text)


def app_env(config):
    env = os.environ.copy()
    env.update({key: str(value) for key, value in config.items() if value is not None})
    env['STATIC_ROOT'] = str(ROOT / 'web')
    env['PYTHONUNBUFFERED'] = '1'
    return env


def process_running(state):
    pid = state.get('pid')
    if not isinstance(pid, int) or pid <= 1:
        return False
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='],
                            capture_output=True, text=True)
    return result.returncode == 0 and str(ROOT / 'backend' / 'server.py') in result.stdout


def read_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def api_ready(url):
    try:
        with urllib.request.urlopen(url + '/api/bootstrap', timeout=3) as response:
            payload = json.load(response)
            return response.status == 200 and isinstance(payload.get('stats'), dict)
    except (OSError, urllib.error.URLError, ValueError):
        return False


def start():
    config = configure()
    database_up()
    python_ready()
    run([PYTHON, ROOT / 'scripts' / 'init_db.py'], env=app_env(config))
    state = read_state()
    if process_running(state):
        if not api_ready(state['url']):
            raise RuntimeError('The application process exists but is not ready. Check .runtime/server.log.')
        print('Already running: ' + state['url'])
        return
    port = int(config['PORT'])
    with socket.socket() as probe:
        try:
            probe.bind(('127.0.0.1', port))
        except OSError as exc:
            raise RuntimeError(f'Port {port} is occupied. Set PORT in backend/config.local.json.') from exc
    with (RUNTIME / 'server.log').open('ab') as log:
        process = subprocess.Popen([str(PYTHON), str(ROOT / 'backend' / 'server.py'), str(port)],
                                   cwd=ROOT, env=app_env(config), stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    state = {'pid': process.pid, 'url': f'http://127.0.0.1:{port}',
             'started_at': datetime.now(timezone.utc).isoformat()}
    save_private(STATE, json.dumps(state, indent=2) + '\n')
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('Application exited. Check .runtime/server.log.')
        if api_ready(state['url']):
            print('Application ready: ' + state['url'])
            print('Log: ' + str(RUNTIME / 'server.log'))
            return
        time.sleep(0.2)
    os.kill(process.pid, signal.SIGTERM)
    STATE.unlink(missing_ok=True)
    raise RuntimeError('Application did not become ready. Check .runtime/server.log.')


def stop():
    state = read_state()
    if process_running(state):
        os.kill(state['pid'], signal.SIGTERM)
        deadline = time.monotonic() + 10
        while process_running(state) and time.monotonic() < deadline:
            time.sleep(0.1)
        if process_running(state):
            raise RuntimeError('Application has not stopped; database was left running.')
    STATE.unlink(missing_ok=True)
    if ENV_FILE.exists():
        compose('stop', 'db')
    print('Stopped. PostgreSQL volume and application data are retained.')


def status():
    state = read_state()
    running = process_running(state)
    output = {'running': running, 'url': state.get('url'),
              'ready': api_ready(state['url']) if running else False}
    print(json.dumps(output, ensure_ascii=False, indent=2))


def restore(path):
    path = path.expanduser().resolve()
    if not path.is_file():
        raise RuntimeError('Backup file does not exist: ' + str(path))
    configure()
    if process_running(read_state()):
        raise RuntimeError('Stop the application before restoring a backup.')
    database_up()
    if existing_tables():
        raise RuntimeError('Restore requires an empty database. Existing data was left unchanged.')
    database_sql('CREATE EXTENSION IF NOT EXISTS pg_trgm')
    archive = '/tmp/decor-recovery.dump'
    listing = '/tmp/decor-recovery.list'
    run(['docker', 'cp', path, CONTAINER + ':' + archive])
    try:
        toc = run(['docker', 'exec', CONTAINER, 'pg_restore', '--list', archive],
                  capture_output=True, text=True).stdout
        # The initial PostgreSQL public schema already exists. Keep every business object.
        lines = ['; ' + line if ' SCHEMA - public ' in line else line for line in toc.splitlines()]
        local_list = RUNTIME / 'restore-list.txt'
        save_private(local_list, '\n'.join(lines) + '\n')
        run(['docker', 'cp', local_list, CONTAINER + ':' + listing])
        run(['docker', 'exec', CONTAINER, 'pg_restore', '-U', 'decor', '-d', 'decor',
             '--no-owner', '--no-privileges', '--exit-on-error', '--single-transaction',
             '--use-list', listing, archive])
    finally:
        run(['docker', 'exec', CONTAINER, 'rm', '-f', archive, listing])
    tables = existing_tables()
    if not TABLES.issubset(tables):
        raise RuntimeError('Backup did not contain all four required application tables.')
    counts = {table: int(database_sql(f'SELECT count(*) FROM public.{table}')) for table in sorted(TABLES)}
    print('Restored: ' + json.dumps(counts, ensure_ascii=False))


def backup(path):
    configure()
    database_up()
    path = path or (RUNTIME / 'backups' / ('decor-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.dump'))
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    # Exclusive creation prevents accidental overwrites of an earlier backup.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as output:
            run(['docker', 'exec', CONTAINER, 'pg_dump', '-U', 'decor', '-d', 'decor',
                 '--format=custom', '--schema=public'], stdout=output)
    except Exception:
        path.unlink(missing_ok=True)
        raise
    print('Backup saved: ' + str(path))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('start', 'stop', 'status'):
        sub.add_parser(name)
    sub.add_parser('restore').add_argument('path', type=Path)
    sub.add_parser('backup').add_argument('path', type=Path, nargs='?')
    args = parser.parse_args()
    try:
        if args.command == 'start': start()
        elif args.command == 'stop': stop()
        elif args.command == 'status': status()
        elif args.command == 'restore': restore(args.path)
        elif args.command == 'backup': backup(args.path)
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print('Error: ' + str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
