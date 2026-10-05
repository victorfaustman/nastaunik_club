"""Install generated track covers only if the catalog has not changed.

Run on the server with a manifest path. Keeps a SQLite backup and a row snapshot;
updates covers/version/timestamp only, never track steps or subscription rules.
"""
from pathlib import Path
import hashlib
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone

def main():
    manifest_path = Path(sys.argv[1]).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    root = Path('/opt/club-bot')
    media = root/'media/mini_app'
    db = sqlite3.connect(root/'bot.db', timeout=30)
    db.row_factory = sqlite3.Row
    rows = []
    for item in manifest['tracks']:
        row = db.execute('SELECT * FROM mini_app_tracks WHERE id=?', (item['id'],)).fetchone()
        if not row or row['version'] != item['version'] or row['cover_url'] != item['previous_cover'] or row['title'] != item['title']:
            raise RuntimeError('Track changed; inspect again: '+str(item['id']))
        source = manifest_path.parent/item['file']
        if hashlib.sha256(source.read_bytes()).hexdigest() != item['sha256']:
            raise RuntimeError('Asset checksum mismatch')
        target = media/source.name
        if target.exists():
            raise RuntimeError('Refusing to overwrite '+str(target))
        rows.append(dict(row))
    backup = Path('/opt/nastaunik-backups')/('track-covers-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True)
    with sqlite3.connect(backup/'bot.db') as dest:
        db.backup(dest)
    (backup/'tracks-before.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Backup:', backup, flush=True)
    db.execute('BEGIN IMMEDIATE')
    try:
        for item in manifest['tracks']:
            source = manifest_path.parent/item['file']
            shutil.copy2(source, media/source.name)
            cursor = db.execute('UPDATE mini_app_tracks SET cover_url=?,version=version+1,updated_at=? WHERE id=? AND version=? AND cover_url=?',
                ('/mini-app/media/'+source.name, datetime.now(timezone.utc).isoformat(timespec='seconds'), item['id'], item['version'], item['previous_cover']))
            if cursor.rowcount != 1:
                raise RuntimeError('Concurrent edit; changes rolled back')
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()
    print('Installed', len(rows), 'covers; services need no restart', flush=True)

if __name__ == '__main__':
    main()
