"""Explicit, additive, idempotent import. Never run as an application startup seed."""
import argparse
import hashlib
import json
import re
import sqlite3
import sys
import unicodedata
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from content.notion_free_20261005 import ARTICLES, BATCH, EXISTING_RELATIONS, RELATIONS

def normal(value):
    return ' '.join(unicodedata.normalize('NFKC', value or '').casefold().split())

def covers(directory):
    result = {}
    for item in ARTICLES:
        files = list(directory.glob(item['key']+'.*'))
        if len(files) != 1 or files[0].suffix not in {'.jpg','.png','.webp'}:
            raise RuntimeError('Missing or ambiguous cover: '+item['key'])
        data = files[0].read_bytes()
        if len(data)<32 or not (data.startswith(b'\x89PNG\r\n\x1a\n') or data.startswith(b'\xff\xd8') or (data[:4]==b'RIFF' and data[8:12]==b'WEBP')):
            raise RuntimeError('Invalid image header: '+str(files[0]))
        digest = hashlib.sha256(data).hexdigest()
        result[item['key']] = ('notion-free-'+item['key']+'-'+digest[:12]+files[0].suffix, data)
    return result

def download(directory):
    directory.mkdir(parents=True, exist_ok=True)
    for item in ARTICLES:
        with urllib.request.urlopen(urllib.request.Request(item['cover_source'], headers={'User-Agent':'Mozilla/5.0'}), timeout=40) as response:
            data = response.read(16*1024*1024+1)
        if len(data) > 16*1024*1024:
            raise RuntimeError('Unexpected image size')
        ext = '.png' if data.startswith(b'\x89PNG') else '.jpg' if data.startswith(b'\xff\xd8') else '.webp' if data[:4] == b'RIFF' and data[8:12] == b'WEBP' else None
        if not ext:
            raise RuntimeError('Not an image: '+item['key'])
        target = directory/(item['key']+ext)
        if target.exists() and target.read_bytes() != data:
            raise RuntimeError('Cover changed; inspect before replacing '+str(target))
        target.write_bytes(data)
        print('Downloaded', item['key'], len(data))
    covers(directory)

def resolve_targets(conn):
    current = list(conn.execute('SELECT id,title,full_description,status,library_visible FROM mini_app_materials'))
    by_title = {}
    for row in current:
        by_title.setdefault(normal(row['title']), []).append(row)
    courses = {}
    for item in ARTICLES:
        for title in item['courses']:
            rows = list(conn.execute("SELECT id FROM mini_app_courses WHERE title=? AND status='published'", (title,)))
            if len(rows) != 1:
                raise RuntimeError('Missing or ambiguous published course: '+title)
            courses[title] = rows[0]['id']
    existing = {}
    for key, titles in EXISTING_RELATIONS.items():
        existing[key] = []
        for title in titles:
            rows = [r for r in by_title.get(normal(title), []) if r['status']=='published' and r['library_visible']]
            if len(rows) != 1:
                raise RuntimeError('Missing or ambiguous related material: '+title)
            existing[key].append(rows[0]['id'])
    # Fail before writing if a previous manual import used the same title or source.
    for item in ARTICLES:
        if normal(item['title']) in by_title or any(item['source'] in (r['full_description'] or '') for r in current):
            raise RuntimeError('Possible duplicate; inspect instead of overwriting: '+item['title'])
    return courses, existing

