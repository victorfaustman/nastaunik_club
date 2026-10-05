"""Guarded deployment of the website-only library menu, with rollback."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import py_compile
import shutil
import subprocess
import time
import urllib.request

EXPECTED = {
    'website/site.js': 'e3613788562002bf52f7886f0d4a843bf3cd9260cc5d1d4b80a012b5935b50b6',
    'website/site.css': '1abd0176c98c858bf75eb11f7c66792934a3e7ecf4160a652a07df6642dd846a',
    'bot/website.py': 'a3449203ab22d0b036f03c8277a8ec23c62d9c42c741018423ed3099874b38f3',
}

def main():
    root = Path('/opt/club-bot')
    payload = Path(__file__).resolve().parent.parent
    for name, expected in EXPECTED.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != expected:
            raise RuntimeError('Live file changed; refusing overwrite: '+name)
    py_compile.compile(str(payload/'bot/website.py'), doraise=True)
    backup = Path('/opt/nastaunik-backups')/('website-library-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    for name in EXPECTED:
        (backup/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root/name, backup/name)
    print('Backup:', backup, flush=True)
    try:
        for name in EXPECTED:
            shutil.copy2(payload/name, root/name)
        subprocess.run(['systemctl','restart','nastaunik-club-admin'], check=True)
        for attempt in range(15):
            try:
                with urllib.request.urlopen('https://nastaunik.aiteacher.by/library?type=materials', timeout=5) as response:
                    if response.status == 200 and 'site.js?v=2' in response.read().decode():
                        print('Website healthy. Mini App and bot files unchanged.');return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError('Website health check failed')
    except BaseException:
        for name in EXPECTED:
            shutil.copy2(backup/name, root/name)
        subprocess.run(['systemctl','restart','nastaunik-club-admin'], check=True)
        raise

if __name__ == '__main__':
    main()
