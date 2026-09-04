from __future__ import annotations

import asyncio
import logging
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import MenuButtonType, ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeChat,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.config import load_settings
from bot.maintenance import MAINTENANCE_MODE, MaintenanceGateMiddleware
from bot.database import Database
from bot.handlers import create_admin_router, create_user_router
from bot.scheduler import run_subscription_checks


async def configure_bot_interface(bot: Bot, admin_ids: set[int], settings_mini_app_url: str | None = None) -> None:
    public_commands = [
        BotCommand(command="start", description="Запустить бота"),
        BotCommand(command="menu", description="Открыть главное меню"),
        BotCommand(command="status", description="Проверить статус доступа"),
    ]
    admin_commands = public_commands + [
        BotCommand(command="admin", description="Открыть админ-панель"),
        BotCommand(command="user", description="Найти пользователя по ID или username"),
    ]

    await bot.set_my_commands(public_commands)
    await bot.set_my_commands(public_commands, scope=BotCommandScopeAllPrivateChats())
    if settings_mini_app_url:
        await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(type=MenuButtonType.WEB_APP, text="Открыть клуб", web_app=WebAppInfo(url=settings_mini_app_url)))
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands(type=MenuButtonType.COMMANDS))

    for admin_id in admin_ids:
        await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        await bot.set_chat_menu_button(
            chat_id=admin_id,
            menu_button=(
                MenuButtonWebApp(type=MenuButtonType.WEB_APP, text="Открыть клуб", web_app=WebAppInfo(url=settings_mini_app_url))
                if settings_mini_app_url
                else MenuButtonCommands(type=MenuButtonType.COMMANDS)
            ),
        )


async def main() -> None:
    settings = load_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )

    db = Database(settings.database_path)
    await db.init()

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await configure_bot_interface(bot, settings.admin_ids, settings.mini_app_url)

    dp = Dispatcher()
    if MAINTENANCE_MODE:
        maintenance_gate = MaintenanceGateMiddleware(settings.admin_ids)
        dp.message.middleware(maintenance_gate)
        dp.callback_query.middleware(maintenance_gate)
    dp.include_router(create_admin_router(db, settings))
    dp.include_router(create_user_router(db, settings))

    scheduler = None
    if not MAINTENANCE_MODE:
        scheduler = AsyncIOScheduler(timezone=ZoneInfo(settings.timezone))
        scheduler.add_job(
            run_subscription_checks,
            trigger="cron",
            hour=9,
            minute=0,
            kwargs={"bot": bot, "db": db, "settings": settings},
            id="subscription_checks",
            replace_existing=True,
        )
        scheduler.start()

        await run_subscription_checks(bot=bot, db=db, settings=settings)

    try:
        await dp.start_polling(bot)
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
