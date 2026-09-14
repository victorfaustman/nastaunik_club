import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import tests.test_mini_app_payments as payments_tests


class ForeignRequestsTests(payments_tests.PaymentsTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        # The inherited test server is frozen; register the production handler on a separate server.
        from aiohttp import web
        from aiohttp.test_utils import TestClient,TestServer
        app=web.Application();app.router.add_post('/request',self.payments.foreign.submit)
        self.foreign_client=TestClient(TestServer(app));await self.foreign_client.start_server()

    async def asyncTearDown(self):
        await self.foreign_client.close()
        await super().asyncTearDown()

    async def test_duplicate_request_and_notification_retry(self):
        replies=await asyncio.gather(*(self.foreign_client.post('/request',headers=self.headers()) for _ in range(2)))
        data=[await reply.json() for reply in replies]
        self.assertEqual(sum(d['created'] for d in data),1)
        self.assertEqual((await self.db.get_user(43)).current_status,'new')
        async with self.db.connect() as conn:
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM foreign_requests')).fetchone())[0],1)
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM mini_app_foreign_notifications')).fetchone())[0],1)
        bot=SimpleNamespace(send_message=AsyncMock(side_effect=RuntimeError('offline')))
        await self.payments.foreign.deliver_pending(bot)
        bot.send_message=AsyncMock(return_value=SimpleNamespace(message_id=19))
        await self.payments.foreign.deliver_pending(bot)
        buttons=bot.send_message.call_args.kwargs['reply_markup'].inline_keyboard[0]
        self.assertEqual([b.callback_data for b in buttons],['foreign:approve:43','foreign:reject:43'])
        await self.payments.foreign.deliver_pending(bot)
        self.assertEqual(bot.send_message.await_count,1)

    async def test_existing_bot_request_decision_and_no_payment(self):
        # Same rows that the live bot's request/decide functions write.
        async with self.db.connect() as conn:
            await conn.execute("INSERT INTO foreign_requests(telegram_id,created_at) VALUES(43,'now')")
            await conn.commit()
        duplicate=await self.foreign_client.post('/request',headers=self.headers())
        self.assertFalse((await duplicate.json())['created'])
        status=await (await self.client.get('/payment',headers=self.headers())).json()
        self.assertEqual(status['foreign_request']['status'],'pending')
        async with self.db.connect() as conn:
            await conn.execute("UPDATE foreign_requests SET status='approved' WHERE telegram_id=43")
            await conn.execute("UPDATE users SET current_status='active',access_start_at=NULL,access_end_at=NULL,grace_end_at=NULL WHERE telegram_id=43")
            await conn.commit()
        status=await (await self.client.get('/payment',headers=self.headers())).json()
        self.assertTrue(status['foreign_request']['access_granted'])
        self.assertFalse(status['user']['is_lifetime_free'])
        self.assertEqual((await self.upload()).status,400)
        async with self.db.connect() as conn:
            self.assertEqual((await (await conn.execute('SELECT COUNT(*) FROM payments')).fetchone())[0],0)
            await conn.execute("UPDATE users SET current_status='expired' WHERE telegram_id=43")
            await conn.commit()
        status=await (await self.client.get('/payment',headers=self.headers())).json()
        self.assertFalse(status['foreign_request']['access_granted'])

    async def test_auth_owner_test_mode_and_rejection(self):
        self.assertEqual((await self.foreign_client.post('/request')).status,401)
        self.assertEqual((await self.foreign_client.post('/request',headers=self.headers(42,mode='unpaid'))).status,403)
        await self.foreign_client.post('/request',headers=self.headers())
        async with self.db.connect() as conn:
            await conn.execute("UPDATE foreign_requests SET status='rejected' WHERE telegram_id=43")
            await conn.commit()
        result=await (await self.foreign_client.post('/request',headers=self.headers())).json()
        self.assertFalse(result['created']);self.assertEqual(result['foreign_request']['status'],'rejected')
        bot=SimpleNamespace(send_message=AsyncMock())
        await self.payments.foreign.deliver_pending(bot)
        bot.send_message.assert_not_called()
