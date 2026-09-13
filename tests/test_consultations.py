import asyncio
import tempfile
import unittest
from pathlib import Path
from datetime import datetime

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from bot.database import Database
from bot.mini_app import MiniApp
from bot.consultations import Consultations
from bot.learning_admin_v2 import LearningAdmin
from tests.test_mini_app import InitDataValidationTests


class ConsultationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.temp.name)/'test.db')
        await self.db.init()
        for uid in (42,43,44):
            await self.db.upsert_user(uid, f'user{uid}', f'User {uid}')
        async with self.db.connect() as conn:
            await conn.execute("UPDATE users SET current_status='active' WHERE telegram_id IN (42,43)")
            await conn.commit()
        self.service=Consultations(self.db, MiniApp(self.db,'123:TEST',set(),{42}))
        await self.service.initialize()
        app=web.Application()
        app.router.add_get('/slots',self.service.schedule)
        app.router.add_post('/slots',self.service.book)
        app.router.add_post('/slots/{booking_id}/cancel',self.service.cancel)
        admin=LearningAdmin(Path(self.temp.name)/'test.db',lambda path,**q:path+'?'+ '&'.join(f'{k}={v}' for k,v in q.items()))
        app.router.add_get('/admin',admin.page)
        app.router.add_post('/admin',admin.action)
        self.client=TestClient(TestServer(app));await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close();self.temp.cleanup()

    def headers(self,uid=43,mode=None):
        h={'X-Telegram-Init-Data':InitDataValidationTests().make_init_data(user_id=uid)}
        if mode:h['X-Nastaunik-Test-Mode']=mode
        return h

    async def test_booking_concurrency_cancel_and_admin(self):
        data=await (await self.client.get('/slots',headers=self.headers())).json()
        self.assertTrue(data['paid_access'])
        for s in data['slots']:
            self.assertIn(datetime.fromisoformat(s['starts_at']).weekday(),(1,3))
            self.assertIn(s['starts_at'][11:16],('19:30','20:00','20:30'))
        start=data['slots'][0]['starts_at']
        responses=await asyncio.gather(*(self.client.post('/slots',headers=self.headers(uid),json={'starts_at':start,'topic':'<script>Тема</script>'}) for uid in (42,43)))
        self.assertEqual(sorted(r.status for r in responses),[200,409])
        idx=next(i for i,r in enumerate(responses) if r.status==200)
        owner=(42,43)[idx];other=(43,42)[idx];bid=(await responses[idx].json())['id']
        self.assertEqual((await self.client.post(f'/slots/{bid}/cancel',headers=self.headers(other))).status,404)
        page=await self.client.get('/admin?section=consultations')
        self.assertEqual(page.status,200,await page.text())
        self.assertIn('&lt;script&gt;',await page.text())
        self.assertEqual((await self.client.post(f'/slots/{bid}/cancel',headers=self.headers(owner))).status,200)
        self.assertEqual((await self.client.post('/slots',headers=self.headers(),json={'starts_at':start})).status,200)

    async def test_permissions_dates_and_test_mode(self):
        start=self.service.slots()[0]
        self.assertEqual((await self.client.get('/slots')).status,401)
        free=await (await self.client.get('/slots',headers=self.headers(44))).json()
        self.assertEqual(free['slots'],[])
        self.assertEqual((await self.client.post('/slots',headers=self.headers(44),json={'starts_at':start})).status,403)
        self.assertEqual((await self.client.post('/slots',headers=self.headers(42,'paid'),json={'starts_at':start})).status,403)
        self.assertEqual((await self.client.post('/slots',headers=self.headers(),json={'starts_at':'2020-01-01T19:30:00+03:00'})).status,400)
        self.assertEqual((await self.client.post('/slots',headers=self.headers(),json={'starts_at':start,'topic':'x'*2001})).status,400)
