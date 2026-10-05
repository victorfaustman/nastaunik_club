"""Browser sign-in bound to a Telegram-issued one-time code and a browser secret."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from aiohttp import web

SESSION_COOKIE = 'nastaunik_site_session'
LOGIN_COOKIE = 'nastaunik_site_login'
SESSION_SECONDS = 30 * 86400
SCHEMA = '''
CREATE TABLE IF NOT EXISTS website_login_challenges(
 token_hash TEXT PRIMARY KEY, browser_hash TEXT NOT NULL, expires_at INTEGER NOT NULL,
 telegram_id INTEGER REFERENCES users(telegram_id), user_json TEXT, code_hash TEXT,
 attempts INTEGER NOT NULL DEFAULT 0, used INTEGER NOT NULL DEFAULT 0,
 ip_hash TEXT NOT NULL, created_at INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS website_sessions(
 token_hash TEXT PRIMARY KEY, telegram_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
 user_json TEXT NOT NULL, csrf TEXT NOT NULL, expires_at INTEGER NOT NULL);
'''


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


async def initialize(db):
    async with db.connect() as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


def same_origin(request, origin):
    if request.headers.get('Origin') != origin:
        raise web.HTTPForbidden(text='Откройте сайт клуба и повторите действие.')


class WebsiteAuth:
    def __init__(self, mini, origin='https://nastaunik.aiteacher.by'):
        self.mini, self.db, self.origin = mini, mini.db, origin.rstrip('/')
        self.bot_username = None

    def register(self, app):
        app.router.add_get('/site/auth/me', self.me)
        app.router.add_post('/site/auth/start', self.start)
        app.router.add_post('/site/auth/finish', self.finish)
        app.router.add_post('/site/auth/logout', self.logout)
        app.cleanup_ctx.append(self.context)

    async def context(self, app):
        await initialize(self.db)
        yield

    async def identity(self, request):
        token = request.cookies.get(SESSION_COOKIE, '')
        if not token:
            return None
        async with self.db.connect() as conn:
            row = await (await conn.execute('SELECT * FROM website_sessions WHERE token_hash=? AND expires_at>?', (digest(token), int(time.time())))).fetchone()
        if not row:
            return None
        if request.method not in {'GET', 'HEAD', 'OPTIONS'}:
            same_origin(request, self.origin)
            if not hmac.compare_digest(request.headers.get('X-Nastaunik-CSRF', ''), row['csrf']):
                raise web.HTTPForbidden(text='Обновите страницу и повторите действие.')
        return json.loads(row['user_json'])

    async def me(self, request):
        token = request.cookies.get(SESSION_COOKIE, '')
        async with self.db.connect() as conn:
            row = await (await conn.execute('SELECT csrf,expires_at FROM website_sessions WHERE token_hash=? AND expires_at>?', (digest(token), int(time.time())))).fetchone()
        return web.json_response({'authenticated': bool(row), 'csrf': row['csrf'] if row else None}, headers={'Cache-Control': 'no-store'})

    async def username(self):
        if not self.bot_username:
            from aiogram import Bot
            async with Bot(self.mini.bot_token) as bot:
                self.bot_username = (await bot.get_me()).username
        return self.bot_username

    async def start(self, request):
        same_origin(request, self.origin)
        now = int(time.time())
        ip = request.headers.get('X-Real-IP') or request.remote or ''
        ip_hash = digest(ip + self.mini.bot_token)
        # Complete the external lookup before invalidating any existing challenge.
        username = await self.username()
        token, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        async with self.db.connect() as conn:
            await conn.execute('BEGIN IMMEDIATE')
            count = (await (await conn.execute('SELECT COUNT(*) FROM website_login_challenges WHERE ip_hash=? AND created_at>?', (ip_hash, now-600))).fetchone())[0]
            if count >= 20:
                raise web.HTTPTooManyRequests(text='Слишком много попыток. Повторите через несколько минут.')
            old = request.cookies.get(LOGIN_COOKIE, '').split('.')
            if len(old) == 2:
                await conn.execute('UPDATE website_login_challenges SET used=1 WHERE token_hash=? AND browser_hash=?', (digest(old[0]), digest(old[1])))
            await conn.execute('INSERT INTO website_login_challenges(token_hash,browser_hash,expires_at,ip_hash,created_at) VALUES(?,?,?,?,?)', (digest(token), digest(browser), now+600, ip_hash, now))
            await conn.execute('DELETE FROM website_login_challenges WHERE expires_at<?', (now-86400,))
            await conn.execute('DELETE FROM website_sessions WHERE expires_at<?', (now,))
            await conn.commit()
        response = web.json_response({'telegram_url': f'https://t.me/{username}?start=web_{token}', 'expires_in': 600}, headers={'Cache-Control': 'no-store'})
        response.set_cookie(LOGIN_COOKIE, token+'.'+browser, secure=True, httponly=True, samesite='Lax', max_age=600, path='/')
        return response

    async def finish(self, request):
        same_origin(request, self.origin)
        parts = request.cookies.get(LOGIN_COOKIE, '').split('.')
        if len(parts) != 2:
            raise web.HTTPUnauthorized(text='Начните вход заново.')
        try:
            data = await request.json()
            code = str(data.get('code') or '').strip()
        except (ValueError, AttributeError):
            raise web.HTTPBadRequest(text='Введите код из Telegram.')
        if len(code) != 6 or not code.isascii() or not code.isdigit():
            raise web.HTTPBadRequest(text='Код состоит из шести цифр.')
        now = int(time.time())
        async with self.db.connect() as conn:
            await conn.execute('BEGIN IMMEDIATE')
            row = await (await conn.execute('SELECT * FROM website_login_challenges WHERE token_hash=? AND browser_hash=? AND expires_at>? AND used=0 AND attempts<5', (digest(parts[0]), digest(parts[1]), now))).fetchone()
            if not row:
                raise web.HTTPUnauthorized(text='Код устарел. Начните вход заново.')
            if not row['code_hash']:
                raise web.HTTPBadRequest(text='Откройте бота по кнопке выше и нажмите «Запустить», чтобы получить код.')
            if not hmac.compare_digest(row['code_hash'], digest(parts[0]+':'+code)):
                await conn.execute('UPDATE website_login_challenges SET attempts=attempts+1 WHERE token_hash=?', (row['token_hash'],))
                await conn.commit()
                raise web.HTTPUnauthorized(text='Неверный код. Проверьте сообщение в боте.')
            await conn.execute('UPDATE website_login_challenges SET used=1 WHERE token_hash=?', (row['token_hash'],))
            session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
            await conn.execute('INSERT INTO website_sessions(token_hash,telegram_id,user_json,csrf,expires_at) VALUES(?,?,?,?,?)', (digest(session), row['telegram_id'], row['user_json'], csrf, now+SESSION_SECONDS))
            await conn.commit()
        response = web.json_response({'ok': True, 'csrf': csrf}, headers={'Cache-Control': 'no-store'})
        response.set_cookie(SESSION_COOKIE, session, secure=True, httponly=True, samesite='Lax', max_age=SESSION_SECONDS, path='/')
        response.del_cookie(LOGIN_COOKIE, path='/')
        return response

    async def logout(self, request):
        same_origin(request, self.origin)
        user = await self.identity(request)
        if user:
            async with self.db.connect() as conn:
                await conn.execute('DELETE FROM website_sessions WHERE token_hash=?', (digest(request.cookies[SESSION_COOKIE]),))
                await conn.commit()
        response = web.json_response({'ok': True})
        response.del_cookie(SESSION_COOKIE, path='/')
        return response


async def issue_code(db, token, user):
    """Only the Telegram bot can bind a user and issue the code. Never expose it to polling."""
    now = int(time.time())
    async with db.connect() as conn:
        await conn.execute('BEGIN IMMEDIATE')
        row = await (await conn.execute('SELECT * FROM website_login_challenges WHERE token_hash=? AND used=0 AND expires_at>?', (digest(token), now))).fetchone()
        if not row or (row['telegram_id'] and row['telegram_id'] != user['id']):
            return None
        # A repeated /start does not reset the attempt limit.
        if row['attempts'] >= 5:
            return None
        code = f'{secrets.randbelow(1000000):06d}'
        await conn.execute('UPDATE website_login_challenges SET telegram_id=?,user_json=?,code_hash=? WHERE token_hash=?', (user['id'], json.dumps(user, ensure_ascii=False), digest(token+':'+code), digest(token)))
        await conn.commit()
    return code


def create_website_router(db):
    router = Router(name='website_login')

    @router.message(CommandStart(), F.text.regexp(r'^/start(?:@\w+)? web_[A-Za-z0-9_-]{43}$'), F.chat.type == 'private')
    async def login(message: Message):
        user = message.from_user
        if not user:
            return
        await initialize(db)
        await db.upsert_user(user.id, user.username, user.full_name)
        identity = dict(id=user.id, username=user.username, first_name=user.first_name, last_name=user.last_name)
        token = message.text.split('web_', 1)[1]
        code = await issue_code(db, token, identity)
        if not code:
            await message.answer('Ссылка для входа устарела. Вернитесь на сайт и нажмите «Войти через Telegram» ещё раз.')
            return
        await message.answer(f'Ваш код для входа на <b>nastaunik.aiteacher.by</b>:\n\n<code>{code}</code>\n\nВернитесь в браузер и введите эти шесть цифр. Код действует только для начатого входа.\n\nНикому не пересылайте код. Если вы не начинали вход на сайте клуба, не используйте его.', parse_mode='HTML')

    return router
