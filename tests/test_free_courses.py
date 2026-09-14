import tempfile
import unittest
from pathlib import Path
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from bot.database import Database
from bot.mini_app import MiniApp
from bot.learning_admin_v2 import LearningAdmin
from tests.test_mini_app import InitDataValidationTests


class FreeCourseTests(unittest.IsolatedAsyncioTestCase):
    async def test_free_course_access_progress_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            db=Database(Path(directory)/'test.db');await db.init()
            await db.upsert_user(43,'member','Member')
            async with db.connect() as conn:
                for cid,free in [(1,0),(2,1)]:
                    await conn.execute("INSERT INTO mini_app_courses(id,title,status,is_free,sort_order,created_at,updated_at) VALUES(?,?,'published',?,?,'now','now')",(cid,f'Course {cid}',free,cid))
                    await conn.execute("INSERT INTO mini_app_course_units(id,course_id,title,created_at,updated_at) VALUES(?,?,'Lesson','now','now')",(cid,cid))
                await conn.commit()
            mini=MiniApp(db,'123:TEST',set(),{42})
            app=web.Application()
            app.router.add_get('/bootstrap',mini.bootstrap)
            routes=[('/course/{course_id}',mini.course,'GET'),('/course/{course_id}/lesson/{lesson_id}',mini.course_lesson,'GET'),('/course/{course_id}/lesson/{lesson_id}/complete',mini.course_lesson_complete,'POST'),('/course/{course_id}/like',mini.course_like,'POST'),('/course/{course_id}/review',mini.course_review,'POST'),('/course/{course_id}/lesson/{lesson_id}/test/{block_id}',mini.course_test_answer,'POST'),('/course/{course_id}/lesson/{lesson_id}/assignment/{block_id}',mini.course_assignment_submit,'POST'),('/course/{course_id}/lesson/{lesson_id}/video/{block_id}',mini.course_video_event,'POST')]
            for path,handler,method in routes:app.router.add_route(method,path,handler)
            admin=LearningAdmin(db.path,lambda path,**q:path)
            app.router.add_post('/admin',admin.action)
            headers={'X-Telegram-Init-Data':InitDataValidationTests().make_init_data(user_id=43)}
            async with TestClient(TestServer(app)) as client:
                data=await (await client.get('/bootstrap',headers=headers)).json()
                self.assertEqual([c['id'] for c in data['courses']],[1,2])
                self.assertTrue(data['courses'][0]['locked']);self.assertFalse(data['courses'][1]['locked'])
                for path,_,method in routes:
                    url=path.format(course_id=1,lesson_id=1,block_id=1)
                    self.assertEqual((await client.request(method,url,headers=headers)).status,403,url)
                self.assertEqual((await client.get('/course/2',headers=headers)).status,200)
                self.assertEqual((await client.get('/course/2/lesson/2',headers=headers)).status,200)
                result=await client.post('/course/2/lesson/2/complete',headers=headers)
                self.assertEqual(result.status,200,await result.text())
                self.assertTrue((await result.json())['completed'])
                self.assertEqual((await client.post('/course/2/like',headers=headers)).status,200)
                form={'action':'course_save','course_id':'2','title':'Free course','is_visible':'1','is_free':'1'}
                self.assertEqual((await client.post('/admin',data=form,allow_redirects=False)).status,303)
                async with db.connect() as conn:
                    snapshot=await admin.course_admin.course_snapshot(conn,2)
                    self.assertEqual(snapshot['is_free'],1)
                del form['is_free']
                self.assertEqual((await client.post('/admin',data=form,allow_redirects=False)).status,303)
                self.assertEqual((await client.get('/course/2',headers=headers)).status,403)
                async with db.connect() as conn:
                    revision=await (await conn.execute("SELECT id FROM mini_app_admin_revisions WHERE entity_type='course' AND entity_id=2 AND json_extract(snapshot_json,'$.is_free')=1 ORDER BY id DESC LIMIT 1")).fetchone()
                self.assertIsNotNone(revision)
                restore={'action':'course_revision_restore','course_id':'2','revision_id':str(revision['id'])}
                self.assertEqual((await client.post('/admin',data=restore,allow_redirects=False)).status,303)
                self.assertEqual((await client.get('/course/2',headers=headers)).status,200)
