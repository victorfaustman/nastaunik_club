# Telegram bot for Nastaunik club

Current version: `0.1`

MVP Telegram bot on `aiogram 3` for onboarding users into the private Nastaunik club. The bot uses only inline buttons, accepts payment receipts, sends applications to the admin, activates access for 30 days, reminds about renewal, and closes access after the 5-day grace period.

## Features

- `/start` with the main inline menu
- Screens: club info, contents, author, payment, questions
- Receipt submission flow with photo, file, or text support
- Admin approval and rejection via inline buttons
- 30-day access period with renewal rules
- First reminder 5 days before the end date
- Second reminder on the expiration day
- Automatic move to grace period and expiration
- Pre-registration by Telegram username for prepaid members with a custom monthly price
- Optional admin command `/user <telegram_id>`
- Optional manual 30-day extension for admins

## Project structure

- `app.py` - entry point
- `bot/config.py` - `.env` loading
- `bot/texts.py` - all bot texts
- `bot/keyboards.py` - inline keyboards only
- `bot/database.py` - SQLite schema and queries
- `bot/services/membership.py` - access period calculation
- `bot/handlers/user.py` - user flows
- `bot/handlers/admin.py` - admin flows
- `bot/scheduler.py` - daily subscription checks

## Setup

1. Create and activate a virtual environment.
2. Install dependencies: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill in the values.
4. Start the bot: `python app.py`

## Environment variables

- `BOT_TOKEN` - Telegram bot token
- `ADMIN_IDS` - comma-separated admin Telegram IDs
- `CLUB_INVITE_LINK` - invite link to the private club/chat
- `OWNER_CONTACT_URL` - contact link shown to users
- `DATABASE_PATH` - path to SQLite database file
- `TIMEZONE` - scheduler timezone, for example `Europe/Minsk`
- `CLUB_CHAT_ID` - optional private group ID for automatic removal
- `LOG_LEVEL` - logger level, for example `INFO`

## Notes

- If `CLUB_CHAT_ID` is set and the bot has admin rights in the club chat, it will try to remove users after the grace period expires.
- The database schema is created automatically on first run.
- Use `python scripts/import_special_rate_members.py` to seed prepaid members who have not started the bot yet.
- All menus and admin actions are implemented through inline buttons only.
