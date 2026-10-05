"""Local browser fixture with a test-only code issuer; no production data or Telegram messages."""
import asyncio
from aiohttp import web
from aiohttp.test_utils import TestClient,TestServer
from tests.test_website import WebsiteTests
from bot.website_auth import issue_code


async def main():
    fixture=WebsiteTests()
    await fixture.asyncSetUp()
    await fixture.client.close()
    app=web.Application()
    fixture.mini.register(app);fixture.site.register(app);app.cleanup_ctx.clear()
    await fixture.mini.consultations.initialize()
    app.router.add_get('/',fixture.site.index)
    async def code(request):
        value=await issue_code(fixture.db,request.query['token'],dict(id=43,first_name='Вячеслав',username='member'))
        return web.json_response({'code':value})
    app.router.add_get('/test/code',code)
    app.router.add_get('/{page:.*}',fixture.site.index)
    fixture.client=TestClient(TestServer(app));await fixture.client.start_server()
    fixture.site.auth.origin=str(fixture.client.make_url('/')).rstrip('/')
    async with fixture.db.connect() as conn:
        await conn.execute("INSERT INTO mini_app_course_blocks(lesson_id,block_type,content,created_at,updated_at) VALUES(2,'longread','<p>Учебный текст</p>','now','now')")
        await conn.commit()
    print(fixture.client.make_url('/'),flush=True)
    try:
        await asyncio.Event().wait()
    finally:
        await fixture.asyncTearDown()


if __name__=='__main__':
    asyncio.run(main())
