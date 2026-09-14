"""Mini App adapter for the bot's shared foreign_requests workflow.

Decisions stay in the bot's existing foreign:approve/reject handlers.
"""
import html
import logging
from datetime import datetime

from aiohttp import web
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


class MiniAppForeign:
    def __init__(self, app):
        self.app, self.db = app, app.db

    async def initialize(self):
        async with self.db.connect() as conn:
            # Identical to the live bot schema; CREATE IF NOT EXISTS never resets requests.
            await conn.executescript('''
                CREATE TABLE IF NOT EXISTS foreign_requests (
                    telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id),
                    status TEXT NOT NULL DEFAULT 'pending', created_at TEXT NOT NULL,
                    decided_at TEXT, decided_by INTEGER, invite_link TEXT,
                    notified INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS mini_app_foreign_notifications (
                    telegram_id INTEGER NOT NULL REFERENCES foreign_requests(telegram_id) ON DELETE CASCADE,
                    admin_id INTEGER NOT NULL, message_id INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(telegram_id,admin_id)
                );
            ''')
            await conn.commit()

    async def status(self, user):
        if user.get('test_mode'):
            return None
        async with self.db.connect() as conn:
            row = await (await conn.execute('SELECT status,created_at,decided_at FROM foreign_requests WHERE telegram_id=?', (user['telegram_id'],))).fetchone()
        if not row:
            return None
        result = dict(row)
        result['access_granted'] = row['status']=='approved' and user['state']=='active' and not user.get('access_end_at') and not user.get('is_lifetime_free')
        return result

    async def submit(self, request):
        _, _, user = await self.app.authorised(request)
        if user.get('test_mode'):
            raise web.HTTPForbidden(text='В тестовом режиме настоящие заявки не отправляются.')
        if user.get('is_lifetime_free'):
            raise web.HTTPBadRequest(text='У вас уже есть бессрочный доступ.')
        admins = sorted(self.app.test_mode_ids)
        if not admins:
            raise web.HTTPServiceUnavailable(text='Не удалось связаться с администратором. Попробуйте позже.')
        async with self.db.connect() as conn:
            await conn.execute('BEGIN IMMEDIATE')
            cursor = await conn.execute('INSERT OR IGNORE INTO foreign_requests(telegram_id,created_at) VALUES(?,?)', (user['telegram_id'], datetime.utcnow().isoformat()))
            created = cursor.rowcount == 1
            if created:
                await conn.executemany('INSERT INTO mini_app_foreign_notifications(telegram_id,admin_id) VALUES(?,?)', [(user['telegram_id'], admin) for admin in admins])
            await conn.commit()
        return web.json_response({'ok':True, 'created':created, 'foreign_request':await self.status(user)}, headers={'Cache-Control':'no-store'})

    async def deliver_pending(self, bot):
        async with self.db.connect() as conn:
            rows = await (await conn.execute('''SELECT n.*,u.full_name,u.username FROM mini_app_foreign_notifications n
                JOIN foreign_requests f ON f.telegram_id=n.telegram_id
                JOIN users u ON u.telegram_id=n.telegram_id
                WHERE n.message_id IS NULL AND f.status='pending'
                ORDER BY n.attempts,n.telegram_id LIMIT 20''')).fetchall()
        for row in rows:
            uid = row['telegram_id']
            try:
                keyboard = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text='Одобрить',callback_data=f'foreign:approve:{uid}'),
                    InlineKeyboardButton(text='Отклонить',callback_data=f'foreign:reject:{uid}'),
                ]])
                message = await bot.send_message(row['admin_id'],
                    f'Заявка «Не из РБ» · Mini App\n{html.escape(row["full_name"])}\n'
                    f'@{html.escape(row["username"] or "без_username")} · ID {uid}\n'
                    'Просит временный доступ до подключения международной оплаты.', reply_markup=keyboard)
                async with self.db.connect() as conn:
                    await conn.execute('UPDATE mini_app_foreign_notifications SET message_id=? WHERE telegram_id=? AND admin_id=?', (message.message_id,uid,row['admin_id']))
                    await conn.commit()
            except Exception:
                logger.warning('Foreign request notification retry: %s',uid)
                async with self.db.connect() as conn:
                    await conn.execute('UPDATE mini_app_foreign_notifications SET attempts=attempts+1 WHERE telegram_id=? AND admin_id=?', (uid,row['admin_id']))
                    await conn.commit()
