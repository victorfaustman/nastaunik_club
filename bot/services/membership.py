from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from bot.database import TRIAL_DAYS, UserRecord


PROMO_FIRST_MONTH_DAYS = 30


@dataclass(slots=True)
class AccessPeriod:
    access_start_at: str
    access_end_at: str
    grace_end_at: str


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


def _calculate_period(base_start: datetime, original_start: datetime | None = None, days: int = 30) -> AccessPeriod:
    end = base_start + timedelta(days=days)
    grace_end = end + timedelta(days=5)
    return AccessPeriod(
        access_start_at=(original_start or base_start).isoformat(timespec="seconds"),
        access_end_at=end.isoformat(timespec="seconds"),
        grace_end_at=grace_end.isoformat(timespec="seconds"),
    )


def calculate_period_for_payment(user: UserRecord | None, now: datetime | None = None) -> AccessPeriod:
    current_time = now or datetime.utcnow()
    existing_end = parse_iso(user.access_end_at) if user else None
    if existing_end and existing_end >= current_time and user and user.current_status == "active":
        return _calculate_period(existing_end, parse_iso(user.access_start_at) if user.access_start_at else existing_end, 30)
    return _calculate_period(current_time, current_time, 30)


def calculate_manual_extension(user: UserRecord | None, now: datetime | None = None) -> AccessPeriod:
    current_time = now or datetime.utcnow()
    existing_end = parse_iso(user.access_end_at) if user else None
    start = existing_end if existing_end and existing_end >= current_time else current_time
    original_start = parse_iso(user.access_start_at) if user and user.access_start_at else start
    return _calculate_period(start, original_start, 30)


def calculate_period_for_promo(user: UserRecord | None, grant_days: int = PROMO_FIRST_MONTH_DAYS, now: datetime | None = None) -> AccessPeriod:
    current_time = now or datetime.utcnow()
    existing_end = parse_iso(user.access_end_at) if user else None
    if existing_end and existing_end >= current_time and user and user.current_status in {"active", "grace_period"}:
        original_start = parse_iso(user.access_start_at) if user.access_start_at else existing_end
        return _calculate_period(existing_end, original_start, grant_days)
    return _calculate_period(current_time, current_time, grant_days)


def calculate_trial_period(now: datetime | None = None) -> tuple[str, str]:
    current_time = now or datetime.utcnow()
    end = current_time + timedelta(days=TRIAL_DAYS)
    return (
        current_time.isoformat(timespec="seconds"),
        end.isoformat(timespec="seconds"),
    )
