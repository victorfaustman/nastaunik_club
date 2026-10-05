import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from bot.database import Database
from bot.mini_app import MiniApp
from bot.website import Website
from bot.website_auth import initialize, issue_code, digest, SESSION_COOKIE, LOGIN_COOKIE
from bot.learning import get_bootstrap
from tests.test_mini_app import InitDataValidationTests


class WebsiteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Database(Path(self.tmp.name)/'db.sqlite');await self.db.init();await initialize(self.db)
        await self.db.upsert_user(43,'member','Member')
        async with self.db.connect() as c:
            await c.execute("UPDATE users SET current_status='active' WHERE telegram_id=43")
            for i in (1,2):
                await c.execute("INSERT INTO mini_app_materials(id,title,is_free,library_visible,status,full_description,created_at,updated_at) VALUES(?,?,?,1,'published',?,'now','now')",(i,f'Material {i}',i==1,f'<p>Body {i}</p>'))
                await c.execute("INSERT INTO mini_app_courses(id,title,is_free,status,created_at,updated_at) VALUES(?,?,?,'published','now','now')",(i,f'Course {i}',i==1))
                await c.execute("INSERT INTO mini_app_course_units(id,course_id,title,is_required,created_at,updated_at) VALUES(?,?,?,1,'now','now')",(i,i,f'Lesson {i}'))
            await c.commit()
        self.mini=MiniApp(self.db,'123:TEST',test_mode_ids={42})
        self.site=Website(self.mini);self.site.auth.bot_username='test_bot'
        app=web.Application();self.mini.register(app);self.site.register(app)
        app.cleanup_ctx.clear()
        await self.mini.payments.initialize()
        # Public test routes emulate the production reverse proxy.
        app.router.add_get('/',self.site.index)
        app.router.add_get('/library',self.site.index)
        app.router.add_get('/material/{id}',self.site.index)
        self.client=TestClient(TestServer(app));await self.client.start_server()
        self.site.auth.origin=str(self.client.make_url('/')).rstrip('/')

    async def asyncTearDown(self):
        await self.client.close();self.tmp.cleanup()

    def origin(self):
        return {'Origin':self.site.auth.origin}

    async def begin(self):
        r=await self.client.post('/site/auth/start',headers=self.origin());self.assertEqual(r.status,200,await r.text())
        data=await r.json();self.login=r.cookies[LOGIN_COOKIE].value
        self.token=parse_qs(urlparse(data['telegram_url']).query)['start'][0][4:]
        return data

    async def login_as(self,uid=43):
        await self.begin()
        await self.db.upsert_user(uid,'member','Member')
        code=await issue_code(self.db,self.token,dict(id=uid,first_name='Member',username='member'))
        r=await self.client.post('/site/auth/finish',json={'code':code},headers={**self.origin(),'Cookie':f'{LOGIN_COOKIE}={self.login}'})
        self.assertEqual(r.status,200,await r.text());data=await r.json()
        self.session=r.cookies[SESSION_COOKIE].value;self.csrf=data['csrf']
        return {'Cookie':f'{SESSION_COOKIE}={self.session}','X-Nastaunik-CSRF':self.csrf,**self.origin(),'X-Nastaunik-Site':'1'}

    async def test_public_catalog_free_content_and_paid_server_guard(self):
        r=await self.client.get('/');self.assertEqual(r.status,200)
        html=await r.text();self.assertIn('NASTAUNIK_SITE',html);self.assertNotIn('telegram-web-app.js',html)
        h={'X-Nastaunik-Site':'1'}
        data=await (await self.client.get('/mini-app/api/bootstrap',headers=h)).json()
        self.assertTrue(data['user']['guest']);self.assertEqual([m['locked'] for m in data['materials']],[False,True])
        self.assertEqual((await self.client.get('/mini-app/api/material/1',headers=h)).status,200)
        self.assertEqual((await self.client.get('/mini-app/api/material/2',headers=h)).status,403)
        self.assertEqual((await self.client.get('/mini-app/api/course/1/lesson/1',headers=h)).status,200)
        self.assertEqual((await self.client.get('/mini-app/api/course/2',headers=h)).status,403)
        self.assertEqual((await self.client.post('/mini-app/api/material/1/like',headers=h)).status,401)
        async with self.db.connect() as c:
            self.assertIsNone(await (await c.execute('SELECT * FROM users WHERE telegram_id=0')).fetchone())

    async def test_login_common_progress_csrf_logout_and_revocation(self):
        headers=await self.login_as()
        r=await self.client.post('/mini-app/api/material/2/complete',headers=headers);self.assertEqual(r.status,200,await r.text())
        mini_headers={'X-Telegram-Init-Data':InitDataValidationTests().make_init_data(user_id=43)}
        payload=await (await self.client.get('/mini-app/api/bootstrap',headers=mini_headers)).json()
        self.assertTrue(next(m for m in payload['materials'] if m['id']==2)['viewed'])
        bad={**headers,'X-Nastaunik-CSRF':'wrong'}
        self.assertEqual((await self.client.post('/mini-app/api/material/1/like',headers=bad)).status,403)
        self.assertEqual((await self.client.post('/mini-app/api/material/1/like',headers={**headers,'Origin':'https://evil.test'})).status,403)
        self.assertEqual((await self.client.post('/mini-app/api/course/2/lesson/2/complete',headers=headers)).status,200)
        data=await (await self.client.get('/mini-app/api/bootstrap',headers=mini_headers)).json()
        self.assertTrue(next(c for c in data['courses'] if c['id']==2)['completed'])
        async with self.db.connect() as c:
            await c.execute("UPDATE users SET current_status='expired' WHERE telegram_id=43");await c.commit()
        self.assertEqual((await self.client.get('/mini-app/api/material/2',headers=headers)).status,403)
        self.assertEqual((await self.client.post('/site/auth/logout',headers=headers)).status,200)
        self.assertFalse((await (await self.client.get('/site/auth/me',headers=headers)).json())['authenticated'])

    async def test_challenge_binding_attempts_expiry_and_replay(self):
        await self.begin();code=await issue_code(self.db,self.token,dict(id=43,first_name='Member'))
        headers={**self.origin(),'Cookie':f'{LOGIN_COOKIE}={self.login}'}
        wrong_cookie=self.token+'.'+('x'*43)
        self.assertEqual((await self.client.post('/site/auth/finish',json={'code':code},headers={**headers,'Cookie':f'{LOGIN_COOKIE}={wrong_cookie}'})).status,401)
        wrong='000001' if code!='000001' else '000002'
        for _ in range(5):
            self.assertEqual((await self.client.post('/site/auth/finish',json={'code':wrong},headers=headers)).status,401)
        self.assertIsNone(await issue_code(self.db,self.token,dict(id=43)))
        self.assertEqual((await self.client.post('/site/auth/finish',json={'code':code},headers=headers)).status,401)
        await self.login_as();r=await self.client.post('/site/auth/finish',json={'code':'123456'},headers={**self.origin(),'Cookie':f'{LOGIN_COOKIE}={self.login}'})
        self.assertEqual(r.status,401)
        async with self.db.connect() as c:
            await c.execute('UPDATE website_sessions SET expires_at=0');await c.commit()
        self.assertFalse((await (await self.client.get('/site/auth/me',headers={'Cookie':f'{SESSION_COOKIE}={self.session}'})).json())['authenticated'])

    async def test_login_origin_and_test_mode_guard(self):
        self.assertEqual((await self.client.post('/site/auth/start',headers={'Origin':'https://evil.test'})).status,403)
        h=await self.login_as(43);h['X-Nastaunik-Test-Mode']='paid'
        data=await (await self.client.get('/mini-app/api/bootstrap',headers=h)).json()
        self.assertIsNone(data['user']['test_mode'])

    async def test_metadata_ssr_404_and_security_headers(self):
        r=await self.client.get('/material/1');text=await r.text()
        self.assertEqual(r.status,200);self.assertIn('Body 1',text);self.assertIn('og:title',text)
        self.assertIn('Content-Security-Policy',r.headers);self.assertIn('Strict-Transport-Security',r.headers)
        r=await self.client.get('/material/2');text=await r.text()
        self.assertNotIn('Body 2',text);self.assertIn('noindex',text)
        self.assertEqual((await self.client.get('/material/999')).status,404)
        r=await self.client.get('/site/not-a-real-page');self.assertEqual(r.status,404)
        r=await self.client.get('/site/robots.txt');self.assertEqual(r.content_type,'text/plain');self.assertIn('Sitemap:',await r.text())
        r=await self.client.get('/site/sitemap.xml');text=await r.text()
        self.assertEqual(r.content_type,'application/xml');self.assertIn('/material/1</loc>',text);self.assertNotIn('/material/2</loc>',text)
        r=await self.client.get('/site/privacy');self.assertIn('служебные cookies',(await r.text()).lower())

    async def test_signed_media_expiry_range_and_admin_cookie(self):
        from unittest.mock import patch
        from bot.media_security import signed_text, token, ADMIN_COOKIE, signature
        root=Path(self.tmp.name)/'media';root.mkdir();(root/'private.mp4').write_bytes(b'0123456789')
        async with self.db.connect() as c:
            await c.execute("UPDATE mini_app_materials SET full_description='<video src=\"/mini-app/media/private.mp4\"></video>' WHERE id=2")
            await c.commit()
        with patch('bot.mini_app.MEDIA_DIR',root):
            self.assertEqual((await self.client.get('/mini-app/media/private.mp4')).status,403)
            headers=await self.login_as()
            text=await (await self.client.get('/mini-app/api/material/2',headers=headers)).text()
            self.assertIn('sig=',text)
            url=signed_text(self.mini.bot_token,'/mini-app/media/private.mp4')
            r=await self.client.get(url,headers={'Range':'bytes=2-4'})
            self.assertEqual(r.status,206);self.assertEqual(await r.read(),b'234');self.assertEqual(r.headers['Cache-Control'],'private, no-store')
            self.assertEqual((await self.client.get(url.replace('private.mp4','missing.mp4'))).status,404)
            self.assertEqual((await self.client.get('/mini-app/media/private.mp4?expires=1&sig='+signature(self.mini.bot_token,'private.mp4',1))).status,403)
            expires,sig=token(self.mini.bot_token,'admin')
            self.assertEqual((await self.client.get('/mini-app/media/private.mp4',headers={'Cookie':ADMIN_COOKIE+'='+expires+'.'+sig})).status,200)

    async def test_media_signer_does_not_sign_user_answers(self):
        from bot.media_security import middleware
        async def handler(request):
            return web.json_response({'response_text':'/mini-app/media/private.mp4','content':'/mini-app/media/lesson.mp4'})
        from aiohttp.test_utils import make_mocked_request
        r=await middleware(self.mini.bot_token)(make_mocked_request('GET','/mini-app/api/course/1/lesson/1'),handler)
        payload=json.loads(r.text)
        self.assertEqual(payload['response_text'],'/mini-app/media/private.mp4');self.assertIn('sig=',payload['content'])


if __name__=='__main__':
    unittest.main()
