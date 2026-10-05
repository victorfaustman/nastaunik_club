"""Reviewed access requests for members unable to pay from abroad."""
import asyncio
import html
import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.types import InlineKeyboardButton as Button, InlineKeyboardMarkup as Markup

logger = logging.getLogger(__name__)
SCHEMA = """CREATE TABLE IF NOT EXISTS foreign_requests (
    telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id),
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL,
    decided_at TEXT,
    decided_by INTEGER,
    invite_link TEXT,
    notified INTEGER NOT NULL DEFAULT 0
)"""
APPROVED = (
    "Добро пожаловать в клуб Nastaŭnik!\n\n"
    "Сейчас мы пока не можем принимать оплату из России и других стран за пределами Беларуси. "
    "Но нам хочется, чтобы полезные идеи и материалы уже сейчас помогали вам в работе. "
    "Поэтому мы приглашаем вас в клуб без оплаты на время, пока настраиваем международные платежи.\n\n"
    "Нажмите «Перейти в клуб», чтобы стать участником.\n\n"
    "Когда появится возможность оплаты, мы сообщим вам об условиях продолжения участия. "
    "Вы сами решите, хотите ли остаться в клубе. Автоматических списаний не будет."
)
REJECTED = (
    "Спасибо за интерес к клубу Nastaŭnik! Сейчас мы пока не принимаем оплату из-за рубежа "
    "и не можем предоставить доступ по вашей заявке. Мы сообщим вам, когда появится "
    "возможность оплаты. Если у вас есть вопросы, напишите Вячеславу."
)


async def initialize(db):
    async with db.connect() as conn:
        await conn.execute(SCHEMA)
        await conn.commit()


async def get_request(db, user_id):
    async with db.connect() as conn:
        cur = await conn.execute("SELECT * FROM foreign_requests WHERE telegram_id = ?", (user_id,))
        return await cur.fetchone()


async def decide(db, user_id, admin_id, approved, link):
    async with db.connect() as conn:
        await conn.execute("BEGIN IMMEDIATE")
        cur = await conn.execute(
            "UPDATE foreign_requests SET status=?, decided_at=?, decided_by=?, invite_link=? "
            "WHERE telegram_id=? AND status='pending'",
            ('approved' if approved else 'rejected', datetime.utcnow().isoformat(), admin_id, link, user_id),
        )
        changed = cur.rowcount == 1
        if changed and approved:
            # This grant has no payment and no expiry; the renewal scheduler ignores NULL dates.
            await conn.execute(
                "UPDATE users SET current_status='active', access_start_at=NULL, access_end_at=NULL, grace_end_at=NULL, "
                "club_invite_link=?, reminder_5_sent_at=NULL, expiry_notice_sent_at=NULL, updated_at=? "
                "WHERE telegram_id=?", (link, datetime.utcnow().isoformat(), user_id),
            )
        await conn.commit()
        return changed


def create_foreign_router(db, settings):
    router = Router(name='foreign_access')
    decision_lock = asyncio.Lock()

    def keyboard(link=None):
        rows = [[Button(text='Перейти в клуб', url=link)]] if link else []
        rows += [[Button(text='Задать вопрос', url=settings.owner_contact_url)],
                 [Button(text='Вернуться в меню', callback_data='menu:main')]]
        return Markup(inline_keyboard=rows)

    @router.callback_query(F.data == 'foreign:request')
    async def request(callback, state):
        actor = callback.from_user
        await db.upsert_user(actor.id, actor.username, actor.full_name)
        await state.clear()
        async with db.connect() as conn:
            cur = await conn.execute(
                "INSERT OR IGNORE INTO foreign_requests (telegram_id, created_at) VALUES (?, ?)",
                (actor.id, datetime.utcnow().isoformat()),
            )
            created = cur.rowcount == 1
            await conn.commit()
        if not created:
            row = await get_request(db, actor.id)
            if row['status'] == 'approved':
                await callback.answer('Заявка уже одобрена. Откройте «Мой статус».', show_alert=True)
            else:
                await callback.answer('Ваша заявка уже зарегистрирована.', show_alert=True)
            return
        await callback.answer()
        await callback.bot.send_message(actor.id,
            'Спасибо! Мы получили вашу заявку. Администратор рассмотрит её и свяжется с вами. '
            'Решение придёт в этот бот.', reply_markup=keyboard())
        buttons = Markup(inline_keyboard=[[
            Button(text='Одобрить', callback_data=f'foreign:approve:{actor.id}'),
            Button(text='Отклонить', callback_data=f'foreign:reject:{actor.id}'),
        ]])
        delivered = 0
        for admin_id in settings.admin_ids:
            try:
                await callback.bot.send_message(admin_id,
                    f'Заявка «Не из РБ»\n{html.escape(actor.full_name)}\n'
                    f'@{html.escape(actor.username or "без_username")} · ID {actor.id}\n'
                    'Просит временный доступ до подключения международной оплаты.', reply_markup=buttons)
                delivered += 1
            except Exception:
                logger.exception('Foreign request admin notification failed: %s', admin_id)
        if not delivered:
            async with db.connect() as conn:
                await conn.execute("DELETE FROM foreign_requests WHERE telegram_id=? AND status='pending'", (actor.id,))
                await conn.commit()
            await callback.bot.send_message(actor.id,
                'Не удалось уведомить администратора. Попробуйте ещё раз или нажмите «Задать вопрос».',
                reply_markup=keyboard())

    @router.callback_query(F.data.startswith('foreign:approve:') | F.data.startswith('foreign:reject:'))
    async def decision(callback):
        async with decision_lock:
            await process_decision(callback)

    async def process_decision(callback):
        if callback.from_user.id not in settings.admin_ids:
            await callback.answer('Недостаточно прав.', show_alert=True)
            return
        user_id = int(callback.data.rsplit(':', 1)[1])
        row = await get_request(db, user_id)
        if not row:
            await callback.answer('Заявка не найдена.', show_alert=True)
            return
        await callback.answer()
        approved = callback.data.startswith('foreign:approve:')
        if row['status'] == 'pending':
            link = None
            if approved:
                try:
                    invite = await callback.bot.create_chat_invite_link(
                        settings.club_chat_id, name=f'Foreign {user_id}')
                    link = invite.invite_link
                    await callback.bot.unban_chat_member(settings.club_chat_id, user_id, only_if_banned=True)
                except Exception:
                    logger.exception('Foreign invite creation failed')
                    await callback.message.answer('Не удалось подготовить приглашение. Заявка осталась на проверке. Повторите одобрение.')
                    return
            await decide(db, user_id, callback.from_user.id, approved, link)
            row = await get_request(db, user_id)
        if row['notified']:
            await callback.message.answer('Заявка уже обработана.')
            return
        try:
            await callback.bot.send_message(user_id, APPROVED if row['status'] == 'approved' else REJECTED,
                reply_markup=keyboard(row['invite_link'] if row['status'] == 'approved' else None))
        except Exception:
            logger.exception('Foreign decision delivery failed: %s', user_id)
            await callback.message.answer('Решение сохранено, сообщение не доставлено. Повторное нажатие повторит отправку.')
            return
        async with db.connect() as conn:
            await conn.execute('UPDATE foreign_requests SET notified=1 WHERE telegram_id=?', (user_id,))
            await conn.commit()
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer('Доступ предоставлен.' if row['status'] == 'approved' else 'Заявка отклонена.')

    return router
