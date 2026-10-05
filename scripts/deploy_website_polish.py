"""Guarded final dark-theme contrast and cache-version update."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import shutil
import subprocess
import time
import urllib.request

EXPECTED={'bot/website.py':'07adeda2ff326ed1f406b647059eec99480f17d69d393c85ca8ff89f8d45385f','website/site.css':'6652186a49bf8503e12e0249778a9835ea17d2ef54cbdf1747a6f385c7e2a553'}
def main():
    root=Path('/opt/club-bot');payload=Path(__file__).resolve().parent.parent
    for name,value in EXPECTED.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest()!=value: raise RuntimeError('Live file changed: '+name)
    backup=Path('/opt/nastaunik-backups')/('website-polish-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    for name in EXPECTED:
        (backup/name).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,backup/name)
    print('Backup:',backup,flush=True)
    try:
        for name in EXPECTED: shutil.copy2(payload/name,root/name)
        subprocess.run(['systemctl','restart','nastaunik-club-admin'],check=True)
        for _ in range(20):
            try:
                with urllib.request.urlopen('https://nastaunik.aiteacher.by/',timeout=5) as r:
                    if 'site.css?v=4' in r.read().decode(): print('Healthy');return
            except Exception: pass
            time.sleep(1)
        raise RuntimeError('Health check failed')
    except BaseException:
        for name in EXPECTED: shutil.copy2(backup/name,root/name)
        subprocess.run(['systemctl','restart','nastaunik-club-admin'],check=True);raise
if __name__=='__main__': main()
