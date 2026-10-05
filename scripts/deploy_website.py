"""Guarded website release with code/database backup and automatic code rollback."""
import hashlib
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASELINES = {
 'admin_web.py': '6e06c494ef837f37c6d2044e36086b25af4c189ecda4c277b3ed312402f0604e',
 'app.py': '2e692815de4b19eb70a79f33aedda16debd3189b31f8844f745536b2f3cc55cc',
 'bot/mini_app.py': '721067aaee47916fee1bb41fd90d3b86cd13ba254fec4ff04bd1d8e9935188f2',
 'mini_app/index.html': '1833130c015c75ce8ad0d12328e7f98cd1f0ed76eaa6390577489efb124f1211',
 'mini_app/static/app.js': '60f2aeaa33771f0a354701e194df3af7b4ff5f1bf71172bb8862650fdba152e6',
 'mini_app/static/profile.js': 'ea9368a9d42ee6d0d7be349c70008a57d22d57aabdf0626ed011f8b50e22f2fc',
}
NEW = {'bot/website_auth.py', 'bot/website.py', 'website/site.js', 'website/site.css'}
CONFIG = 'deploy/nastaunik-website.conf'
NGINX_HASH = 'bdaffd651be0321518efa6036e7d020bdc843c34c0d01b5758b2c03ac43092cb'
SERVICES = ['nastaunik-club-admin', 'nastaunik-bot']

def run(*args):
    subprocess.run(args, check=True)

def main():
    root = Path('/opt/nastaunik_club').resolve()
    nginx = Path('/etc/nginx/conf.d/nastaunik-miniapp.conf')
    if root != Path('/opt/club-bot'):
        raise RuntimeError('Unexpected application root')
    for name, expected in BASELINES.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Production changed: '+name)
    if hashlib.sha256(nginx.read_bytes()).hexdigest() != NGINX_HASH:
        raise RuntimeError('Nginx configuration changed')
    if any((root/name).exists() for name in NEW):
        raise RuntimeError('Website files already exist; inspect before retrying')
    with tarfile.open(sys.argv[1], 'r:gz') as archive:
        members = archive.getmembers()
        expected = set(BASELINES) | NEW | {CONFIG}
        if len(members) != len(expected) or {m.name for m in members} != expected or any(not m.isfile() for m in members):
            raise RuntimeError('Unexpected archive contents')
        payload = {m.name: archive.extractfile(m).read() for m in members}
    for name, data in payload.items():
        if name.endswith('.py'):
            compile(data, name, 'exec')
    backup = Path('/opt/nastaunik-backups')/('website-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, exist_ok=False)
    originals = {name: (root/name).read_bytes() for name in BASELINES}
    old_nginx = nginx.read_bytes()
    with tarfile.open(backup/'code.tar.gz', 'w:gz') as out:
        for name in BASELINES:
            out.add(root/name, arcname=name)
    (backup/'nginx.conf').write_bytes(old_nginx)
    with sqlite3.connect(root/'bot.db') as source, sqlite3.connect(backup/'bot.db') as target:
        source.backup(target)
    print('Backup:', backup, flush=True)
    run('systemctl', 'stop', *SERVICES)
    try:
        for name, data in payload.items():
            if name == CONFIG:
                continue
            path = root/name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        nginx.write_bytes(payload[CONFIG])
        run('nginx', '-t')
        run('systemctl', 'start', *SERVICES)
        ready = False
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:18191/site/auth/me', timeout=2) as response:
                    ready = response.status == 200
                if ready:
                    break
            except Exception:
                time.sleep(1)
        if not ready:
            raise RuntimeError('Website did not become healthy')
        run('systemctl', 'is-active', *SERVICES)
        run('systemctl', 'reload', 'nginx')
    except BaseException:
        run('systemctl', 'stop', *SERVICES)
        for name, data in originals.items():
            (root/name).write_bytes(data)
        nginx.write_bytes(old_nginx)
        for name in NEW:
            (root/name).unlink(missing_ok=True)
        # Schema additions remain; never roll back real user activity.
        run('nginx', '-t')
        run('systemctl', 'start', *SERVICES)
        run('systemctl', 'reload', 'nginx')
        raise
    print('Website installed; shared user data and media preserved.', flush=True)

if __name__ == '__main__':
    main()
