from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID, uuid5


def _resolve_workspace_root() -> Path:
    current = Path(__file__).resolve()
    candidates: list[Path] = []

    env_root = os.getenv("AI_TEACHER_CORE_ROOT", "").strip()
    if env_root:
        candidates.append(Path(env_root).expanduser())

    candidates.extend(
        [
            current.parent,
            *current.parents,
            Path.cwd(),
            Path("/opt/ai-teacher-core"),
        ]
    )

    seen: set[str] = set()
    for candidate in candidates:
        candidate_str = str(candidate)
        if candidate_str in seen:
            continue
        seen.add(candidate_str)
        if (candidate / "src" / "core").exists():
            return candidate
    # Local fallback for standalone module deployments where the repo root
    # is not a fixed number of levels above this file.
    return current.parents[2]


WORKSPACE_ROOT = _resolve_workspace_root()
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

CORE_SYNC_AVAILABLE = True

try:
    from src.core.application.events import EventWriter
    from src.core.application.users import UserResolveInput, UserResolver
    from src.core.domain.access.models import Membership
    from src.core.domain.catalog.events import CoreEventNames
    from src.core.domain.commerce.models import Order, Payment, Product
    from src.core.domain.events.models import DomainEvent
    from src.core.domain.identity.models import ModulePresence
    from src.core.infrastructure.repositories.sqlite_access_repositories import SQLiteMembershipRepository
    from src.core.infrastructure.repositories.sqlite_commerce_repositories import (
        SQLiteOrderRepository,
        SQLitePaymentRepository,
        SQLiteProductRepository,
        parse_amount_label,
    )
    from src.core.infrastructure.repositories.sqlite_event_repository import SQLiteEventRepository
    from src.core.infrastructure.repositories.sqlite_presence_repository import SQLiteModulePresenceRepository
    from src.core.infrastructure.repositories.sqlite_user_repositories import (
        SQLiteUserIdentityRepository,
        SQLiteUserRepository,
    )
except Exception:
    CORE_SYNC_AVAILABLE = False


logger = logging.getLogger(__name__)
CORE_REGISTRY_DB_PATH = WORKSPACE_ROOT / "data" / "core_registry.db"
CORE_NAMESPACE = UUID("2d46f6f5-7bc3-4699-833a-c1c791e40254")
CLUB_PRODUCT_ID = uuid5(CORE_NAMESPACE, "product:club-bot:nastaunik-club")


def resolve_club_user(
    telegram_user_id: int,
    username: str | None,
    full_name: str | None,
    *,
    seen_at: datetime | None = None,
) -> UUID:
    if not CORE_SYNC_AVAILABLE:
        fallback_user_id = uuid5(CORE_NAMESPACE, f"user:club-bot:{telegram_user_id}")
        logger.warning(
            "Core registry sync disabled; using fallback user id for telegram_user_id=%s",
            telegram_user_id,
        )
        return fallback_user_id

    user_repository = SQLiteUserRepository(CORE_REGISTRY_DB_PATH)
    identity_repository = SQLiteUserIdentityRepository(CORE_REGISTRY_DB_PATH)
    resolver = UserResolver(user_repository, identity_repository)

    result = resolver.resolve(
        UserResolveInput(
            source_module="club-bot",
            source_first_touch="club",
            telegram_user_id=telegram_user_id,
            telegram_username=username,
            full_name=full_name,
            seen_at=seen_at or datetime.utcnow(),
        )
    )
    logger.info(
        "Resolved club user into core registry: action=%s user_id=%s telegram_user_id=%s",
        result.action,
        result.user.user_id,
        telegram_user_id,
    )
    _record_module_presence(
        user_id=result.user.user_id,
        seen_at=seen_at or datetime.utcnow(),
        current_status="known",
        source_first_touch=(result.user.source_first_touch == "club"),
    )
    return result.user.user_id


def sync_club_membership(user) -> None:
    if user is None or not CORE_SYNC_AVAILABLE:
        return

    canonical_user_id = resolve_club_user(
        user.telegram_id,
        user.username,
        user.full_name,
        seen_at=_parse_iso(user.updated_at or user.created_at) or datetime.utcnow(),
    )
    repository = SQLiteMembershipRepository(CORE_REGISTRY_DB_PATH)
    event_writer = EventWriter(SQLiteEventRepository(CORE_REGISTRY_DB_PATH))

    started_at = _parse_iso(user.access_start_at or user.trial_started_at)
    expires_at = _parse_iso(user.access_end_at or user.trial_ends_at)
    grace_ends_at = _parse_iso(user.grace_end_at)
    cancelled_at = _build_cancelled_at(user.current_status, expires_at)
    access_level = _resolve_access_level(user)
    now = datetime.utcnow()

    membership = Membership(
        membership_id=uuid5(CORE_NAMESPACE, f"membership:club-bot:{user.telegram_id}"),
        user_id=canonical_user_id,
        product_id=CLUB_PRODUCT_ID,
        membership_status=user.current_status,
        access_level=access_level,
        started_at=started_at,
        expires_at=expires_at,
        grace_ends_at=grace_ends_at,
        cancelled_at=cancelled_at,
        created_at=started_at or now,
        updated_at=now,
    )
    repository.upsert(membership)
    logger.info(
        "Synced club membership into core registry: user_id=%s status=%s access_level=%s",
        canonical_user_id,
        membership.membership_status,
        membership.access_level,
    )
    event_writer.write(
        DomainEvent(
            event_name=_membership_event_name(user.current_status),
            source_module="club-bot",
            event_time=now,
            user_id=canonical_user_id,
            object_type="membership",
            object_id=str(membership.membership_id),
            properties={
                "telegram_user_id": user.telegram_id,
                "status": membership.membership_status,
                "access_level": membership.access_level,
                "expires_at": membership.expires_at.isoformat() if membership.expires_at else None,
                "grace_ends_at": membership.grace_ends_at.isoformat() if membership.grace_ends_at else None,
            },
        )
    )


