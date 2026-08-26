from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, FSInputFile, Message, ReplyKeyboardRemove

from bot import keyboards, texts
from bot.config import Settings
from bot.core_sync import resolve_club_user, sync_club_membership, sync_club_payment
from bot.database import DEFAULT_AMOUNT_LABEL, Database
from bot.states import ReceiptStates

MENU_IMAGE_STATE_KEY = "last_welcome_image_at"
MENU_IMAGE_COOLDOWN_SECONDS = 120

logger = logging.getLogger(__name__)


def create_user_router(db: Database, settings: Settings) -> Router:
    router = Router(name="user")

    async def remove_legacy_account_from_club(old_telegram_id: int, message: Message) -> None:
        if not settings.club_chat_id:
            return
        try:
            await message.bot.ban_chat_member(settings.club_chat_id, old_telegram_id)
            await message.bot.unban_chat_member(settings.club_chat_id, old_telegram_id, only_if_banned=True)
        except Exception:
            logger.exception("Failed to remove legacy account %s from club chat during account transfer", old_telegram_id)

    def should_show_renew_button(user) -> bool:
        return bool(
            user
            and user.current_status in {"active", "grace_period", "expired"}
            and not user.is_lifetime_free
            and user.access_start_at
        )

    def should_hide_entry_actions(user) -> bool:
        return bool(
            user
            and (
                user.is_lifetime_free
                or user.current_status in {"active", "grace_period", "trial_active", "waiting_confirmation"}
            )
        )

    def format_dt(value: str | None) -> str:
        if not value:
            return "—"
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")

    def format_status(status: str) -> str:
        labels = {
            "new": "новый пользователь",
            "waiting_payment": "ожидается чек",
            "waiting_confirmation": "чек на проверке",
            "active": "доступ активен",
            "trial_active": "тестовый период активен",
            "grace_period": "льготный период",
            "expired": "доступ закрыт",
            "rejected": "чек отклонён",
        }
        return labels.get(status, status)

    def build_user_status_text(user) -> str:
        if user is None:
            return "Ваш статус в клубе Nastaŭnik\n\nДанные о доступе пока не найдены."

        if user.is_lifetime_free:
            return "Ваш статус в клубе Nastaŭnik\n\nСтатус: Вечно бесплатный доступ"

        amount_label = user.recurring_amount_label or DEFAULT_AMOUNT_LABEL
        access_start_at = format_dt(user.access_start_at)
        access_end_at = format_dt(user.access_end_at)

        if user.current_status == "trial_active":
            return (
                "Ваш статус в клубе Nastaŭnik\n\n"
                "Статус: Тестовый доступ активен\n"
                f"Пробный доступ до: {format_dt(user.trial_ends_at)}"
            )

        if amount_label.startswith("7 BYN"):
            lines = [
                "Ваш статус в клубе Nastaŭnik\n",
                "Статус: Особая цена - 7 BYN / месяц",
            ]
            if user.access_start_at or user.access_end_at:
                lines.append(f"Период: {access_start_at} - {access_end_at}")
            return "\n".join(lines)

        if user.current_status in {"active", "grace_period"}:
            lines = [
                "Ваш статус в клубе Nastaŭnik\n",
                f"Тариф: {amount_label}",
            ]
            if user.access_start_at or user.access_end_at:
                lines.append(f"Период: {access_start_at} - {access_end_at}")
            return "\n".join(lines)

        return texts.USER_STATUS_CARD.format(
            recurring_amount_label=amount_label,
            status=format_status(user.current_status),
            access_start_at=access_start_at,
            access_end_at=access_end_at,
            trial_end_at=format_dt(user.trial_ends_at),
        )

    async def ensure_user(message: Message) -> None:
        user = message.from_user
        if user is None:
            return
        await db.upsert_user(user.id, user.username, user.full_name)
        old_telegram_id = await db.consume_account_transfer_request(user.id, user.username, user.full_name)
        if old_telegram_id is not None:
            try:
                sync_club_membership(await db.get_user(user.id))
            except Exception:
                logger.exception("Failed to sync transferred club membership into core registry")
            await remove_legacy_account_from_club(old_telegram_id, message)
        preset = await db.activate_username_access_preset(
            telegram_id=user.id,
            username=user.username,
            full_name=user.full_name,
            club_invite_link=settings.club_invite_link,
        )
        if preset and (preset.is_lifetime_free or preset.access_end_at):
            try:
                sync_club_membership(await db.get_user(user.id))
            except Exception:
                logger.exception("Failed to sync preset-based club membership into core registry")
        try:
            resolve_club_user(user.id, user.username, user.full_name)
        except Exception:
            logger.exception("Failed to sync club user into core registry")

    async def reset_state_preserving_menu_image(state: FSMContext) -> None:
        data = await state.get_data()
        last_image_at = data.get(MENU_IMAGE_STATE_KEY)
        await state.clear()
        if last_image_at:
            await state.update_data(**{MENU_IMAGE_STATE_KEY: last_image_at})

    async def get_payment_screen(telegram_id: int | None) -> tuple[str, object]:
        if telegram_id is None:
            return texts.payment_info(), keyboards.payment_keyboard()
        user = await db.get_user(telegram_id)
        amount_label = user.recurring_amount_label if user and user.recurring_amount_label else DEFAULT_AMOUNT_LABEL
        hide_entry_actions = should_hide_entry_actions(user)
        return (
            texts.payment_info(amount_label=amount_label, is_renewal=should_show_renew_button(user)),
            keyboards.payment_keyboard(hide_entry_actions=hide_entry_actions),
        )

    async def render_menu(target: Message | CallbackQuery, screen: str) -> None:
        actor_id = None
        if isinstance(target, CallbackQuery) and target.from_user:
            actor_id = target.from_user.id
        if isinstance(target, Message) and target.from_user:
            actor_id = target.from_user.id

        if screen in {"payment", "join"}:
            text, reply_markup = await get_payment_screen(actor_id)
        else:
            user = await db.get_user(actor_id) if actor_id is not None else None
            hide_entry_actions = should_hide_entry_actions(user)
            screen_map = {
                "about": (texts.ABOUT_CLUB, keyboards.about_keyboard(hide_entry_actions=hide_entry_actions)),
                "inside": (texts.WHAT_IS_INSIDE, keyboards.inside_keyboard(hide_entry_actions=hide_entry_actions)),
                "author": (texts.ABOUT_AUTHOR, keyboards.author_keyboard(settings.owner_contact_url, hide_entry_actions=hide_entry_actions)),
                "question": (
                    texts.QUESTION_TEXT.format(owner_contact_url=settings.owner_contact_url),
                    keyboards.question_keyboard(settings.owner_contact_url, hide_entry_actions=hide_entry_actions),
                ),
            }
            if screen == "main":
                text, reply_markup = texts.WELCOME, keyboards.main_menu_keyboard(
                    show_renew_button=should_show_renew_button(user),
                    hide_entry_actions=hide_entry_actions,
                )
            else:
                text, reply_markup = screen_map.get(
                    screen,
                    (texts.WELCOME, keyboards.main_menu_keyboard(
                        show_renew_button=should_show_renew_button(user),
                        hide_entry_actions=hide_entry_actions,
                    )),
                )

        if isinstance(target, CallbackQuery) and target.message:
            try:
                await target.message.edit_text(text, reply_markup=reply_markup)
            except TelegramBadRequest:
                await target.message.answer(text, reply_markup=reply_markup)
            await target.answer()
            return

        if isinstance(target, Message):
            await target.answer(text, reply_markup=reply_markup)

    async def maybe_send_welcome_image(message: Message, state: FSMContext, *, force: bool = False) -> bool:
        photo_source = None
        if settings.welcome_image_path and settings.welcome_image_path.exists():
            photo_source = FSInputFile(settings.welcome_image_path)
        elif settings.welcome_image_url:
            photo_source = settings.welcome_image_url

        if photo_source is None:
            return False

        state_data = await state.get_data()
        last_sent_raw = state_data.get(MENU_IMAGE_STATE_KEY)
        if not force and last_sent_raw:
            try:
                last_sent_at = datetime.fromisoformat(last_sent_raw)
            except ValueError:
                last_sent_at = None
            else:
                if datetime.utcnow() - last_sent_at < timedelta(seconds=MENU_IMAGE_COOLDOWN_SECONDS):
                    return False

        try:
            await message.answer_photo(photo=photo_source, reply_markup=ReplyKeyboardRemove())
        except TelegramBadRequest:
            return False
        await state.update_data(**{MENU_IMAGE_STATE_KEY: datetime.utcnow().isoformat(timespec="seconds")})
        return True

    async def show_main_menu(message: Message, state: FSMContext) -> None:
        await ensure_user(message)
        await reset_state_preserving_menu_image(state)
        image_sent = await maybe_send_welcome_image(message, state)
        if not image_sent:
            await message.answer("Открываю меню.", reply_markup=ReplyKeyboardRemove())
        await render_menu(message, "main")

    async def show_user_status(target: Message | CallbackQuery) -> None:
        actor = target.from_user if isinstance(target, (Message, CallbackQuery)) else None
        if actor is None:
            return

        user = await db.get_user(actor.id)
        text = build_user_status_text(user)
        reply_markup = keyboards.user_status_keyboard(
            show_renew_button=should_show_renew_button(user),
            club_invite_link=user.club_invite_link if user and user.current_status == "active" else None,
            hide_entry_actions=should_hide_entry_actions(user),
        )

        if isinstance(target, CallbackQuery) and target.message:
            try:
                await target.message.edit_text(text, reply_markup=reply_markup)
            except TelegramBadRequest:
                await target.message.answer(text, reply_markup=reply_markup)
            await target.answer()
            return

        if isinstance(target, Message):
            await target.answer(text, reply_markup=reply_markup)

    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        await show_main_menu(message, state)

    @router.message(Command("menu"))
    async def menu_command_handler(message: Message, state: FSMContext) -> None:
        await show_main_menu(message, state)

    @router.message(Command("status"))
    async def status_command_handler(message: Message) -> None:
        await ensure_user(message)
        await show_user_status(message)

    @router.callback_query(F.data.startswith("menu:"))
    async def menu_handler(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.from_user:
            await db.upsert_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
            await db.activate_username_access_preset(
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                full_name=callback.from_user.full_name,
                club_invite_link=settings.club_invite_link,
            )

        destination = callback.data.split(":", maxsplit=1)[1]
        if destination == "status":
            await show_user_status(callback)
            return
        if destination == "main":
            await reset_state_preserving_menu_image(state)
            if callback.message:
                await maybe_send_welcome_image(callback.message, state)
        await render_menu(callback, destination)

    @router.callback_query(F.data == "trial:start")
    async def trial_start_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer("Тестовый период сейчас недоступен.", show_alert=True)

    @router.callback_query(F.data == "promo:enter")
    async def promo_entry_handler(callback: CallbackQuery, state: FSMContext) -> None:
        await state.clear()
        await callback.answer("Промокоды сейчас недоступны.", show_alert=True)

    @router.callback_query(F.data == "payment:send_receipt")
    async def request_receipt(callback: CallbackQuery, state: FSMContext) -> None:
        if callback.from_user:
            await db.upsert_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
            await db.activate_username_access_preset(
                telegram_id=callback.from_user.id,
                username=callback.from_user.username,
                full_name=callback.from_user.full_name,
                club_invite_link=settings.club_invite_link,
            )
            try:
                resolve_club_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
            except Exception:
                logger.exception("Failed to sync club callback user into core registry")
            user = await db.get_user(callback.from_user.id)
            latest_payment = await db.get_latest_payment_for_user(callback.from_user.id)
            if user and user.current_status == "waiting_confirmation" and latest_payment and latest_payment.status == "pending":
                await callback.answer("Ваш чек уже отправлен на проверку.", show_alert=True)
                return
            await db.set_waiting_payment(callback.from_user.id)
        await state.set_state(ReceiptStates.waiting_for_receipt)
        if callback.message:
            await callback.message.answer(texts.RECEIPT_REQUEST)
        await callback.answer()

    @router.message(F.photo | F.document | F.text)
    async def receipt_handler(message: Message, state: FSMContext) -> None:
        current_state = await state.get_state()
        if current_state != ReceiptStates.waiting_for_receipt.state:
            return

        await ensure_user(message)
        if message.from_user is None:
            return

        receipt_type = "text"
        receipt_file_id = None
        receipt_text = message.text or message.caption

        if message.photo:
            receipt_type = "photo"
            receipt_file_id = message.photo[-1].file_id
        elif message.document:
            receipt_type = "document"
            receipt_file_id = message.document.file_id
        elif message.text:
            receipt_type = "text"
        else:
            await message.answer("Пожалуйста, отправьте фото, файл или текстовое сообщение с информацией об оплате.")
            return

        user = await db.get_user(message.from_user.id)
        amount_label = user.recurring_amount_label if user and user.recurring_amount_label else DEFAULT_AMOUNT_LABEL
        payment_id = await db.save_receipt_and_create_payment(
            message.from_user.id,
            receipt_type,
            receipt_file_id,
            receipt_text,
            amount_label,
        )
        try:
            sync_club_payment(await db.get_payment(payment_id), await db.get_user(message.from_user.id))
        except Exception:
            logger.exception("Failed to sync pending club payment into core registry")
        await state.clear()

        username = f"@{message.from_user.username}" if message.from_user.username else "не указан"
        admin_text = texts.admin_new_application(
            full_name=message.from_user.full_name,
            username=username,
            telegram_id=message.from_user.id,
            amount_label=amount_label,
        )
        admin_message_id = None
        for admin_id in settings.admin_ids:
            admin_message = await message.bot.send_message(
                admin_id,
                admin_text,
                reply_markup=keyboards.admin_payment_keyboard(payment_id, message.from_user.id),
            )
            admin_message_id = admin_message.message_id
            await message.bot.copy_message(chat_id=admin_id, from_chat_id=message.chat.id, message_id=message.message_id)
        if admin_message_id is not None:
            await db.set_payment_admin_message(payment_id, admin_message_id)

        await message.answer(texts.RECEIPT_RECEIVED, reply_markup=keyboards.receipt_received_keyboard())

    return router
