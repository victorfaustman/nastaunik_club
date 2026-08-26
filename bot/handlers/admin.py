from __future__ import annotations

import logging
from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot import keyboards, texts
from bot.config import Settings
from bot.core_sync import sync_club_membership, sync_club_payment
from bot.database import DEFAULT_AMOUNT_LABEL, Database
from bot.services.membership import PROMO_FIRST_MONTH_DAYS, calculate_manual_extension, calculate_period_for_payment
from bot.states import AdminStates

logger = logging.getLogger(__name__)


def create_admin_router(db: Database, settings: Settings) -> Router:
    router = Router(name="admin")

    def is_admin(user_id: int) -> bool:
        return user_id in settings.admin_ids

    def format_dt(value: str | None) -> str:
        if not value:
            return "—"
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")

    def format_date(value: str | None) -> str:
        if not value:
            return "—"
        return datetime.fromisoformat(value).strftime("%d.%m.%Y")

    def special_label(user) -> str:
        labels = []
        if user.is_lifetime_free:
            labels.append("вечный бесплатный")
        amount_label = user.recurring_amount_label
        if amount_label and amount_label != DEFAULT_AMOUNT_LABEL:
            labels.append(amount_label)
        return ", ".join(labels) if labels else "обычный"

    async def remove_from_club(callback: CallbackQuery, user_id: int) -> None:
        if not settings.club_chat_id:
            return
        try:
            await callback.bot.ban_chat_member(settings.club_chat_id, user_id)
            await callback.bot.unban_chat_member(settings.club_chat_id, user_id, only_if_banned=True)
        except Exception:
            logger.exception("Failed to remove user %s from club chat", user_id)

    async def send_user_card(target: Message | CallbackQuery, user) -> None:
        username = f"@{user.username}" if user.username else "не указан"
        text = texts.ADMIN_USER_CARD.format(
            full_name=user.full_name,
            username=username,
            telegram_id=user.telegram_id,
            status=user.current_status,
            lifetime_free="да" if user.is_lifetime_free else "нет",
            recurring_amount_label=user.recurring_amount_label or "10 BYN / месяц",
            payment_confirmed_at=format_dt(user.payment_confirmed_at),
            access_start_at=format_dt(user.access_start_at or user.trial_started_at),
            access_end_at=format_dt(user.access_end_at or user.trial_ends_at),
            grace_end_at=format_dt(user.grace_end_at),
        )
        reply_markup = keyboards.admin_user_keyboard(user.telegram_id)
        if isinstance(target, CallbackQuery) and target.message:
            await target.message.edit_text(text, reply_markup=reply_markup)
            await target.answer()
            return
        if isinstance(target, Message):
            await target.answer(text, reply_markup=reply_markup)

    async def notify_user(callback: CallbackQuery, user_id: int, text: str, reply_markup) -> None:
        try:
            await callback.bot.send_message(user_id, text, reply_markup=reply_markup)
        except Exception:
            logger.exception("Failed to notify user %s", user_id)

    async def send_admin_panel(target: Message | CallbackQuery) -> None:
        text = "Админ-панель Nastaunik\n\nЗдесь можно посмотреть статистику, пользователей и запускать рассылку."
        reply_markup = keyboards.admin_panel_keyboard()
        if isinstance(target, CallbackQuery) and target.message:
            await target.message.edit_text(text, reply_markup=reply_markup)
            await target.answer()
            return
        if isinstance(target, Message):
            await target.answer(text, reply_markup=reply_markup)

    async def send_admin_stats(target: CallbackQuery) -> None:
        stats = await db.get_user_stats()
        text = (
            "Статистика по боту\n\n"
            f"Всего пользователей: {stats['total_users']}\n"
            f"Активный доступ: {stats['active_users']}\n"
            f"Вечный бесплатный доступ: {stats['lifetime_free_users']}\n"
            f"Тестовый период: {stats['trial_users']}\n"
            f"Льготный период: {stats['grace_users']}\n"
            f"Ожидают подтверждения: {stats['waiting_confirmation_users']}\n"
            f"Доступ истёк: {stats['expired_users']}\n"
            f"Отклонённые чеки: {stats['rejected_users']}"
        )
        if target.message:
            await target.message.edit_text(text, reply_markup=keyboards.admin_stats_keyboard())
        await target.answer()

    async def send_promo_panel(target: Message | CallbackQuery) -> None:
        text = (
            "Промокоды\n\n"
            "Промокод даёт пользователю специальную цену на первый месяц участия — 7 BYN вместо 10 BYN.\n"
            f"После подтверждения оплаты доступ открывается на {PROMO_FIRST_MONTH_DAYS} дней, а все следующие продления идут уже по обычной цене 10 BYN."
        )
        reply_markup = keyboards.admin_promo_panel_keyboard()
        if isinstance(target, CallbackQuery) and target.message:
            await target.message.edit_text(text, reply_markup=reply_markup)
            await target.answer()
            return
        if isinstance(target, Message):
            await target.answer(text, reply_markup=reply_markup)

    async def send_users_panel(target: Message | CallbackQuery) -> None:
        text = (
            "Пользователи\n\n"
            "Здесь можно быстро открыть состав клуба, всех, кто запускал бот, особых участников и оплату."
        )
        reply_markup = keyboards.admin_users_panel_keyboard()
        if isinstance(target, CallbackQuery) and target.message:
            await target.message.edit_text(text, reply_markup=reply_markup)
            await target.answer()
            return
        if isinstance(target, Message):
            await target.answer(text, reply_markup=reply_markup)

    async def send_users_list(callback: CallbackQuery, title: str, users: list) -> None:
        if not callback.message:
            await callback.answer()
            return
        if not users:
            text = f"{title}\n\nСейчас список пуст."
        else:
            lines = [f"{title}\n"]
            for user in users:
                username = f"@{user.username}" if user.username else "без username"
                end_at = format_dt(user.access_end_at or user.trial_ends_at)
                lines.append(
                    f"{user.full_name} | {username} | ID {user.telegram_id} | {user.current_status} | до {end_at}"
                )
            lines.append("\nОткрыть карточку: /user <telegram_id> или /user @username")
            text = "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=keyboards.admin_users_panel_keyboard())
        await callback.answer()

    async def send_admin_roster(callback: CallbackQuery, title: str, users: list, *, mode: str) -> None:
        if not callback.message:
            await callback.answer()
            return
        if not users:
            text = f"{title}\n\nСейчас список пуст."
        else:
            lines = [f"{title}\n", f"Показаны последние {len(users)} записей.\n"]
            for index, user in enumerate(users, start=1):
                username = f"@{user.username}" if user.username else "без username"
                marker = special_label(user)
                if mode == "activated":
                    lines.append(
                        f"{index}. {user.full_name} | {username}\n"
                        f"ID {user.telegram_id} | статус: {user.current_status} | запустил: {format_date(user.created_at)}"
                    )
                else:
                    lines.append(
                        f"{index}. {user.full_name} | {username}\n"
                        f"ID {user.telegram_id} | статус: {user.current_status} | оплата: {format_date(user.payment_confirmed_at)} | до: {format_date(user.access_end_at)} | {marker}"
                    )
            lines.append("\nКарточка участника: /user <telegram_id> или /user @username")
            text = "\n".join(lines)
        await callback.message.edit_text(text, reply_markup=keyboards.admin_users_panel_keyboard())
        await callback.answer()

    @router.message(Command("admin"))
    async def admin_panel_handler(message: Message, state: FSMContext) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        await state.clear()
        await send_admin_panel(message)

    @router.callback_query(F.data == "admin:panel")
    async def admin_panel_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        await state.clear()
        await send_admin_panel(callback)

    @router.callback_query(F.data == "admin:stats")
    async def admin_stats_callback(callback: CallbackQuery) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        await send_admin_stats(callback)

    @router.callback_query(F.data == "admin:broadcast")
    async def admin_broadcast_start(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        await state.set_state(AdminStates.waiting_for_broadcast_message)
        if callback.message:
            await callback.message.answer(
                "Отправьте одно сообщение, которое нужно разослать всем пользователям бота.\nМожно отправить текст, фото или документ.",
                reply_markup=keyboards.admin_broadcast_keyboard(),
            )
        await callback.answer()

    @router.callback_query(F.data == "admin:broadcast_cancel")
    async def admin_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        await state.clear()
        if callback.message:
            await callback.message.edit_text("Рассылка отменена.", reply_markup=keyboards.admin_panel_keyboard())
        await callback.answer()

    @router.message(AdminStates.waiting_for_broadcast_message)
    async def admin_broadcast_send(message: Message, state: FSMContext) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        user_ids = await db.list_all_user_ids()
        delivered = 0
        failed = 0
        await state.clear()
        await message.answer("Начинаю рассылку...")
        for user_id in user_ids:
            try:
                await message.bot.copy_message(chat_id=user_id, from_chat_id=message.chat.id, message_id=message.message_id)
                delivered += 1
            except Exception:
                failed += 1
                logger.exception("Broadcast delivery failed for user %s", user_id)
        await message.answer(
            "Рассылка завершена.\n\n"
            f"Получателей в базе: {len(user_ids)}\n"
            f"Успешно отправлено: {delivered}\n"
            f"Ошибок доставки: {failed}",
            reply_markup=keyboards.admin_panel_keyboard(),
        )

    @router.callback_query(F.data == "admin:promo_panel")
    async def admin_promo_panel(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        await state.clear()
        await send_promo_panel(callback)

    @router.callback_query(F.data == "admin:users_panel")
    async def admin_users_panel(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        await state.clear()
        await send_users_panel(callback)

    @router.callback_query(F.data.startswith("admin:list:"))
    async def admin_users_list(callback: CallbackQuery) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        filter_name = callback.data.rsplit(":", maxsplit=1)[1]
        if filter_name == "members":
            await send_admin_roster(callback, "Кто сейчас состоит в клубе", await db.list_club_members(), mode="members")
            return
        if filter_name == "activated":
            await send_admin_roster(callback, "Кто активировал бот", await db.list_bot_activated_users(), mode="activated")
            return
        if filter_name == "special":
            await send_admin_roster(callback, "Особые участники", await db.list_special_members(), mode="special")
            return
        if filter_name == "active":
            await send_users_list(callback, "Активные пользователи", await db.list_users_by_status(["active"]))
            return
        if filter_name == "trial":
            await send_users_list(callback, "Пользователи на тестовом периоде", await db.list_users_by_status(["trial_active"]))
            return
        if filter_name == "expiring":
            await send_users_list(callback, "Скоро истекают", await db.list_users_expiring_soon(days=7))
            return
        if filter_name == "waiting_confirmation":
            await send_users_list(callback, "Ожидают подтверждения оплаты", await db.list_users_by_status(["waiting_confirmation"]))
            return
        if filter_name == "expired":
            await send_users_list(callback, "Пользователи с истёкшим доступом", await db.list_users_by_status(["expired"]))
            return
        await callback.answer("Неизвестный фильтр.", show_alert=True)

    @router.callback_query(F.data.startswith("admin:promo_create:"))
    async def admin_promo_create(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        promo_type = callback.data.rsplit(":", maxsplit=1)[1]
        await state.set_data({"promo_type": promo_type})
        await state.set_state(AdminStates.waiting_for_promo_code_value)
        if callback.message:
            title = "постоянный" if promo_type == "permanent" else "временный"
            await callback.message.answer(
                f"Создаём {title} промокод.\n\nОтправьте сам код одним сообщением, например SPRING2026.",
                reply_markup=keyboards.admin_promo_cancel_keyboard(),
            )
        await callback.answer()

    @router.message(AdminStates.waiting_for_promo_code_value)
    async def admin_promo_code_value(message: Message, state: FSMContext) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        if not message.text:
            await message.answer("Отправьте код текстом одним сообщением.")
            return
        code = message.text.strip().upper()
        if len(code) < 3:
            await message.answer("Код слишком короткий. Укажите не менее 3 символов.")
            return
        if await db.get_promo_code_by_code(code):
            await message.answer("Такой промокод уже существует. Укажите другой код.")
            return
        data = await state.get_data()
        data["promo_code"] = code
        data["grant_days"] = PROMO_FIRST_MONTH_DAYS
        await state.set_data(data)
        await state.set_state(AdminStates.waiting_for_promo_max_uses)
        await message.answer(
            "Сколько раз можно использовать код? Отправьте число. Для безлимита отправьте 0.",
            reply_markup=keyboards.admin_promo_cancel_keyboard(),
        )

    @router.message(AdminStates.waiting_for_promo_max_uses)
    async def admin_promo_max_uses(message: Message, state: FSMContext) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        raw = (message.text or "").strip()
        if not raw.isdigit() or int(raw) < 0:
            await message.answer("Укажите 0 для безлимита или положительное целое число.")
            return
        data = await state.get_data()
        data["max_uses"] = None if int(raw) == 0 else int(raw)
        if data.get("promo_type") == "temporary":
            await state.set_data(data)
            await state.set_state(AdminStates.waiting_for_promo_valid_until)
            await message.answer(
                "До какой даты действует код? Формат: ГГГГ-ММ-ДД ЧЧ:ММ\nНапример: 2026-04-15 23:59",
                reply_markup=keyboards.admin_promo_cancel_keyboard(),
            )
            return

        promo_id = await db.create_promo_code(
            code=data["promo_code"],
            promo_type=data["promo_type"],
            grant_days=data["grant_days"],
            max_uses=data["max_uses"],
            valid_until=None,
            created_by=message.from_user.id,
            comment="Первый месяц за 7 BYN",
        )
        await state.clear()
        await message.answer(
            "Промокод создан.\n\n"
            f"ID: {promo_id}\n"
            f"Код: {data['promo_code']}\n"
            "Тип: постоянный\n"
            f"Условие: первый месяц {PROMO_FIRST_MONTH_DAYS} дней за 7 BYN\n"
            f"Лимит активаций: {data['max_uses'] if data['max_uses'] is not None else 'без лимита'}",
            reply_markup=keyboards.admin_promo_panel_keyboard(),
        )

    @router.message(AdminStates.waiting_for_promo_valid_until)
    async def admin_promo_valid_until(message: Message, state: FSMContext) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        raw = (message.text or "").strip()
        try:
            valid_until = datetime.strptime(raw, "%Y-%m-%d %H:%M")
        except ValueError:
            await message.answer("Не удалось разобрать дату. Используйте формат ГГГГ-ММ-ДД ЧЧ:ММ")
            return
        data = await state.get_data()
        promo_id = await db.create_promo_code(
            code=data["promo_code"],
            promo_type=data["promo_type"],
            grant_days=data["grant_days"],
            max_uses=data["max_uses"],
            valid_until=valid_until.isoformat(timespec="seconds"),
            created_by=message.from_user.id,
            comment="Первый месяц за 7 BYN",
        )
        await state.clear()
        await message.answer(
            "Промокод создан.\n\n"
            f"ID: {promo_id}\n"
            f"Код: {data['promo_code']}\n"
            "Тип: временный\n"
            f"Условие: первый месяц {PROMO_FIRST_MONTH_DAYS} дней за 7 BYN\n"
            f"Лимит активаций: {data['max_uses'] if data['max_uses'] is not None else 'без лимита'}\n"
            f"Действует до: {valid_until.strftime('%d.%m.%Y %H:%M')}",
            reply_markup=keyboards.admin_promo_panel_keyboard(),
        )

    @router.callback_query(F.data == "admin:promo_list")
    async def admin_promo_list(callback: CallbackQuery) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        promo_codes = await db.list_promo_codes(limit=20)
        if not promo_codes:
            text = "Промокодов пока нет."
        else:
            lines = ["Список промокодов\n"]
            for promo in promo_codes:
                limit_text = promo.max_uses if promo.max_uses is not None else "∞"
                valid_until_text = format_dt(promo.valid_until)
                status = "активен" if promo.is_active else "выключен"
                lines.append(
                    f"{promo.code} | {promo.promo_type} | 1-й месяц за 7 BYN | {promo.current_uses}/{limit_text} | до {valid_until_text} | {status}"
                )
            text = "\n".join(lines)
        if callback.message:
            await callback.message.edit_text(text, reply_markup=keyboards.admin_promo_list_keyboard())
        await callback.answer()

    @router.callback_query(F.data == "admin:promo_cancel")
    async def admin_promo_cancel(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        await state.clear()
        if callback.message:
            await callback.message.edit_text("Создание промокода отменено.", reply_markup=keyboards.admin_promo_panel_keyboard())
        await callback.answer()

    @router.callback_query(F.data.startswith("admin:"))
    async def admin_action_handler(callback: CallbackQuery) -> None:
        if not callback.from_user or not is_admin(callback.from_user.id):
            await callback.answer("Недостаточно прав.", show_alert=True)
            return
        parts = callback.data.split(":")
        if len(parts) != 3:
            await callback.answer("Неизвестное действие.", show_alert=True)
            return
        _, action, raw_id = parts
        if action in {"approve", "reject"}:
            payment = await db.get_payment(int(raw_id))
            if payment is None:
                await callback.answer("Заявка не найдена.", show_alert=True)
                return
            if payment.status != "pending":
                await callback.answer("Эта заявка уже обработана.", show_alert=True)
                return
            user = await db.get_user(payment.telegram_id)
            if user is None:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return
            if action == "approve":
                pending_promo_code = user.pending_promo_code
                period = calculate_period_for_payment(user)
                await db.approve_payment(payment.id, settings.club_invite_link, period.access_start_at, period.access_end_at, period.grace_end_at)
                if pending_promo_code:
                    promo = await db.get_promo_code_by_code(pending_promo_code)
                    if promo is not None:
                        await db.apply_promo_code(promo.id, user.telegram_id, period.access_start_at, period.access_end_at)
                try:
                    sync_club_payment(await db.get_payment(payment.id), await db.get_user(user.telegram_id))
                except Exception:
                    logger.exception("Failed to sync approved club payment into core registry")
                try:
                    sync_club_membership(await db.get_user(user.telegram_id))
                except Exception:
                    logger.exception("Failed to sync approved club membership into core registry")
                await notify_user(
                    callback,
                    user.telegram_id,
                    texts.PAYMENT_APPROVED.format(
                        club_invite_link=settings.club_invite_link,
                        owner_contact_url=settings.owner_contact_url,
                    ),
                    keyboards.approved_keyboard(settings.club_invite_link, settings.owner_contact_url),
                )
                if callback.message:
                    await callback.message.edit_text(f"{callback.message.text}\n\n{texts.ADMIN_PAYMENT_APPROVED}", reply_markup=None)
                await callback.answer("Оплата подтверждена")
                return
            await db.reject_payment(payment.id)
            try:
                sync_club_payment(await db.get_payment(payment.id), await db.get_user(user.telegram_id))
            except Exception:
                logger.exception("Failed to sync rejected club payment into core registry")
            await notify_user(
                callback,
                user.telegram_id,
                texts.PAYMENT_REJECTED.format(owner_contact_url=settings.owner_contact_url),
                keyboards.rejected_keyboard(settings.owner_contact_url),
            )
            if callback.message:
                await callback.message.edit_text(f"{callback.message.text}\n\n{texts.ADMIN_PAYMENT_REJECTED}", reply_markup=None)
            await callback.answer("Платёж отклонён")
            return
        if action == "extend":
            user = await db.get_user(int(raw_id))
            if user is None:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return
            period = calculate_manual_extension(user)
            await db.manual_extend(user.telegram_id, period.access_start_at, period.access_end_at, period.grace_end_at)
            try:
                sync_club_membership(await db.get_user(user.telegram_id))
            except Exception:
                logger.exception("Failed to sync manually extended club membership into core registry")
            await notify_user(
                callback,
                user.telegram_id,
                "Ваш доступ к клубу Nastaunik был продлён администратором на 30 дней.",
                keyboards.approved_keyboard(settings.club_invite_link, settings.owner_contact_url),
            )
            await callback.answer("Доступ продлён")
            return
        if action == "disable":
            user = await db.get_user(int(raw_id))
            if user is None:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return
            await db.manual_disable_access(user.telegram_id, admin_comment="Доступ отключён администратором")
            try:
                sync_club_membership(await db.get_user(user.telegram_id))
            except Exception:
                logger.exception("Failed to sync disabled club membership into core registry")
            await remove_from_club(callback, user.telegram_id)
            updated_user = await db.get_user(user.telegram_id)
            if updated_user is not None:
                await send_user_card(callback, updated_user)
            await notify_user(
                callback,
                user.telegram_id,
                "Администратор отключил ваш доступ к клубу Nastaunik. Если это ошибка, напишите Вячеславу.",
                keyboards.expired_keyboard(),
            )
            return
        if action == "payments":
            user = await db.get_user(int(raw_id))
            if user is None:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return
            payments = await db.list_payments_for_user(user.telegram_id, limit=10)
            if not payments:
                text = f"История оплат пользователя {user.full_name}\n\nПлатежей пока нет."
            else:
                lines = [f"История оплат пользователя {user.full_name}\n"]
                for payment in payments:
                    status_label = {
                        "pending": "ожидает проверки",
                        "approved": "подтверждён",
                        "rejected": "отклонён",
                    }.get(payment.status, payment.status)
                    lines.append(
                        f"#{payment.id} | {status_label} | {payment.amount_label} | создан {format_dt(payment.created_at)} | подтверждён {format_dt(payment.confirmed_at)}"
                    )
                text = "\n".join(lines)
            if callback.message:
                await callback.message.edit_text(text, reply_markup=keyboards.admin_user_keyboard(user.telegram_id))
            await callback.answer()
            return
        if action == "lifetime_on":
            user = await db.get_user(int(raw_id))
            if user is None:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return
            await db.grant_lifetime_free_access(user.telegram_id, club_invite_link=settings.club_invite_link, admin_comment="Вечный бесплатный доступ")
            try:
                sync_club_membership(await db.get_user(user.telegram_id))
            except Exception:
                logger.exception("Failed to sync lifetime access membership into core registry")
            updated_user = await db.get_user(user.telegram_id)
            if updated_user is not None:
                await send_user_card(callback, updated_user)
            await notify_user(
                callback,
                user.telegram_id,
                "Администратор выдал вам вечный бесплатный доступ в клуб Nastaunik.",
                keyboards.approved_keyboard(settings.club_invite_link, settings.owner_contact_url),
            )
            return
        if action == "lifetime_off":
            user = await db.get_user(int(raw_id))
            if user is None:
                await callback.answer("Пользователь не найден.", show_alert=True)
                return
            await db.revoke_lifetime_free_access(user.telegram_id, admin_comment="Вечный бесплатный доступ снят")
            try:
                sync_club_membership(await db.get_user(user.telegram_id))
            except Exception:
                logger.exception("Failed to sync lifetime revoke membership into core registry")
            updated_user = await db.get_user(user.telegram_id)
            if updated_user is not None:
                await send_user_card(callback, updated_user)
            await notify_user(
                callback,
                user.telegram_id,
                "Администратор снял вечный бесплатный доступ. Для дальнейшего участия используйте обычную оплату клуба.",
                keyboards.expired_keyboard(),
            )
            return
        await callback.answer("Неизвестное действие.", show_alert=True)

    @router.message(Command("user"))
    async def admin_user_lookup(message: Message) -> None:
        if not message.from_user or not is_admin(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) != 2:
            await message.answer("Используйте команду в формате: /user 123456789 или /user @username")
            return
        lookup_value = parts[1].strip()
        user = await db.find_user_by_telegram_id(int(lookup_value)) if lookup_value.isdigit() else await db.find_user_by_username(lookup_value)
        if user is None:
            await message.answer("Пользователь не найден.")
            return
        await send_user_card(message, user)

    return router
