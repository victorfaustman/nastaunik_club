from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(slots=True)
class Settings:
    bot_token: str
    admin_ids: set[int]
    club_invite_link: str
    trial_club_invite_link: str
    owner_contact_url: str
    database_path: Path
    timezone: str
    club_chat_id: int | None
    trial_chat_id: int | None
    log_level: str
    welcome_image_path: Path | None
    welcome_image_url: str | None
    mini_app_url: str | None

    @property
    def owner_contact_handle(self) -> str:
        if self.owner_contact_url.startswith("https://t.me/"):
            return "@" + self.owner_contact_url.removeprefix("https://t.me/")
        return self.owner_contact_url


def _parse_admin_ids(raw_value: str) -> set[int]:
    values = {item.strip() for item in raw_value.split(",") if item.strip()}
    return {int(item) for item in values}


def load_settings() -> Settings:
    load_dotenv()

    bot_token = os.getenv("BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("BOT_TOKEN is required")

    admin_ids_raw = os.getenv("ADMIN_IDS", "").strip()
    if not admin_ids_raw:
        raise ValueError("ADMIN_IDS is required")

    club_invite_link = os.getenv("CLUB_INVITE_LINK", "").strip()
    if not club_invite_link:
        raise ValueError("CLUB_INVITE_LINK is required")

    trial_club_invite_link = os.getenv("TRIAL_CLUB_INVITE_LINK", "").strip() or club_invite_link
    owner_contact_url = os.getenv("OWNER_CONTACT_URL", "https://t.me/kopytov_v_a").strip()
    database_path = Path(os.getenv("DATABASE_PATH", "bot.db")).expanduser().resolve()
    timezone = os.getenv("TIMEZONE", "Europe/Minsk").strip()
    club_chat_id_raw = os.getenv("CLUB_CHAT_ID", "").strip()
    club_chat_id = int(club_chat_id_raw) if club_chat_id_raw else None
    trial_chat_id_raw = os.getenv("TRIAL_CHAT_ID", "").strip()
    trial_chat_id = int(trial_chat_id_raw) if trial_chat_id_raw else None
    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()

    welcome_image_path_raw = os.getenv("WELCOME_IMAGE_PATH", "").strip()
    welcome_image_path = Path(welcome_image_path_raw).expanduser().resolve() if welcome_image_path_raw else None
    welcome_image_url = os.getenv("WELCOME_IMAGE_URL", "").strip() or None
    mini_app_url = os.getenv("MINI_APP_URL", "").strip() or None

    return Settings(
        bot_token=bot_token,
        admin_ids=_parse_admin_ids(admin_ids_raw),
        club_invite_link=club_invite_link,
        trial_club_invite_link=trial_club_invite_link,
        owner_contact_url=owner_contact_url,
        database_path=database_path,
        timezone=timezone,
        club_chat_id=club_chat_id,
        trial_chat_id=trial_chat_id,
        log_level=log_level,
        welcome_image_path=welcome_image_path,
        welcome_image_url=welcome_image_url,
        mini_app_url=mini_app_url,
    )
