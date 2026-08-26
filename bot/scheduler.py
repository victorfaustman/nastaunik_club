from __future__ import annotations

import logging
from datetime import datetime, timedelta

from aiogram import Bot

from bot import keyboards, texts
from bot.config import Settings
from bot.database import Database, UserRecord

logger = logging.getLogger(__name__)


async def _safe_send(bot: Bot, user_id: int, text: str, reply_markup) -> None:
    try:
        await bot.send_message(user_id, text, reply_markup=reply_markup)
    except Exception:
        logger.exception("Failed to send scheduled message to user %s", user_id)


async def _safe_send_admins(bot: Bot, admin_ids: set[int], text: str) -> None:
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text)
        except Exception:
            logger.exception("Failed to send scheduled admin message to %s", admin_id)


async def _remove_from_club(bot: Bot, settings: Settings, user: UserRecord) -> None:
    if not settings.club_chat_id:
        return
    try:
        await bot.ban_chat_member(settings.club_chat_id, user.telegram_id)
        await bot.unban_chat_member(settings.club_chat_id, user.telegram_id, only_if_banned=True)
    except Exception:
        logger.exception("Failed to remove user %s from club chat", user.telegram_id)


async def _remove_from_trial_club(bot: Bot, settings: Settings, user: UserRecord) -> None:
    target_chat_id = settings.trial_chat_id or settings.club_chat_id
    if not target_chat_id:
        return
    try:
        await bot.ban_chat_member(target_chat_id, user.telegram_id)
        await bot.unban_chat_member(target_chat_id, user.telegram_id, only_if_banned=True)
    except Exception:
        logger.exception("Failed to remove user %s from trial club chat", user.telegram_id)


async def run_subscription_checks(bot: Bot, db: Database, settings: Settings) -> None:
    now = datetime.utcnow()
    reminder_date = (now + timedelta(days=5)).date().isoformat()
    expiry_date = now.date().isoformat()
    timestamp = now.isoformat(timespec="seconds")

    users_for_reminder = await db.get_users_for_reminder_five_days(reminder_date)
    for user in users_for_reminder:
        amount_label = user.recurring_amount_label or "10 BYN в месяц"
        await _safe_send(bot, user.telegram_id, texts.reminder_five_days(amount_label), keyboards.reminder_keyboard())
        await db.mark_reminder_five_days_sent(user.telegram_id)

    users_for_expiry_notice = await db.get_users_for_expiry_notice(expiry_date)
    for user in users_for_expiry_notice:
        await _safe_send(bot, user.telegram_id, texts.REMINDER_EXPIRY_DAY, keyboards.reminder_keyboard())
        await db.move_to_grace_period(user.telegram_id)

    users_for_expiration = await db.get_users_for_expiration(timestamp)
    for user in users_for_expiration:
        await _remove_from_club(bot, settings, user)
        await _safe_send(bot, user.telegram_id, texts.ACCESS_EXPIRED, keyboards.expired_keyboard())
        await db.expire_user(user.telegram_id)


async def run_trial_checks(bot: Bot, db: Database, settings: Settings) -> None:
    now = datetime.utcnow()
    reminder_date = (now + timedelta(days=1)).date().isoformat()
    timestamp = now.isoformat(timespec="seconds")

    users_for_trial_reminder = await db.get_users_for_trial_reminder(reminder_date)
    for user in users_for_trial_reminder:
        await _safe_send(bot, user.telegram_id, texts.TRIAL_ONE_DAY_LEFT, keyboards.trial_finished_keyboard())
        await db.mark_trial_reminder_sent(user.telegram_id)

    users_with_finished_trial = await db.get_users_with_finished_trial(timestamp)
    for user in users_with_finished_trial:
        await _remove_from_trial_club(bot, settings, user)
        amount_label = user.recurring_amount_label or "10 BYN в месяц"
        await _safe_send(bot, user.telegram_id, texts.trial_ended_user(amount_label), keyboards.trial_finished_keyboard())
        username = f"@{user.username}" if user.username else "не указан"
        await _safe_send_admins(
            bot,
            settings.admin_ids,
            texts.admin_trial_ended(user.full_name, username, user.telegram_id),
        )
        await db.finish_trial_access(user.telegram_id)
