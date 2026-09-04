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
- `bot/mini_app.py` - Telegram Mini App API and initData validation
- `bot/learning.py` - Mini App catalog/progress queries
- `bot/learning_admin.py` - CMS screen for Mini App content
- `mini_app/` - mobile-first Mini App frontend

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
- `MINI_APP_URL` - HTTPS URL of the Mini App, for example `https://example.com/club-admin/mini-app/`

## Notes

- If `CLUB_CHAT_ID` is set and the bot has admin rights in the club chat, it will try to remove users after the grace period expires.
- The database schema is created automatically on first run.
- Use `python scripts/import_special_rate_members.py` to seed prepaid members who have not started the bot yet.
- All menus and admin actions are implemented through inline buttons only.

## Telegram Mini App

The Mini App is served by the existing `admin_web.py` aiohttp service at `/mini-app/`. Its API is public at the network layer, but every API request must include Telegram `initData` in `X-Telegram-Init-Data`; the backend verifies the HMAC with `BOT_TOKEN`, refreshes the existing user record, and derives access from the existing subscription status. No Telegram ID supplied by frontend JSON is trusted.

Set `MINI_APP_URL` to the public HTTPS URL and restart the bot. The bot then exposes an `Открыть клуб` Web App menu button for members and admins. Configure the join/renew URLs, guest/expired copy, and all content from CRM → `Обучение`.

Deep links use Telegram Mini App `startapp` parameters: `home`, `library`, `material_<id>`, `category_<id>`, `courses`, `course_<id>`, `consultations`, and `profile`. Example: `https://t.me/<bot_username>?startapp=course_3`.

The CMS never creates seed categories, courses, materials, or demo records. The schema migration is documented in `migrations/001_mini_app.sql` and is applied idempotently by the existing database initializer. Materials are single entities and can be reused by multiple courses and home blocks; deleting a category leaves materials intact.
