import json
import tempfile
import unittest
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from bot.database import Database
from bot.learning import get_bootstrap
from bot.learning_admin_v2 import LearningAdmin


class CourseOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_order_move_reorder_new_course_and_audiences(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(Path(directory)/'db.sqlite');await db.init()
            async with db.connect() as conn:
                for cid,free,status in [(1,0,'published'),(2,1,'published'),(3,0,'draft')]:
                    await conn.execute('INSERT INTO mini_app_courses(id,title,status,is_free,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',(cid,str(cid),status,free,cid,'now','now'))
                await conn.commit()
            admin=LearningAdmin(db.path,lambda path,**q:path)
            app=web.Application();app.router.add_post('/action',admin.action);app.router.add_get('/page',admin.page)
            async with TestClient(TestServer(app)) as client:
                page=await client.get('/page?section=courses');self.assertEqual(page.status,200,await page.text())
                self.assertIn('data-course-drag',await page.text())
                for state in ['new','active']:
                    data=await get_bootstrap(db,{'telegram_id':0,'state':state})
                    self.assertEqual([c['id'] for c in data['courses']],[1,2])
                move={'action':'course_move','course_id':'2','direction':'up'}
                self.assertEqual((await client.post('/action',data=move,allow_redirects=False)).status,303)
                data=await get_bootstrap(db,{'telegram_id':0,'state':'new'})
                self.assertEqual([c['id'] for c in data['courses']],[2,1])
                reorder={'action':'course_reorder','original_order':json.dumps([2,1,3]),'order':json.dumps([3,1,2])}
                self.assertEqual((await client.post('/action',data=reorder)).status,200)
                self.assertEqual((await client.post('/action',data=reorder)).status,409)
                reorder.update(original_order=json.dumps([3,1,2]),order=json.dumps([1,1,2]))
                self.assertEqual((await client.post('/action',data=reorder)).status,409)
                self.assertEqual((await client.post('/action',data={'action':'course_save','title':'New','is_visible':'1'},allow_redirects=False)).status,303)
                data=await get_bootstrap(db,{'telegram_id':0,'state':'new'})
                self.assertEqual([c['id'] for c in data['courses']],[1,2,4])
                self.assertEqual((await client.post('/action',data={'action':'course_save','course_id':'1','title':'Edited','is_visible':'1'},allow_redirects=False)).status,303)
                data=await get_bootstrap(db,{'telegram_id':0,'state':'active'})
                self.assertEqual([c['id'] for c in data['courses']],[1,2,4])
