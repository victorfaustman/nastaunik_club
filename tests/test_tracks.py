import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import urlencode

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from bot.database import Database
from bot.learning import get_bootstrap, complete_material, complete_course_lesson
from bot.learning_admin_v2 import LearningAdmin
from bot.mini_app import MiniApp
from bot.tracks import Tracks, catalog, preferences
from tests.test_mini_app import InitDataValidationTests


class TrackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.tmp.name)/'db.sqlite')
        await self.db.init()
        await self.db.upsert_user(42, 'owner', 'Owner')
        await self.db.upsert_user(43, 'member', 'Member')
        async with self.db.connect() as c:
            await c.execute("UPDATE users SET current_status='active' WHERE telegram_id=43")
            for i in (1, 2):
                await c.execute("INSERT INTO mini_app_materials(id,title,is_free,library_visible,status,created_at,updated_at) VALUES(?,?,?,1,'published','now','now')", (i, f'Material {i}', i==1))
            await c.execute("INSERT INTO mini_app_courses(id,title,status,created_at,updated_at) VALUES(1,'Course','published','now','now')")
            await c.execute("INSERT INTO mini_app_course_units(id,course_id,title,is_required,created_at,updated_at) VALUES(1,1,'Lesson',1,'now','now')")
            await c.commit()
        self.mini = MiniApp(self.db, '123:TEST', test_mode_ids={42})
        self.tracks = Tracks(self.mini)
        self.admin = LearningAdmin(self.db.path, lambda p, **q: ('/action' if p.endswith('/action') else '/page')+'?'+urlencode(q))
        app = web.Application()
        self.tracks.register(app)
        app.cleanup_ctx.clear()  # No real Telegram network in tests.
        app.router.add_post('/action', self.admin.action)
        app.router.add_get('/page', self.admin.page)
        app.router.add_get('/preview', self.mini.preview)
        app.router.add_get('/mini-app/preview', self.mini.preview)
        app.router.add_get('/mini-app/static/{filename:.*}', self.mini.static)
        app.router.add_get('/mini-app/api/material/{material_id}', self.mini.material)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    def headers(self, uid=43, mode=None):
        h = {'X-Telegram-Init-Data': InitDataValidationTests().make_init_data(user_id=uid)}
        if mode:
            h['X-Nastaunik-Test-Mode'] = mode
        return h

    async def create(self):
        form = dict(action='track_save', title='Start', description='Learn', level='beginner', published='1', steps=json.dumps([{'kind':'material','id':1},{'kind':'course','id':1},{'kind':'material','id':2}]))
        r = await self.client.post('/action', data=form, allow_redirects=False)
        self.assertEqual(r.status, 303, await r.text())
        return form

    async def test_editor_progress_access_order_conflict_and_preview(self):
        form = await self.create()
        r = await self.client.get('/page?section=tracks&track=1')
        self.assertEqual(r.status, 200, await r.text())
        self.assertIn('track-picker', await r.text())
        data = await catalog(self.db, dict(telegram_id=43, state='new'))
        self.assertEqual([s['locked'] for s in data['tracks'][0]['steps']], [False, True, True])
        await complete_material(self.db, 1, 43)
        await complete_course_lesson(self.db, 1, 1, 43)
        data = await get_bootstrap(self.db, dict(telegram_id=43, state='active'))
        self.assertEqual(data['tracks'][0]['progress'], 67)
        self.assertEqual(data['tracks'][0]['next_step']['item_id'], 2)
        form.update(track_id='1', version='1', steps=json.dumps([{'kind':'material','id':2},{'kind':'course','id':1},{'kind':'material','id':1}]))
        self.assertEqual((await self.client.post('/action',data=form,allow_redirects=False)).status,303)
        self.assertEqual((await self.client.post('/action',data=form,allow_redirects=False)).status,409)
        data=await catalog(self.db,dict(telegram_id=43,state='active'))
        self.assertEqual([s['item_id'] for s in data['tracks'][0]['steps']],[2,1,1])
        self.assertEqual(data['tracks'][0]['progress'],67)
        for mode in ('paid','unpaid'):
            r=await self.client.get('/preview?track=1&mode='+mode)
            self.assertEqual(r.status,200,await r.text())
            self.assertIn('NASTAUNIK_PREVIEW',await r.text())
        await self.client.post('/mini-app/api/tracks/1/select',headers=self.headers(42))
        r=await self.client.get('/mini-app/api/material/2',headers=self.headers(42))
        self.assertEqual(r.status,403)
        await self.client.post('/action',data=dict(action='track_delete',track_id='1',version='2'),allow_redirects=False)
        self.assertIsNone((await preferences(self.db,42))['active_track_id'])
        self.assertEqual((await get_bootstrap(self.db,dict(telegram_id=43,state='active')))['materials'][0]['viewed'],True)

    async def test_preferences_test_mode_isolation_and_validation(self):
        await self.create()
        self.assertEqual((await self.client.get('/mini-app/api/tracks')).status,401)
        self.assertEqual((await self.client.post('/mini-app/api/tracks/1/select',headers=self.headers())).status,200)
        self.assertFalse((await preferences(self.db,43))['reminders'])
        p=dict(tempo='calm',days=[1],reminders=True,local_time='19:30',timezone='Europe/Minsk')
        self.assertEqual((await self.client.post('/mini-app/api/tracks/preferences',json=p,headers=self.headers())).status,200)
        self.assertEqual((await self.client.post('/mini-app/api/tracks/preferences',json={**p,'days':[1,2]},headers=self.headers())).status,400)
        self.assertEqual((await self.client.post('/mini-app/api/tracks/preferences',json={**p,'timezone':'Bad/Zone'},headers=self.headers())).status,400)
        await self.client.post('/mini-app/api/tracks/1/select',headers=self.headers(42,'paid'))
        await self.client.post('/mini-app/api/tracks/preferences',json=p,headers=self.headers(42,'paid'))
        self.assertIsNone((await preferences(self.db,42))['active_track_id'])
        self.assertFalse((await preferences(self.db,42))['reminders'])
        self.assertTrue((await preferences(self.db,43))['reminders'])

    async def test_reminders_opt_in_dedup_recent_activity_complete_and_snooze(self):
        await self.create()
        now=datetime(2026,9,22,16,30,tzinfo=timezone.utc) # Tuesday 19:30 Minsk.
        bot=SimpleNamespace(get_me=AsyncMock(return_value=SimpleNamespace(username='test_bot')),send_message=AsyncMock())
        await self.tracks.deliver(bot,now);bot.send_message.assert_not_awaited()
        await self.client.post('/mini-app/api/tracks/1/select',headers=self.headers())
        p=dict(tempo='calm',days=[1],reminders=True,local_time='19:30',timezone='Europe/Minsk')
        await self.client.post('/mini-app/api/tracks/preferences',json=p,headers=self.headers())
        async with self.db.connect() as c:
            await c.execute('UPDATE mini_app_track_preferences SET last_activity=?',(now.isoformat(),));await c.commit()
        await self.tracks.deliver(bot,now);bot.send_message.assert_not_awaited()
        async with self.db.connect() as c:
            await c.execute('UPDATE mini_app_track_preferences SET last_activity=NULL,snooze_until=?',('2026-09-23T00:00:00+00:00',));await c.commit()
        await self.tracks.deliver(bot,now);bot.send_message.assert_not_awaited()
        async with self.db.connect() as c:
            await c.execute('UPDATE mini_app_track_preferences SET snooze_until=NULL');await c.commit()
        await self.tracks.deliver(bot,now);await self.tracks.deliver(bot,now)
        self.assertEqual(bot.send_message.await_count,1)
        await complete_material(self.db,1,43);await complete_material(self.db,2,43);await complete_course_lesson(self.db,1,1,43)
        await self.tracks.deliver(bot,datetime(2026,9,29,16,30,tzinfo=timezone.utc))
        self.assertEqual(bot.send_message.await_count,1)

    async def test_hidden_steps_and_invalid_publish(self):
        form=await self.create()
        async with self.db.connect() as c:
            await c.execute("UPDATE mini_app_materials SET status='draft' WHERE id=1");await c.commit()
        data=await catalog(self.db,dict(telegram_id=43,state='active'))
        step=data['tracks'][0]['steps'][0]
        self.assertTrue(step['unavailable']);self.assertEqual(step['title'],'Шаг временно недоступен')
        form.update(track_id='1',version='1')
        self.assertEqual((await self.client.post('/action',data=form,allow_redirects=False)).status,400)
        form.update(steps='[]')
        self.assertEqual((await self.client.post('/action',data=form,allow_redirects=False)).status,400)
