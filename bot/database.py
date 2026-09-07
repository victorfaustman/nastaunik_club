from __future__ import annotations

import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import aiosqlite


USER_STATUSES = {
    "new",
    "waiting_payment",
    "waiting_confirmation",
    "active",
    "trial_active",
    "grace_period",
    "expired",
    "rejected",
}

PROMO_TYPES = {"permanent", "temporary"}
DEFAULT_AMOUNT_LABEL = "10 BYN / месяц"
SPECIAL_AMOUNT_LABEL_7 = "7 BYN / месяц"
PROMO_FIRST_MONTH_LABEL = "7 BYN / первый месяц"
TRIAL_DAYS = 5


@dataclass(slots=True)
class UserRecord:
    telegram_id: int
    username: str | None
    full_name: str
    current_status: str
    created_at: str
    updated_at: str
    payment_confirmed_at: str | None
    access_start_at: str | None
    access_end_at: str | None
    grace_end_at: str | None
    last_receipt_file_id: str | None
    club_invite_link: str | None
    admin_comment: str | None
    recurring_amount_label: str | None
    reminder_5_sent_at: str | None
    expiry_notice_sent_at: str | None
    pending_amount_label: str | None
    pending_promo_code: str | None
    trial_started_at: str | None
    trial_ends_at: str | None
    trial_used_at: str | None
    trial_reminder_sent_at: str | None
    trial_notice_sent_at: str | None
    is_lifetime_free: int
    lifetime_free_granted_at: str | None


@dataclass(slots=True)
class PaymentRecord:
    id: int
    telegram_id: int
    status: str
    amount_label: str
    receipt_type: str
    receipt_file_id: str | None
    receipt_text: str | None
    admin_message_id: int | None
    created_at: str
    confirmed_at: str | None
    rejected_at: str | None
    admin_comment: str | None


@dataclass(slots=True)
class PromoCodeRecord:
    id: int
    code: str
    promo_type: str
    grant_days: int
    max_uses: int | None
    current_uses: int
    is_active: int
    valid_until: str | None
    comment: str | None
    created_at: str
    created_by: int | None


@dataclass(slots=True)
class UsernameAccessPresetRecord:
    id: int
    username: str
    full_name: str
    recurring_amount_label: str | None
    access_start_at: str | None
    access_end_at: str | None
    grace_end_at: str | None
    payment_confirmed_at: str | None
    is_lifetime_free: int
    admin_comment: str | None
    activated_telegram_id: int | None
    activated_at: str | None
    created_at: str
    updated_at: str


@dataclass(slots=True)
class AccountTransferRequestRecord:
    id: int
    old_telegram_id: int
    new_username: str
    note: str | None
    created_at: str
    consumed_at: str | None
    consumed_by_telegram_id: int | None


