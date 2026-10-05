"""Scoped favicon deployment with backup and rollback."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import shutil
import subprocess
import time
import urllib.request

def main():
    root = Path('/opt/club-bot')
    payload = Path(__file__).resolve().parent.parent
    code = 'bot/website.py'
    icons = ['website/favicon.svg', 'website/favicon-32.png', 'website/apple-touch-icon.png']
    if hashlib.sha256((root/code).read_bytes()).hexdigest() != 'd02998de2b0a862bb760606150de44e96d6dfd2cd9138c9373fb78c265a44490':
        raise RuntimeError('Website code changed; inspect again')
    if any((root/icon).exists() for icon in icons):
        raise RuntimeError('Refusing to overwrite existing icons')
    backup = Path('/opt/nastaunik-backups')/('website-favicon-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    (backup/'bot').mkdir(parents=True)
    shutil.copy2(root/code, backup/code)
    print('Backup:', backup, flush=True)
    try:
        for name in icons+[code]:
            shutil.copy2(payload/name, root/name)
        subprocess.run([str(root/'.venv/bin/python'), '-m', 'py_compile', str(root/code)], check=True)
        subprocess.run(['systemctl', 'restart', 'nastaunik-club-admin'], check=True)
        for _ in range(20):
            try:
                with urllib.request.urlopen('https://nastaunik.aiteacher.by/', timeout=5) as response:
                    if 'favicon.svg?v=1' in response.read().decode():
                        print('Healthy', flush=True)
                        return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError('Health check failed')
    except BaseException:
        shutil.copy2(backup/code, root/code)
        subprocess.run(['systemctl', 'restart', 'nastaunik-club-admin'], check=True)
        # Keep newly added icons recoverable; they are no longer referenced.
        raise

if __name__ == '__main__':
    main()