def sync_club_payment(payment, user) -> None:
    if payment is None or user is None or not CORE_SYNC_AVAILABLE:
        return

    now = datetime.utcnow()
    canonical_user_id = resolve_club_user(
        user.telegram_id,
        user.username,
        user.full_name,
        seen_at=_parse_iso(user.updated_at or user.created_at) or datetime.utcnow(),
    )
    product_repository = SQLiteProductRepository(CORE_REGISTRY_DB_PATH)
    order_repository = SQLiteOrderRepository(CORE_REGISTRY_DB_PATH)
    payment_repository = SQLitePaymentRepository(CORE_REGISTRY_DB_PATH)
    event_writer = EventWriter(SQLiteEventRepository(CORE_REGISTRY_DB_PATH))

    product_repository.upsert(
        Product(
            product_id=CLUB_PRODUCT_ID,
            product_type="membership",
            product_name="Nastaunik Club",
            product_status="active",
            owner_module="club-bot",
            created_at=now,
            updated_at=now,
        )
    )

    order = Order(
        order_id=uuid5(CORE_NAMESPACE, f"order:club-bot:{payment.id}"),
        user_id=canonical_user_id,
        product_id=CLUB_PRODUCT_ID,
        offer_id=None,
        promo_code_id=None,
        order_status=_resolve_order_status(payment.status),
        source_channel="telegram",
        source_module="club-bot",
        created_at=_parse_iso(payment.created_at) or now,
        paid_at=_parse_iso(payment.confirmed_at),
        cancelled_at=_parse_iso(payment.rejected_at),
    )
    payment_record = Payment(
        payment_id=uuid5(CORE_NAMESPACE, f"payment:club-bot:{payment.id}"),
        order_id=order.order_id,
        user_id=canonical_user_id,
        amount=parse_amount_label(payment.amount_label) or Decimal("0"),
        currency="BYN",
        payment_provider="manual_receipt",
        payment_status=_resolve_payment_status(payment.status),
        created_at=_parse_iso(payment.created_at) or now,
        external_payment_id=str(payment.id),
        paid_at=_parse_iso(payment.confirmed_at),
        refunded_at=_parse_iso(payment.rejected_at) if payment.status == "rejected" else None,
        updated_at=now,
    )

    order_repository.upsert(order)
    payment_repository.upsert(payment_record)
    event_writer.write(
        DomainEvent(
            event_name=_payment_event_name(payment.status),
            source_module="club-bot",
            event_time=now,
            user_id=canonical_user_id,
            object_type="payment",
            object_id=str(payment_record.payment_id),
            properties={
                "telegram_user_id": user.telegram_id,
                "local_payment_id": payment.id,
                "payment_status": payment.status,
                "amount_label": payment.amount_label,
                "amount_numeric": str(payment_record.amount),
                "currency": payment_record.currency,
            },
        )
    )


def _parse_iso(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _build_cancelled_at(status: str, fallback: datetime | None) -> datetime | None:
    if status in {"expired", "rejected"}:
        return fallback or datetime.utcnow()
    return None


def _resolve_access_level(user) -> str | None:
    if user.is_lifetime_free:
        return "lifetime"
    if user.current_status == "trial_active":
        return "trial"
    if user.current_status in {"active", "grace_period"}:
        return "member"
    return None


def _membership_event_name(status: str) -> str:
    if status == "active":
        return CoreEventNames.CLUB_MEMBERSHIP_STARTED
    return CoreEventNames.CLUB_MEMBERSHIP_UPDATED


def _resolve_order_status(status: str) -> str:
    return {
        "pending": "pending",
        "approved": "paid",
        "rejected": "cancelled",
    }.get(status, "pending")


def _resolve_payment_status(status: str) -> str:
    return {
        "pending": "pending",
        "approved": "succeeded",
        "rejected": "failed",
    }.get(status, "pending")


def _payment_event_name(status: str) -> str:
    return {
        "pending": CoreEventNames.PAYMENT_CREATED,
        "approved": CoreEventNames.PAYMENT_SUCCEEDED,
        "rejected": CoreEventNames.PAYMENT_FAILED,
    }.get(status, CoreEventNames.PAYMENT_CREATED)


def _record_module_presence(
    *,
    user_id: UUID,
    seen_at: datetime,
    current_status: str | None,
    source_first_touch: bool,
) -> None:
    repository = SQLiteModulePresenceRepository(CORE_REGISTRY_DB_PATH)
    existing = repository.get_by_user_and_module(user_id, "club-bot")
    repository.upsert(
        ModulePresence(
            presence_id=existing.presence_id if existing else uuid5(CORE_NAMESPACE, f"presence:club-bot:{user_id}"),
            user_id=user_id,
            module_key="club-bot",
            first_seen_at=existing.first_seen_at if existing else seen_at,
            last_seen_at=seen_at,
            last_activity_at=seen_at,
            source_first_touch=source_first_touch or (existing.source_first_touch if existing else False),
            current_status=current_status or (existing.current_status if existing else None),
            created_at=existing.created_at if existing else seen_at,
            updated_at=seen_at,
        )
    )
