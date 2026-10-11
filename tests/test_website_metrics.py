import unittest
from datetime import timedelta
from unittest.mock import patch
from tests.test_website import WebsiteTests
from bot.website_metrics import today, admin_page
from bot.learning_admin_v2 import LearningAdmin


class MetricsTests(WebsiteTests):
    async def event(self, **changes):
        data = dict(visit='a'*32, event='b'*32, path='/library', source='https://google.com/search?q=private')
        data.update(changes)
        return await self.client.post('/site/metrics', json=data, headers=self.origin())

    async def test_counts_dedup_privacy_retention_and_daily_visit(self):
        self.assertEqual((await self.event()).status,204)
        self.assertEqual((await self.event()).status,204)
        self.assertEqual((await self.event(event='c'*32,path='/material/1')).status,204)
        async with self.db.connect() as conn:
            rows = await (await conn.execute('SELECT * FROM website_page_events')).fetchall()
            self.assertEqual(len(rows),2)
            self.assertEqual(rows[0]['source'],'google.com')
            self.assertNotEqual(rows[0]['visit'],'a'*32)
            self.assertEqual(rows[0]['visit'],rows[1]['visit'])
            await conn.execute('INSERT INTO website_page_events VALUES(?,?,?,?,?)',('2001-01-01','old','old','/','direct'))
            await conn.commit()
        with patch('bot.website_metrics.today', return_value=today()+timedelta(days=1)):
            self.assertEqual((await self.event()).status,204)
        async with self.db.connect() as conn:
            rows=await (await conn.execute('SELECT * FROM website_page_events')).fetchall()
            self.assertEqual(len(rows),3)
            self.assertNotEqual(rows[0]['visit'], rows[2]['visit'])

    async def test_origin_validation_bots_dnt_no_admin(self):
        self.assertEqual((await self.client.post('/site/metrics',json={})).status,403)
        for data in [dict(path='/admin/'),dict(path='/library?q=secret'),dict(visit='x'),dict(source=9)]:
            self.assertEqual((await self.event(**data)).status,400)
        for headers in [dict(DNT='1'),{'Sec-GPC':'1'},{'User-Agent':'Googlebot'}]:
            r=await self.client.post('/site/metrics',json=dict(visit='a'*32,event='b'*32,path='/'),headers={**self.origin(),**headers})
            self.assertEqual(r.status,204)
        async with self.db.connect() as conn:
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM website_page_events')).fetchone())[0],0)

    async def test_report_and_tracking_asset(self):
        await self.event()
        owner=LearningAdmin(self.db.path,lambda path,**kw:'/admin/?section=visitors')
        from aiohttp.test_utils import make_mocked_request
        response=await admin_page(owner,make_mocked_request('GET','/admin/?section=visitors&days=7'))
        self.assertIn('google.com',response.text)
        self.assertIn('визитов',response.text)
        self.assertEqual(response.headers['Cache-Control'],'no-store')
        response=await self.client.get('/')
        self.assertIn('/site/static/metrics.js?v=1',await response.text())
        self.assertEqual((await self.client.get('/site/static/metrics.js?v=1')).status,200)

    async def test_public_crawlable_links_and_sitemap(self):
        async with self.db.connect() as conn:
            await conn.execute("INSERT INTO mini_app_tracks(id,title,status,created_at,updated_at) VALUES(1,'Track public','published','now','now'),(2,'Track draft','draft','now','now')")
            await conn.commit()
        text=await (await self.client.get('/')).text()
        self.assertIn('href="/material/1"',text)
        self.assertIn('href="/course/1"',text)
        self.assertNotIn('href="/material/2"',text)
        text=await (await self.client.get('/library?type=courses')).text()
        self.assertIn('href="/course/1"',text)
        self.assertNotIn('href="/material/1"',text)
        text=await (await self.client.get('/site/sitemap.xml')).text()
        self.assertIn('/track/1</loc>',text)
        self.assertNotIn('/track/2</loc>',text)
        self.assertIn('/library?type=courses</loc>',text)


if __name__=='__main__':
    unittest.main()