def import_batch(conn, media_dir, cover_dir):
    images = covers(cover_dir)
    created_files = []
    now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec='seconds')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.execute('''CREATE TABLE IF NOT EXISTS mini_app_content_imports(
          batch_id TEXT NOT NULL,source_url TEXT NOT NULL,material_id INTEGER NOT NULL REFERENCES mini_app_materials(id),
          content_sha256 TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(batch_id,source_url))''')
        previous = list(conn.execute('SELECT source_url,material_id FROM mini_app_content_imports WHERE batch_id=?', (BATCH,)))
        if previous:
            if len(previous)!=12 or {r['source_url'] for r in previous}!={a['source'] for a in ARTICLES}:
                raise RuntimeError('Partial or unexpected prior import')
            conn.rollback()
            return {'already_imported':True,'materials':{r['source_url']:r['material_id'] for r in previous}}
        courses, existing = resolve_targets(conn)
        from bot.learning_admin_v2 import clean_rich_text
        for item in ARTICLES:
            if clean_rich_text(item['html']) != item['html']:
                raise RuntimeError('Article is not compatible with the existing sanitizer: '+item['key'])
        media_dir.mkdir(parents=True,exist_ok=True)
        tags = {normal(r['name']):r['id'] for r in conn.execute('SELECT id,name FROM mini_app_tags')}
        new_tags = []
        ids = {}
        # Same default sort order as manually created articles. Do not reorder existing rows.
        for item in ARTICLES:
            filename,data = images[item['key']]
            target = media_dir/filename
            if target.exists():
                if target.read_bytes()!=data:
                    raise RuntimeError('Media filename collision')
            else:
                with target.open('xb') as out: out.write(data)
                created_files.append(target)
            cur = conn.execute('''INSERT INTO mini_app_materials(title,short_description,full_description,cover_url,
              is_free,library_visible,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,1,1,'published',0,?,?)''',
              (item['title'],item['description'],item['html'],'/mini-app/media/'+filename,now,now))
            material_id = ids[item['key']] = cur.lastrowid
            tag_ids = []
            for name in item['tags']:
                if normal(name) not in tags:
                    slug = 'notion-'+hashlib.sha256(normal(name).encode()).hexdigest()[:12]
                    cur = conn.execute('INSERT INTO mini_app_tags(name,slug,color,created_at,updated_at) VALUES(?,?,?,?,?)', (name,slug,'#c77a59',now,now))
                    tags[normal(name)] = cur.lastrowid
                    new_tags.append(cur.lastrowid)
                tag_id=tags[normal(name)]; tag_ids.append(tag_id)
                conn.execute('INSERT INTO mini_app_material_tags(material_id,tag_id) VALUES(?,?)',(material_id,tag_id))
            snapshot=dict(title=item['title'],short_description=item['description'],full_description=item['html'],
                          cover_url='/mini-app/media/'+filename,is_free=1,library_visible=1,status='published',tag_ids=sorted(tag_ids))
            conn.execute('INSERT INTO mini_app_admin_revisions(entity_type,entity_id,snapshot_json,source,created_at) VALUES(?,?,?,?,?)',
                         ('material',material_id,json.dumps(snapshot,ensure_ascii=False,sort_keys=True,separators=(',',':')),'manual',now))
            conn.execute('INSERT INTO mini_app_content_imports VALUES(?,?,?,?,?)',(BATCH,item['source'],material_id,hashlib.sha256(item['html'].encode()).hexdigest(),now))
            for title in item['courses']:
                conn.execute('INSERT INTO mini_app_material_course_relations(material_id,course_id) VALUES(?,?)',(material_id,courses[title]))
        def relate(a,b):
            # Explicitly insert both directions; works with and without mirroring triggers.
            for source,target in ((a,b),(b,a)):
                order=conn.execute('SELECT COALESCE(MAX(sort_order),-1)+1 FROM mini_app_material_relations WHERE material_id=?',(source,)).fetchone()[0]
                conn.execute('INSERT OR IGNORE INTO mini_app_material_relations(material_id,related_material_id,sort_order,created_at) VALUES(?,?,?,?)',(source,target,order,now))
        for a,b in RELATIONS: relate(ids[a],ids[b])
        for key, targets in existing.items():
            for target in targets: relate(ids[key],target)
        conn.commit()
        return dict(already_imported=False,materials=ids,created_tags=new_tags,covers=[p.name for p in created_files])
    except BaseException:
        conn.rollback()
        for path in created_files: path.unlink()
        raise

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--download-covers',type=Path)
    parser.add_argument('--db',type=Path)
    parser.add_argument('--covers',type=Path)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    if args.download_covers:
        download(args.download_covers); return
    if not args.db or not args.covers or not args.db.is_file(): parser.error('Provide existing --db and --covers')
    conn=sqlite3.connect(args.db,timeout=30);conn.row_factory=sqlite3.Row
    if not args.apply:
        covers(args.covers)
        courses,existing=resolve_targets(conn)
        print(json.dumps(dict(articles=len(ARTICLES),courses=courses,existing_links=existing),ensure_ascii=False,indent=2));return
    db=args.db.resolve()
    if db!=Path('/opt/club-bot/bot.db'): raise RuntimeError('Production target must be /opt/club-bot/bot.db')
    backup=Path('/opt/nastaunik-backups')/(BATCH+'-'+datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(parents=True,exist_ok=False)
    with sqlite3.connect(backup/'bot.db') as target: conn.backup(target)
    print('Backup:',backup,flush=True)
    result=import_batch(conn,db.parent/'media/mini_app',args.covers)
    (backup/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
