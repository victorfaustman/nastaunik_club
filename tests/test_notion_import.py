import asyncio
import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bot.database import Database
from bot.learning import get_bootstrap, get_material
from content.notion_free_20261005 import ARTICLES, EXISTING_RELATIONS
from scripts.import_notion_materials import import_batch, resolve_targets

class NotionImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.path=self.root/'test.db'; asyncio.run(Database(self.path).init())
        self.conn=sqlite3.connect(self.path);self.conn.row_factory=sqlite3.Row
        self.covers=self.root/'covers';self.covers.mkdir()
        image=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aHdoAAAAASUVORK5CYII=')
        for item in ARTICLES:(self.covers/(item['key']+'.png')).write_bytes(image)
        for title in {t for a in ARTICLES for t in a['courses']}:
            self.conn.execute("INSERT INTO mini_app_courses(title,is_free,status,created_at,updated_at) VALUES(?,0,'published','before','before')",(title,))
        for title in {t for ts in EXISTING_RELATIONS.values() for t in ts}:
            self.conn.execute("INSERT INTO mini_app_materials(title,full_description,is_free,status,created_at,updated_at) VALUES(?,'<p>Existing paid content</p>',0,'published','before','before')",(title,))
        self.conn.execute("INSERT INTO mini_app_tags(name,slug,color,created_at) VALUES('Промты','prompts','#123456','before')")
        self.conn.commit()
        self.old_materials=[tuple(r) for r in self.conn.execute('SELECT * FROM mini_app_materials ORDER BY id')]
        self.old_courses=[tuple(r) for r in self.conn.execute('SELECT * FROM mini_app_courses ORDER BY id')]

    def tearDown(self):self.conn.close();self.tmp.cleanup()

    def test_free_access_reciprocity_covers_and_no_old_changes(self):
        result=import_batch(self.conn,self.root/'media',self.covers)
        ids=list(result['materials'].values());self.assertEqual(len(ids),12)
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM mini_app_materials ORDER BY id') if r['id'] not in ids],self.old_materials)
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM mini_app_courses ORDER BY id')],self.old_courses)
        self.assertEqual(self.conn.execute("SELECT color FROM mini_app_tags WHERE slug='prompts'").fetchone()[0],'#123456')
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM mini_app_admin_revisions WHERE entity_type='material'").fetchone()[0],12)
        for row in self.conn.execute('SELECT material_id,related_material_id FROM mini_app_material_relations'):
            self.assertNotEqual(row[0],row[1])
            self.assertIsNotNone(self.conn.execute('SELECT 1 FROM mini_app_material_relations WHERE material_id=? AND related_material_id=?',(row[1],row[0])).fetchone())
        async def check():
            db=Database(self.path)
            data=await get_bootstrap(db,dict(telegram_id=0,state='new'))
            imported=[a for a in data['materials'] if a['id'] in ids]
            self.assertEqual(len(imported),12)
            for item in imported:
                self.assertFalse(item['locked']);self.assertTrue(item['is_free']);self.assertTrue(item['tags'])
                detail=await get_material(db,item['id'])
                self.assertIn('<pre><code>',detail['full_description'])
                self.assertNotIn('Loading JavaScript',detail['full_description'])
                self.assertTrue(detail['related_materials']);self.assertTrue(detail['related_courses'])
                self.assertTrue((self.root/'media'/item['cover_url'].rsplit('/',1)[1]).is_file())
            self.assertTrue(all(c['locked'] for c in data['courses']))
        asyncio.run(check())

    def test_retry_is_noop_and_does_not_overwrite_manual_edits(self):
        first=import_batch(self.conn,self.root/'media',self.covers)
        material=first['materials']['prompt']
        self.conn.execute('UPDATE mini_app_materials SET title=? WHERE id=?',('My subsequent edit',material));self.conn.commit()
        count=self.conn.execute('SELECT COUNT(*) FROM mini_app_materials').fetchone()[0]
        second=import_batch(self.conn,self.root/'media',self.covers)
        self.assertTrue(second['already_imported']);self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM mini_app_materials').fetchone()[0],count)
        self.assertEqual(self.conn.execute('SELECT title FROM mini_app_materials WHERE id=?',(material,)).fetchone()[0],'My subsequent edit')

    def test_duplicate_title_aborts_before_media_and_data_changes(self):
        self.conn.execute("INSERT INTO mini_app_materials(title,created_at,updated_at) VALUES(?,'before','before')",(ARTICLES[0]['title'],));self.conn.commit()
        before=self.conn.execute('SELECT COUNT(*) FROM mini_app_materials').fetchone()[0]
        with self.assertRaisesRegex(RuntimeError,'duplicate'):import_batch(self.conn,self.root/'media',self.covers)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM mini_app_materials').fetchone()[0],before)
        self.assertFalse((self.root/'media').exists())

    def test_invalid_link_target_aborts(self):
        self.conn.execute("UPDATE mini_app_courses SET status='draft'");self.conn.commit()
        with self.assertRaisesRegex(RuntimeError,'course'):resolve_targets(self.conn)

if __name__=='__main__':unittest.main()
