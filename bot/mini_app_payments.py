"""Private receipt uploads and durable Telegram notifications for Mini App payments."""
import asyncio
import logging
import os
import secrets
from contextlib import suppress
from pathlib import Path

from aiohttp import web
from aiogram import Bot
from aiogram.types import FSInputFile

from bot import keyboards, texts
from bot.database import DEFAULT_AMOUNT_LABEL
from bot.core_sync import sync_club_payment

logger = logging.getLogger(__name__)
MAX_RECEIPT_BYTES = 10 * 1024 * 1024


class MiniAppPayments:
    def __init__(self, mini_app):
        self.app = mini_app
        self.db = mini_app.db
        self.directory = Path(self.db.path).resolve().parent / 'private_receipts'
        self.admin_ids = sorted(mini_app.test_mode_ids)

    async def initialize(self):
        async with self.db.connect() as conn:
            await conn.executescript('''
                CREATE TABLE IF NOT EXISTS mini_app_payment_uploads (
                    payment_id INTEGER PRIMARY KEY REFERENCES payments(id) ON DELETE CASCADE,
                    telegram_id INTEGER NOT NULL,
                    request_id TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    UNIQUE(telegram_id, request_id)
                );
                CREATE TABLE IF NOT EXISTS mini_app_payment_notifications (
                    payment_id INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
                    admin_id INTEGER NOT NULL,
                    receipt_message_id INTEGER,
                    message_id INTEGER,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(payment_id, admin_id)
                );
            ''')
            await conn.commit()

    async def context(self, app):
        await self.initialize()
        task = asyncio.create_task(self.worker())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def status(self, request):
        _, record, user = await self.app.authorised(request)
        latest = None if user.get('test_mode') else await self.db.get_latest_payment_for_user(user['telegram_id'])
        return web.json_response({
            'user': user,
            'amount_label': user.get('amount_label') or DEFAULT_AMOUNT_LABEL,
            'card': texts.PAYMENT_CARD,
            'phone': texts.PAYMENT_PHONE,
            'contact_url': os.getenv('OWNER_CONTACT_URL', 'https://t.me/kopytov_v_a'),
            'latest_payment': None if not latest else {
                'id': latest.id, 'status': latest.status, 'created_at': latest.created_at,
                'confirmed_at': latest.confirmed_at,
                'reason': (latest.admin_comment or 'Не удалось подтвердить оплату. Проверьте перевод и прикрепите новый чек.') if latest.status == 'rejected' else None,
            },
            'test_mode': bool(user.get('test_mode')),
        }, headers={'Cache-Control': 'no-store'})

    @staticmethod
    def extension(header):
        if header.startswith(b'%PDF-'):
            return '.pdf'
        if header.startswith(b'\x89PNG\r\n\x1a\n'):
            return '.png'
        if header.startswith(b'\xff\xd8\xff'):
            return '.jpg'
        if header.startswith(b'RIFF') and header[8:12] == b'WEBP':
            return '.webp'
        raise web.HTTPBadRequest(text='Прикрепите изображение JPG, PNG, WEBP или PDF.')

    async def submit(self, request):
        _, record, user = await self.app.authorised(request)
        if user.get('test_mode'):
            raise web.HTTPForbidden(text='В тестовом режиме отправка настоящих чеков отключена.')
        if user.get('is_lifetime_free'):
            raise web.HTTPBadRequest(text='У вас бессрочный доступ — оплата не требуется.')
        if not self.admin_ids:
            raise web.HTTPServiceUnavailable(text='Приём чеков временно недоступен. Попробуйте позже.')
        request_id = request.headers.get('X-Payment-Request', '')
        if not request_id or len(request_id) > 80:
            raise web.HTTPBadRequest(text='Обновите страницу оплаты и повторите отправку.')
        if request.content_type != 'multipart/form-data':
            raise web.HTTPBadRequest(text='Выберите файл чека.')
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        target = self.directory / (secrets.token_hex(24) + '.upload')
        saved = False
        try:
            reader = await request.multipart()
            part = await reader.next()
            if part is None or part.name != 'receipt' or not part.filename:
                raise web.HTTPBadRequest(text='Выберите чек.')
            size = 0
            header = b''
            with target.open('xb') as output:
                while chunk := await part.read_chunk():
                    size += len(chunk)
                    if size > MAX_RECEIPT_BYTES:
                        raise web.HTTPBadRequest(text='Размер чека должен быть не больше 10 МБ.')
                    header = (header + chunk)[:32]
                    output.write(chunk)
            extension = self.extension(header)
            renamed = target.with_suffix(extension)
            target.rename(renamed)
            target = renamed
            os.chmod(target, 0o600)
            stamp = self.db._now_iso()
            async with self.db.connect() as conn:
                await conn.execute('BEGIN IMMEDIATE')
                previous = await (await conn.execute(
                    'SELECT payment_id FROM mini_app_payment_uploads WHERE telegram_id=? AND request_id=?',
                    (user['telegram_id'], request_id),
                )).fetchone()
                pending = await (await conn.execute(
                    "SELECT id FROM payments WHERE telegram_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
                    (user['telegram_id'],),
                )).fetchone()
                if previous or pending:
                    return web.json_response({'ok': True, 'payment_id': (previous or pending)[0], 'already_received': True})
                # Read the personal tariff at submission time, never from the client.
                current = await (await conn.execute('SELECT recurring_amount_label FROM users WHERE telegram_id=?', (user['telegram_id'],))).fetchone()
                cur = await conn.execute(
                    "INSERT INTO payments(telegram_id,status,amount_label,receipt_type,receipt_text,created_at) VALUES(?,'pending',?,'document',?,?)",
                    (user['telegram_id'], current['recurring_amount_label'] or DEFAULT_AMOUNT_LABEL, 'Чек из Mini App', stamp),
                )
                payment_id = cur.lastrowid
                await conn.execute('INSERT INTO mini_app_payment_uploads VALUES(?,?,?,?)', (payment_id, user['telegram_id'], request_id, target.name))
                await conn.executemany('INSERT INTO mini_app_payment_notifications(payment_id,admin_id) VALUES(?,?)', [(payment_id, admin) for admin in self.admin_ids])
                await conn.execute(
                    "UPDATE users SET current_status=CASE WHEN current_status IN ('active','grace_period','trial_active') OR is_lifetime_free=1 THEN current_status ELSE 'waiting_confirmation' END,updated_at=? WHERE telegram_id=?",
                    (stamp, user['telegram_id']),
                )
                await conn.commit()
                saved = True
            try:
                sync_club_payment(await self.db.get_payment(payment_id), await self.db.get_user(user['telegram_id']))
            except Exception:
                logger.warning('Core synchronization pending for Mini App payment %s', payment_id)
            return web.json_response({'ok': True, 'payment_id': payment_id})
        finally:
            if not saved:
                target.unlink(missing_ok=True)

    async def deliver(self, bot, row):
        payment = await self.db.get_payment(row['payment_id'])
        user = await self.db.get_user(payment.telegram_id)
        if not row['receipt_message_id']:
            message = await bot.send_document(
                row['admin_id'], FSInputFile(self.directory / Path(row['stored_name']).name),
                caption=f'Чек из Mini App · заявка №{payment.id} · Telegram ID {user.telegram_id}',
            )
            async with self.db.connect() as conn:
                await conn.execute('UPDATE mini_app_payment_notifications SET receipt_message_id=? WHERE payment_id=? AND admin_id=?', (message.message_id, payment.id, row['admin_id']))
                await conn.execute('UPDATE payments SET receipt_file_id=? WHERE id=?', (message.document.file_id, payment.id))
                await conn.commit()
        text = texts.admin_new_application(user.full_name, '@'+user.username if user.username else 'не указан', user.telegram_id, payment.amount_label)
        message = await bot.send_message(
            row['admin_id'], text + f'\n\nИсточник: Mini App · заявка №{payment.id}',
            reply_markup=keyboards.admin_payment_keyboard(payment.id, user.telegram_id) if payment.status == 'pending' else None,
        )
        async with self.db.connect() as conn:
            await conn.execute('UPDATE mini_app_payment_notifications SET message_id=? WHERE payment_id=? AND admin_id=?', (message.message_id, payment.id, row['admin_id']))
            await conn.execute('UPDATE payments SET admin_message_id=? WHERE id=?', (message.message_id, payment.id))
            await conn.commit()

    async def worker(self):
        async with Bot(self.app.bot_token) as bot:
            while True:
                try:
                    async with self.db.connect() as conn:
                        rows = await (await conn.execute('''SELECT n.*,u.stored_name FROM mini_app_payment_notifications n
                            JOIN mini_app_payment_uploads u ON u.payment_id=n.payment_id
                            WHERE n.message_id IS NULL ORDER BY n.attempts,n.payment_id LIMIT 20''')).fetchall()
                    for row in rows:
                        try:
                            await self.deliver(bot, row)
                        except Exception:
                            logger.warning('Telegram notification retry for payment %s', row['payment_id'])
                            async with self.db.connect() as conn:
                                await conn.execute('UPDATE mini_app_payment_notifications SET attempts=attempts+1 WHERE payment_id=? AND admin_id=?', (row['payment_id'], row['admin_id']))
                                await conn.commit()
                except Exception:
                    logger.warning('Mini App payment notification queue temporarily unavailable')
                await asyncio.sleep(15)
