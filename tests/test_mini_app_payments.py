import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiohttp import web, FormData
from aiohttp.test_utils import TestClient, TestServer

from bot.database import Database
from bot.mini_app import MiniApp
from bot.mini_app_payments import MiniAppPayments
from bot.services.membership import calculate_period_for_payment
from tests.test_mini_app import InitDataValidationTests


class PaymentsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Database(Path(self.temp.name) / 'test.db')
        await self.db.init()
        await self.db.upsert_user(42, 'owner', 'Owner')
        await self.db.upsert_user(43, 'member', 'Member')
        self.payments = MiniAppPayments(MiniApp(self.db, '123:TEST', set(), {42}))
        await self.payments.initialize()
        app = web.Application()
        app.router.add_get('/payment', self.payments.status)
        app.router.add_post('/receipt', self.payments.submit)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        self.sync = patch('bot.mini_app_payments.sync_club_payment')
        self.sync.start()

    async def asyncTearDown(self):
        self.sync.stop()
        await self.client.close()
        self.temp.cleanup()

    def headers(self, user_id=43, request_id='test-request', mode=None):
        h = {'X-Telegram-Init-Data': InitDataValidationTests().make_init_data(user_id=user_id), 'X-Payment-Request': request_id}
        if mode:
            h['X-Nastaunik-Test-Mode'] = mode
        return h

    async def upload(self, **kwargs):
        data = FormData()
        data.add_field('receipt', kwargs.pop('content', b'%PDF-1.4 test receipt'), filename='receipt.pdf', content_type='application/pdf')
        return await self.client.post('/receipt', data=data, headers=self.headers(**kwargs))

    async def test_upload_tariff_dedup_and_status(self):
        async with self.db.connect() as conn:
            await conn.execute("UPDATE users SET recurring_amount_label='7 BYN / месяц' WHERE telegram_id=43")
            await conn.commit()
        response = await self.upload()
        self.assertEqual(response.status, 200, await response.text())
        pid = (await response.json())['payment_id']
        payment = await self.db.get_payment(pid)
        self.assertEqual(payment.amount_label, '7 BYN / месяц')
        self.assertEqual(payment.status, 'pending')
        self.assertEqual((await self.db.get_user(43)).current_status, 'waiting_confirmation')
        retry = await self.upload(request_id='different-request')
        self.assertEqual((await retry.json())['payment_id'], pid)
        bot_pid = await self.db.save_receipt_and_create_payment(43, 'photo', 'file', None, '10 BYN')
        self.assertEqual(bot_pid, pid)
        self.assertEqual(len(list(self.payments.directory.iterdir())), 1)
        status = await (await self.client.get('/payment', headers=self.headers())).json()
        self.assertEqual(status['latest_payment']['status'], 'pending')
        await self.db.reject_payment(pid, 'На чеке не видна дата')
        status = await (await self.client.get('/payment', headers=self.headers())).json()
        self.assertEqual(status['latest_payment']['reason'], 'На чеке не видна дата')
        retry = await self.upload()  # Lost response for original submission stays idempotent after rejection.
        self.assertEqual((await retry.json())['payment_id'], pid)
        new = await self.upload(request_id='new-receipt')
        self.assertNotEqual((await new.json())['payment_id'], pid)

    async def test_renewal_keeps_access_and_extends_existing_end(self):
        now = datetime.utcnow()
        end = (now + timedelta(days=12)).isoformat(timespec='seconds')
        await self.db.activate_user_access(43, '', now.isoformat(), end, end)
        await self.db.set_waiting_payment(43)
        response = await self.upload()
        pid = (await response.json())['payment_id']
        user = await self.db.get_user(43)
        self.assertEqual(user.current_status, 'active')
        period = calculate_period_for_payment(user, now)
        self.assertEqual(datetime.fromisoformat(period.access_end_at), datetime.fromisoformat(end) + timedelta(days=30))
        await self.db.reject_payment(pid)
        self.assertEqual((await self.db.get_user(43)).current_status, 'active')
        new = await self.upload(request_id='replacement')
        await self.db.approve_payment((await new.json())['payment_id'], '', period.access_start_at, period.access_end_at, period.grace_end_at)
        status = await (await self.client.get('/payment', headers=self.headers())).json()
        self.assertEqual(status['user']['state'], 'active')
        self.assertEqual(status['user']['access_end_at'], period.access_end_at)
        self.assertEqual(status['latest_payment']['status'], 'approved')

    async def test_auth_file_validation_and_test_modes(self):
        r = await self.client.get('/payment')
        self.assertEqual(r.status, 401)
        r = await self.upload(content=b'<html>not a receipt</html>')
        self.assertEqual(r.status, 400)
        with patch('bot.mini_app_payments.MAX_RECEIPT_BYTES', 4):
            r = await self.upload()
            self.assertEqual(r.status, 400)
        for mode in ('paid', 'unpaid'):
            r = await self.upload(user_id=42, mode=mode)
            self.assertEqual(r.status, 403)
        r = await self.upload(mode='paid')  # Regular user cannot spoof owner test mode.
        self.assertEqual(r.status, 200)
        status = await (await self.client.get('/payment', headers=self.headers(mode='paid'))).json()
        self.assertFalse(status['test_mode'])
        self.assertEqual(status['user']['state'], 'new')

    async def test_notification_contains_receipt_and_existing_approval_buttons(self):
        response = await self.upload()
        pid = (await response.json())['payment_id']
        async def queued():
            async with self.db.connect() as conn:
                return await (await conn.execute('SELECT n.*,u.stored_name FROM mini_app_payment_notifications n JOIN mini_app_payment_uploads u ON n.payment_id=u.payment_id WHERE n.payment_id=?', (pid,))).fetchone()
        bot = SimpleNamespace(
            send_document=AsyncMock(return_value=SimpleNamespace(message_id=11, document=SimpleNamespace(file_id='telegram-file'))),
            send_message=AsyncMock(side_effect=RuntimeError('temporary error')),
        )
        with self.assertRaises(RuntimeError):
            await self.payments.deliver(bot, await queued())
        bot.send_message = AsyncMock(return_value=SimpleNamespace(message_id=12))
        await self.payments.deliver(bot, await queued())
        self.assertEqual(bot.send_document.await_count, 1)
        markup = bot.send_message.call_args.kwargs['reply_markup']
        self.assertEqual(markup.inline_keyboard[0][0].callback_data, f'admin:approve:{pid}')
        self.assertEqual(markup.inline_keyboard[1][0].callback_data, f'admin:reject:{pid}')
        self.assertEqual((await queued())['message_id'], 12)
        self.assertEqual((await self.db.get_payment(pid)).receipt_file_id, 'telegram-file')
