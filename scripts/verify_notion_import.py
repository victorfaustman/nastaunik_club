"""Read-only production verification against the pre-import backup."""
import json
import sqlite3
import urllib.request
from pathlib import Path

def main():
    before = sqlite3.connect('/opt/nastaunik-backups/notion-free-20261005-20261005-094427/bot.db')
    now = sqlite3.connect('/opt/club-bot/bot.db')
    for table in ('mini_app_materials','mini_app_courses','mini_app_tags'):
        old = before.execute('SELECT * FROM '+table+' ORDER BY id').fetchall()
        ids = [row[0] for row in old]
        current = now.execute('SELECT * FROM '+table+' WHERE id IN ('+','.join('?' for _ in ids)+') ORDER BY id', ids).fetchall()
        assert old == current, 'Existing rows changed: '+table
    imported = now.execute("SELECT material_id FROM mini_app_content_imports WHERE batch_id='notion-free-20261005'").fetchall()
    assert len(imported) == 12
    ids = {row[0] for row in imported}
    assert now.execute('PRAGMA foreign_key_check').fetchall() == []
    for source, target in now.execute('SELECT material_id,related_material_id FROM mini_app_material_relations'):
        if source in ids or target in ids:
            assert now.execute('SELECT 1 FROM mini_app_material_relations WHERE material_id=? AND related_material_id=?',(target, source)).fetchone()
    request = urllib.request.Request('https://nastaunik.aiteacher.by/mini-app/api/bootstrap', headers={'X-Nastaunik-Site':'1'})
    data = json.load(urllib.request.urlopen(request, timeout=20))
    materials = [m for m in data['materials'] if m['id'] in ids]
    assert len(materials) == 12
    for item in materials:
        assert item['is_free'] and not item['locked'], item['title']
        cover = item['cover_url']
        with urllib.request.urlopen('https://nastaunik.aiteacher.by'+cover, timeout=20) as response:
            assert response.status == 200 and response.headers['Content-Type'].startswith('image/')
        request = urllib.request.Request('https://nastaunik.aiteacher.by/mini-app/api/material/'+str(item['id']),headers={'X-Nastaunik-Site':'1'})
        detail = json.load(urllib.request.urlopen(request, timeout=20))
        assert detail.get('full_description'), item['title']
    print('PASS: 12 free public articles and covers; reciprocal links; original materials, courses and tags unchanged; foreign keys valid.')

if __name__ == '__main__':
    main()
