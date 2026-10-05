"""Guarded website hardening deployment; preserve unrelated services/configuration."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import py_compile
import shutil
import subprocess
import time
import urllib.request

EXPECTED={
 'admin_web.py':'2890f9509e1b6b359d8372e90de9a2ee92d2c0b743c65e274b948e4d06075f77',
 'bot/mini_app.py':'9c9baf5fdfdb93d9e6912ef0b0a9c66b6ed81f0b672ff455e2737b982d6a0109',
 'bot/website.py':'f196e874192a80f26264dbff9c35edf5026c0adae84e6f76e23b164c94a017d2',
 'website/site.js':'ef0bb6c3d58b1b33b5167643cdb5eea7a77be450b96ef814081ff8eb908ed2c7',
 'website/site.css':'a8cdbece6f71544eabdcaf7f6e078102ab86161f2ec7515b798221b347f88b12',
}
NEW=['bot/media_security.py','bot/website_pages.py']
NGINX=Path('/etc/nginx/conf.d/nastaunik-miniapp.conf')

def main():
    root=Path('/opt/club-bot');payload=Path(__file__).resolve().parent.parent
    for name,expected in EXPECTED.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=expected: raise RuntimeError('Live change: '+name)
    for name in NEW:
        if (root/name).exists(): raise RuntimeError('New target already exists: '+name)
    if hashlib.sha256(NGINX.read_bytes()).hexdigest()!='e47e67514be65cd56406addfb5e2e2b40dcea89fc1fa75fa3f5c263866590425': raise RuntimeError('Nginx changed')
    for name in list(EXPECTED)+NEW:
        if name.endswith('.py'): py_compile.compile(str(payload/name),doraise=True)
    backup=Path('/opt/nastaunik-backups')/('website-audit-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir();print('Backup:',backup,flush=True)
    for name in EXPECTED:
        (backup/name).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,backup/name)
    shutil.copy2(NGINX,backup/'nginx.conf')
    try:
        for name in list(EXPECTED)+NEW: shutil.copy2(payload/name,root/name)
        # Restart the app before removing the old static media alias.
        subprocess.run(['systemctl','restart','nastaunik-club-admin'],check=True)
        for attempt in range(20):
            try:
                with urllib.request.urlopen('https://nastaunik.aiteacher.by/',timeout=5) as r:
                    if 'site.js?v=3' in r.read().decode(): break
            except Exception: pass
            time.sleep(1)
        else: raise RuntimeError('New app did not start')
        # Only replace this exact block; never overwrite the rest of the live config.
        config=NGINX.read_text()
        old='''    location ^~ /mini-app/media/ {
        alias /opt/club-bot/media/mini_app/;
        sendfile on;
        tcp_nopush on;
        add_header Cache-Control "no-cache" always;
    }'''
        new='''    location ^~ /mini-app/media/ {
        proxy_pass http://127.0.0.1:18191;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 900s;
    }'''
        if config.count(old)!=1: raise RuntimeError('Expected media block not found')
        NGINX.write_text(config.replace(old,new))
        subprocess.run(['nginx','-t'],check=True);subprocess.run(['systemctl','reload','nginx'],check=True)
        with urllib.request.urlopen('https://nastaunik.aiteacher.by/robots.txt',timeout=10) as r:
            if 'text/plain' not in r.headers['Content-Type']: raise RuntimeError('Robots failed')
        print('DEPLOYED. Bot and database contents unchanged.',flush=True)
    except BaseException:
        for name in EXPECTED: shutil.copy2(backup/name,root/name)
        # New modules can remain unused; do not recursively delete files.
        shutil.copy2(backup/'nginx.conf',NGINX)
        subprocess.run(['nginx','-t'],check=True);subprocess.run(['systemctl','reload','nginx'],check=True)
        subprocess.run(['systemctl','restart','nastaunik-club-admin'],check=True)
        raise

if __name__=='__main__': main()
