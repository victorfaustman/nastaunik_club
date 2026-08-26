import asyncio
from aiogram import Bot
from bot.config import load_settings

async def main():
    settings = load_settings()
    bot = Bot(token=settings.bot_token)
    commands = await bot.get_my_commands()
    menu = await bot.get_chat_menu_button()
    print('COMMANDS:', [(c.command, c.description) for c in commands])
    print('MENU:', menu)
    await bot.session.close()

asyncio.run(main())
