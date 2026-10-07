import unittest
from tests.test_tracks import TrackTests


class AdminUXTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = TrackTests()
        await self.fixture.asyncSetUp()

    async def asyncTearDown(self):
        await self.fixture.asyncTearDown()

    async def test_analytics_filters_and_mobile_labels(self):
        client = self.fixture.client
        response = await client.get('/page?analytics=1&q=Material&access=free&sort=completion')
        self.assertEqual(response.status, 200)
        html = await response.text()
        self.assertIn('Material 1', html)
        self.assertNotIn('Material 2', html)
        self.assertIn('data-label="Просмотры"', html)
        response = await client.get('/page?analytics=1&q=absent&sort=invalid')
        self.assertEqual(response.status, 200)
        self.assertIn('Найдено материалов: 0', await response.text())

    async def test_track_move_keeps_steps_and_rejects_stale_version(self):
        async with self.fixture.db.connect() as conn:
            for identity in (10, 11):
                await conn.execute("INSERT INTO mini_app_tracks(id,title,sort_order,created_at,updated_at) VALUES(?,?,?,'now','now')", (identity, str(identity), identity))
            await conn.execute('INSERT INTO mini_app_track_steps(track_id,material_id,sort_order) VALUES(10,1,0)')
            rows = await (await conn.execute('SELECT id,version FROM mini_app_tracks ORDER BY id')).fetchall()
            version = rows[1]['version']
            await conn.commit()
        body = dict(action='track_move', track_id='11', version=str(version), direction='up')
        response = await self.fixture.client.post('/action', data=body, allow_redirects=False)
        self.assertEqual(response.status, 303)
        response = await self.fixture.client.post('/action', data=body, allow_redirects=False)
        self.assertEqual(response.status, 409)
        async with self.fixture.db.connect() as conn:
            ids = [r['id'] for r in await (await conn.execute('SELECT id FROM mini_app_tracks ORDER BY sort_order,id')).fetchall()]
            self.assertEqual(ids, [11, 10])
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM mini_app_track_steps WHERE track_id=10')).fetchone())[0], 1)
