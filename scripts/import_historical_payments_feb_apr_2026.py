from __future__ import annotations

import asyncio
from collections.abc import Iterable

from bot.config import load_settings
from bot.database import DEFAULT_AMOUNT_LABEL, Database, SPECIAL_AMOUNT_LABEL_7


HISTORICAL_PAYMENTS = [
    {"full_name": "Татьяна Козел", "username": "taniakozel", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Елена Шарапова", "username": "Elena_Sharapova_Mogilev", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Дмитрий Кравцов", "username": "Simed777", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Виктория Валерьевна", "username": "Victoriya_Vv0", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-04-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Ольга Филинова", "username": "olyapolyaff", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-04-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "ИринаS", "username": "Irina_Sourta", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-04-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Татьяна", "username": "T_I_SA", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-04-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Marielle", "username": "mahha_official", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Maria", "username": "mworlova", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-04-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Holi Loli", "username": "zhigalov_r", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-04-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Ольга Ротаренко", "username": "Cvetik0311", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-04-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Catharina", "username": "catharina_gm", "payments": [("2026-02-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-03-01T00:00:00", SPECIAL_AMOUNT_LABEL_7), ("2026-04-01T00:00:00", SPECIAL_AMOUNT_LABEL_7)]},
    {"full_name": "Виталий Близнюк", "username": "VitaliiBliznyuk", "payments": [("2026-04-01T00:00:00", DEFAULT_AMOUNT_LABEL)]},
]


def build_history_note(payments: Iterable[tuple[str, str]]) -> str:
    chunks = []
    for payment_date, amount_label in payments:
        chunks.append(f"{payment_date[:10]} -> {amount_label}")
    return "История оплат до запуска бота: " + "; ".join(chunks)


async def payment_exists(db: Database, telegram_id: int, confirmed_at: str, amount_label: str) -> bool:
    async with db.connect() as conn:
        cursor = await conn.execute(
            """
            SELECT 1
            FROM payments
            WHERE telegram_id = ?
              AND status = 'approved'
              AND confirmed_at = ?
              AND amount_label = ?
              AND receipt_type = 'historical_import'
            LIMIT 1
            """,
            (telegram_id, confirmed_at, amount_label),
        )
        return await cursor.fetchone() is not None


async def insert_payment(db: Database, telegram_id: int, confirmed_at: str, amount_label: str, note: str) -> None:
    async with db.connect() as conn:
        await conn.execute(
            """
            INSERT INTO payments (
                telegram_id,
                status,
                amount_label,
                receipt_type,
                receipt_file_id,
                receipt_text,
                admin_message_id,
                created_at,
                confirmed_at,
                rejected_at,
                admin_comment
            ) VALUES (?, 'approved', ?, 'historical_import', NULL, ?, NULL, ?, ?, NULL, ?)
            """,
            (
                telegram_id,
                amount_label,
                note,
                confirmed_at,
                confirmed_at,
                "Импорт исторической оплаты до запуска Telegram-бота",
            ),
        )
        await conn.commit()


async def append_note_to_preset(db: Database, username: str, note: str) -> None:
    preset = await db.get_username_access_preset_by_username(username)
    if preset is None:
        return
    existing_comment = preset.admin_comment or ""
    if note in existing_comment:
        return
    updated_comment = f"{existing_comment}\n{note}".strip()
    async with db.connect() as conn:
        await conn.execute(
            """
            UPDATE username_access_presets
            SET admin_comment = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (updated_comment, preset.id),
        )
        await conn.commit()


async def main() -> None:
    settings = load_settings()
    db = Database(settings.database_path)
    await db.init()

    for member in HISTORICAL_PAYMENTS:
        username = member["username"]
        full_name = member["full_name"]
        payments = member["payments"]
        note = build_history_note(payments)
        user = await db.find_user_by_username(username)

        if user is None:
            await append_note_to_preset(db, username, note)
            print(f"preset-only: {username} ({full_name})")
            continue

        inserted = 0
        for confirmed_at, amount_label in payments:
            if await payment_exists(db, user.telegram_id, confirmed_at, amount_label):
                continue
            await insert_payment(db, user.telegram_id, confirmed_at, amount_label, note)
            inserted += 1
        print(f"user: {username} ({full_name}) inserted={inserted}")


if __name__ == "__main__":
    asyncio.run(main())