class Database:
    def __init__(self, path: Path):
        self.path = path

    @asynccontextmanager
    async def connect(self):
        connection = await aiosqlite.connect(self.path)
        connection.row_factory = sqlite3.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            await connection.close()

    async def init(self) -> None:
        async with self.connect() as db:
            await db.executescript(
                f"""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    username TEXT,
                    full_name TEXT NOT NULL,
                    current_status TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    payment_confirmed_at TEXT,
                    access_start_at TEXT,
                    access_end_at TEXT,
                    grace_end_at TEXT,
                    last_receipt_file_id TEXT,
                    club_invite_link TEXT,
                    admin_comment TEXT,
                    recurring_amount_label TEXT,
                    reminder_5_sent_at TEXT,
                    expiry_notice_sent_at TEXT,
                    pending_amount_label TEXT,
                    pending_promo_code TEXT,
                    trial_started_at TEXT,
                    trial_ends_at TEXT,
                    trial_used_at TEXT,
                    trial_reminder_sent_at TEXT,
                    trial_notice_sent_at TEXT,
                    is_lifetime_free INTEGER NOT NULL DEFAULT 0,
                    lifetime_free_granted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS payments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    amount_label TEXT NOT NULL DEFAULT '{DEFAULT_AMOUNT_LABEL}',
                    receipt_type TEXT NOT NULL,
                    receipt_file_id TEXT,
                    receipt_text TEXT,
                    admin_message_id INTEGER,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    rejected_at TEXT,
                    admin_comment TEXT,
                    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
                );

                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT
                );

                CREATE TABLE IF NOT EXISTS promo_codes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT NOT NULL UNIQUE,
                    promo_type TEXT NOT NULL,
                    grant_days INTEGER NOT NULL,
                    max_uses INTEGER,
                    current_uses INTEGER NOT NULL DEFAULT 0,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    valid_until TEXT,
                    comment TEXT,
                    created_at TEXT NOT NULL,
                    created_by INTEGER
                );

                CREATE TABLE IF NOT EXISTS promo_code_usages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    promo_code_id INTEGER NOT NULL,
                    telegram_id INTEGER NOT NULL,
                    used_at TEXT NOT NULL,
                    access_start_at TEXT NOT NULL,
                    access_end_at TEXT NOT NULL,
                    FOREIGN KEY (promo_code_id) REFERENCES promo_codes (id),
                    FOREIGN KEY (telegram_id) REFERENCES users (telegram_id),
                    UNIQUE(promo_code_id, telegram_id)
                );

                CREATE TABLE IF NOT EXISTS username_access_presets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    recurring_amount_label TEXT,
                    access_start_at TEXT,
                    access_end_at TEXT,
                    grace_end_at TEXT,
                    payment_confirmed_at TEXT,
                    is_lifetime_free INTEGER NOT NULL DEFAULT 0,
                    admin_comment TEXT,
                    activated_telegram_id INTEGER,
                    activated_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS account_transfer_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    old_telegram_id INTEGER NOT NULL UNIQUE,
                    new_username TEXT NOT NULL UNIQUE,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT,
                    consumed_by_telegram_id INTEGER
                );

                CREATE TABLE IF NOT EXISTS mini_app_categories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    icon TEXT,
                    cover_url TEXT,
                    is_visible INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mini_app_materials (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    short_description TEXT,
                    full_description TEXT,
                    cover_url TEXT,
                    telegram_url TEXT,
                    category_id INTEGER,
                    format TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (category_id) REFERENCES mini_app_categories(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS mini_app_courses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    cover_url TEXT,
                    category_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'draft',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (category_id) REFERENCES mini_app_categories(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS mini_app_course_lessons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    course_id INTEGER NOT NULL,
                    material_id INTEGER NOT NULL,
                    title_override TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(course_id, material_id),
                    FOREIGN KEY (course_id) REFERENCES mini_app_courses(id) ON DELETE CASCADE,
                    FOREIGN KEY (material_id) REFERENCES mini_app_materials(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mini_app_home_sections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    section_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    item_id INTEGER,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    is_visible INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY (item_id) REFERENCES mini_app_materials(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS mini_app_consultation (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    title TEXT NOT NULL DEFAULT 'Консультации',
                    description TEXT,
                    body TEXT,
                    booking_label TEXT,
                    booking_url TEXT,
                    contact_label TEXT,
                    contact_url TEXT,
                    topic_label TEXT,
                    topic_url TEXT,
                    show_booking INTEGER NOT NULL DEFAULT 0,
                    show_contact INTEGER NOT NULL DEFAULT 0,
                    show_topic INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mini_app_user_progress (
                    telegram_id INTEGER NOT NULL,
                    lesson_id INTEGER NOT NULL,
                    completed_at TEXT NOT NULL,
                    PRIMARY KEY (telegram_id, lesson_id),
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
                    FOREIGN KEY (lesson_id) REFERENCES mini_app_course_lessons(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mini_app_favorites (
                    telegram_id INTEGER NOT NULL,
                    material_id INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (telegram_id, material_id),
                    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE,
                    FOREIGN KEY (material_id) REFERENCES mini_app_materials(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mini_app_material_files (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    file_name TEXT NOT NULL,
                    stored_name TEXT NOT NULL UNIQUE,
                    mime_type TEXT,
                    file_size INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (material_id) REFERENCES mini_app_materials(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mini_app_material_blocks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    material_id INTEGER NOT NULL,
                    block_type TEXT NOT NULL,
                    title TEXT,
                    content TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (material_id) REFERENCES mini_app_materials(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS mini_app_tags (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    slug TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS mini_app_material_tags (
                    material_id INTEGER NOT NULL,
                    tag_id INTEGER NOT NULL,
                    PRIMARY KEY (material_id, tag_id),
                    FOREIGN KEY (material_id) REFERENCES mini_app_materials(id) ON DELETE CASCADE,
                    FOREIGN KEY (tag_id) REFERENCES mini_app_tags(id) ON DELETE CASCADE
                );
                """
            )
            for column_name in (
                "recurring_amount_label",
                "pending_amount_label",
                "pending_promo_code",
                "trial_started_at",
                "trial_ends_at",
                "trial_used_at",
                "trial_reminder_sent_at",
                "trial_notice_sent_at",
            ):
                await self._ensure_column(db, "users", column_name, "TEXT")
            await self._ensure_column(db, "users", "is_lifetime_free", "INTEGER NOT NULL DEFAULT 0")
            await self._ensure_column(db, "users", "lifetime_free_granted_at", "TEXT")
            await db.commit()

    async def _ensure_column(self, db: aiosqlite.Connection, table_name: str, column_name: str, column_definition: str) -> None:
        cursor = await db.execute(f"PRAGMA table_info({table_name})")
        rows = await cursor.fetchall()
        existing_columns = {row["name"] for row in rows}
        if column_name not in existing_columns:
            await db.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_definition}")

    @staticmethod
    def _now_iso() -> str:
        return datetime.utcnow().isoformat(timespec="seconds")

    @staticmethod
    def _row_to_user(row: sqlite3.Row | None) -> UserRecord | None:
        if row is None:
            return None
        return UserRecord(**dict(row))

    @staticmethod
    def _row_to_payment(row: sqlite3.Row | None) -> PaymentRecord | None:
        if row is None:
            return None
        return PaymentRecord(**dict(row))

    @staticmethod
    def _row_to_promo(row: sqlite3.Row | None) -> PromoCodeRecord | None:
        if row is None:
            return None
        return PromoCodeRecord(**dict(row))

    @staticmethod
    def _row_to_username_access_preset(row: sqlite3.Row | None) -> UsernameAccessPresetRecord | None:
        if row is None:
            return None
        return UsernameAccessPresetRecord(**dict(row))

    @staticmethod
    def _row_to_account_transfer_request(row: sqlite3.Row | None) -> AccountTransferRequestRecord | None:
        if row is None:
            return None
        return AccountTransferRequestRecord(**dict(row))

    async def upsert_user(self, telegram_id: int, username: str | None, full_name: str) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO users (telegram_id, username, full_name, current_status, created_at, updated_at)
                VALUES (?, ?, ?, 'new', ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name,
                    updated_at = excluded.updated_at
                """,
                (telegram_id, username, full_name, now, now),
            )
            await db.commit()

    async def upsert_username_access_preset(
        self,
        *,
        username: str,
        full_name: str,
        recurring_amount_label: str | None,
        access_start_at: str | None,
        access_end_at: str | None,
        grace_end_at: str | None,
        payment_confirmed_at: str | None = None,
        is_lifetime_free: bool = False,
        admin_comment: str | None = None,
    ) -> int:
        normalized_username = username.lstrip("@").strip()
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO username_access_presets (
                    username,
                    full_name,
                    recurring_amount_label,
                    access_start_at,
                    access_end_at,
                    grace_end_at,
                    payment_confirmed_at,
                    is_lifetime_free,
                    admin_comment,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    full_name = excluded.full_name,
                    recurring_amount_label = excluded.recurring_amount_label,
                    access_start_at = excluded.access_start_at,
                    access_end_at = excluded.access_end_at,
                    grace_end_at = excluded.grace_end_at,
                    payment_confirmed_at = excluded.payment_confirmed_at,
                    is_lifetime_free = excluded.is_lifetime_free,
                    admin_comment = excluded.admin_comment,
                    updated_at = excluded.updated_at
                """,
                (
                    normalized_username,
                    full_name,
                    recurring_amount_label,
                    access_start_at,
                    access_end_at,
                    grace_end_at,
                    payment_confirmed_at,
                    1 if is_lifetime_free else 0,
                    admin_comment,
                    now,
                    now,
                ),
            )
            cursor = await db.execute(
                "SELECT id FROM username_access_presets WHERE lower(username) = lower(?) LIMIT 1",
                (normalized_username,),
            )
            row = await cursor.fetchone()
            await db.commit()
            if row is None:
                raise ValueError("Failed to upsert username access preset")
            return int(row["id"])

    async def get_user(self, telegram_id: int) -> UserRecord | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            return self._row_to_user(await cursor.fetchone())

    async def create_account_transfer_request(self, old_telegram_id: int, new_username: str, note: str | None = None) -> int:
        normalized_username = new_username.lstrip("@").strip()
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO account_transfer_requests (old_telegram_id, new_username, note, created_at, consumed_at, consumed_by_telegram_id)
                VALUES (?, ?, ?, ?, NULL, NULL)
                ON CONFLICT(old_telegram_id) DO UPDATE SET
                    new_username = excluded.new_username,
                    note = excluded.note,
                    created_at = excluded.created_at,
                    consumed_at = NULL,
                    consumed_by_telegram_id = NULL
                """,
                (old_telegram_id, normalized_username, note, now),
            )
            cursor = await db.execute(
                "SELECT id FROM account_transfer_requests WHERE old_telegram_id = ? LIMIT 1",
                (old_telegram_id,),
            )
            row = await cursor.fetchone()
            await db.commit()
            if row is None:
                raise ValueError("Failed to create account transfer request")
            return int(row["id"])

    async def consume_account_transfer_request(
        self,
        new_telegram_id: int,
        new_username: str | None,
        new_full_name: str,
    ) -> int | None:
        if not new_username:
            return None
        normalized_username = new_username.lstrip("@").strip()
        now = self._now_iso()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM account_transfer_requests
                WHERE lower(new_username) = lower(?)
                  AND consumed_at IS NULL
                LIMIT 1
                """,
                (normalized_username,),
            )
            request = self._row_to_account_transfer_request(await cursor.fetchone())
            if request is None:
                return None

            cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (request.old_telegram_id,))
            source_user = self._row_to_user(await cursor.fetchone())
            if source_user is None:
                return None

            await db.execute(
                """
                INSERT INTO users (telegram_id, username, full_name, current_status, created_at, updated_at)
                VALUES (?, ?, ?, 'new', ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name,
                    updated_at = excluded.updated_at
                """,
                (new_telegram_id, normalized_username, new_full_name, now, now),
            )

            if request.old_telegram_id != new_telegram_id:
                await db.execute("UPDATE payments SET telegram_id = ? WHERE telegram_id = ?", (new_telegram_id, request.old_telegram_id))
                await db.execute(
                    "UPDATE promo_code_usages SET telegram_id = ? WHERE telegram_id = ?",
                    (new_telegram_id, request.old_telegram_id),
                )

            await db.execute(
                """
                UPDATE users
                SET username = ?,
                    full_name = ?,
                    current_status = ?,
                    created_at = ?,
                    updated_at = ?,
                    payment_confirmed_at = ?,
                    access_start_at = ?,
                    access_end_at = ?,
                    grace_end_at = ?,
                    last_receipt_file_id = ?,
                    club_invite_link = ?,
                    admin_comment = ?,
                    recurring_amount_label = ?,
                    reminder_5_sent_at = ?,
                    expiry_notice_sent_at = ?,
                    pending_amount_label = ?,
                    pending_promo_code = ?,
                    trial_started_at = ?,
                    trial_ends_at = ?,
                    trial_used_at = ?,
                    trial_reminder_sent_at = ?,
                    trial_notice_sent_at = ?,
                    is_lifetime_free = ?,
                    lifetime_free_granted_at = ?
                WHERE telegram_id = ?
                """,
                (
                    normalized_username,
                    new_full_name,
                    source_user.current_status,
                    source_user.created_at,
                    now,
                    source_user.payment_confirmed_at,
                    source_user.access_start_at,
                    source_user.access_end_at,
                    source_user.grace_end_at,
                    source_user.last_receipt_file_id,
                    source_user.club_invite_link,
                    source_user.admin_comment,
                    source_user.recurring_amount_label,
                    source_user.reminder_5_sent_at,
                    source_user.expiry_notice_sent_at,
                    source_user.pending_amount_label,
                    source_user.pending_promo_code,
                    source_user.trial_started_at,
                    source_user.trial_ends_at,
                    source_user.trial_used_at,
                    source_user.trial_reminder_sent_at,
                    source_user.trial_notice_sent_at,
                    source_user.is_lifetime_free,
                    source_user.lifetime_free_granted_at,
                    new_telegram_id,
                ),
            )

            await db.execute(
                """
                UPDATE username_access_presets
                SET username = ?,
                    activated_telegram_id = ?,
                    updated_at = ?
                WHERE activated_telegram_id = ?
                """,
                (normalized_username, new_telegram_id, now, request.old_telegram_id),
            )

            if request.old_telegram_id != new_telegram_id:
                await db.execute("DELETE FROM users WHERE telegram_id = ?", (request.old_telegram_id,))

            await db.execute(
                """
                UPDATE account_transfer_requests
                SET consumed_at = ?,
                    consumed_by_telegram_id = ?
                WHERE id = ?
                """,
                (now, new_telegram_id, request.id),
            )
            await db.commit()
            return request.old_telegram_id

    async def get_username_access_preset_by_username(self, username: str) -> UsernameAccessPresetRecord | None:
        normalized_username = username.lstrip("@").strip()
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM username_access_presets WHERE lower(username) = lower(?) LIMIT 1",
                (normalized_username,),
            )
            return self._row_to_username_access_preset(await cursor.fetchone())

    async def activate_username_access_preset(
        self,
        *,
        telegram_id: int,
        username: str | None,
        full_name: str,
        club_invite_link: str | None = None,
    ) -> UsernameAccessPresetRecord | None:
        if not username:
            return None
        normalized_username = username.lstrip("@").strip()
        now = self._now_iso()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM username_access_presets
                WHERE lower(username) = lower(?)
                  AND (activated_telegram_id IS NULL OR activated_telegram_id = ?)
                LIMIT 1
                """,
                (normalized_username, telegram_id),
            )
            preset_row = await cursor.fetchone()
            preset = self._row_to_username_access_preset(preset_row)
            if preset is None:
                return None

            target_status = "active" if (preset.is_lifetime_free or preset.access_end_at) else "new"
            await db.execute(
                """
                UPDATE users
                SET username = ?,
                    full_name = ?,
                    current_status = ?,
                    payment_confirmed_at = COALESCE(?, payment_confirmed_at),
                    access_start_at = COALESCE(?, access_start_at),
                    access_end_at = COALESCE(?, access_end_at),
                    grace_end_at = COALESCE(?, grace_end_at),
                    club_invite_link = COALESCE(?, club_invite_link),
                    admin_comment = COALESCE(?, admin_comment),
                    recurring_amount_label = COALESCE(?, recurring_amount_label),
                    reminder_5_sent_at = NULL,
                    expiry_notice_sent_at = NULL,
                    pending_amount_label = NULL,
                    pending_promo_code = NULL,
                    trial_started_at = NULL,
                    trial_ends_at = NULL,
                    trial_reminder_sent_at = NULL,
                    trial_notice_sent_at = NULL,
                    is_lifetime_free = ?,
                    lifetime_free_granted_at = CASE
                        WHEN ? = 1 THEN COALESCE(lifetime_free_granted_at, ?, ?)
                        ELSE lifetime_free_granted_at
                    END,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (
                    normalized_username,
                    full_name,
                    target_status,
                    preset.payment_confirmed_at,
                    preset.access_start_at,
                    preset.access_end_at,
                    preset.grace_end_at,
                    club_invite_link,
                    preset.admin_comment,
                    preset.recurring_amount_label,
                    preset.is_lifetime_free,
                    preset.is_lifetime_free,
                    preset.payment_confirmed_at,
                    now,
                    now,
                    telegram_id,
                ),
            )
            await db.execute(
                """
                UPDATE username_access_presets
                SET activated_telegram_id = ?,
                    activated_at = COALESCE(activated_at, ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (telegram_id, now, now, preset.id),
            )
            await db.commit()
            return preset

    async def set_user_status(self, telegram_id: int, status: str) -> None:
        if status not in USER_STATUSES:
            raise ValueError(f"Unsupported user status: {status}")
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET current_status = ?, updated_at = ? WHERE telegram_id = ?",
                (status, self._now_iso(), telegram_id),
            )
            await db.commit()

    async def set_pending_promo_offer(self, telegram_id: int, promo_code: str, amount_label: str = PROMO_FIRST_MONTH_LABEL) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE users
                SET current_status = 'waiting_payment',
                    pending_amount_label = ?,
                    pending_promo_code = ?,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (amount_label, promo_code, now, telegram_id),
            )
            await db.commit()

    async def clear_pending_offer(self, telegram_id: int) -> None:
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET pending_amount_label = NULL, pending_promo_code = NULL, updated_at = ? WHERE telegram_id = ?",
                (self._now_iso(), telegram_id),
            )
            await db.commit()

    async def has_used_trial(self, telegram_id: int) -> bool:
        user = await self.get_user(telegram_id)
        return bool(user and user.trial_used_at)

    async def start_trial_access(self, telegram_id: int, club_invite_link: str, trial_started_at: str, trial_ends_at: str) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE users
                SET current_status = 'trial_active',
                    club_invite_link = ?,
                    trial_started_at = ?,
                    trial_ends_at = ?,
                    trial_used_at = COALESCE(trial_used_at, ?),
                    trial_reminder_sent_at = NULL,
                    trial_notice_sent_at = NULL,
                    pending_amount_label = NULL,
                    pending_promo_code = NULL,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (club_invite_link, trial_started_at, trial_ends_at, trial_started_at, now, telegram_id),
            )
            await db.commit()

    async def get_users_for_trial_reminder(self, target_date: str) -> list[UserRecord]:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE current_status = 'trial_active' AND date(trial_ends_at) = date(?) AND trial_reminder_sent_at IS NULL",
                (target_date,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows if row is not None]

    async def mark_trial_reminder_sent(self, telegram_id: int) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET trial_reminder_sent_at = ?, updated_at = ? WHERE telegram_id = ?",
                (now, now, telegram_id),
            )
            await db.commit()

    async def get_users_with_finished_trial(self, target_timestamp: str) -> list[UserRecord]:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE current_status = 'trial_active' AND trial_ends_at IS NOT NULL AND trial_notice_sent_at IS NULL"
            )
            rows = await cursor.fetchall()
            finished_users: list[UserRecord] = []
            for row in rows:
                user = self._row_to_user(row)
                if user and user.trial_ends_at and user.trial_ends_at <= target_timestamp:
                    finished_users.append(user)
            return finished_users

    async def finish_trial_access(self, telegram_id: int) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE users
                SET current_status = 'expired',
                    trial_notice_sent_at = ?,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (now, now, telegram_id),
            )
            await db.commit()

    async def find_user_by_username(self, username: str) -> UserRecord | None:
        normalized_username = username.lstrip("@").strip()
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE lower(username) = lower(?) LIMIT 1",
                (normalized_username,),
            )
            return self._row_to_user(await cursor.fetchone())

    async def grant_lifetime_free_access(
        self,
        telegram_id: int,
        club_invite_link: str | None = None,
        admin_comment: str | None = None,
    ) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE users
                SET current_status = 'active',
                    club_invite_link = COALESCE(?, club_invite_link),
                    admin_comment = ?,
                    recurring_amount_label = recurring_amount_label,
                    reminder_5_sent_at = NULL,
                    expiry_notice_sent_at = NULL,
                    pending_amount_label = NULL,
                    pending_promo_code = NULL,
                    trial_started_at = NULL,
                    trial_ends_at = NULL,
                    trial_reminder_sent_at = NULL,
                    trial_notice_sent_at = NULL,
                    is_lifetime_free = 1,
                    lifetime_free_granted_at = COALESCE(lifetime_free_granted_at, ?),
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (club_invite_link, admin_comment, now, now, telegram_id),
            )
            await db.commit()

    async def revoke_lifetime_free_access(self, telegram_id: int, admin_comment: str | None = None) -> None:
        now = self._now_iso()
        user = await self.get_user(telegram_id)
        if user is None:
            return
        current_status = user.current_status
        if current_status == "active" and not user.access_end_at:
            current_status = "expired"
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE users
                SET current_status = ?,
                    admin_comment = ?,
                    is_lifetime_free = 0,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (current_status, admin_comment, now, telegram_id),
            )
            await db.commit()

    async def get_effective_amount_label(self, telegram_id: int) -> str:
        user = await self.get_user(telegram_id)
        if user and user.pending_amount_label:
            return user.pending_amount_label
        if user and user.recurring_amount_label:
            return user.recurring_amount_label
        return DEFAULT_AMOUNT_LABEL

    async def save_receipt_and_create_payment(
        self,
        telegram_id: int,
        receipt_type: str,
        receipt_file_id: str | None,
        receipt_text: str | None,
        amount_label: str,
    ) -> int:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE users
                SET current_status = 'waiting_confirmation',
                    last_receipt_file_id = ?,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (receipt_file_id, now, telegram_id),
            )
            cursor = await db.execute(
                """
                INSERT INTO payments (
                    telegram_id, status, amount_label, receipt_type, receipt_file_id, receipt_text, created_at
                ) VALUES (?, 'pending', ?, ?, ?, ?, ?)
                """,
                (telegram_id, amount_label, receipt_type, receipt_file_id, receipt_text, now),
            )
            await db.commit()
            return cursor.lastrowid

    async def set_payment_admin_message(self, payment_id: int, admin_message_id: int) -> None:
        async with self.connect() as db:
            await db.execute("UPDATE payments SET admin_message_id = ? WHERE id = ?", (admin_message_id, payment_id))
            await db.commit()

    async def get_payment(self, payment_id: int) -> PaymentRecord | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
            return self._row_to_payment(await cursor.fetchone())

    async def get_latest_payment_for_user(self, telegram_id: int) -> PaymentRecord | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM payments WHERE telegram_id = ? ORDER BY id DESC LIMIT 1", (telegram_id,))
            return self._row_to_payment(await cursor.fetchone())

    async def list_payments_for_user(self, telegram_id: int, limit: int = 10) -> list[PaymentRecord]:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM payments WHERE telegram_id = ? ORDER BY id DESC LIMIT ?",
                (telegram_id, limit),
            )
            rows = await cursor.fetchall()
            return [self._row_to_payment(row) for row in rows if row is not None]

    async def approve_payment(
        self,
        payment_id: int,
        club_invite_link: str,
        access_start_at: str,
        access_end_at: str,
        grace_end_at: str,
        admin_comment: str | None = None,
    ) -> int:
        now = self._now_iso()
        async with self.connect() as db:
            cursor = await db.execute("SELECT telegram_id FROM payments WHERE id = ?", (payment_id,))
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("Payment not found")
            telegram_id = int(row["telegram_id"])
            await db.execute(
                "UPDATE payments SET status = 'approved', confirmed_at = ?, admin_comment = ? WHERE id = ?",
                (now, admin_comment, payment_id),
            )
            await db.execute(
                """
                UPDATE users
                SET current_status = 'active',
                    payment_confirmed_at = ?,
                    access_start_at = ?,
                    access_end_at = ?,
                    grace_end_at = ?,
                    club_invite_link = ?,
                    admin_comment = ?,
                    reminder_5_sent_at = NULL,
                    expiry_notice_sent_at = NULL,
                    pending_amount_label = NULL,
                    pending_promo_code = NULL,
                    is_lifetime_free = 0,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (now, access_start_at, access_end_at, grace_end_at, club_invite_link, admin_comment, now, telegram_id),
            )
            await db.commit()
            return telegram_id

    async def activate_user_access(
        self,
        telegram_id: int,
        club_invite_link: str,
        access_start_at: str,
        access_end_at: str,
        grace_end_at: str,
        admin_comment: str | None = None,
        payment_confirmed_at: str | None = None,
    ) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE users
                SET current_status = 'active',
                    payment_confirmed_at = COALESCE(?, payment_confirmed_at),
                    access_start_at = ?,
                    access_end_at = ?,
                    grace_end_at = ?,
                    club_invite_link = ?,
                    admin_comment = ?,
                    reminder_5_sent_at = NULL,
                    expiry_notice_sent_at = NULL,
                    pending_amount_label = NULL,
                    pending_promo_code = NULL,
                    is_lifetime_free = 0,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (payment_confirmed_at, access_start_at, access_end_at, grace_end_at, club_invite_link, admin_comment, now, telegram_id),
            )
            await db.commit()

    async def reject_payment(self, payment_id: int, admin_comment: str | None = None) -> int:
        now = self._now_iso()
        async with self.connect() as db:
            cursor = await db.execute("SELECT telegram_id FROM payments WHERE id = ?", (payment_id,))
            row = await cursor.fetchone()
            if row is None:
                raise ValueError("Payment not found")
            telegram_id = int(row["telegram_id"])
            await db.execute(
                "UPDATE payments SET status = 'rejected', rejected_at = ?, admin_comment = ? WHERE id = ?",
                (now, admin_comment, payment_id),
            )
            await db.execute(
                "UPDATE users SET current_status = 'rejected', admin_comment = ?, updated_at = ? WHERE telegram_id = ?",
                (admin_comment, now, telegram_id),
            )
            await db.commit()
            return telegram_id

    async def set_waiting_payment(self, telegram_id: int) -> None:
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET current_status = 'waiting_payment', updated_at = ? WHERE telegram_id = ?",
                (self._now_iso(), telegram_id),
            )
            await db.commit()

    async def find_user_by_telegram_id(self, telegram_id: int) -> UserRecord | None:
        return await self.get_user(telegram_id)

    async def manual_extend(self, telegram_id: int, access_start_at: str, access_end_at: str, grace_end_at: str) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE users
                SET current_status = 'active',
                    access_start_at = ?,
                    access_end_at = ?,
                    grace_end_at = ?,
                    reminder_5_sent_at = NULL,
                    expiry_notice_sent_at = NULL,
                    is_lifetime_free = 0,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (access_start_at, access_end_at, grace_end_at, now, telegram_id),
            )
            await db.commit()

    async def manual_disable_access(self, telegram_id: int, admin_comment: str | None = None) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                UPDATE users
                SET current_status = 'expired',
                    admin_comment = ?,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (admin_comment, now, telegram_id),
            )
            await db.commit()

    async def list_users_by_status(self, statuses: list[str], limit: int = 20) -> list[UserRecord]:
        if not statuses:
            return []
        placeholders = ", ".join("?" for _ in statuses)
        query = f"SELECT * FROM users WHERE current_status IN ({placeholders}) ORDER BY updated_at DESC LIMIT ?"
        async with self.connect() as db:
            cursor = await db.execute(query, (*statuses, limit))
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows if row is not None]

    async def list_users_expiring_soon(self, days: int = 7, limit: int = 20, now: datetime | None = None) -> list[UserRecord]:
        current_time = now or datetime.utcnow()
        max_date = (current_time + timedelta(days=days)).date().isoformat()
        min_date = current_time.date().isoformat()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM users
                WHERE current_status = 'active'
                  AND is_lifetime_free = 0
                  AND access_end_at IS NOT NULL
                  AND date(access_end_at) >= date(?)
                  AND date(access_end_at) <= date(?)
                ORDER BY access_end_at ASC
                LIMIT ?
                """,
                (min_date, max_date, limit),
            )
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows if row is not None]

    async def list_club_members(self, limit: int = 30) -> list[UserRecord]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM users
                WHERE current_status IN ('active', 'grace_period')
                   OR is_lifetime_free = 1
                ORDER BY is_lifetime_free DESC, access_end_at ASC, payment_confirmed_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows if row is not None]

    async def list_bot_activated_users(self, limit: int = 30) -> list[UserRecord]:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM users ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows if row is not None]

    async def list_special_members(self, limit: int = 30) -> list[UserRecord]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT * FROM users
                WHERE is_lifetime_free = 1
                   OR (
                        recurring_amount_label IS NOT NULL
                    AND recurring_amount_label != ''
                    AND recurring_amount_label != ?
                   )
                ORDER BY is_lifetime_free DESC, updated_at DESC
                LIMIT ?
                """,
                (DEFAULT_AMOUNT_LABEL, limit),
            )
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows if row is not None]

    async def get_users_for_reminder_five_days(self, target_date: str) -> list[UserRecord]:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE current_status = 'active' AND is_lifetime_free = 0 AND date(access_end_at) = date(?) AND reminder_5_sent_at IS NULL",
                (target_date,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows if row is not None]

    async def mark_reminder_five_days_sent(self, telegram_id: int) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET reminder_5_sent_at = ?, updated_at = ? WHERE telegram_id = ?",
                (now, now, telegram_id),
            )
            await db.commit()

    async def get_users_for_expiry_notice(self, target_date: str) -> list[UserRecord]:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE current_status = 'active' AND is_lifetime_free = 0 AND date(access_end_at) = date(?) AND expiry_notice_sent_at IS NULL",
                (target_date,),
            )
            rows = await cursor.fetchall()
            return [self._row_to_user(row) for row in rows if row is not None]

    async def move_to_grace_period(self, telegram_id: int) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET current_status = 'grace_period', expiry_notice_sent_at = ?, updated_at = ? WHERE telegram_id = ?",
                (now, now, telegram_id),
            )
            await db.commit()

    async def get_users_for_expiration(self, target_timestamp: str) -> list[UserRecord]:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT * FROM users WHERE current_status IN ('active', 'grace_period') AND is_lifetime_free = 0 AND grace_end_at IS NOT NULL"
            )
            rows = await cursor.fetchall()
            expired_users: list[UserRecord] = []
            for row in rows:
                user = self._row_to_user(row)
                if user and user.grace_end_at and user.grace_end_at <= target_timestamp:
                    expired_users.append(user)
            return expired_users

    async def expire_user(self, telegram_id: int) -> None:
        async with self.connect() as db:
            await db.execute(
                "UPDATE users SET current_status = 'expired', updated_at = ? WHERE telegram_id = ?",
                (self._now_iso(), telegram_id),
            )
            await db.commit()

    async def get_user_stats(self) -> dict[str, int]:
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT
                    COUNT(*) AS total_users,
                    SUM(CASE WHEN current_status = 'active' THEN 1 ELSE 0 END) AS active_users,
                    SUM(CASE WHEN is_lifetime_free = 1 THEN 1 ELSE 0 END) AS lifetime_free_users,
                    SUM(CASE WHEN current_status = 'trial_active' THEN 1 ELSE 0 END) AS trial_users,
                    SUM(CASE WHEN current_status = 'grace_period' THEN 1 ELSE 0 END) AS grace_users,
                    SUM(CASE WHEN current_status = 'waiting_confirmation' THEN 1 ELSE 0 END) AS waiting_confirmation_users,
                    SUM(CASE WHEN current_status = 'expired' THEN 1 ELSE 0 END) AS expired_users,
                    SUM(CASE WHEN current_status = 'rejected' THEN 1 ELSE 0 END) AS rejected_users
                FROM users
                """
            )
            row = await cursor.fetchone()
            if row is None:
                return {
                    "total_users": 0,
                    "active_users": 0,
                    "lifetime_free_users": 0,
                    "trial_users": 0,
                    "grace_users": 0,
                    "waiting_confirmation_users": 0,
                    "expired_users": 0,
                    "rejected_users": 0,
                }
            return {key: int(row[key] or 0) for key in row.keys()}

    async def list_all_user_ids(self) -> list[int]:
        async with self.connect() as db:
            cursor = await db.execute("SELECT telegram_id FROM users ORDER BY created_at ASC")
            rows = await cursor.fetchall()
            return [int(row["telegram_id"]) for row in rows]

    async def create_promo_code(
        self,
        code: str,
        promo_type: str,
        grant_days: int,
        max_uses: int | None,
        valid_until: str | None,
        created_by: int | None,
        comment: str | None = None,
    ) -> int:
        if promo_type not in PROMO_TYPES:
            raise ValueError("Unsupported promo type")
        normalized_code = code.strip().upper()
        now = self._now_iso()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                INSERT INTO promo_codes (code, promo_type, grant_days, max_uses, current_uses, is_active, valid_until, comment, created_at, created_by)
                VALUES (?, ?, ?, ?, 0, 1, ?, ?, ?, ?)
                """,
                (normalized_code, promo_type, grant_days, max_uses, valid_until, comment, now, created_by),
            )
            await db.commit()
            return cursor.lastrowid

    async def get_promo_code_by_code(self, code: str) -> PromoCodeRecord | None:
        normalized_code = code.strip().upper()
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM promo_codes WHERE code = ?", (normalized_code,))
            return self._row_to_promo(await cursor.fetchone())

    async def get_promo_code_by_id(self, promo_code_id: int) -> PromoCodeRecord | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM promo_codes WHERE id = ?", (promo_code_id,))
            return self._row_to_promo(await cursor.fetchone())

    async def has_user_used_promo(self, promo_code_id: int, telegram_id: int) -> bool:
        async with self.connect() as db:
            cursor = await db.execute(
                "SELECT 1 FROM promo_code_usages WHERE promo_code_id = ? AND telegram_id = ? LIMIT 1",
                (promo_code_id, telegram_id),
            )
            return await cursor.fetchone() is not None

    async def apply_promo_code(self, promo_code_id: int, telegram_id: int, access_start_at: str, access_end_at: str) -> None:
        now = self._now_iso()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO promo_code_usages (promo_code_id, telegram_id, used_at, access_start_at, access_end_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (promo_code_id, telegram_id, now, access_start_at, access_end_at),
            )
            await db.execute("UPDATE promo_codes SET current_uses = current_uses + 1 WHERE id = ?", (promo_code_id,))
            await db.commit()

    async def list_promo_codes(self, limit: int = 20) -> list[PromoCodeRecord]:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM promo_codes ORDER BY created_at DESC LIMIT ?", (limit,))
            rows = await cursor.fetchall()
            return [self._row_to_promo(row) for row in rows if row is not None]
