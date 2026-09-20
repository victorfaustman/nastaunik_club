"""One-off guarded tracks release. Run with server Python and a selected-file archive."""
import asyncio
import hashlib
import py_compile
import sqlite3
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

BASELINES = {
    'bot/database.py': 'cc8418883c13e1507e44fe1234160e0a18eff069abb06e41be97012146f1a550',
    'bot/learning.py': 'f7cbf52a05f8de46733fff3760276100392a19d7b8db19ffad34eb30e1397850',
    'bot/mini_app.py': 'd34523ea80cde65379003b0d9bfd70e58aff3a9d128ca2fc4ce45913f930b41d',
    'bot/course_admin.py': '74755520ae27325cf346e00758d3ea2e5b9a922a515343e67f4122332807529d',
    'bot/learning_admin_v2.py': '6bed8e8acbaf724133d5340aaeb9727c60bd8be50eb172af3da483576820bcfd',
    'mini_app/static/app.js': '91ee386de93977533f968ac6fa22fd805b2c8c3894a7685078022ed5a21c87c1',
    'mini_app/index.html': 'f9a602fa97b995c3b43b1eaf72d6c14f52b0d5e0a970361feaafff3751dee332',
}
NEW = {'bot/tracks.py', 'bot/track_admin.py', 'mini_app/static/tracks.js',
       'mini_app/static/tracks.css', 'mini_app/static/track-admin.js'}


def main():
    root = Path('/opt/nastaunik_club').resolve()
    if root != Path('/opt/club-bot'):
        raise RuntimeError('Unexpected application root')
    for name, digest in BASELINES.items():
        if hashlib.sha256((root/name).read_bytes()).hexdigest() != digest:
            raise RuntimeError(f'Production changed; refusing to overwrite {name}')
    if any((root/name).exists() for name in NEW):
        raise RuntimeError('New release files already exist; inspect before retrying')
    archive = tarfile.open(sys.argv[1], 'r:gz')
    members = archive.getmembers()
    expected = set(BASELINES) | NEW
    if len(members) != len(expected) or {m.name for m in members} != expected or any(not m.isfile() for m in members):
        raise RuntimeError('Unexpected release contents')
    payload = {m.name: archive.extractfile(m).read() for m in members}
    for name, data in payload.items():
        if name.endswith('.py'):
            compile(data, name, 'exec')
    backup = Path('/opt/nastaunik-backups')/('tracks-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True, exist_ok=False)
    with tarfile.open(backup/'code.tar.gz', 'w:gz') as out:
        for name in BASELINES:
            out.add(root/name, arcname=name)
    with sqlite3.connect(root/'bot.db') as source, sqlite3.connect(backup/'bot.db') as target:
        source.backup(target)
    print('Backup:', backup, flush=True)
    subprocess.run(['systemctl', 'stop', 'nastaunik-club-admin'], check=True)
    try:
        for name, data in payload.items():
            (root/name).write_bytes(data)
        sys.path.insert(0, str(root))
        from bot.database import Database
        asyncio.run(Database(root/'bot.db').init())
        for name in payload:
            if name.endswith('.py'):
                py_compile.compile(str(root/name), doraise=True)
    except BaseException:
        with tarfile.open(backup/'code.tar.gz') as old:
            for name in BASELINES:
                (root/name).write_bytes(old.extractfile(name).read())
        # Keep additive schema changes; no user data is reverted or overwritten.
        for name in NEW:
            (root/name).unlink(missing_ok=True)
        raise
    finally:
        subprocess.run(['systemctl', 'start', 'nastaunik-club-admin'], check=True)
    print('Tracks release installed; bot files and credentials unchanged.', flush=True)


if __name__ == '__main__':
    main()
