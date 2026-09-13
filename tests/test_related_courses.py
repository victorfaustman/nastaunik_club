import tempfile
import unittest
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from bot.database import Database
from bot.learning import get_material, get_course
from bot.learning_admin_v2 import LearningAdmin


class RelatedCoursesTests(unittest.IsolatedAsyncioTestCase):
    async def test_editor_add_remove_and_publication(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(Path(directory)/'test.db');await db.init()
            async with db.connect() as conn:
                m=await conn.execute("INSERT INTO mini_app_materials(title,status,created_at,updated_at) VALUES('Article','published','now','now')")
                c=await conn.execute("INSERT INTO mini_app_courses(title,status,created_at,updated_at) VALUES('Course','published','now','now')")
                mid,cid=m.lastrowid,c.lastrowid;await conn.commit()
            admin=LearningAdmin(db.path,lambda path,**q:path)
            app=web.Application();app.router.add_post('/action',admin.action);app.router.add_get('/editor',admin.page)
            async with TestClient(TestServer(app)) as client:
                form={'action':'related_course_add','material_id':str(mid),'course_id':str(cid)}
                response=await client.post('/action',data=form,allow_redirects=False)
                self.assertEqual(response.status,303,await response.text())
                self.assertEqual((await get_material(db,mid))['related_courses'][0]['id'],cid)
                self.assertEqual((await get_course(db,cid,None))['related_materials'][0]['id'],mid)
                course_page=await client.get(f'/editor?course={cid}')
                self.assertEqual(course_page.status,200,await course_page.text())
                self.assertIn('course_related_material_delete',await course_page.text())
                response=await client.get(f'/editor?material={mid}')
                self.assertEqual(response.status,200,await response.text())
                self.assertIn('Курс · Course',await response.text())
                async with db.connect() as conn:
                    await conn.execute("UPDATE mini_app_courses SET status='draft' WHERE id=?",(cid,));await conn.commit()
                self.assertEqual((await get_material(db,mid))['related_courses'],[])
                self.assertEqual((await client.post('/action',data=form)).status,400)
                form['action']='related_course_delete'
                self.assertEqual((await client.post('/action',data=form,allow_redirects=False)).status,303)
                async with db.connect() as conn:
                    self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM mini_app_material_course_relations')).fetchone())[0],0)
                manual={'action':'course_related_material_add','course_id':str(cid),'material_id':str(mid)}
                self.assertEqual((await client.post('/action',data=manual,allow_redirects=False)).status,303)
                async with db.connect() as conn:
                    await conn.execute("UPDATE mini_app_courses SET status='published' WHERE id=?",(cid,));await conn.commit()
                self.assertEqual((await get_course(db,cid,None))['related_materials'][0]['id'],mid)
                self.assertEqual((await get_material(db,mid))['related_courses'][0]['id'],cid)
                manual['action']='course_related_material_delete'
                self.assertEqual((await client.post('/action',data=manual,allow_redirects=False)).status,303)
                self.assertEqual((await get_course(db,cid,None))['related_materials'],[])
