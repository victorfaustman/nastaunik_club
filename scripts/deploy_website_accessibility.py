"""Deploy the accessibility delta with checked live hashes and rollback."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import shutil
import subprocess
import time
import urllib.request

EXPECTED = {
    'website/site.css': '9625c327d634278c73a21b32c5237edddd9817310f6781040d78f5a9d87e41e2',
    'website/site.js': '33436fbd355ac317500f82509c5c2e49b9ec2027e89cf6be3ac948bbf9e1c048',
    'bot/website.py': 'd7d89a6a153e23ee6735d317179a89b8132bfdaa7ec7f5ccc9ca8958ae666450',
}

def main():
    root = Path('/opt/club-bot')
    payload = Path(__file__).resolve().parent.parent
    for name, digest in EXPECTED.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError('Live file changed: '+name)
    backup = Path('/opt/nastaunik-backups')/('website-accessibility-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    for name in EXPECTED:
        (backup/name).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root/name, backup/name)
    print('Backup:', backup, flush=True)
    try:
        for name in EXPECTED:
            shutil.copy2(payload/name, root/name)
        subprocess.run([str(root/'.venv/bin/python'), '-m', 'py_compile', str(root/'bot/website.py')], check=True)
        subprocess.run(['systemctl', 'restart', 'nastaunik-club-admin'], check=True)
        for _ in range(20):
            try:
                with urllib.request.urlopen('https://nastaunik.aiteacher.by/', timeout=5) as response:
                    if 'site.css?v=7' in response.read().decode():
                        print('Healthy', flush=True)
                        return
            except Exception:
                pass
            time.sleep(1)
        raise RuntimeError('Health check failed')
    except BaseException:
        for name in EXPECTED:
            shutil.copy2(backup/name, root/name)
        subprocess.run(['systemctl', 'restart', 'nastaunik-club-admin'], check=True)
        raise

if __name__ == '__main__':
    main()
