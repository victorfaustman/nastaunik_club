from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from bot.config import load_settings
from bot.database import Database, SPECIAL_AMOUNT_LABEL_7


PREPAID_MEMBERS = [
    {"full_name": "Татьяна Козел", "username": "@taniakozel"},
    {"full_name": "Елена Шарапова", "username": "@Elena_Sharapova_Mogilev"},
    {"full_name": "Виктория Валерьевна", "username": "@Victoriya_Vv0"},
    {"full_name": "Oльга Филинова", "username": "@olyapolyaff"},
    {"full_name": "ИринаS", "username": "@Irina_Sourta"},
    {"full_name": "Татьяна", "username": "@T_I_SA"},
    {"full_name": "Marielle", "username": "@mahha_official"},
    {"full_name": "Maria", "username": "@mworlova"},
    {"full_name": "Holi Loli", "username": "@zhigalov_r"},
    {"full_name": "Ольга Ротаренко", "username": "@Cvetik0311"},
    {"full_name": "Catharina", "username": "@catharina_gm"},
]


def april_2026_period() -> tuple[str, str, str]:
    access_start = datetime(2026, 4, 1, 0, 0, 0)
    access_end = access_start + timedelta(days=30)
    grace_end = access_end + timedelta(days=5)
    return (
        access_start.isoformat(timespec="seconds"),
        access_end.isoformat(timespec="seconds"),
        grace_end.isoformat(timespec="seconds"),
    )


async def main() -> None:
    settings = load_settings()
    db = Database(settings.database_path)
    await db.init()

    access_start_at, access_end_at, grace_end_at = april_2026_period()

    for member in PREPAID_MEMBERS:
        await db.upsert_username_access_preset(
            username=member["username"],
            full_name=member["full_name"],
            recurring_amount_label=SPECIAL_AMOUNT_LABEL_7,
            access_start_at=access_start_at,
            access_end_at=access_end_at,
            grace_end_at=grace_end_at,
            payment_confirmed_at=access_start_at,
            admin_comment="Предоплата по спецтарифу 7 BYN/месяц. Апрель 2026 оплачен заранее.",
        )
        print(f"Imported preset for {member['full_name']} ({member['username']})")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
