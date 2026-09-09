from __future__ import annotations

import asyncio
import base64
import csv
import html
import io
import os
import re
import sqlite3
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import aiosqlite
from aiohttp import ClientSession, ClientTimeout
from aiohttp import web
from dotenv import load_dotenv

from bot.database import Database
from bot.learning_admin_v2 import LearningAdmin
from bot.mini_app import MiniApp

DEFAULT_AMOUNT_LABEL = "10 BYN / месяц"
ADMIN_UPLOAD_LIMIT_BYTES = 500 * 1024 * 1024
AMOUNT_RE = re.compile(r"(\d+(?:[.,]\d+)?)")
MONTH_NAMES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}
AUDIENCE_LABELS = {
    "regular": "Всем, кроме особенных",
    "special": "Только особенным",
    "free": "Только бесплатным",
    "expired": "Истекшим",
    "all": "Всем",
}
BROADCAST_STATUS_FILTERS = {
    "any": "Любой статус",
    "in_club": "Состоит в клубе",
    "not_in_club": "Активировал бот, но не состоит в клубе",
    "waiting_confirmation": "Чек на проверке",
    "expired": "Истекшие",
    "expiring_7": "Скоро истекают за 7 дней",
}
BROADCAST_TYPE_FILTERS = {
    "any": "Любой тип",
    "regular": "Обычные",
    "special_any": "Все особенные",
    "special_rate": "Особый тариф",
    "free": "Вечно бесплатные",
}
CLIENT_STATUS_FILTERS = {
    "any": "Все статусы",
    "in_club": "Состоит в клубе",
    "not_in_club": "Активировал бот, но не состоит",
    "waiting_payment": "Ждет чек",
    "waiting_confirmation": "Чек на проверке",
    "expired": "Истекшие",
    "expiring": "Скоро истекают",
    "rejected": "Отклоненные",
}
SMART_SEGMENTS = {
    "all": ("Все клиенты", "any", "any", ""),
    "needs_payment": ("Не оплатили", "not_in_club", "regular", ""),
    "pending_checks": ("Чеки на проверке", "waiting_confirmation", "any", ""),
    "special_outside": ("Особые не в клубе", "not_in_club", "special_any", ""),
    "expired_recent": ("Истекшие", "expired", "any", ""),
    "expiring_7": ("Истекают за 7 дней", "expiring", "any", "7"),
    "free": ("Вечно бесплатные", "any", "free", ""),
}
DEFAULT_BROADCAST_TEMPLATES = [
    ("Напоминание об оплате", "Добрый день! Напоминаю, что доступ к клубу скоро заканчивается. Если хотите продолжить участие, пришлите, пожалуйста, чек об оплате в бот."),
    ("Возврат в клуб", "Добрый день! Доступ к клубу снова активен. Нажмите кнопку входа в боте, чтобы вернуться в клуб."),
    ("Новость клуба", "Добрый день! В клубе появилось важное обновление. Загляните, пожалуйста, в чат клуба."),
]
STATUS_LABELS = {
    "new": "Новый",
    "waiting_payment": "Ждет чек",
    "waiting_confirmation": "Чек на проверке",
    "active": "В клубе",
    "trial_active": "Пробный доступ",
    "grace_period": "В клубе",
    "expired": "Истек",
    "rejected": "Отклонен",
}


@dataclass(slots=True)
class WebSettings:
    host: str
    port: int
    database_path: Path
    username: str
    password: str
    base_path: str
    excluded_ids: set[int]
    bot_token: str
    club_invite_link: str
    club_chat_id: str
    public_channel_id: str
    public_channel_member_count: int | None
    public_channel_live_count: bool
    mini_app_allowed_ids: set[int] = field(default_factory=set)
    mini_app_test_mode_ids: set[int] = field(default_factory=set)


def parse_ids(value: str) -> set[int]:
    ids: set[int] = set()
    for item in value.replace(";", ",").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError:
            continue
    return ids


def load_web_settings() -> WebSettings:
    load_dotenv()
    public_channel_member_count_raw = os.getenv("PUBLIC_CHANNEL_MEMBER_COUNT", "").strip()
    try:
        public_channel_member_count = int(public_channel_member_count_raw) if public_channel_member_count_raw else None
    except ValueError:
        public_channel_member_count = None
    return WebSettings(
        host=os.getenv("CLUB_ADMIN_HOST", "0.0.0.0").strip(),
        port=int(os.getenv("CLUB_ADMIN_PORT", "8091").strip()),
        database_path=Path(os.getenv("DATABASE_PATH", "bot.db")).expanduser().resolve(),
        username=os.getenv("CLUB_ADMIN_USERNAME", "admin").strip(),
        password=os.getenv("CLUB_ADMIN_PASSWORD", "").strip(),
        base_path=os.getenv("CLUB_ADMIN_BASE_PATH", "").strip().rstrip("/"),
        excluded_ids=parse_ids(
            ",".join(
                [
                    os.getenv("ADMIN_IDS", ""),
                    os.getenv("CLUB_ADMIN_EXCLUDED_IDS", ""),
                ]
            )
        ),
        bot_token=os.getenv("BOT_TOKEN", "").strip(),
        club_invite_link=os.getenv("CLUB_INVITE_LINK", "").strip(),
        club_chat_id=os.getenv("CLUB_CHAT_ID", "").strip(),
        public_channel_id=(
            os.getenv("PUBLIC_CHANNEL_ID")
            or os.getenv("PUBLIC_TELEGRAM_CHANNEL_ID")
            or os.getenv("TELEGRAM_CHANNEL_ID")
            or ""
        ).strip(),
        public_channel_member_count=public_channel_member_count,
        public_channel_live_count=os.getenv("PUBLIC_CHANNEL_LIVE_COUNT", "").strip().lower() in {"1", "true", "yes"},
        mini_app_allowed_ids=parse_ids(os.getenv("MINI_APP_ALLOWED_IDS", "")) or parse_ids(os.getenv("ADMIN_IDS", "")),
        mini_app_test_mode_ids=parse_ids(os.getenv("ADMIN_IDS", "")),
    )


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def format_date(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y")
    except ValueError:
        return value[:10]


def format_dt(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return value


def parse_amount(value: str | None) -> float:
    if not value:
        return 0.0
    match = AMOUNT_RE.search(value)
    if not match:
        return 0.0
    return float(match.group(1).replace(",", "."))


def format_money(value: float) -> str:
    if value == int(value):
        return f"{int(value)} BYN"
    return f"{value:.2f} BYN".replace(".", ",")


def current_month_key() -> str:
    return datetime.utcnow().strftime("%Y-%m")


def month_label(month_key: str) -> str:
    try:
        value = datetime.strptime(month_key, "%Y-%m")
    except ValueError:
        return month_key
    return f"{MONTH_NAMES[value.month]} {value.year}"


def special_label(row: sqlite3.Row) -> str:
    labels: list[str] = []
    if int(row["is_lifetime_free"] or 0):
        labels.append("вечный бесплатный")
    recurring = row["recurring_amount_label"]
    if recurring and recurring != DEFAULT_AMOUNT_LABEL:
        labels.append(str(recurring))
    return ", ".join(labels)


def is_in_club(row: sqlite3.Row) -> bool:
    return row["current_status"] in {"active", "grace_period"} or bool(row["is_lifetime_free"])


class ClubAdminWebApp:
    def __init__(self, settings: WebSettings):
        self.settings = settings
        self._admin_tables_ready = False
        self._admin_tables_lock = asyncio.Lock()
        self._public_channel_count_cache: tuple[datetime, int | None] | None = None
        self._public_channel_funnel_cache: tuple[datetime, dict[str, int] | None] | None = None
        self.learning_admin = LearningAdmin(settings.database_path, self.url)
        def public_learning_url(path: str = "/", **query: object) -> str:
            if path.endswith("/action"):
                target = "/learning-action"
            elif path.endswith("/learning"):
                target = "/"
            else:
                target = "/"
            if query:
                target = f"{target}?{urlencode(query)}"
            return target
        self.public_learning_admin = LearningAdmin(settings.database_path, public_learning_url)
        self.mini_app = MiniApp(
            Database(settings.database_path),
            settings.bot_token,
            settings.mini_app_allowed_ids,
            settings.mini_app_test_mode_ids,
        )

    def build_app(self) -> web.Application:
        app = web.Application(
            middlewares=[self.auth_middleware],
            client_max_size=ADMIN_UPLOAD_LIMIT_BYTES,
        )
        app.router.add_get("/", self.dashboard)
        app.router.add_get("/clients", self.clients)
        app.router.add_get("/finance", self.finance_page)
        app.router.add_get("/broadcasts", self.broadcasts_page)
        app.router.add_post("/broadcast/template", self.save_broadcast_template)
        app.router.add_post("/broadcast/test", self.broadcast_test)
        app.router.add_post("/broadcast/preview", self.broadcast_preview)
        app.router.add_post("/broadcast", self.broadcast)
        app.router.add_get("/finance/export.csv", self.export_finance_csv)
        app.router.add_get("/user/{telegram_id}", self.user_detail)
        app.router.add_post("/user/{telegram_id}/message/preview", self.personal_message_preview)
        app.router.add_post("/user/{telegram_id}/message", self.personal_message)
        app.router.add_post("/user/{telegram_id}/manual-payment", self.manual_payment)
        app.router.add_post("/user/{telegram_id}/restore-access", self.restore_access)
        app.router.add_post("/payment/{payment_id}/approve", self.approve_payment)
        app.router.add_post("/payment/{payment_id}/reject", self.reject_payment)
        app.router.add_get("/health", self.health)
        app.router.add_get("/learning", self.learning_admin.page)
        app.router.add_post("/learning/action", self.learning_admin.action)
        app.router.add_post("/learning/material/action", self.learning_admin.action)
        app.router.add_get("/public-learning", self.public_learning_admin.page)
        app.router.add_post("/public-learning/action", self.public_learning_admin.action)
        app.cleanup_ctx.append(self.learning_admin.video_worker_context)
        self.mini_app.register(app)
        return app

    def url(self, path: str = "/", **query: object) -> str:
        if not path.startswith("/"):
            path = "/" + path
        target = f"{self.settings.base_path}{path}"
        if query:
            target = f"{target}?{urlencode(query)}"
        return target

    @web.middleware
    async def auth_middleware(self, request: web.Request, handler):
        if request.path == "/health" or (
            request.path.startswith("/mini-app/") and request.path != "/mini-app/preview"
        ):
            return await handler(request)
        if not self.settings.password:
            return web.Response(text="CLUB_ADMIN_PASSWORD is not configured", status=503)
        expected = f"{self.settings.username}:{self.settings.password}"
        expected_token = "Basic " + base64.b64encode(expected.encode("utf-8")).decode("ascii")
        if request.headers.get("Authorization") != expected_token:
            return web.Response(
                text="Authentication required",
                status=401,
                headers={"WWW-Authenticate": 'Basic realm="Nastaunik Club Admin"'},
            )
        return await handler(request)

    @asynccontextmanager
    async def connect(self):
        connection = await aiosqlite.connect(self.settings.database_path, timeout=8)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        finally:
            await connection.close()

    async def health(self, request: web.Request) -> web.Response:
        return web.json_response({"ok": True})

    async def ensure_admin_tables(self) -> None:
        if self._admin_tables_ready:
            return
        async with self._admin_tables_lock:
            if self._admin_tables_ready:
                return
            async with self.connect() as db:
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS broadcast_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        audience TEXT NOT NULL,
                        message TEXT NOT NULL,
                        recipients_count INTEGER NOT NULL DEFAULT 0,
                        sent_count INTEGER NOT NULL DEFAULT 0,
                        failed_count INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS action_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        telegram_id INTEGER,
                        action_type TEXT NOT NULL,
                        title TEXT NOT NULL,
                        details TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                await db.execute(
                    """
                    CREATE TABLE IF NOT EXISTS broadcast_templates (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        message TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                cursor = await db.execute("SELECT COUNT(*) AS total FROM broadcast_templates")
                row = await cursor.fetchone()
                if int(row["total"] or 0) == 0:
                    now = datetime.utcnow().isoformat(timespec="seconds")
                    await db.executemany(
                        "INSERT INTO broadcast_templates (title, message, created_at, updated_at) VALUES (?, ?, ?, ?)",
                        [(title, message, now, now) for title, message in DEFAULT_BROADCAST_TEMPLATES],
                    )
                await db.commit()
            self._admin_tables_ready = True

    async def dashboard(self, request: web.Request) -> web.Response:
        await self.ensure_admin_tables()
        legacy_view = request.query.get("view")
        if legacy_view:
            if legacy_view == "finance":
                raise web.HTTPSeeOther(location=self.url("/finance", month=request.query.get("month", current_month_key())))
            if legacy_view in {"members", "activated", "special", "waiting", "expiring", "expired"}:
                status_map = {
                    "members": "in_club",
                    "activated": "any",
                    "waiting": "waiting_confirmation",
                    "expiring": "expiring",
                    "expired": "expired",
                }
                type_map = {"special": "special_any"}
                raise web.HTTPSeeOther(
                    location=self.url(
                        "/clients",
                        q=request.query.get("q", ""),
                        status_filter=status_map.get(legacy_view, "any"),
                        type_filter=type_map.get(legacy_view, "any"),
                        days=request.query.get("days", "7"),
                    )
                )

        stats = await self.load_stats()
        finances = await self.load_finances(selected_month=current_month_key())
        funnel = await self.load_funnel_stats()
        finance_series = await self.load_finance_series(months=6)
        reminders = await self.load_reminder_overview()
        pending_payments = await self.load_pending_payments(limit=6)
        expiring_users = await self.load_users(view="expiring", query="", expiring_days=7)
        broadcast_logs = await self.load_broadcast_logs(limit=5)
        recent_activity = await self.load_recent_activity(limit=8)
        body = self.render_home_dashboard(
            stats=stats,
            finances=finances,
            funnel=funnel,
            finance_series=finance_series,
            reminders=reminders,
            pending_payments=pending_payments,
            expiring_rows=expiring_users[:6],
            expiring_count=len(expiring_users),
            broadcast_logs=broadcast_logs,
            recent_activity=recent_activity,
        )
        return web.Response(text=body, content_type="text/html")

    async def clients(self, request: web.Request) -> web.Response:
        await self.ensure_admin_tables()
        query = request.query.get("q", "").strip()
        status_filter = request.query.get("status_filter", "any").strip() or "any"
        type_filter = request.query.get("type_filter", "any").strip() or "any"
        try:
            expiring_days = int(request.query.get("days", "7"))
        except ValueError:
            expiring_days = 7
        if expiring_days not in {1, 3, 5, 7, 14, 30}:
            expiring_days = 7
        rows = await self.load_users(
            view="activated",
            query=query,
            expiring_days=expiring_days,
            status_filter=status_filter,
            type_filter=type_filter,
        )
        stats = await self.load_stats()
        body = self.render_clients_page(
            rows=rows,
            stats=stats,
            query=query,
            status_filter=status_filter,
            type_filter=type_filter,
            expiring_days=expiring_days,
        )
        return web.Response(text=body, content_type="text/html")

    async def finance_page(self, request: web.Request) -> web.Response:
        await self.ensure_admin_tables()
        mode = request.query.get("mode", "month").strip() or "month"
        year = request.query.get("year", "").strip()
        month = request.query.get("month", current_month_key()).strip() or current_month_key()
        date_from = request.query.get("from", "").strip()
        date_to = request.query.get("to", "").strip()
        selected_month, period_start, period_end = self.resolve_finance_period(
            mode=mode,
            year=year,
            month=month,
            date_from=date_from,
            date_to=date_to,
        )
        finances = await self.load_finances(
            selected_month=selected_month,
            period_start=period_start,
            period_end=period_end,
        )
        pending_payments = await self.load_pending_payments(limit=80)
        finance_series = await self.load_finance_series(months=6)
        body = self.render_finance_page(
            finances=finances,
            finance_series=finance_series,
            pending_payments=pending_payments,
            mode=mode,
            year=year,
            selected_month=selected_month,
            date_from=date_from,
            date_to=date_to,
            payment_done=request.query.get("payment_done"),
        )
        return web.Response(text=body, content_type="text/html")

    async def broadcasts_page(self, request: web.Request) -> web.Response:
        await self.ensure_admin_tables()
        broadcast_logs: list[sqlite3.Row] = []
        templates = await self.load_broadcast_templates()
        body = self.render_broadcasts_page(
            broadcast_logs=broadcast_logs,
            templates=templates,
            broadcast_sent=request.query.get("broadcast_sent"),
            broadcast_failed=request.query.get("broadcast_failed"),
            test_sent=request.query.get("test_sent"),
            test_failed=request.query.get("test_failed"),
            template_saved=request.query.get("template_saved"),
        )
        return web.Response(text=body, content_type="text/html")

    async def save_broadcast_template(self, request: web.Request) -> web.Response:
        await self.ensure_admin_tables()
        form = await request.post()
        title = str(form.get("title") or "").strip()
        message = str(form.get("message") or "").strip()
        if not title or not message:
            raise web.HTTPBadRequest(text="Нужно указать название и текст шаблона")
        now = datetime.utcnow().isoformat(timespec="seconds")
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO broadcast_templates (title, message, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (title[:120], message[:4096], now, now),
            )
            await db.commit()
        raise web.HTTPSeeOther(location=self.url("/broadcasts", template_saved=1))

    async def broadcast_test(self, request: web.Request) -> web.Response:
        if not self.settings.bot_token:
            raise web.HTTPServiceUnavailable(text="BOT_TOKEN is not configured")
        form = await request.post()
        message = str(form.get("message") or "").strip()
        self.validate_personal_message(message)
        admin_ids = sorted(self.settings.excluded_ids)
        if not admin_ids:
            raise web.HTTPBadRequest(text="Не настроен ADMIN_IDS для тестовой отправки")
        sent = 0
        failed = 0
        api_url = f"https://api.telegram.org/bot{self.settings.bot_token}/sendMessage"
        async with ClientSession() as session:
            for telegram_id in admin_ids:
                try:
                    async with session.post(
                        api_url,
                        json={"chat_id": telegram_id, "text": message, "disable_web_page_preview": True},
                        timeout=15,
                    ) as response:
                        if response.status == 200:
                            sent += 1
                        else:
                            failed += 1
                except Exception:
                    failed += 1
        await self.log_action(
            telegram_id=None,
            action_type="broadcast_test",
            title="Тестовая рассылка отправлена админу",
            details=f"Отправлено {sent}, ошибок {failed}: {message[:200]}",
        )
        raise web.HTTPSeeOther(location=self.url("/broadcasts", test_sent=sent, test_failed=failed))

    async def broadcast_preview(self, request: web.Request) -> web.Response:
        form = await request.post()
        status_filter = str(form.get("status_filter") or "any").strip()
        type_filter = str(form.get("type_filter") or "any").strip()
        message = str(form.get("message") or "").strip()
        self.validate_broadcast_payload(status_filter, type_filter, message)
        recipients = await self.load_broadcast_recipients(status_filter=status_filter, type_filter=type_filter)
        return web.Response(
            text=self.render_broadcast_preview(
                status_filter=status_filter,
                type_filter=type_filter,
                message=message,
                recipients_count=len(recipients),
            ),
            content_type="text/html",
        )

    async def broadcast(self, request: web.Request) -> web.Response:
        if not self.settings.bot_token:
            raise web.HTTPServiceUnavailable(text="BOT_TOKEN is not configured")

        form = await request.post()
        status_filter = str(form.get("status_filter") or "any").strip()
        type_filter = str(form.get("type_filter") or "any").strip()
        message = str(form.get("message") or "").strip()
        self.validate_broadcast_payload(status_filter, type_filter, message)
        if str(form.get("confirm") or "") != "1":
            return web.Response(
                text=self.render_broadcast_preview(
                    status_filter=status_filter,
                    type_filter=type_filter,
                    message=message,
                    recipients_count=len(
                        await self.load_broadcast_recipients(status_filter=status_filter, type_filter=type_filter)
                    ),
                ),
                content_type="text/html",
            )

        recipients = await self.load_broadcast_recipients(status_filter=status_filter, type_filter=type_filter)
        sent = 0
        failed = 0
        sent_recipients: list[int] = []
        api_url = f"https://api.telegram.org/bot{self.settings.bot_token}/sendMessage"
        async with ClientSession() as session:
            for telegram_id in recipients:
                try:
                    async with session.post(
                        api_url,
                        json={
                            "chat_id": telegram_id,
                            "text": message,
                            "disable_web_page_preview": True,
                        },
                        timeout=15,
                    ) as response:
                        if response.status == 200:
                            sent += 1
                            sent_recipients.append(telegram_id)
                        else:
                            failed += 1
                except Exception:
                    failed += 1
                await asyncio.sleep(0.04)

        audience = self.broadcast_filter_label(status_filter, type_filter)
        await self.log_broadcast(
            audience=audience,
            message=message,
            recipients_count=len(recipients),
            sent_count=sent,
            failed_count=failed,
        )
        for telegram_id in sent_recipients:
            await self.log_action(
                telegram_id=telegram_id,
                action_type="broadcast_received",
                title="Получена рассылка",
                details=f"{audience}: {message[:200]}",
            )
        raise web.HTTPSeeOther(location=self.url("/broadcasts", broadcast_sent=sent, broadcast_failed=failed))

    async def export_finance_csv(self, request: web.Request) -> web.Response:
        mode = request.query.get("mode", "month").strip() or "month"
        year = request.query.get("year", "").strip()
        month = request.query.get("month", current_month_key()).strip() or current_month_key()
        date_from = request.query.get("from", "").strip()
        date_to = request.query.get("to", "").strip()
        selected_month, period_start, period_end = self.resolve_finance_period(
            mode=mode,
            year=year,
            month=month,
            date_from=date_from,
            date_to=date_to,
        )
        finances = await self.load_finances(
            selected_month=selected_month,
            period_start=period_start,
            period_end=period_end,
        )
        payments = finances.get("selected_payments", [])
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["date", "telegram_id", "name", "username", "amount_label", "amount_byn", "comment"])
        if isinstance(payments, list):
            for payment in payments:
                writer.writerow(
                    [
                        payment["confirmed_at"],
                        payment["telegram_id"],
                        payment["full_name"],
                        payment["username"] or "",
                        payment["amount_label"],
                        parse_amount(payment["amount_label"]),
                        payment["admin_comment"] or "",
                    ]
                )
        safe_period = str(finances.get("period_key") or selected_month).replace("/", "-")
        filename = f"club-finance-{safe_period}.csv"
        return web.Response(
            body=output.getvalue().encode("utf-8-sig"),
            content_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    def resolve_finance_period(
        self,
        *,
        mode: str,
        year: str,
        month: str,
        date_from: str,
        date_to: str,
    ) -> tuple[str, datetime | None, datetime | None]:
        selected_month = month if re.fullmatch(r"\d{4}-\d{2}", month) else current_month_key()
        try:
            datetime.strptime(selected_month, "%Y-%m")
        except ValueError:
            selected_month = current_month_key()
        if mode == "year" and re.fullmatch(r"\d{4}", year):
            start = datetime(int(year), 1, 1)
            end = datetime(int(year) + 1, 1, 1)
            return selected_month, start, end
        if mode == "range":
            try:
                start = datetime.strptime(date_from, "%Y-%m-%d") if date_from else None
            except ValueError:
                start = None
            try:
                end = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1) if date_to else None
            except ValueError:
                end = None
            return selected_month, start, end
        start = datetime.strptime(selected_month, "%Y-%m").replace(day=1)
        end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        return selected_month, start, end

    def validate_broadcast_payload(self, status_filter: str, type_filter: str, message: str) -> None:
        if status_filter not in BROADCAST_STATUS_FILTERS:
            raise web.HTTPBadRequest(text="Неизвестный фильтр статуса")
        if type_filter not in BROADCAST_TYPE_FILTERS:
            raise web.HTTPBadRequest(text="Неизвестный фильтр типа участника")
        if not message:
            raise web.HTTPBadRequest(text="Нужно написать текст сообщения")
        if len(message) > 4096:
            raise web.HTTPBadRequest(text="Telegram не принимает сообщения длиннее 4096 символов")

    def broadcast_filter_label(self, status_filter: str, type_filter: str) -> str:
        return f"{BROADCAST_STATUS_FILTERS.get(status_filter, status_filter)}; {BROADCAST_TYPE_FILTERS.get(type_filter, type_filter)}"

    async def user_detail(self, request: web.Request) -> web.Response:
        telegram_id = int(request.match_info["telegram_id"])
        if telegram_id in self.settings.excluded_ids:
            raise web.HTTPNotFound(text="User not found")
        async with self.connect() as db:
            user_cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = await user_cursor.fetchone()
            payment_cursor = await db.execute(
                "SELECT * FROM payments WHERE telegram_id = ? ORDER BY created_at DESC LIMIT 30",
                (telegram_id,),
            )
            payments = await payment_cursor.fetchall()
        if user is None:
            raise web.HTTPNotFound(text="User not found")
        club_status = await self.get_club_member_status(telegram_id)
        action_logs = await self.load_action_logs(telegram_id)
        return web.Response(
            text=self.render_user_detail(
                user,
                payments,
                action_logs=action_logs,
                club_status=club_status,
                saved=request.query.get("saved") == "1",
                restore_sent=request.query.get("restore_sent"),
                restore_failed=request.query.get("restore_failed"),
                message_sent=request.query.get("message_sent"),
                message_failed=request.query.get("message_failed"),
            ),
            content_type="text/html",
        )

    async def get_club_member_status(self, telegram_id: int) -> str:
        if not self.settings.bot_token or not self.settings.club_chat_id:
            return "не настроено"
        api_url = f"https://api.telegram.org/bot{self.settings.bot_token}/getChatMember"
        try:
            async with ClientSession() as session:
                async with session.post(
                    api_url,
                    json={"chat_id": self.settings.club_chat_id, "user_id": telegram_id},
                    timeout=15,
                ) as response:
                    data = await response.json()
        except Exception:
            return "не удалось проверить"
        if not data.get("ok"):
            return "не удалось проверить"
        status = data.get("result", {}).get("status")
        return {
            "creator": "в клубе, владелец",
            "administrator": "в клубе, админ",
            "member": "в клубе",
            "restricted": "в клубе, ограничен",
            "left": "не в клубе",
            "kicked": "удален или заблокирован",
        }.get(status, str(status or "неизвестно"))

    async def personal_message_preview(self, request: web.Request) -> web.Response:
        telegram_id = int(request.match_info["telegram_id"])
        if telegram_id in self.settings.excluded_ids:
            raise web.HTTPNotFound(text="User not found")
        form = await request.post()
        message = str(form.get("message") or "").strip()
        self.validate_personal_message(message)
        user = await self.load_user(telegram_id)
        if user is None:
            raise web.HTTPNotFound(text="User not found")
        return web.Response(
            text=self.render_personal_message_preview(user=user, message=message),
            content_type="text/html",
        )

    async def personal_message(self, request: web.Request) -> web.Response:
        telegram_id = int(request.match_info["telegram_id"])
        if telegram_id in self.settings.excluded_ids:
            raise web.HTTPNotFound(text="User not found")
        if not self.settings.bot_token:
            raise web.HTTPServiceUnavailable(text="BOT_TOKEN is not configured")
        form = await request.post()
        message = str(form.get("message") or "").strip()
        self.validate_personal_message(message)
        if str(form.get("confirm") or "") != "1":
            user = await self.load_user(telegram_id)
            if user is None:
                raise web.HTTPNotFound(text="User not found")
            return web.Response(text=self.render_personal_message_preview(user=user, message=message), content_type="text/html")

        sent = 0
        failed = 0
        try:
            async with ClientSession() as session:
                async with session.post(
                    f"https://api.telegram.org/bot{self.settings.bot_token}/sendMessage",
                    json={
                        "chat_id": telegram_id,
                        "text": message,
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                ) as response:
                    if response.status == 200:
                        sent = 1
                    else:
                        failed = 1
        except Exception:
            failed = 1

        await self.log_action(
            telegram_id=telegram_id,
            action_type="personal_message",
            title="Отправлено личное сообщение",
            details=f"Отправлено: {sent}; ошибок: {failed}; {message[:200]}",
        )
        raise web.HTTPSeeOther(location=self.url(f"/user/{telegram_id}", message_sent=sent, message_failed=failed))

    def validate_personal_message(self, message: str) -> None:
        if not message:
            raise web.HTTPBadRequest(text="Нужно написать текст сообщения")
        if len(message) > 4096:
            raise web.HTTPBadRequest(text="Telegram не принимает сообщения длиннее 4096 символов")

    async def load_user(self, telegram_id: int) -> sqlite3.Row | None:
        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            return await cursor.fetchone()

    async def restore_access(self, request: web.Request) -> web.Response:
        telegram_id = int(request.match_info["telegram_id"])
        if telegram_id in self.settings.excluded_ids:
            raise web.HTTPNotFound(text="User not found")
        if not self.settings.bot_token or not self.settings.club_invite_link:
            raise web.HTTPServiceUnavailable(text="BOT_TOKEN or CLUB_INVITE_LINK is not configured")

        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            user = await cursor.fetchone()
        if user is None:
            raise web.HTTPNotFound(text="User not found")
        if not is_in_club(user):
            raise web.HTTPBadRequest(text="У пользователя нет активного доступа к клубу")

        sent = 0
        failed = 0
        api_url = f"https://api.telegram.org/bot{self.settings.bot_token}"
        async with ClientSession() as session:
            if self.settings.club_chat_id:
                try:
                    async with session.post(
                        f"{api_url}/unbanChatMember",
                        json={
                            "chat_id": self.settings.club_chat_id,
                            "user_id": telegram_id,
                            "only_if_banned": True,
                        },
                        timeout=15,
                    ) as response:
                        if response.status != 200:
                            failed += 1
                except Exception:
                    failed += 1
            try:
                async with session.post(
                    f"{api_url}/sendMessage",
                    json={
                        "chat_id": telegram_id,
                        "text": (
                            "Здравствуйте! Ваш доступ в клуб Nastaunik активен.\n\n"
                            "Если вас случайно удалило из клуба, нажмите кнопку ниже, чтобы вернуться."
                        ),
                        "reply_markup": {
                            "inline_keyboard": [[{"text": "Вернуться в клуб", "url": self.settings.club_invite_link}]]
                        },
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                ) as response:
                    if response.status == 200:
                        sent += 1
                    else:
                        failed += 1
            except Exception:
                failed += 1

        await self.log_action(
            telegram_id=telegram_id,
            action_type="restore_link",
            title="Отправлена ссылка для возврата",
            details=f"Отправлено: {sent}; ошибок: {failed}",
        )
        raise web.HTTPSeeOther(location=self.url(f"/user/{telegram_id}", restore_sent=sent, restore_failed=failed))

    async def manual_payment(self, request: web.Request) -> web.Response:
        telegram_id = int(request.match_info["telegram_id"])
        if telegram_id in self.settings.excluded_ids:
            raise web.HTTPNotFound(text="User not found")

        form = await request.post()
        paid_at_raw = str(form.get("paid_at") or "").strip()
        amount_label = str(form.get("amount_label") or DEFAULT_AMOUNT_LABEL).strip() or DEFAULT_AMOUNT_LABEL
        note = str(form.get("note") or "Внесено вручную через веб-админку").strip()
        access_days_raw = str(form.get("access_days") or "30").strip()

        try:
            paid_at = datetime.strptime(paid_at_raw, "%Y-%m-%d")
        except ValueError as exc:
            raise web.HTTPBadRequest(text="Нужно указать дату оплаты в формате YYYY-MM-DD") from exc

        try:
            access_days = int(access_days_raw)
        except ValueError as exc:
            raise web.HTTPBadRequest(text="Количество дней доступа должно быть числом") from exc
        if access_days < 1 or access_days > 370:
            raise web.HTTPBadRequest(text="Количество дней доступа должно быть от 1 до 370")

        access_start_at = paid_at.replace(hour=0, minute=0, second=0, microsecond=0)
        access_end_at = access_start_at + timedelta(days=access_days)
        now = datetime.utcnow().isoformat(timespec="seconds")
        paid_iso = access_start_at.isoformat(timespec="seconds")
        access_start_iso = access_start_at.isoformat(timespec="seconds")
        access_end_iso = access_end_at.isoformat(timespec="seconds")

        async with self.connect() as db:
            cursor = await db.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (telegram_id,))
            if await cursor.fetchone() is None:
                raise web.HTTPNotFound(text="User not found")
            await db.execute(
                """
                INSERT INTO payments (
                    telegram_id,
                    status,
                    amount_label,
                    receipt_type,
                    receipt_text,
                    created_at,
                    confirmed_at,
                    admin_comment
                ) VALUES (?, 'approved', ?, 'manual', ?, ?, ?, ?)
                """,
                (telegram_id, amount_label, note, now, paid_iso, note),
            )
            await db.execute(
                """
                UPDATE users
                SET current_status = 'active',
                    payment_confirmed_at = ?,
                    access_start_at = ?,
                    access_end_at = ?,
                    grace_end_at = ?,
                    recurring_amount_label = ?,
                    admin_comment = ?,
                    reminder_5_sent_at = NULL,
                    expiry_notice_sent_at = NULL,
                    pending_amount_label = NULL,
                    pending_promo_code = NULL,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (
                    paid_iso,
                    access_start_iso,
                    access_end_iso,
                    access_end_iso,
                    amount_label,
                    note,
                    now,
                    telegram_id,
                ),
            )
            await db.commit()

        await self.log_action(
            telegram_id=telegram_id,
            action_type="manual_payment",
            title="Оплата внесена вручную",
            details=f"{amount_label}; дата оплаты {paid_iso}; доступ до {access_end_iso}",
        )
        raise web.HTTPSeeOther(location=self.url(f"/user/{telegram_id}", saved=1))

    async def approve_payment(self, request: web.Request) -> web.Response:
        payment_id = int(request.match_info["payment_id"])
        form = await request.post()
        comment = str(form.get("comment") or "Подтверждено через веб-админку").strip()
        now_dt = datetime.utcnow()
        now = now_dt.isoformat(timespec="seconds")

        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT p.*, u.access_start_at, u.access_end_at, u.current_status
                FROM payments p
                JOIN users u ON u.telegram_id = p.telegram_id
                WHERE p.id = ?
                """,
                (payment_id,),
            )
            payment = await cursor.fetchone()
            if payment is None:
                raise web.HTTPNotFound(text="Payment not found")
            if payment["status"] != "pending":
                raise web.HTTPBadRequest(text="Платеж уже обработан")
            telegram_id = int(payment["telegram_id"])
            if telegram_id in self.settings.excluded_ids:
                raise web.HTTPNotFound(text="Payment not found")

            existing_end = None
            if payment["access_end_at"]:
                try:
                    existing_end = datetime.fromisoformat(payment["access_end_at"])
                except ValueError:
                    existing_end = None
            start = existing_end if existing_end and existing_end >= now_dt and payment["current_status"] in {"active", "grace_period"} else now_dt
            original_start = start
            if payment["access_start_at"]:
                try:
                    original_start = datetime.fromisoformat(payment["access_start_at"])
                except ValueError:
                    original_start = start
            end = start + timedelta(days=30)
            access_start_iso = original_start.isoformat(timespec="seconds")
            access_end_iso = end.isoformat(timespec="seconds")

            await db.execute(
                "UPDATE payments SET status = 'approved', confirmed_at = ?, admin_comment = ? WHERE id = ?",
                (now, comment, payment_id),
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
                (
                    now,
                    access_start_iso,
                    access_end_iso,
                    access_end_iso,
                    self.settings.club_invite_link,
                    comment,
                    now,
                    telegram_id,
                ),
            )
            await db.commit()

        await self.send_payment_result_message(telegram_id, approved=True)
        await self.log_action(
            telegram_id=telegram_id,
            action_type="payment_approved",
            title="Чек подтвержден",
            details=f"Платеж #{payment_id}; доступ до {access_end_iso}; {comment}",
        )
        raise web.HTTPSeeOther(location=self.url("/finance", payment_done=1))

    async def reject_payment(self, request: web.Request) -> web.Response:
        payment_id = int(request.match_info["payment_id"])
        form = await request.post()
        comment = str(form.get("comment") or "Отклонено через веб-админку").strip()
        now = datetime.utcnow().isoformat(timespec="seconds")

        async with self.connect() as db:
            cursor = await db.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
            payment = await cursor.fetchone()
            if payment is None:
                raise web.HTTPNotFound(text="Payment not found")
            if payment["status"] != "pending":
                raise web.HTTPBadRequest(text="Платеж уже обработан")
            telegram_id = int(payment["telegram_id"])
            if telegram_id in self.settings.excluded_ids:
                raise web.HTTPNotFound(text="Payment not found")
            await db.execute(
                "UPDATE payments SET status = 'rejected', rejected_at = ?, admin_comment = ? WHERE id = ?",
                (now, comment, payment_id),
            )
            await db.execute(
                """
                UPDATE users
                SET current_status = CASE
                        WHEN access_end_at IS NOT NULL AND datetime(access_end_at) >= datetime(?) THEN 'active'
                        ELSE 'rejected'
                    END,
                    admin_comment = ?,
                    updated_at = ?
                WHERE telegram_id = ?
                """,
                (now, comment, now, telegram_id),
            )
            await db.commit()

        await self.send_payment_result_message(telegram_id, approved=False)
        await self.log_action(
            telegram_id=telegram_id,
            action_type="payment_rejected",
            title="Чек отклонен",
            details=f"Платеж #{payment_id}; {comment}",
        )
        raise web.HTTPSeeOther(location=self.url("/finance", payment_done=1))

    async def send_payment_result_message(self, telegram_id: int, *, approved: bool) -> None:
        if not self.settings.bot_token:
            return
        if approved:
            text = (
                "Оплата подтверждена. Добро пожаловать в клуб Nastaunik.\n\n"
                "Вот ваш доступ в клуб:"
            )
            reply_markup = {
                "inline_keyboard": [[{"text": "Перейти в клуб", "url": self.settings.club_invite_link}]]
            }
        else:
            text = (
                "Пока не удалось подтвердить оплату.\n"
                "Проверьте, пожалуйста, данные перевода или отправьте чек заново."
            )
            reply_markup = {"inline_keyboard": [[{"text": "Отправить чек заново", "callback_data": "payment:send_receipt"}]]}
        try:
            async with ClientSession() as session:
                await session.post(
                    f"https://api.telegram.org/bot{self.settings.bot_token}/sendMessage",
                    json={
                        "chat_id": telegram_id,
                        "text": text,
                        "reply_markup": reply_markup,
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )
        except Exception:
            pass

    def exclusion_condition(self, alias: str = "u") -> tuple[str, list[int]]:
        if not self.settings.excluded_ids:
            return "", []
        column = f"{alias}.telegram_id" if alias else "telegram_id"
        placeholders = ", ".join("?" for _ in self.settings.excluded_ids)
        return f"{column} NOT IN ({placeholders})", list(self.settings.excluded_ids)

    def special_condition(self, alias: str = "u") -> str:
        return (
            f"({alias}.is_lifetime_free = 1 OR "
            f"({alias}.recurring_amount_label IS NOT NULL AND {alias}.recurring_amount_label != '' "
            f"AND {alias}.recurring_amount_label != ?))"
        )

    def special_rate_condition(self, alias: str = "u") -> str:
        return (
            f"({alias}.is_lifetime_free = 0 AND "
            f"{alias}.recurring_amount_label IS NOT NULL AND {alias}.recurring_amount_label != '' "
            f"AND {alias}.recurring_amount_label != ?)"
        )

    def free_condition(self, alias: str = "u") -> str:
        return f"{alias}.is_lifetime_free = 1"

    async def load_broadcast_recipients(
        self,
        audience: str | None = None,
        *,
        status_filter: str = "any",
        type_filter: str = "any",
    ) -> list[int]:
        where: list[str] = []
        params: list[object] = []
        excluded_sql, excluded_params = self.exclusion_condition(alias="u")
        if excluded_sql:
            where.append(excluded_sql)
            params.extend(excluded_params)
        if audience:
            if audience == "special":
                status_filter = "any"
                type_filter = "special_rate"
            elif audience == "free":
                status_filter = "any"
                type_filter = "free"
            elif audience == "expired":
                status_filter = "expired"
                type_filter = "any"
            elif audience == "regular":
                status_filter = "not_in_club"
                type_filter = "regular"
            elif audience == "all":
                status_filter = "any"
                type_filter = "any"
            else:
                raise ValueError("Unknown broadcast audience")

        if status_filter == "in_club":
            where.append("(u.current_status IN ('active', 'grace_period') OR u.is_lifetime_free = 1)")
        elif status_filter == "not_in_club":
            where.append("NOT (u.current_status IN ('active', 'grace_period') OR u.is_lifetime_free = 1)")
        elif status_filter == "waiting_confirmation":
            where.append("u.current_status = 'waiting_confirmation'")
        elif status_filter == "expired":
            where.append("u.current_status = 'expired'")
        elif status_filter == "expiring_7":
            where.append("u.current_status IN ('active', 'grace_period')")
            where.append("u.is_lifetime_free = 0")
            where.append("u.access_end_at IS NOT NULL")
            where.append("date(u.access_end_at) <= date(?)")
            params.append((datetime.utcnow() + timedelta(days=7)).date().isoformat())
        elif status_filter != "any":
            raise ValueError("Unknown broadcast status filter")

        if type_filter == "regular":
            where.append(f"NOT {self.special_condition(alias='u')}")
            params.append(DEFAULT_AMOUNT_LABEL)
        elif type_filter == "special_any":
            where.append(self.special_condition(alias="u"))
            params.append(DEFAULT_AMOUNT_LABEL)
        elif type_filter == "special_rate":
            where.append(self.special_rate_condition(alias="u"))
            params.append(DEFAULT_AMOUNT_LABEL)
        elif type_filter == "free":
            where.append(self.free_condition(alias="u"))
        elif type_filter != "any":
            raise ValueError("Unknown broadcast type filter")

        sql = f"""
            SELECT u.telegram_id
            FROM users u
            WHERE {" AND ".join(where) if where else "1 = 1"}
            ORDER BY u.telegram_id
        """
        async with self.connect() as db:
            cursor = await db.execute(sql, params)
            rows = await cursor.fetchall()
        return [int(row["telegram_id"]) for row in rows]

    async def count_broadcast_recipients(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for audience in ("regular", "special", "free", "expired", "all"):
            counts[audience] = len(await self.load_broadcast_recipients(audience))
        return counts

    async def log_broadcast(
        self,
        *,
        audience: str,
        message: str,
        recipients_count: int,
        sent_count: int,
        failed_count: int,
    ) -> None:
        await self.ensure_admin_tables()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO broadcast_logs (
                    audience,
                    message,
                    recipients_count,
                    sent_count,
                    failed_count,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    audience,
                    message,
                    recipients_count,
                    sent_count,
                    failed_count,
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )
            await db.commit()

    async def load_broadcast_logs(self, limit: int = 8) -> list[sqlite3.Row]:
        await self.ensure_admin_tables()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM broadcast_logs
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return await cursor.fetchall()

    async def log_action(
        self,
        *,
        telegram_id: int | None,
        action_type: str,
        title: str,
        details: str | None = None,
    ) -> None:
        await self.ensure_admin_tables()
        async with self.connect() as db:
            await db.execute(
                """
                INSERT INTO action_logs (
                    telegram_id,
                    action_type,
                    title,
                    details,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    telegram_id,
                    action_type,
                    title,
                    details,
                    datetime.utcnow().isoformat(timespec="seconds"),
                ),
            )
            await db.commit()

    async def load_action_logs(self, telegram_id: int, limit: int = 40) -> list[sqlite3.Row]:
        await self.ensure_admin_tables()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM action_logs
                WHERE telegram_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (telegram_id, limit),
            )
            return await cursor.fetchall()

    async def load_recent_activity(self, limit: int = 8) -> list[sqlite3.Row]:
        await self.ensure_admin_tables()
        excluded_sql, excluded_params = self.exclusion_condition(alias="a")
        where_sql = f"WHERE (a.telegram_id IS NULL OR {excluded_sql})" if excluded_sql else ""
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT
                    a.telegram_id,
                    a.action_type,
                    a.title,
                    a.details,
                    a.created_at,
                    u.full_name,
                    u.username
                FROM action_logs a
                LEFT JOIN users u ON u.telegram_id = a.telegram_id
                {where_sql}
                ORDER BY a.created_at DESC, a.id DESC
                LIMIT ?
                """,
                [*excluded_params, limit],
            )
            return await cursor.fetchall()

    async def load_public_channel_count(self) -> int | None:
        if self.settings.public_channel_member_count is not None:
            return self.settings.public_channel_member_count
        if not self.settings.public_channel_live_count:
            return None
        if not self.settings.bot_token or not self.settings.public_channel_id:
            return None
        now = datetime.utcnow()
        if self._public_channel_count_cache:
            cached_at, cached_count = self._public_channel_count_cache
            if (now - cached_at).total_seconds() < 300:
                return cached_count
        api_url = f"https://api.telegram.org/bot{self.settings.bot_token}/getChatMemberCount"
        try:
            timeout = ClientTimeout(total=2, connect=1, sock_connect=1, sock_read=1)
            async with ClientSession(timeout=timeout) as session:
                request = session.post(api_url, json={"chat_id": self.settings.public_channel_id})
                async with await asyncio.wait_for(request, timeout=2.5) as response:
                    data = await asyncio.wait_for(response.json(), timeout=1)
            count = int(data["result"]) if data.get("ok") else None
        except Exception:
            count = None
        self._public_channel_count_cache = (now, count)
        return count

    async def load_public_channel_funnel_counts(self) -> dict[str, int] | None:
        if not self.settings.public_channel_live_count:
            return None
        if not self.settings.bot_token or not self.settings.public_channel_id:
            return None
        now = datetime.utcnow()
        if self._public_channel_funnel_cache:
            cached_at, cached_counts = self._public_channel_funnel_cache
            if (now - cached_at).total_seconds() < 900:
                return cached_counts

        excluded_sql, excluded_params = self.exclusion_condition(alias="u")
        where_sql = f"WHERE {excluded_sql}" if excluded_sql else ""
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT u.telegram_id,
                       CASE
                         WHEN u.current_status IN ('active', 'grace_period') OR u.is_lifetime_free = 1 THEN 1
                         ELSE 0
                       END AS in_club
                FROM users u
                {where_sql}
                """,
                excluded_params,
            )
            rows = await cursor.fetchall()

        timeout = ClientTimeout(total=2, connect=1, sock_connect=1, sock_read=1)
        api_url = f"https://api.telegram.org/bot{self.settings.bot_token}/getChatMember"
        semaphore = asyncio.Semaphore(8)

        async def is_channel_member(row: sqlite3.Row) -> tuple[bool, bool]:
            async with semaphore:
                try:
                    async with ClientSession(timeout=timeout) as session:
                        response = await asyncio.wait_for(
                            session.post(
                                api_url,
                                json={
                                    "chat_id": self.settings.public_channel_id,
                                    "user_id": int(row["telegram_id"]),
                                },
                            ),
                            timeout=2.5,
                        )
                        try:
                            data = await asyncio.wait_for(response.json(), timeout=1)
                        finally:
                            response.release()
                    status = str((data.get("result") or {}).get("status") or "")
                    return status not in {"left", "kicked"}, bool(row["in_club"])
                except Exception:
                    return False, bool(row["in_club"])

        try:
            checks = await asyncio.wait_for(
                asyncio.gather(*(is_channel_member(row) for row in rows)),
                timeout=6,
            )
        except Exception:
            self._public_channel_funnel_cache = (now, None)
            return None

        started_from_channel = sum(1 for is_member, _ in checks if is_member)
        bought_from_channel = sum(1 for is_member, in_club in checks if is_member and in_club)
        counts = {
            "started_from_channel": started_from_channel,
            "bought_from_channel": bought_from_channel,
        }
        self._public_channel_funnel_cache = (now, counts)
        return counts

    async def load_funnel_stats(self) -> list[dict[str, object]]:
        excluded_sql, excluded_params = self.exclusion_condition(alias="u")
        where_sql = f"WHERE {excluded_sql}" if excluded_sql else ""
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT
                    COUNT(*) AS started,
                    SUM(CASE WHEN u.current_status IN ('waiting_payment', 'new') THEN 1 ELSE 0 END) AS no_payment,
                    SUM(CASE WHEN u.current_status = 'waiting_confirmation' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN u.current_status IN ('active', 'grace_period') OR u.is_lifetime_free = 1 THEN 1 ELSE 0 END) AS active,
                    SUM(CASE WHEN u.current_status = 'expired' THEN 1 ELSE 0 END) AS expired
                FROM users u
                {where_sql}
                """,
                excluded_params,
            )
            row = await cursor.fetchone()
        started = int(row["started"] or 0) if row else 0
        active = int(row["active"] or 0) if row else 0
        public_channel_count = await self.load_public_channel_count()
        channel_funnel = await self.load_public_channel_funnel_counts()
        if channel_funnel is not None:
            started = channel_funnel["started_from_channel"]
            active = channel_funnel["bought_from_channel"]
        channel_count = public_channel_count if public_channel_count is not None else 0
        base = channel_count or started or 1
        steps = [
            ("В публичном канале", channel_count, public_channel_count is not None),
            ("Запустили бот из канала", started, True),
            ("Купили и вошли в клуб", active, True),
        ]
        result: list[dict[str, object]] = []
        previous_count: int | None = None
        for label, count, known in steps:
            step_percent = None
            if known and previous_count:
                step_percent = round(count / previous_count * 100, 1)
            result.append(
                {
                    "label": label,
                    "count": count,
                    "known": known,
                    "percent": round((count / base * 100), 1) if known and base else 0,
                    "step_percent": step_percent,
                }
            )
            if known:
                previous_count = count
        return result

    async def load_finance_series(self, *, months: int = 6) -> list[dict[str, object]]:
        excluded_sql, excluded_params = self.exclusion_condition(alias="u")
        where = ["p.status = 'approved'", "p.confirmed_at IS NOT NULL"]
        params: list[object] = []
        if excluded_sql:
            where.append(excluded_sql)
            params.extend(excluded_params)
        cutoff_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        for _ in range(max(months - 1, 0)):
            cutoff_month = cutoff_month.replace(year=cutoff_month.year - 1, month=12) if cutoff_month.month == 1 else cutoff_month.replace(month=cutoff_month.month - 1)
        where.append("p.confirmed_at >= ?")
        params.append(cutoff_month.isoformat(timespec="seconds"))
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT substr(p.confirmed_at, 1, 7) AS month_key,
                       p.amount_label
                FROM payments p
                JOIN users u ON u.telegram_id = p.telegram_id
                WHERE {" AND ".join(where)}
                ORDER BY p.confirmed_at ASC
                """,
                params,
            )
            rows = await cursor.fetchall()
        by_month: dict[str, dict[str, object]] = {}
        for row in rows:
            month_key = row["month_key"]
            item = by_month.setdefault(month_key, {"month": month_key, "label": month_label(month_key), "total": 0.0, "count": 0})
            item["total"] = float(item["total"]) + parse_amount(row["amount_label"])
            item["count"] = int(item["count"]) + 1
        return list(by_month.values())[-months:]

    async def load_reminder_overview(self) -> dict[str, int]:
        excluded_sql, excluded_params = self.exclusion_condition(alias="u")
        where = ["u.current_status IN ('active', 'grace_period')", "u.is_lifetime_free = 0", "u.access_end_at IS NOT NULL"]
        params: list[object] = []
        if excluded_sql:
            where.append(excluded_sql)
            params.extend(excluded_params)
        today = datetime.utcnow().date()
        in_five = (today + timedelta(days=5)).isoformat()
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT
                    SUM(CASE WHEN date(u.access_end_at) = date(?) AND u.reminder_5_sent_at IS NULL THEN 1 ELSE 0 END) AS due_5,
                    SUM(CASE WHEN date(u.access_end_at) = date(?) AND u.expiry_notice_sent_at IS NULL THEN 1 ELSE 0 END) AS due_today,
                    SUM(CASE WHEN u.grace_end_at IS NOT NULL AND datetime(u.grace_end_at) <= datetime(?) THEN 1 ELSE 0 END) AS overdue_remove,
                    SUM(CASE WHEN u.reminder_5_sent_at IS NOT NULL THEN 1 ELSE 0 END) AS reminder_sent
                FROM users u
                WHERE {" AND ".join(where)}
                """,
                [in_five, today.isoformat(), datetime.utcnow().isoformat(timespec="seconds"), *params],
            )
            row = await cursor.fetchone()
        return {key: int(row[key] or 0) for key in row.keys()} if row else {"due_5": 0, "due_today": 0, "overdue_remove": 0, "reminder_sent": 0}

    async def load_broadcast_templates(self, limit: int = 20) -> list[sqlite3.Row]:
        await self.ensure_admin_tables()
        async with self.connect() as db:
            cursor = await db.execute(
                """
                SELECT *
                FROM broadcast_templates
                ORDER BY updated_at DESC, id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return await cursor.fetchall()

    async def load_finances(
        self,
        *,
        selected_month: str,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
    ) -> dict[str, object]:
        excluded_sql, excluded_params = self.exclusion_condition(alias="u")
        where = ["p.status = 'approved'", "p.confirmed_at IS NOT NULL"]
        params: list[object] = []
        if excluded_sql:
            where.append(excluded_sql)
            params.extend(excluded_params)
        sql = f"""
            SELECT
                p.id,
                p.telegram_id,
                p.amount_label,
                p.confirmed_at,
                p.created_at,
                p.admin_comment,
                u.full_name,
                u.username
            FROM payments p
            JOIN users u ON u.telegram_id = p.telegram_id
            WHERE {" AND ".join(where)}
            ORDER BY p.confirmed_at DESC, p.id DESC
        """
        async with self.connect() as db:
            cursor = await db.execute(sql, params)
            payments = await cursor.fetchall()

        now = datetime.utcnow()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=6)
        month_start = today_start.replace(day=1)
        if period_start is None or period_end is None:
            period_start = datetime.strptime(selected_month, "%Y-%m").replace(day=1)
            period_end = period_start.replace(year=period_start.year + 1, month=1) if period_start.month == 12 else period_start.replace(month=period_start.month + 1)
        totals = {
            "today": 0.0,
            "week": 0.0,
            "month": 0.0,
            "selected_month": 0.0,
            "all": 0.0,
        }
        counts = {
            "today": 0,
            "week": 0,
            "month": 0,
            "selected_month": 0,
            "all": 0,
        }
        available_months: set[str] = {selected_month, current_month_key()}
        available_years: set[str] = {current_month_key()[:4]}
        selected_payments: list[sqlite3.Row] = []
        recent: list[sqlite3.Row] = []
        for payment in payments:
            amount = parse_amount(payment["amount_label"])
            try:
                confirmed_at = datetime.fromisoformat(payment["confirmed_at"])
            except (TypeError, ValueError):
                continue
            available_months.add(confirmed_at.strftime("%Y-%m"))
            available_years.add(confirmed_at.strftime("%Y"))
            totals["all"] += amount
            counts["all"] += 1
            if confirmed_at >= today_start:
                totals["today"] += amount
                counts["today"] += 1
            if confirmed_at >= week_start:
                totals["week"] += amount
                counts["week"] += 1
            if confirmed_at >= month_start:
                totals["month"] += amount
                counts["month"] += 1
            if (period_start is None or confirmed_at >= period_start) and (period_end is None or confirmed_at < period_end):
                totals["selected_month"] += amount
                counts["selected_month"] += 1
                selected_payments.append(payment)
            if len(recent) < 12:
                recent.append(payment)
        period_key = "all"
        period_label = "Все время"
        if period_start and period_end:
            period_key = f"{period_start.date().isoformat()}_{(period_end - timedelta(days=1)).date().isoformat()}"
            period_label = f"{format_date(period_start.date().isoformat())} - {format_date((period_end - timedelta(days=1)).date().isoformat())}"
        elif period_start:
            period_key = f"from_{period_start.date().isoformat()}"
            period_label = f"с {format_date(period_start.date().isoformat())}"
        elif period_end:
            period_key = f"to_{(period_end - timedelta(days=1)).date().isoformat()}"
            period_label = f"до {format_date((period_end - timedelta(days=1)).date().isoformat())}"
        return {
            "selected_month": selected_month,
            "available_months": sorted(available_months, reverse=True),
            "available_years": sorted(available_years, reverse=True),
            "period_key": period_key,
            "period_label": period_label,
            "period_start": period_start,
            "period_end": period_end,
            "totals": totals,
            "counts": counts,
            "selected_payments": selected_payments,
            "recent": recent,
        }

    async def load_pending_payments(self, *, limit: int = 50) -> list[sqlite3.Row]:
        excluded_sql, excluded_params = self.exclusion_condition(alias="u")
        where = ["p.status = 'pending'"]
        params: list[object] = []
        if excluded_sql:
            where.append(excluded_sql)
            params.extend(excluded_params)
        sql = f"""
            SELECT
                p.id,
                p.telegram_id,
                p.amount_label,
                p.receipt_type,
                p.receipt_text,
                p.created_at,
                u.full_name,
                u.username,
                u.current_status
            FROM payments p
            JOIN users u ON u.telegram_id = p.telegram_id
            WHERE {" AND ".join(where)}
            ORDER BY p.created_at DESC, p.id DESC
            LIMIT ?
        """
        async with self.connect() as db:
            cursor = await db.execute(sql, [*params, limit])
            return await cursor.fetchall()

    async def load_stats(self) -> dict[str, int]:
        excluded_sql, excluded_params = self.exclusion_condition(alias="")
        where_sql = f"WHERE {excluded_sql}" if excluded_sql else ""
        async with self.connect() as db:
            cursor = await db.execute(
                f"""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN current_status IN ('active', 'grace_period') OR is_lifetime_free = 1 THEN 1 ELSE 0 END) AS members,
                    SUM(CASE WHEN current_status = 'waiting_confirmation' THEN 1 ELSE 0 END) AS waiting,
                    SUM(CASE WHEN current_status = 'expired' THEN 1 ELSE 0 END) AS expired,
                    SUM(CASE WHEN is_lifetime_free = 0 AND recurring_amount_label IS NOT NULL AND recurring_amount_label != '' AND recurring_amount_label != ? THEN 1 ELSE 0 END) AS special,
                    SUM(CASE WHEN is_lifetime_free = 1 THEN 1 ELSE 0 END) AS free
                FROM users
                {where_sql}
                """,
                [DEFAULT_AMOUNT_LABEL, *excluded_params],
            )
            row = await cursor.fetchone()
        return {key: int(row[key] or 0) for key in row.keys()} if row else {}

    async def load_users(
        self,
        *,
        view: str,
        query: str,
        expiring_days: int = 7,
        status_filter: str = "any",
        type_filter: str = "any",
    ) -> list[sqlite3.Row]:
        where: list[str] = []
        params: list[object] = []
        excluded_sql, excluded_params = self.exclusion_condition(alias="u")
        if excluded_sql:
            where.append(excluded_sql)
            params.extend(excluded_params)
        if view == "members":
            where.append("(u.current_status IN ('active', 'grace_period') OR u.is_lifetime_free = 1)")
        elif view == "activated":
            where.append("1 = 1")
        elif view == "special":
            where.append(self.special_condition(alias="u"))
            params.append(DEFAULT_AMOUNT_LABEL)
        elif view == "waiting":
            where.append("u.current_status = 'waiting_confirmation'")
        elif view == "expiring":
            where.append("u.current_status IN ('active', 'grace_period')")
            where.append("u.is_lifetime_free = 0")
            where.append("u.access_end_at IS NOT NULL")
            where.append("date(u.access_end_at) <= date(?)")
            params.append((datetime.utcnow() + timedelta(days=expiring_days)).date().isoformat())
        elif view == "expired":
            where.append("u.current_status = 'expired'")
        else:
            where.append("1 = 1")

        if status_filter != "any":
            if status_filter == "in_club":
                where.append("(u.current_status IN ('active', 'grace_period') OR u.is_lifetime_free = 1)")
            elif status_filter == "not_in_club":
                where.append("NOT (u.current_status IN ('active', 'grace_period') OR u.is_lifetime_free = 1)")
            elif status_filter == "waiting_confirmation":
                where.append("u.current_status = 'waiting_confirmation'")
            elif status_filter == "expired":
                where.append("u.current_status = 'expired'")
            elif status_filter == "expiring":
                where.append("u.current_status IN ('active', 'grace_period')")
                where.append("u.is_lifetime_free = 0")
                where.append("u.access_end_at IS NOT NULL")
                where.append("date(u.access_end_at) <= date(?)")
                params.append((datetime.utcnow() + timedelta(days=expiring_days)).date().isoformat())

        if type_filter != "any":
            if type_filter == "regular":
                where.append(f"NOT {self.special_condition(alias='u')}")
                params.append(DEFAULT_AMOUNT_LABEL)
            elif type_filter == "special_any":
                where.append("(u.is_lifetime_free = 1 OR (u.recurring_amount_label IS NOT NULL AND u.recurring_amount_label != '' AND u.recurring_amount_label != ?))")
                params.append(DEFAULT_AMOUNT_LABEL)
            elif type_filter == "special_rate":
                where.append(self.special_rate_condition(alias="u"))
                params.append(DEFAULT_AMOUNT_LABEL)
            elif type_filter == "free":
                where.append(self.free_condition(alias="u"))

        if query:
            where.append("(u.full_name LIKE ? OR u.username LIKE ? OR CAST(u.telegram_id AS TEXT) LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like])

        sql = f"""
            SELECT
                u.*,
                u.payment_confirmed_at AS last_paid_at,
                COALESCE(u.recurring_amount_label, ?) AS last_amount_label,
                (
                    SELECT COUNT(*)
                    FROM payments p
                    WHERE p.telegram_id = u.telegram_id
                      AND p.status = 'approved'
                ) AS payments_count,
                (
                    SELECT GROUP_CONCAT(p.amount_label, '||')
                    FROM payments p
                    WHERE p.telegram_id = u.telegram_id
                      AND p.status = 'approved'
                ) AS payment_amount_labels,
                NULL AS pending_payment_id,
                NULL AS pending_receipt_text
            FROM users u
            WHERE {" AND ".join(where)}
            ORDER BY
                u.is_lifetime_free DESC,
                CASE WHEN u.current_status IN ('active', 'grace_period') THEN 0 ELSE 1 END,
                u.access_end_at ASC,
                u.created_at DESC
            LIMIT 120
        """
        params = [DEFAULT_AMOUNT_LABEL, *params]
        async with self.connect() as db:
            cursor = await db.execute(sql, params)
            return await cursor.fetchall()

    def render_funnel(self, funnel: list[dict[str, object]]) -> str:
        max_count = max((int(item.get("count", 0)) for item in funnel), default=0) or 1
        row_parts: list[str] = []
        for item in funnel:
            known = bool(item.get("known", True))
            count = int(item.get("count", 0)) if known else 0
            label = item.get("label")
            step_percent = item.get("step_percent")
            if known:
                meta = f"{count} чел. · {esc(item.get('percent', 0))}% от канала"
                if step_percent is not None:
                    meta += f" · {esc(step_percent)}% от прошлого шага"
            else:
                meta = "не настроен PUBLIC_CHANNEL_ID"
            width = max(6, int(count / max_count * 100)) if known else 6
            row_parts.append(
                f"""
                <div class="funnel-row {'' if known else 'muted-row'}">
                  <div><b>{esc(label)}</b><span>{meta}</span></div>
                  <div class="funnel-track"><i style="width:{width}%"></i></div>
                </div>
                """
            )
        rows = "".join(row_parts)
        return f"""
        <article class="crm-card wide-card">
          <p class="eyebrow">Воронка</p>
          <h2>Путь клиента</h2>
          <p class="muted">От публичного Telegram-канала к запуску бота и участию в клубе.</p>
          <div class="funnel-list">{rows}</div>
        </article>
        """

    def render_action_center(
        self,
        *,
        pending_count: int,
        expiring_count: int,
        reminders: dict[str, int],
    ) -> str:
        items = [
            {
                "label": "Проверить чеки",
                "value": pending_count,
                "hint": "ожидают подтверждения оплаты",
                "href": self.url("/finance") + "#pending",
                "tone": "hot" if pending_count else "calm",
            },
            {
                "label": "Истекают сегодня",
                "value": reminders.get("due_today", 0),
                "hint": "нужны уведомления об окончании",
                "href": self.url("/clients", status_filter="expiring", days=1),
                "tone": "warn" if reminders.get("due_today", 0) else "calm",
            },
            {
                "label": "Пора удалить",
                "value": reminders.get("overdue_remove", 0),
                "hint": "просрочен льготный период",
                "href": self.url("/clients", status_filter="expired"),
                "tone": "hot" if reminders.get("overdue_remove", 0) else "calm",
            },
            {
                "label": "Скоро истекают",
                "value": expiring_count,
                "hint": "доступ заканчивается за 7 дней",
                "href": self.url("/clients", status_filter="expiring", days=7),
                "tone": "warn" if expiring_count else "calm",
            },
        ]
        rows = "".join(
            f"""
            <a class="action-item {esc(item['tone'])}" href="{esc(item['href'])}">
              <span>{esc(item['label'])}</span>
              <b>{int(item['value'])}</b>
              <small>{esc(item['hint'])}</small>
            </a>
            """
            for item in items
        )
        return f"""
        <section class="priority-card">
          <div class="section-head tight"><div><p class="eyebrow">Сегодня</p><h2>Требует внимания</h2></div></div>
          <div class="action-grid">{rows}</div>
        </section>
        """

    def render_finance_snapshot(self, finances: dict[str, object], series: list[dict[str, object]]) -> str:
        totals = finances.get("totals", {})
        counts = finances.get("counts", {})
        if not isinstance(totals, dict):
            totals = {}
        if not isinstance(counts, dict):
            counts = {}
        month_total = float(totals.get("month", 0.0))
        week_total = float(totals.get("week", 0.0))
        today_total = float(totals.get("today", 0.0))
        month_count = int(counts.get("month", 0))
        average = month_total / month_count if month_count else 0.0
        previous = float(series[-2].get("total", 0.0)) if len(series) > 1 else 0.0
        diff = month_total - previous
        diff_text = f"+{format_money(diff)} к прошлому месяцу" if diff >= 0 else f"-{format_money(abs(diff))} к прошлому месяцу"
        cards = [
            ("Месяц", format_money(month_total), f"оплат: {month_count}"),
            ("Неделя", format_money(week_total), "последние 7 дней"),
            ("Сегодня", format_money(today_total), "подтверждено сегодня"),
            ("Средний платёж", format_money(average), diff_text),
        ]
        rows = "".join(
            f"<div><span>{esc(label)}</span><b>{esc(value)}</b><small>{esc(hint)}</small></div>"
            for label, value, hint in cards
        )
        return f"""
        <section class="finance-snapshot">
          <div class="section-head tight">
            <div><p class="eyebrow">Деньги</p><h2>Финансовый срез</h2></div>
            <a class="text-link" href="{esc(self.url('/finance'))}">Подробнее</a>
          </div>
          <div class="finance-grid">{rows}</div>
        </section>
        """

    def render_system_health(self, *, funnel: list[dict[str, object]], reminders: dict[str, int]) -> str:
        channel_known = bool(funnel and funnel[0].get("known"))
        checks = [
            ("CRM", "работает", "ok"),
            ("Бот", "токен настроен" if self.settings.bot_token else "нет токена", "ok" if self.settings.bot_token else "bad"),
            ("Канал", "читается" if channel_known else "не подключен live-счётчик", "ok" if channel_known else "warn"),
            ("Автоматика", "есть задачи" if sum(reminders.values()) else "очередь пустая", "warn" if sum(reminders.values()) else "ok"),
        ]
        rows = "".join(
            f"""
            <li class="{esc(tone)}">
              <span>{esc(label)}</span>
              <b>{esc(status)}</b>
            </li>
            """
            for label, status, tone in checks
        )
        return f"""
        <article class="crm-card health-card">
          <p class="eyebrow">Система</p>
          <h2>Здоровье CRM</h2>
          <ul class="health-list">{rows}</ul>
        </article>
        """

    def render_recent_activity(self, events: list[sqlite3.Row]) -> str:
        grouped: list[dict[str, object]] = []
        grouped_index: dict[tuple[str, str, str, str], dict[str, object]] = {}
        for event in events:
            username = event["username"]
            name = event["full_name"] or (f"@{username}" if username else "Системное событие")
            user_part = ""
            if event["telegram_id"]:
                user_url = self.url(f"/user/{int(event['telegram_id'])}")
                user_part = f'<a class="name" href="{esc(user_url)}">{esc(name)}</a>'
            else:
                user_part = f'<b>{esc(name)}</b>'
            details = str(event["details"] or event["action_type"] or "")
            if len(details) > 150:
                details = details[:147].rstrip() + "..."
            group_key = (
                str(event["action_type"] or ""),
                str(event["title"] or ""),
                details,
                str(event["created_at"] or "")[:16],
            )
            if str(event["action_type"] or "") == "broadcast_received" and group_key in grouped_index:
                grouped_index[group_key]["count"] = int(grouped_index[group_key]["count"]) + 1
                continue
            grouped_event = {
                "user_part": user_part,
                "created_at": event["created_at"],
                "title": event["title"],
                "details": details,
                "count": 1,
            }
            grouped.append(grouped_event)
            grouped_index[group_key] = grouped_event
        rows = []
        for event in grouped:
            title = str(event["title"])
            if int(event["count"]) > 1:
                title = f"{title} · {int(event['count'])} получателя"
            rows.append(
                f"""
                <li>
                  <div>{event["user_part"]}<span>{esc(format_dt(event["created_at"]))}</span></div>
                  <p>{esc(title)}</p>
                  <small>{esc(event["details"])}</small>
                </li>
                """
            )
        return f"""
        <section class="history-card activity-card">
          <div class="section-head tight"><div><p class="eyebrow">Журнал</p><h2>Последние действия</h2></div></div>
          <ul class="activity-list">{''.join(rows) or '<li class="empty">Действий пока нет</li>'}</ul>
        </section>
        """

    def render_reminder_overview(self, reminders: dict[str, int]) -> str:
        items = [
            ("Напомнить за 5 дней", reminders.get("due_5", 0)),
            ("Истекают сегодня", reminders.get("due_today", 0)),
            ("Пора удалить", reminders.get("overdue_remove", 0)),
            ("Уже получали 5-дн. напоминание", reminders.get("reminder_sent", 0)),
        ]
        rows = "".join(f'<li><span>{esc(label)}</span><b>{int(value)}</b></li>' for label, value in items)
        return f"""
        <article class="crm-card">
          <p class="eyebrow">Автоматика</p>
          <h2>Напоминания</h2>
          <p class="muted">Контроль того, что бот должен сделать по оплатам.</p>
          <ul class="metric-list">{rows}</ul>
        </article>
        """

    def render_finance_chart(self, series: list[dict[str, object]]) -> str:
        max_total = max((float(item.get("total", 0.0)) for item in series), default=0.0) or 1.0
        bars = "".join(
            f"""
            <div class="chart-bar">
              <div class="bar-track"><i style="height:{max(4, int(float(item.get('total', 0.0)) / max_total * 100))}%"></i></div>
              <b>{esc(format_money(float(item.get('total', 0.0))))}</b>
              <span>{esc(str(item.get('month', '')))}</span>
            </div>
            """
            for item in series
        )
        current = float(series[-1].get("total", 0.0)) if series else 0.0
        previous = float(series[-2].get("total", 0.0)) if len(series) > 1 else 0.0
        diff = current - previous
        diff_label = f"+{format_money(diff)}" if diff >= 0 else f"-{format_money(abs(diff))}"
        return f"""
        <section class="chart-card">
          <div class="section-head"><div><p class="eyebrow">Динамика</p><h2>Поступления по месяцам</h2></div><span class="counter">{esc(diff_label)}</span></div>
          <div class="bar-chart">{bars or '<p class="empty">Пока нет данных для графика</p>'}</div>
        </section>
        """

    def render_smart_segments(self, *, status_filter: str, type_filter: str, expiring_days: int) -> str:
        parts: list[str] = []
        for key, (label, status, user_type, days) in SMART_SEGMENTS.items():
            href = self.url(
                "/clients",
                status_filter=status,
                type_filter=user_type,
                days=days or expiring_days,
            )
            active = status == status_filter and user_type == type_filter and (not days or int(days) == expiring_days)
            parts.append(f'<a class="segment {"active" if active else ""}" href="{esc(href)}">{esc(label)}</a>')
        return "".join(parts)

    def render_broadcast_templates(self, templates: list[sqlite3.Row], template_url: str) -> str:
        rows = "".join(
            f"""
            <article class="template-item">
              <div><b>{esc(template['title'])}</b><span>{esc(format_dt(template['updated_at']))}</span></div>
              <p>{esc(str(template['message'])[:220])}</p>
              <button type="button" class="mini-button secondary-button" data-template="{esc(template['message'])}">Вставить в сообщение</button>
            </article>
            """
            for template in templates
        )
        return f"""
        <section class="history-card templates-card">
          <div class="section-head"><div><p class="eyebrow">Шаблоны</p><h2>Быстрые сообщения</h2></div></div>
          <div class="templates-grid">{rows or '<p class="empty">Шаблонов пока нет</p>'}</div>
          <details class="template-form-wrap">
            <summary>Добавить новый шаблон</summary>
            <form class="template-form" method="post" action="{esc(template_url)}">
              <label class="field"><span>Название</span><input name="title" maxlength="120" required></label>
              <label class="field"><span>Текст</span><textarea name="message" rows="4" maxlength="4096" required></textarea></label>
              <button type="submit">Сохранить шаблон</button>
            </form>
          </details>
        </section>
        """

    def render_home_dashboard(
        self,
        *,
        stats: dict[str, int],
        finances: dict[str, object],
        funnel: list[dict[str, object]],
        finance_series: list[dict[str, object]],
        reminders: dict[str, int],
        pending_payments: list[sqlite3.Row],
        expiring_rows: list[sqlite3.Row],
        expiring_count: int,
        broadcast_logs: list[sqlite3.Row],
        recent_activity: list[sqlite3.Row],
    ) -> str:
        totals = finances.get("totals", {})
        counts = finances.get("counts", {})
        if not isinstance(totals, dict):
            totals = {}
        if not isinstance(counts, dict):
            counts = {}
        expiring_html = "".join(self.render_user_row(row) for row in expiring_rows)
        operations_block = ""
        if expiring_rows or pending_payments:
            operations_block = f"""
            <section class="split-grid dashboard-split">
              <div class="split-pane">
                <div class="section-head">
                  <div><p class="eyebrow">Риск доступа</p><h2>Кому нужен контроль</h2></div>
                  <a class="text-link" href="{esc(self.url('/clients', status_filter='expiring', days=7))}">Все</a>
                </div>
                <section class="table-wrap compact">
                  <table>
                    <thead><tr><th>Участник</th><th>Статус</th><th>Оплата</th><th>LTC</th><th>Доступ</th><th>Особый</th><th>Бот</th></tr></thead>
                    <tbody>{expiring_html or '<tr><td colspan="7" class="empty">В ближайшие 7 дней истечений нет</td></tr>'}</tbody>
                  </table>
                </section>
              </div>
              <div class="split-pane">
                {self.render_pending_payments(pending_payments, compact=True)}
              </div>
            </section>
            """
        return self.page(
            "CRM клуба Nastaunik",
            f"""
            <section class="hero crm-hero">
              <div>
                <p class="eyebrow">Nastaunik club CRM</p>
                <h1>Главная</h1>
                <p class="muted">Пульс клуба: люди, деньги, чеки и ближайшие риски по доступу.</p>
              </div>
              <div class="hero-actions">
                <a class="button" href="{esc(self.url('/clients'))}">Открыть клиентов</a>
                <a class="button secondary" href="{esc(self.url('/broadcasts'))}">Написать участникам</a>
              </div>
            </section>
            {self.render_action_center(
                pending_count=len(pending_payments),
                expiring_count=expiring_count,
                reminders=reminders,
            )}
            <section class="stats dashboard-stats">
              <div><span>Активных в клубе</span><b>{stats.get('members', 0)}</b><small>людей с доступом сейчас</small></div>
              <div><span>Всего в базе</span><b>{stats.get('total', 0)}</b><small>запускали бот когда-либо</small></div>
              <div><span>Особые тарифы</span><b>{stats.get('special', 0)}</b><small>отдельная категория</small></div>
              <div><span>Бесплатные</span><b>{stats.get('free', 0)}</b><small>вечный доступ</small></div>
            </section>
            <section class="crm-grid two-one">
              {self.render_funnel(funnel)}
              {self.render_system_health(funnel=funnel, reminders=reminders)}
            </section>
            {self.render_finance_snapshot(finances, finance_series)}
            {self.render_finance_chart(finance_series)}
            {self.render_recent_activity(recent_activity)}
            {operations_block}
            """,
            active="dashboard",
        )

    def render_clients_page(
        self,
        *,
        rows: list[sqlite3.Row],
        stats: dict[str, int],
        query: str,
        status_filter: str,
        type_filter: str,
        expiring_days: int,
    ) -> str:
        status_labels = {
            "any": "Все статусы",
            "in_club": "Состоит в клубе",
            "not_in_club": "Активировал бот, но не состоит",
            "waiting_confirmation": "Чек на проверке",
            "expired": "Истекшие",
            "expiring": "Скоро истекают",
        }
        type_labels = BROADCAST_TYPE_FILTERS
        status_options = "".join(
            f'<option value="{esc(key)}" {"selected" if key == status_filter else ""}>{esc(label)}</option>'
            for key, label in status_labels.items()
        )
        type_options = "".join(
            f'<option value="{esc(key)}" {"selected" if key == type_filter else ""}>{esc(label)}</option>'
            for key, label in type_labels.items()
        )
        day_options = "".join(
            f'<option value="{days}" {"selected" if days == expiring_days else ""}>{days} дней</option>'
            for days in (1, 3, 5, 7, 14, 30)
        )
        rows_html = "".join(self.render_user_row(row) for row in rows)
        table_filter_row = """
                  <tr class="column-filter-row">
                    <th><input class="column-filter" data-filter-key="name" placeholder="Фильтр по участнику"></th>
                    <th>
                      <select class="column-filter" data-filter-key="status">
                        <option value="">Все</option>
                        <option value="active">В клубе</option>
                        <option value="waiting_confirmation">Чек на проверке</option>
                        <option value="expired">Истекшие</option>
                        <option value="not_in_club">Не в клубе</option>
                      </select>
                    </th>
                    <th>
                      <select class="column-filter" data-filter-key="payment">
                        <option value="">Все</option>
                        <option value="paid">Оплатили</option>
                        <option value="pending">Чек на проверке</option>
                        <option value="no_payment">Без оплаты</option>
                      </select>
                    </th>
                    <th></th>
                    <th>
                      <select class="column-filter" data-filter-key="access">
                        <option value="">Все</option>
                        <option value="active">Есть доступ</option>
                        <option value="expiring">Скоро истекает</option>
                        <option value="expired">Истек</option>
                        <option value="none">Нет даты</option>
                      </select>
                    </th>
                    <th>
                      <select class="column-filter" data-filter-key="special">
                        <option value="">Все</option>
                        <option value="regular">Обычные</option>
                        <option value="special">Особые</option>
                        <option value="free">Бесплатные</option>
                      </select>
                    </th>
                    <th>
                      <select class="column-filter" data-filter-key="bot">
                        <option value="">Все</option>
                        <option value="activated">Активировали</option>
                      </select>
                    </th>
                  </tr>
        """
        return self.page(
            "Клиенты клуба",
            f"""
            <section class="hero">
              <div>
                <p class="eyebrow">CRM</p>
                <h1>Клиенты</h1>
                <p class="muted">Все, кто запускал бот. Фильтруй по статусу, типу участника и сроку доступа. В таблице показываются первые 120 записей по выбранным фильтрам.</p>
              </div>
            </section>
            <section class="segment-strip">
              {self.render_smart_segments(status_filter=status_filter, type_filter=type_filter, expiring_days=expiring_days)}
            </section>
            <section class="stats compact-stats">
              <div><b>{stats.get('total', 0)}</b><span>всего в базе</span></div>
              <div><b>{stats.get('members', 0)}</b><span>в клубе</span></div>
              <div><b>{stats.get('waiting', 0)}</b><span>ждут проверки</span></div>
              <div><b>{stats.get('expired', 0)}</b><span>истекшие</span></div>
              <div><b>{stats.get('free', 0)}</b><span>бесплатные</span></div>
            </section>
            <section class="filters-card">
              <form class="filters-form" method="get" action="{esc(self.url('/clients'))}">
                <label class="field"><span>Поиск</span><input name="q" value="{esc(query)}" placeholder="Имя, username или Telegram ID"></label>
                <label class="field"><span>Статус</span><select name="status_filter">{status_options}</select></label>
                <label class="field"><span>Тип</span><select name="type_filter">{type_options}</select></label>
                <label class="field"><span>Если скоро истекают</span><select name="days">{day_options}</select></label>
                <button type="submit">Применить</button>
                <a class="button secondary" href="{esc(self.url('/clients'))}">Сбросить</a>
              </form>
            </section>
            <section class="table-wrap">
              <table class="client-filter-table">
                <thead>
                  <tr><th>Участник</th><th>Статус</th><th>Оплата</th><th>LTC</th><th>Доступ</th><th>Особый</th><th>Бот</th></tr>
                  {table_filter_row}
                </thead>
                <tbody>{rows_html or '<tr><td colspan="7" class="empty">Нет клиентов под эти фильтры</td></tr>'}<tr class="client-filter-empty hidden"><td colspan="7" class="empty">Нет клиентов под эти фильтры в таблице</td></tr></tbody>
              </table>
            </section>
            """,
            active="clients",
        )

    def render_finance_page(
        self,
        *,
        finances: dict[str, object],
        finance_series: list[dict[str, object]],
        pending_payments: list[sqlite3.Row],
        mode: str,
        year: str,
        selected_month: str,
        date_from: str,
        date_to: str,
        payment_done: str | None = None,
    ) -> str:
        notice = '<div class="notice">Действие по чеку выполнено.</div>' if payment_done else ""
        return self.page(
            "Финансы клуба",
            f"""
            <section class="hero">
              <div>
                <p class="eyebrow">CRM</p>
                <h1>Финансы</h1>
                <p class="muted">Поступления, экспорт и чеки на проверке в одном разделе.</p>
              </div>
            </section>
            {notice}
            {self.render_finance_chart(finance_series)}
            {self.render_finances(finances, mode=mode, year=year, selected_month=selected_month, date_from=date_from, date_to=date_to)}
            <div id="pending">{self.render_pending_payments(pending_payments)}</div>
            """,
            active="finance",
        )

    def render_broadcasts_page(
        self,
        *,
        broadcast_logs: list[sqlite3.Row],
        templates: list[sqlite3.Row],
        broadcast_sent: str | None = None,
        broadcast_failed: str | None = None,
        test_sent: str | None = None,
        test_failed: str | None = None,
        template_saved: str | None = None,
    ) -> str:
        broadcast_preview_url = self.url("/broadcast/preview")
        broadcast_test_url = self.url("/broadcast/test")
        template_url = self.url("/broadcast/template")
        broadcast_notice = ""
        if broadcast_sent is not None:
            broadcast_notice = (
                f'<div class="notice">Рассылка завершена: отправлено {esc(broadcast_sent)}, '
                f'ошибок {esc(broadcast_failed or "0")}.</div>'
            )
        if test_sent is not None:
            broadcast_notice += (
                f'<div class="notice">Тест отправлен админу: отправлено {esc(test_sent)}, '
                f'ошибок {esc(test_failed or "0")}.</div>'
            )
        if template_saved is not None:
            broadcast_notice += '<div class="notice">Шаблон сохранен.</div>' 
        status_filter_options = "".join(
            f'<option value="{esc(key)}">{esc(label)}</option>'
            for key, label in BROADCAST_STATUS_FILTERS.items()
        )
        type_filter_options = "".join(
            f'<option value="{esc(key)}">{esc(label)}</option>'
            for key, label in BROADCAST_TYPE_FILTERS.items()
        )
        return self.page(
            "Рассылки клуба",
            f"""
            <section class="hero">
              <div>
                <p class="eyebrow">CRM</p>
                <h1>Рассылки</h1>
                <p class="muted">Сегментируй аудиторию фильтрами и отправляй только после предпросмотра.</p>
              </div>
            </section>
            {broadcast_notice}
            <section class="broadcast-card full">
              <div>
                <p class="eyebrow">Сообщение в бот</p>
                <h2>Новая рассылка</h2>
                <p class="muted">Отправка идет от имени клубного Telegram-бота. Твой админский аккаунт не включается.</p>
              </div>
              <form class="broadcast-form" method="post" action="{esc(broadcast_preview_url)}">
                <div class="filter-grid">
                  <label class="field"><span>Состояние</span><select name="status_filter" required>{status_filter_options}</select></label>
                  <label class="field"><span>Тип участника</span><select name="type_filter" required>{type_filter_options}</select></label>
                </div>
                <p class="muted small">Например: “Активировал бот, но не состоит в клубе” + “Все особенные”.</p>
                <textarea id="broadcast-message" name="message" rows="6" maxlength="4096" placeholder="Текст сообщения..." required></textarea>
                <div class="button-row">
                  <button type="submit">Предпросмотр</button>
                  <button class="secondary-button" type="submit" formaction="{esc(broadcast_test_url)}">Отправить тест себе</button>
                </div>
              </form>
            </section>
            {self.render_broadcast_templates(templates, template_url)}
            {self.render_broadcast_history(broadcast_logs)}
            """,
            active="broadcasts",
        )

    def render_pending_payments(self, payments: list[sqlite3.Row], *, compact: bool = False) -> str:
        rows: list[str] = []
        for payment in payments:
            user_url = self.url(f"/user/{int(payment['telegram_id'])}")
            approve_url = self.url(f"/payment/{int(payment['id'])}/approve")
            reject_url = self.url(f"/payment/{int(payment['id'])}/reject")
            actions = "" if compact else f"""
                <form method="post" action="{esc(approve_url)}">
                  <input type="hidden" name="comment" value="Подтверждено через CRM">
                  <button type="submit">Подтвердить</button>
                </form>
                <form method="post" action="{esc(reject_url)}">
                  <input type="hidden" name="comment" value="Отклонено через CRM">
                  <button class="danger" type="submit">Отклонить</button>
                </form>
            """
            rows.append(
                f"""
                <tr>
                  <td>{esc(format_dt(payment['created_at']))}</td>
                  <td><a class="name" href="{esc(user_url)}">{esc(payment['full_name'])}</a><span class="sub">{esc('@' + payment['username'] if payment['username'] else 'без username')}</span></td>
                  <td><strong>{esc(payment['amount_label'])}</strong><span class="sub">{esc(payment['receipt_text'] or payment['receipt_type'] or 'чек без текста')}</span></td>
                  <td><div class="payment-actions">{actions}<a class="button secondary mini-button" href="{esc(user_url)}">Карточка</a></div></td>
                </tr>
                """
            )
        title = "Чеки на проверке"
        empty = "Чеков на проверке нет"
        if compact:
            compact_parts: list[str] = []
            for payment in payments:
                compact_user_url = self.url(f"/user/{int(payment['telegram_id'])}")
                compact_parts.append(
                    f"""
                    <tr>
                      <td>{esc(format_dt(payment['created_at']))}</td>
                      <td><a class="name" href="{esc(compact_user_url)}">{esc(payment['full_name'])}</a><span class="sub">{esc(payment['amount_label'])}</span></td>
                      <td><span class="sub">{esc(payment['receipt_text'] or payment['receipt_type'] or 'чек без текста')}</span></td>
                    </tr>
                    """
                )
            compact_rows = "".join(compact_parts)
            return f"""
            <section class="history-card pending-card compact-pending">
              <div class="section-head"><div><p class="eyebrow">Оплаты</p><h2>{title}</h2></div><span class="counter">{len(payments)}</span></div>
              <div class="table-wrap compact dashboard-table">
                <table>
                  <thead><tr><th>Дата</th><th>Участник</th><th>Чек</th></tr></thead>
                  <tbody>{compact_rows or f'<tr><td colspan="3" class="empty">{empty}</td></tr>'}</tbody>
                </table>
              </div>
            </section>
            """
        return f"""
        <section class="history-card pending-card">
          <div class="section-head"><div><p class="eyebrow">Оплаты</p><h2>{title}</h2></div><span class="counter">{len(payments)}</span></div>
          <div class="table-wrap compact">
            <table>
              <thead><tr><th>Дата</th><th>Участник</th><th>Чек</th><th>Действия</th></tr></thead>
              <tbody>{''.join(rows) or f'<tr><td colspan="4" class="empty">{empty}</td></tr>'}</tbody>
            </table>
          </div>
        </section>
        """

    def render_dashboard(
        self,
        *,
        view: str,
        query: str,
        month: str,
        expiring_days: int,
        rows: list[sqlite3.Row],
        stats: dict[str, int],
        finances: dict[str, object],
        broadcast_counts: dict[str, int],
        broadcast_logs: list[sqlite3.Row],
        broadcast_sent: str | None = None,
        broadcast_failed: str | None = None,
    ) -> str:
        tabs = [
            ("members", "Кто в клубе"),
            ("activated", "Активировали бот"),
            ("special", "Особые"),
            ("waiting", "Чеки на проверке"),
            ("expiring", "Скоро истекают"),
            ("expired", "Истекшие"),
            ("finance", "Финансы"),
        ]
        tab_parts: list[str] = []
        for key, label in tabs:
            href = self.url(
                "/",
                view=key,
                q=query,
                month=month if key == "finance" else "",
                days=expiring_days if key == "expiring" else "",
            )
            tab_parts.append(f'<a class="tab {"active" if key == view else ""}" href="{esc(href)}">{esc(label)}</a>')
        tab_html = "".join(tab_parts)
        rows_html = "".join(self.render_user_row(row) for row in rows)
        broadcast_preview_url = self.url("/broadcast/preview")
        broadcast_notice = ""
        if broadcast_sent is not None:
            broadcast_notice = (
                f'<div class="notice">Рассылка завершена: отправлено {esc(broadcast_sent)}, '
                f'ошибок {esc(broadcast_failed or "0")}.</div>'
            )
        status_filter_options = "".join(
            f'<option value="{esc(key)}">{esc(label)}</option>'
            for key, label in BROADCAST_STATUS_FILTERS.items()
        )
        type_filter_options = "".join(
            f'<option value="{esc(key)}">{esc(label)}</option>'
            for key, label in BROADCAST_TYPE_FILTERS.items()
        )
        expiring_filters = ""
        if view == "expiring":
            filter_parts: list[str] = []
            for days in (1, 3, 5, 7):
                href = self.url("/", view="expiring", days=days)
                filter_parts.append(f'<a class="tab {"active" if days == expiring_days else ""}" href="{esc(href)}">{days} дн.</a>')
            expiring_filters = f'<nav class="tabs mini">{"".join(filter_parts)}</nav>'
        main_content = (
            self.render_finances(finances)
            if view == "finance"
            else f"""
            {expiring_filters}
            <section class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Участник</th>
                    <th>Статус</th>
                    <th>Оплата</th>
                    <th>LTC</th>
                    <th>Доступ</th>
                    <th>Особый</th>
                    <th>Бот</th>
                  </tr>
                </thead>
                <tbody>{rows_html or '<tr><td colspan="7" class="empty">Нет записей</td></tr>'}</tbody>
              </table>
            </section>
            """
        )
        return self.page(
            "Админка клуба Nastaunik",
            f"""
            <section class="hero">
              <div>
                <p class="eyebrow">Nastaunik club</p>
                <h1>Админка клуба</h1>
                <p class="muted">Участники, активации бота, оплаты и особые отметки в одном месте.</p>
              </div>
              <form class="search" method="get" action="{esc(self.url("/"))}">
                <input type="hidden" name="view" value="{esc(view)}">
                <input name="q" value="{esc(query)}" placeholder="Имя, username или Telegram ID">
                <button type="submit">Найти</button>
              </form>
            </section>
            <section class="stats">
              <div><b>{stats.get("members", 0)}</b><span>в клубе</span></div>
              <div><b>{stats.get("total", 0)}</b><span>запускали бот</span></div>
              <div><b>{stats.get("waiting", 0)}</b><span>чеков на проверке</span></div>
              <div><b>{stats.get("special", 0)}</b><span>особых</span></div>
              <div><b>{stats.get("free", 0)}</b><span>бесплатных</span></div>
            </section>
            {broadcast_notice}
            <section class="broadcast-card">
              <div>
                <p class="eyebrow">Сообщение в бот</p>
                <h2>Рассылка участникам</h2>
                <p class="muted">Отправка идет от имени клубного Telegram-бота. Твой админский аккаунт не включается.</p>
              </div>
              <form class="broadcast-form" method="post" action="{esc(broadcast_preview_url)}">
                <div class="filter-grid">
                  <label class="field">
                    <span>Состояние</span>
                    <select name="status_filter" required>{status_filter_options}</select>
                  </label>
                  <label class="field">
                    <span>Тип участника</span>
                    <select name="type_filter" required>{type_filter_options}</select>
                  </label>
                </div>
                <p class="muted small">Примеры: “Активировал бот, но не состоит в клубе” + “Любой тип”; или “Активировал бот, но не состоит в клубе” + “Все особенные”.</p>
                <textarea name="message" rows="5" maxlength="4096" placeholder="Текст сообщения..." required></textarea>
                <button type="submit">Предпросмотр</button>
              </form>
            </section>
            {self.render_broadcast_history(broadcast_logs)}
            <nav class="tabs">{tab_html}</nav>
            {main_content}
            """,
        )

    def render_broadcast_preview(
        self,
        *,
        status_filter: str,
        type_filter: str,
        message: str,
        recipients_count: int,
    ) -> str:
        filter_label = self.broadcast_filter_label(status_filter, type_filter)
        return self.page(
            "Предпросмотр рассылки",
            f"""
            <p><a class="back" href="{esc(self.url("/broadcasts"))}">← Назад к рассылкам</a></p>
            <section class="preview-card">
              <p class="eyebrow">Проверь перед отправкой</p>
              <h1>Предпросмотр рассылки</h1>
              <div class="details">
                <div><span>Кому</span><b>{esc(filter_label)}</b></div>
                <div><span>Получателей</span><b>{recipients_count}</b></div>
                <div><span>Длина</span><b>{len(message)} символов</b></div>
              </div>
              <div class="message-preview">{esc(message).replace(chr(10), "<br>")}</div>
              <form class="confirm-form" method="post" action="{esc(self.url("/broadcast"))}">
                <input type="hidden" name="status_filter" value="{esc(status_filter)}">
                <input type="hidden" name="type_filter" value="{esc(type_filter)}">
                <input type="hidden" name="message" value="{esc(message)}">
                <input type="hidden" name="confirm" value="1">
                <a class="button secondary" href="{esc(self.url("/broadcasts"))}">Отмена</a>
                <button type="submit">Да, отправить</button>
              </form>
            </section>
            """,
            active="broadcasts",
        )

    def render_broadcast_history(self, logs: list[sqlite3.Row]) -> str:
        rows = "".join(
            f"""
            <tr>
              <td>{esc(format_dt(log["created_at"]))}</td>
              <td>{esc(AUDIENCE_LABELS.get(log["audience"], log["audience"]))}</td>
              <td>{int(log["recipients_count"])}</td>
              <td>{int(log["sent_count"])}</td>
              <td>{int(log["failed_count"])}</td>
              <td><span class="sub">{esc(str(log["message"])[:140])}</span></td>
            </tr>
            """
            for log in logs
        )
        return f"""
        <section class="history-card">
          <h2>История рассылок</h2>
          <div class="table-wrap compact">
            <table>
              <thead><tr><th>Дата</th><th>Кому</th><th>Получ.</th><th>Ок</th><th>Ошибки</th><th>Текст</th></tr></thead>
              <tbody>{rows or '<tr><td colspan="6" class="empty">Рассылок пока не было</td></tr>'}</tbody>
            </table>
          </div>
        </section>
        """

    def render_personal_message_preview(self, *, user: sqlite3.Row, message: str) -> str:
        telegram_id = int(user["telegram_id"])
        user_url = self.url(f"/user/{telegram_id}")
        message_url = self.url(f"/user/{telegram_id}/message")
        return self.page(
            "Предпросмотр личного сообщения",
            f"""
            <p><a class="back" href="{esc(user_url)}">← Назад к пользователю</a></p>
            <section class="preview-card">
              <p class="eyebrow">Личное сообщение</p>
              <h1>Предпросмотр сообщения</h1>
              <div class="details">
                <div><span>Кому</span><b>{esc(user["full_name"])}</b></div>
                <div><span>Username</span><b>{esc("@" + user["username"] if user["username"] else "без username")}</b></div>
                <div><span>Telegram ID</span><b>{telegram_id}</b></div>
              </div>
              <div class="message-preview">{esc(message).replace(chr(10), "<br>")}</div>
              <form class="confirm-form" method="post" action="{esc(message_url)}">
                <input type="hidden" name="message" value="{esc(message)}">
                <input type="hidden" name="confirm" value="1">
                <a class="button secondary" href="{esc(user_url)}">Отмена</a>
                <button type="submit">Да, отправить</button>
              </form>
            </section>
            """,
            active="clients",
        )

    def render_finances(
        self,
        finances: dict[str, object],
        *,
        mode: str = "month",
        year: str = "",
        selected_month: str | None = None,
        date_from: str = "",
        date_to: str = "",
    ) -> str:
        totals = finances.get("totals", {})
        counts = finances.get("counts", {})
        selected_month = selected_month or str(finances.get("selected_month") or current_month_key())
        available_months = finances.get("available_months", [])
        available_years = finances.get("available_years", [])
        selected_payments = finances.get("selected_payments", [])
        period_label = str(finances.get("period_label") or month_label(selected_month))
        if not isinstance(totals, dict):
            totals = {}
        if not isinstance(counts, dict):
            counts = {}
        if not isinstance(available_months, list):
            available_months = [selected_month]
        if not isinstance(available_years, list):
            available_years = [current_month_key()[:4]]
        if not isinstance(selected_payments, list):
            selected_payments = []
        if mode not in {"month", "year", "range"}:
            mode = "month"
        selected_year = year if re.fullmatch(r"\d{4}", year) else selected_month[:4]

        cards = [
            ("Выбранный период", "selected_month"),
            ("Сегодня", "today"),
            ("7 дней", "week"),
            ("Всего", "all"),
        ]
        cards_html = "".join(
            f"""
            <div>
              <b>{esc(format_money(float(totals.get(key, 0.0))))}</b>
              <span>{esc(label)} · оплат: {int(counts.get(key, 0))}</span>
            </div>
            """
            for label, key in cards
        )
        month_options = "".join(
            f'<option value="{esc(month)}" {"selected" if month == selected_month else ""}>{esc(month_label(month))}</option>'
            for month in available_months
        )
        year_options = "".join(
            f'<option value="{esc(item)}" {"selected" if item == selected_year else ""}>{esc(item)}</option>'
            for item in available_years
        )
        row_parts: list[str] = []
        for payment in selected_payments:
            user_url = self.url(f"/user/{int(payment['telegram_id'])}")
            row_parts.append(
                f"""
            <tr>
              <td>{esc(format_dt(payment["confirmed_at"]))}</td>
              <td>
                <a class="name" href="{esc(user_url)}">{esc(payment["full_name"])}</a>
                <span class="sub">{esc("@" + payment["username"] if payment["username"] else "без username")}</span>
              </td>
              <td><strong>{esc(payment["amount_label"])}</strong></td>
              <td>{esc(payment["admin_comment"] or "—")}</td>
            </tr>
            """
            )
        rows_html = "".join(row_parts)
        export_url = self.url("/finance/export.csv", mode=mode, year=selected_year, month=selected_month, **{"from": date_from, "to": date_to})
        return f"""
        <section class="finance-card">
          <div class="finance-head">
            <div>
              <p class="eyebrow">Поступления</p>
              <h2>Деньги клуба</h2>
              <p class="muted">Считаются подтвержденные оплаты по дате подтверждения. Сумма берется из тарифа платежа.</p>
            </div>
          </div>
          <form class="finance-filter-form" method="get" action="{esc(self.url('/finance'))}">
            <label class="field"><span>Режим</span><select name="mode"><option value="month" {"selected" if mode == "month" else ""}>Месяц</option><option value="year" {"selected" if mode == "year" else ""}>Год</option><option value="range" {"selected" if mode == "range" else ""}>Диапазон дат</option></select></label>
            <label class="field"><span>Месяц</span><select name="month">{month_options}</select></label>
            <label class="field"><span>Год</span><select name="year">{year_options}</select></label>
            <label class="field"><span>С даты</span><input type="date" name="from" value="{esc(date_from)}"></label>
            <label class="field"><span>По дату</span><input type="date" name="to" value="{esc(date_to)}"></label>
            <button type="submit">Показать</button>
          </form>
          <p><a class="button secondary" href="{esc(export_url)}">Скачать CSV за период</a></p>
          <div class="money-stats">{cards_html}</div>
          <h2>{esc(period_label)}</h2>
          <div class="table-wrap compact">
            <table>
              <thead><tr><th>Дата</th><th>Участник</th><th>Сумма</th><th>Комментарий</th></tr></thead>
              <tbody>{rows_html or '<tr><td colspan="4" class="empty">В этом периоде поступлений нет</td></tr>'}</tbody>
            </table>
          </div>
        </section>
        """

    def render_user_row(self, row: sqlite3.Row) -> str:
        username = row["username"]
        special = special_label(row)
        special_star = '<span class="star" title="Особый участник">★</span> ' if special else ""
        status = STATUS_LABELS.get(row["current_status"], row["current_status"])
        status_class = "good" if is_in_club(row) else "warn" if row["current_status"] == "waiting_confirmation" else "quiet"
        detail_url = self.url(f"/user/{int(row['telegram_id'])}")
        pending_actions = ""
        try:
            pending_payment_id = int(row["pending_payment_id"]) if row["pending_payment_id"] else 0
        except (IndexError, TypeError, ValueError):
            pending_payment_id = 0
        paid_at = row["last_paid_at"] or row["payment_confirmed_at"]
        payment_filter = "pending" if pending_payment_id else "paid" if paid_at else "no_payment"
        access_filter = "none"
        if row["access_end_at"]:
            try:
                access_end = datetime.fromisoformat(str(row["access_end_at"]))
                today = datetime.utcnow().date()
                if access_end.date() < today or row["current_status"] == "expired":
                    access_filter = "expired"
                elif access_end.date() <= today + timedelta(days=7):
                    access_filter = "expiring"
                else:
                    access_filter = "active"
            except ValueError:
                access_filter = "none"
        elif is_in_club(row):
            access_filter = "active"
        status_filter = "active" if is_in_club(row) else row["current_status"] or "not_in_club"
        if status_filter not in {"active", "waiting_confirmation", "expired"}:
            status_filter = "not_in_club"
        special_filter = "free" if int(row["is_lifetime_free"] or 0) else "special" if special else "regular"
        bot_filter = "activated" if row["created_at"] else ""
        name_filter = f"{row['full_name']} @{username or ''} {int(row['telegram_id'])}".strip().lower()
        try:
            amount_labels = str(row["payment_amount_labels"] or "")
        except (IndexError, KeyError):
            amount_labels = ""
        ltc_total = sum(parse_amount(label) for label in amount_labels.split("||") if label)
        if pending_payment_id:
            approve_url = self.url(f"/payment/{pending_payment_id}/approve")
            reject_url = self.url(f"/payment/{pending_payment_id}/reject")
            pending_actions = f"""
            <div class="payment-actions">
              <span class="sub">{esc(row["pending_receipt_text"] or "чек без текста")}</span>
              <form method="post" action="{esc(approve_url)}">
                <input type="hidden" name="comment" value="Подтверждено через веб-админку">
                <button type="submit">Подтвердить</button>
              </form>
              <form method="post" action="{esc(reject_url)}">
                <input type="hidden" name="comment" value="Отклонено через веб-админку">
                <button class="danger" type="submit">Отклонить</button>
              </form>
            </div>
            """
        return f"""
        <tr
          data-filter-name="{esc(name_filter)}"
          data-filter-status="{esc(status_filter)}"
          data-filter-payment="{esc(payment_filter)}"
          data-filter-access="{esc(access_filter)}"
          data-filter-special="{esc(special_filter)}"
          data-filter-bot="{esc(bot_filter)}"
        >
          <td>
            <a class="name" href="{esc(detail_url)}">{special_star}{esc(row["full_name"])}</a>
            <span class="sub">{esc("@" + username if username else "без username")} · ID {int(row["telegram_id"])}</span>
          </td>
          <td><span class="pill {status_class}">{esc(status)}</span></td>
          <td>
            <strong>{esc(format_date(row["last_paid_at"] or row["payment_confirmed_at"]))}</strong>
            <span class="sub">{esc(row["last_amount_label"] or row["recurring_amount_label"] or DEFAULT_AMOUNT_LABEL)}</span>
            {pending_actions}
          </td>
          <td>
            <strong>{esc(format_money(ltc_total))}</strong>
            <span class="sub">{int(row["payments_count"] or 0)} оплат</span>
          </td>
          <td>
            <strong>до {esc(format_date(row["access_end_at"]))}</strong>
            <span class="sub">актуальный срок</span>
          </td>
          <td>{f'<span class="pill special">{esc(special)}</span>' if special else '<span class="sub">—</span>'}</td>
          <td><span class="sub">с {esc(format_date(row["created_at"]))}</span></td>
        </tr>
        """

    def render_user_detail(
        self,
        user: sqlite3.Row,
        payments: list[sqlite3.Row],
        action_logs: list[sqlite3.Row],
        *,
        club_status: str = "не проверено",
        saved: bool = False,
        restore_sent: str | None = None,
        restore_failed: str | None = None,
        message_sent: str | None = None,
        message_failed: str | None = None,
    ) -> str:
        saved_banner = '<div class="notice">Оплата внесена вручную, доступ обновлен.</div>' if saved else ""
        restore_banner = ""
        if restore_sent is not None:
            restore_banner = (
                f'<div class="notice">Ссылка для возврата отправлена: {esc(restore_sent)}; '
                f'ошибок: {esc(restore_failed or "0")}.</div>'
            )
        message_banner = ""
        if message_sent is not None:
            message_banner = (
                f'<div class="notice">Личное сообщение: отправлено {esc(message_sent)}, '
                f'ошибок {esc(message_failed or "0")}.</div>'
            )
        payment_rows = "".join(
            f"""
            <tr>
              <td>#{int(payment["id"])}</td>
              <td>{esc(payment["status"])}</td>
              <td>{esc(payment["amount_label"])}</td>
              <td>{esc(format_dt(payment["created_at"]))}</td>
              <td>{esc(format_dt(payment["confirmed_at"]))}</td>
              <td>{esc(payment["receipt_text"] or "")}</td>
            </tr>
            """
            for payment in payments
        )
        approved_payments = [payment for payment in payments if payment["status"] == "approved"]
        ltc_total = sum(parse_amount(payment["amount_label"]) for payment in approved_payments)
        events: list[tuple[str, str, str, str]] = []
        for payment in payments:
            if payment["created_at"]:
                events.append(
                    (
                        payment["created_at"],
                        "Чек отправлен",
                        "payment_created",
                        f"Платеж #{int(payment['id'])}; {payment['amount_label']}; {payment['receipt_text'] or 'без текста'}",
                    )
                )
            if payment["confirmed_at"]:
                events.append(
                    (
                        payment["confirmed_at"],
                        "Оплата подтверждена",
                        "payment_confirmed",
                        f"Платеж #{int(payment['id'])}; {payment['amount_label']}",
                    )
                )
            if payment["rejected_at"]:
                events.append(
                    (
                        payment["rejected_at"],
                        "Оплата отклонена",
                        "payment_rejected",
                        f"Платеж #{int(payment['id'])}; {payment['admin_comment'] or 'без комментария'}",
                    )
                )
        for action in action_logs:
            events.append((action["created_at"], action["title"], action["action_type"], action["details"] or "—"))
        if user["current_status"] == "expired":
            events.append(
                (
                    user["updated_at"],
                    "Доступ истек",
                    "access_expired",
                    "Пользователь отмечен как истекший; бот должен удалить его из клуба автоматически.",
                )
            )
        events.sort(key=lambda item: item[0] or "", reverse=True)
        action_rows = "".join(
            f"""
            <tr>
              <td>{esc(format_dt(created_at))}</td>
              <td><strong>{esc(title)}</strong><span class="sub">{esc(action_type)}</span></td>
              <td>{esc(details)}</td>
            </tr>
            """
            for created_at, title, action_type, details in events[:60]
        )
        username = user["username"]
        telegram_link = f"https://t.me/{username}" if username else f"tg://user?id={int(user['telegram_id'])}"
        today = datetime.utcnow().date().isoformat()
        amount_label = user["recurring_amount_label"] or DEFAULT_AMOUNT_LABEL
        manual_payment_url = self.url(f"/user/{int(user['telegram_id'])}/manual-payment")
        restore_access_url = self.url(f"/user/{int(user['telegram_id'])}/restore-access")
        personal_message_preview_url = self.url(f"/user/{int(user['telegram_id'])}/message/preview")
        return self.page(
            str(user["full_name"]),
            f"""
            <p><a class="back" href="{esc(self.url("/clients"))}">← Назад к клиентам</a></p>
            {saved_banner}
            {restore_banner}
            {message_banner}
            <section class="profile">
              <div>
                <p class="eyebrow">Участник</p>
                <h1>{esc(user["full_name"])}</h1>
                <p class="muted">{esc("@" + username if username else "без username")} · ID {int(user["telegram_id"])}</p>
              </div>
              <a class="button" href="{esc(telegram_link)}">Открыть в Telegram</a>
            </section>
            <section class="details">
              <div><span>Статус</span><b>{esc(STATUS_LABELS.get(user["current_status"], user["current_status"]))}</b></div>
              <div><span>Оплата</span><b>{esc(format_dt(user["payment_confirmed_at"]))}</b></div>
              <div><span>Доступ</span><b>{esc(format_date(user["access_start_at"]))} - {esc(format_date(user["access_end_at"]))}</b></div>
              <div><span>В Telegram-клубе</span><b>{esc(club_status)}</b></div>
              <div><span>Бот активирован</span><b>да, {esc(format_dt(user["created_at"]))}</b></div>
              <div><span>Особый</span><b>{esc(special_label(user) or "нет")}</b></div>
              <div><span>Вечно бесплатный</span><b>{'да' if int(user["is_lifetime_free"] or 0) else 'нет'}</b></div>
              <div><span>Тариф</span><b>{esc(user["recurring_amount_label"] or DEFAULT_AMOUNT_LABEL)}</b></div>
              <div><span>LTC</span><b>{esc(format_money(ltc_total))}</b></div>
              <div><span>Оплат всего</span><b>{len(payments)}</b></div>
              <div><span>Подтвержденных оплат</span><b>{len(approved_payments)}</b></div>
              <div><span>Комментарий</span><b>{esc(user["admin_comment"] or "—")}</b></div>
            </section>
            <section class="restore-card">
              <div>
                <b>Вернуть в клуб</b>
                <span>Если оплаченного пользователя удалило из чата, бот снимет возможный бан и отправит кнопку входа.</span>
              </div>
              <form method="post" action="{esc(restore_access_url)}">
                <button type="submit">Отправить ссылку для возврата</button>
              </form>
            </section>
            <h2>Написать пользователю</h2>
            <section class="manual-card">
              <form class="personal-form" method="post" action="{esc(personal_message_preview_url)}">
                <textarea name="message" rows="4" maxlength="4096" placeholder="Текст личного сообщения..." required></textarea>
                <button type="submit">Предпросмотр</button>
              </form>
            </section>
            <h2>Внести оплату вручную</h2>
            <section class="manual-card">
              <form class="manual-form" method="post" action="{esc(manual_payment_url)}">
                <label>
                  <span>Дата оплаты</span>
                  <input type="date" name="paid_at" value="{esc(today)}" required>
                </label>
                <label>
                  <span>Тариф / сумма</span>
                  <input name="amount_label" value="{esc(amount_label)}" required>
                </label>
                <label>
                  <span>Дней доступа</span>
                  <input type="number" name="access_days" value="30" min="1" max="370" required>
                </label>
                <label class="wide">
                  <span>Комментарий</span>
                  <input name="note" value="Внесено вручную через веб-админку">
                </label>
                <button type="submit">Записать оплату</button>
              </form>
            </section>
            <h2>История оплат</h2>
            <section class="table-wrap">
              <table>
                <thead><tr><th>ID</th><th>Статус</th><th>Сумма</th><th>Создан</th><th>Подтвержден</th><th>Текст</th></tr></thead>
                <tbody>{payment_rows or '<tr><td colspan="6" class="empty">Платежей нет</td></tr>'}</tbody>
              </table>
            </section>
            <h2>Журнал действий</h2>
            <section class="table-wrap compact">
              <table>
                <thead><tr><th>Дата</th><th>Действие</th><th>Детали</th></tr></thead>
                <tbody>{action_rows or '<tr><td colspan="3" class="empty">Действий пока нет</td></tr>'}</tbody>
              </table>
            </section>
            """,
            active="clients",
        )

    def page(self, title: str, content: str, *, active: str = "dashboard") -> str:
        nav_items = [
            ("dashboard", "Главная", self.url("/")),
            ("clients", "Клиенты", self.url("/clients")),
            ("finance", "Финансы", self.url("/finance")),
            ("broadcasts", "Рассылки", self.url("/broadcasts")),
            ("learning", "Обучение", self.url("/learning")),
        ]
        nav_html = "".join(
            f'<a class="side-link {"active" if key == active else ""}" href="{esc(href)}">{esc(label)}</a>'
            for key, label, href in nav_items
        )
        return f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{esc(title)}</title>
  <style>
    :root {{
      --bg: #f4f1ea;
      --ink: #20231f;
      --muted: #6e7369;
      --line: #d8d1c2;
      --paper: #fffaf1;
      --green: #1d7b50;
      --green-soft: #dceee5;
      --amber: #9c641f;
      --amber-soft: #f4e1be;
      --blue-soft: #dbe7ef;
    }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--ink); font: 15px/1.45 Georgia, 'Times New Roman', serif; }}
    .app-shell {{ display: grid; grid-template-columns: 230px 1fr; min-height: 100vh; }}
    .sidebar {{ position: sticky; top: 0; height: 100vh; padding: 24px 18px; background: #20231f; color: #fffaf1; border-right: 1px solid #10120f; }}
    .brand {{ display: block; margin-bottom: 28px; color: #fffaf1; text-decoration: none; }}
    .brand b {{ display: block; font-size: 23px; line-height: 1; }}
    .brand span {{ display: block; margin-top: 6px; color: #c8d8bd; font: 12px Verdana, sans-serif; }}
    .side-nav {{ display: grid; gap: 8px; }}
    .side-link {{ display: block; padding: 11px 12px; color: #e8e1d4; text-decoration: none; border: 1px solid transparent; font: 700 13px Verdana, sans-serif; }}
    .side-link:hover, .side-link.active {{ background: #fffaf1; color: #20231f; border-color: #d8d1c2; }}
    .content {{ min-width: 0; }}
    main {{ width: min(1220px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 48px; }}
    .hero, .profile {{ display: flex; justify-content: space-between; align-items: end; gap: 18px; padding: 24px 0; border-bottom: 1px solid var(--line); }}
    h1 {{ margin: 0; font-size: 36px; line-height: 1.05; letter-spacing: 0; }}
    h2 {{ margin: 28px 0 12px; font-size: 22px; }}
    .eyebrow {{ margin: 0 0 8px; color: var(--green); text-transform: uppercase; font: 700 12px/1.2 Verdana, sans-serif; letter-spacing: 0; }}
    .muted, .sub {{ color: var(--muted); }}
    .small {{ font-size: 13px; margin: 0; }}
    .sub {{ display: block; font-size: 13px; margin-top: 3px; }}
    .search {{ display: flex; gap: 8px; }}
    input, textarea, select {{ min-width: 280px; padding: 11px 12px; border: 1px solid var(--line); background: var(--paper); color: var(--ink); font: inherit; }}
    textarea {{ width: 100%; min-width: 0; resize: vertical; }}
    select {{ width: 100%; min-width: 0; }}
    button, .button {{ padding: 11px 14px; border: 0; background: var(--green); color: white; text-decoration: none; font: 700 14px Verdana, sans-serif; cursor: pointer; }}
    .button.secondary {{ background: #7b6c58; display: inline-block; }}
    button.danger {{ background: #9a3d2f; }}
    .hero-actions {{ display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }}
    .stats {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin: 18px 0; }}
    .stats div, .details div {{ background: var(--paper); border: 1px solid var(--line); padding: 14px; }}
    .stats b {{ display: block; font-size: 28px; }}
    .stats span, .details span {{ color: var(--muted); font: 12px Verdana, sans-serif; }}
    .stats small {{ display: block; color: var(--muted); font: 11px Verdana, sans-serif; margin-top: 5px; }}
    .dashboard-stats {{ grid-template-columns: repeat(4, minmax(0, 1fr)); }}
    .dashboard-stats div:first-child {{ background: #20362b; border-color: #20362b; color: #fffaf1; }}
    .dashboard-stats div:first-child span, .dashboard-stats div:first-child small {{ color: #dceee5; }}
    .tabs {{ display: flex; gap: 8px; flex-wrap: wrap; margin: 18px 0; }}
    .tab {{ padding: 9px 11px; border: 1px solid var(--line); color: var(--ink); text-decoration: none; background: var(--paper); font: 13px Verdana, sans-serif; }}
    .tab.active {{ background: var(--green); color: white; border-color: var(--green); }}
    .table-wrap {{ overflow-x: auto; background: var(--paper); border: 1px solid var(--line); }}
    table {{ width: 100%; border-collapse: collapse; min-width: 900px; }}
    th, td {{ text-align: left; padding: 13px 12px; border-bottom: 1px solid var(--line); vertical-align: top; }}
    th {{ color: var(--muted); font: 700 12px Verdana, sans-serif; background: #f8f0df; }}
    .column-filter-row th {{ padding: 8px 10px; background: #fffaf1; }}
    .column-filter {{ width: 100%; min-width: 0; padding: 8px 9px; border: 1px solid var(--line); background: #f8f0df; color: var(--ink); font: 12px Verdana, sans-serif; }}
    .column-filter:focus {{ outline: 2px solid #9cc9b1; outline-offset: -2px; background: white; }}
    .client-filter-empty.hidden {{ display: none; }}
    .name {{ color: var(--ink); font-weight: 700; text-decoration: none; }}
    .star {{ color: var(--amber); font: 700 14px Verdana, sans-serif; }}
    .pill {{ display: inline-block; padding: 4px 8px; border-radius: 6px; font: 700 12px Verdana, sans-serif; }}
    .pill.good {{ background: var(--green-soft); color: var(--green); }}
    .pill.warn {{ background: var(--amber-soft); color: var(--amber); }}
    .pill.quiet {{ background: var(--blue-soft); color: #305168; }}
    .pill.special {{ background: #20231f; color: #fffaf1; }}
    .empty {{ text-align: center; color: var(--muted); padding: 28px; }}
    .details {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin: 18px 0; }}
    .details b {{ display: block; margin-top: 6px; }}
    .manual-card {{ background: var(--paper); border: 1px solid var(--line); padding: 14px; }}
    .manual-form {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; align-items: end; }}
    .manual-form label span {{ display: block; color: var(--muted); font: 12px Verdana, sans-serif; margin-bottom: 5px; }}
    .manual-form .wide {{ grid-column: span 2; }}
    .manual-form input {{ width: 100%; min-width: 0; }}
    .payment-actions {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
    .payment-actions .sub {{ flex-basis: 100%; }}
    .payment-actions button {{ padding: 7px 9px; font-size: 12px; }}
    .broadcast-card {{ display: grid; grid-template-columns: 0.8fr 1.2fr; gap: 18px; background: var(--paper); border: 1px solid var(--line); padding: 16px; margin: 18px 0; }}
    .finance-card {{ background: var(--paper); border: 1px solid var(--line); padding: 16px; margin: 18px 0; }}
    .history-card {{ background: var(--paper); border: 1px solid var(--line); padding: 16px; margin: 18px 0; }}
    .history-card h2 {{ margin-top: 0; }}
    .preview-card {{ background: var(--paper); border: 1px solid var(--line); padding: 20px; margin: 18px 0; }}
    .message-preview {{ white-space: normal; background: #f8f0df; border: 1px solid var(--line); padding: 16px; margin: 16px 0; font-size: 17px; }}
    .confirm-form {{ display: flex; gap: 10px; justify-content: flex-end; }}
    .finance-head {{ display: flex; justify-content: space-between; align-items: end; gap: 18px; }}
    .finance-head h2 {{ margin-top: 0; }}
    .month-form {{ display: flex; align-items: end; gap: 8px; min-width: 320px; }}
    .money-stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin: 14px 0; }}
    .money-stats div {{ background: #f8f0df; border: 1px solid var(--line); padding: 14px; }}
    .money-stats b {{ display: block; font-size: 26px; }}
    .money-stats span {{ color: var(--muted); font: 12px Verdana, sans-serif; }}
    .compact table {{ min-width: 760px; }}
    .restore-card {{ display: flex; justify-content: space-between; align-items: center; gap: 14px; background: var(--green-soft); border: 1px solid #9cc9b1; padding: 14px; margin: 18px 0; }}
    .restore-card b, .restore-card span {{ display: block; }}
    .restore-card span {{ color: var(--muted); margin-top: 4px; }}
    .broadcast-card h2 {{ margin-top: 0; }}
    .broadcast-form {{ display: grid; gap: 10px; }}
    .filter-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
    .personal-form {{ display: grid; gap: 10px; }}
    .field span {{ display: block; color: var(--muted); font: 12px Verdana, sans-serif; margin-bottom: 5px; }}
    .audiences {{ display: grid; gap: 7px; }}
    .audiences label {{ display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 10px; border: 1px solid var(--line); background: #f8f0df; font: 13px Verdana, sans-serif; }}
    .audiences input {{ width: auto; min-width: 0; margin: 0 8px 0 0; }}
    .audiences span {{ color: var(--muted); margin-left: auto; }}

    .priority-card {{ background: #20362b; color: #fffaf1; border: 1px solid #20362b; padding: 18px; margin: 18px 0; }}
    .priority-card .eyebrow, .priority-card h2 {{ color: #fffaf1; }}
    .section-head.tight {{ margin: 0 0 12px; }}
    .action-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }}
    .action-item {{ display: grid; gap: 5px; min-width: 0; padding: 14px; color: inherit; text-decoration: none; background: rgba(255, 250, 241, 0.08); border: 1px solid rgba(255, 250, 241, 0.22); }}
    .action-item span {{ font: 700 12px Verdana, sans-serif; color: #dceee5; }}
    .action-item b {{ font-size: 34px; line-height: 1; }}
    .action-item small {{ color: #dceee5; font: 11px Verdana, sans-serif; }}
    .action-item.hot {{ background: #f4e1be; color: #20231f; border-color: #d09b5a; }}
    .action-item.hot span, .action-item.hot small {{ color: #7b4f18; }}
    .action-item.warn {{ background: rgba(244, 225, 190, 0.18); border-color: rgba(244, 225, 190, 0.45); }}
    .crm-grid {{ display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin: 18px 0; }}
    .crm-card {{ min-width: 0; background: var(--paper); border: 1px solid var(--line); padding: 18px; }}
    .crm-card.accent {{ background: #20362b; color: #fffaf1; border-color: #20362b; }}
    .crm-card.accent .muted, .crm-card.accent .eyebrow, .crm-card.accent .text-link {{ color: #dceee5; }}
    .crm-card h2 {{ margin: 0 0 8px; font-size: 32px; }}
    .split-grid {{ display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 0.85fr); gap: 16px; align-items: start; margin-top: 18px; }}
    .split-pane {{ min-width: 0; }}
    .dashboard-split .history-card {{ margin-top: 0; }}
    .dashboard-split .table-wrap {{ max-width: 100%; }}
    .dashboard-split table {{ min-width: 0; table-layout: fixed; }}
    .dashboard-split th, .dashboard-split td {{ padding: 12px 14px; overflow-wrap: anywhere; }}
    .dashboard-split .dashboard-table table {{ min-width: 0; }}
    .compact-pending {{ overflow: hidden; }}
    .section-head {{ display: flex; justify-content: space-between; align-items: end; gap: 12px; margin: 18px 0 10px; }}
    .section-head h2 {{ margin: 0; }}
    .text-link {{ color: var(--green); font: 700 13px Verdana, sans-serif; }}
    .counter {{ display: inline-flex; min-width: 34px; height: 34px; align-items: center; justify-content: center; background: var(--green-soft); color: var(--green); font: 700 13px Verdana, sans-serif; }}
    .filters-card {{ background: var(--paper); border: 1px solid var(--line); padding: 14px; margin: 18px 0; }}
    .filters-form, .finance-filter-form {{ display: grid; grid-template-columns: 1.3fr 1fr 1fr 1fr auto auto; gap: 10px; align-items: end; }}
    .finance-filter-form {{ grid-template-columns: 0.9fr 1fr 0.8fr 1fr 1fr auto; margin: 14px 0; }}
    .mini-button {{ padding: 7px 9px; font-size: 12px; }}
    .broadcast-card.full {{ grid-template-columns: 0.65fr 1.35fr; }}

    .two-one {{ grid-template-columns: minmax(0, 1.35fr) minmax(0, 0.65fr); }}
    .wide-card h2 {{ margin-bottom: 12px; }}
    .funnel-list {{ display: grid; gap: 10px; margin-top: 14px; }}
    .funnel-row {{ display: grid; grid-template-columns: 190px 1fr; gap: 12px; align-items: center; }}
    .funnel-row b, .funnel-row span {{ display: block; }}
    .funnel-row span {{ color: var(--muted); font: 12px Verdana, sans-serif; margin-top: 3px; }}
    .funnel-track {{ height: 12px; background: #e9dfcc; border: 1px solid var(--line); overflow: hidden; }}
    .funnel-track i {{ display: block; height: 100%; background: linear-gradient(90deg, var(--green), #9c641f); }}
    .metric-list {{ display: grid; gap: 10px; padding: 0; margin: 14px 0 0; list-style: none; }}
    .metric-list li {{ display: flex; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }}
    .metric-list span {{ color: var(--muted); }}
    .health-list {{ display: grid; gap: 9px; list-style: none; padding: 0; margin: 14px 0 0; }}
    .health-list li {{ display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 0; border-bottom: 1px solid var(--line); }}
    .health-list li:before {{ content: ""; width: 9px; height: 9px; flex: 0 0 9px; background: var(--green); border-radius: 999px; }}
    .health-list li.warn:before {{ background: var(--amber); }}
    .health-list li.bad:before {{ background: #9a3d2f; }}
    .health-list span {{ color: var(--muted); margin-right: auto; }}
    .health-list b {{ font: 700 12px Verdana, sans-serif; text-align: right; }}
    .finance-snapshot {{ background: var(--paper); border: 1px solid var(--line); padding: 16px; margin: 18px 0; }}
    .finance-grid {{ display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }}
    .finance-grid div {{ background: #f8f0df; border: 1px solid var(--line); padding: 14px; min-width: 0; }}
    .finance-grid span, .finance-grid small {{ display: block; color: var(--muted); font: 11px Verdana, sans-serif; }}
    .finance-grid b {{ display: block; font-size: 25px; margin: 5px 0; }}
    .activity-card {{ min-width: 0; margin-top: 0; }}
    .activity-list {{ display: grid; gap: 10px; list-style: none; margin: 0; padding: 0; }}
    .activity-list li {{ background: #f8f0df; border: 1px solid var(--line); padding: 12px; }}
    .activity-list div {{ display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }}
    .activity-list p {{ margin: 6px 0 4px; font-weight: 700; }}
    .activity-list span, .activity-list small {{ color: var(--muted); font: 11px Verdana, sans-serif; overflow-wrap: anywhere; }}
    .chart-card {{ background: var(--paper); border: 1px solid var(--line); padding: 16px; margin: 18px 0; }}
    .bar-chart {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; align-items: end; min-height: 180px; }}
    .chart-bar {{ display: grid; gap: 7px; text-align: center; align-items: end; }}
    .bar-track {{ height: 120px; display: flex; align-items: end; justify-content: center; background: #f8f0df; border: 1px solid var(--line); padding: 5px; }}
    .bar-track i {{ display: block; width: 100%; min-height: 4px; background: #1d7b50; }}
    .chart-bar b {{ font-size: 13px; }}
    .chart-bar span {{ color: var(--muted); font: 11px Verdana, sans-serif; }}
    .segment-strip {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0 0; }}
    .segment {{ padding: 9px 11px; background: var(--paper); border: 1px solid var(--line); color: var(--ink); text-decoration: none; font: 700 12px Verdana, sans-serif; }}
    .segment.active {{ background: var(--green); border-color: var(--green); color: white; }}
    .button-row {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .secondary-button {{ background: #7b6c58; color: white; }}
    .templates-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }}
    .template-item {{ background: #f8f0df; border: 1px solid var(--line); padding: 12px; }}
    .template-item b, .template-item span {{ display: block; }}
    .template-item span {{ color: var(--muted); font: 11px Verdana, sans-serif; margin-top: 3px; }}
    .template-item p {{ min-height: 58px; color: var(--muted); }}
    .template-form-wrap {{ margin-top: 14px; }}
    .template-form-wrap summary {{ cursor: pointer; color: var(--green); font: 700 13px Verdana, sans-serif; }}
    .template-form {{ display: grid; gap: 10px; margin-top: 12px; }}
    .notice {{ background: var(--green-soft); color: var(--green); border: 1px solid #9cc9b1; padding: 12px 14px; margin: 12px 0; font: 700 13px Verdana, sans-serif; }}
    .back {{ color: var(--green); }}
    @media (max-width: 760px) {{
      .app-shell {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; height: auto; padding: 16px 10px; }}
      .side-nav {{ grid-template-columns: repeat(2, 1fr); }}
      main {{ width: min(100% - 20px, 1180px); padding-top: 14px; }}
      .hero, .profile {{ align-items: stretch; flex-direction: column; }}
      .hero-actions {{ justify-content: stretch; }}
      .hero-actions .button {{ width: 100%; }}
      h1 {{ font-size: 30px; }}
      .search {{ flex-direction: column; }}
      input {{ min-width: 0; width: 100%; }}
      .stats, .details, .crm-grid, .split-grid, .two-one, .templates-grid {{ grid-template-columns: 1fr; }}
      .action-grid, .finance-grid {{ grid-template-columns: 1fr; }}
      .broadcast-card {{ grid-template-columns: 1fr; }}
      .filter-grid {{ grid-template-columns: 1fr; }}
      .finance-head, .month-form {{ align-items: stretch; flex-direction: column; }}
      .filters-form, .finance-filter-form, .funnel-row {{ grid-template-columns: 1fr; }}
      .bar-chart {{ grid-template-columns: repeat(2, 1fr); }}
      .month-form {{ min-width: 0; }}
      .money-stats {{ grid-template-columns: 1fr; }}
      .restore-card {{ align-items: stretch; flex-direction: column; }}
      .manual-form {{ grid-template-columns: 1fr; }}
      .manual-form .wide {{ grid-column: auto; }}
    }}
  </style>
</head>
<body>
  <div class="app-shell">
    <aside class="sidebar">
      <a class="brand" href="{esc(self.url('/'))}"><b>Nastaunik</b><span>club CRM</span></a>
      <nav class="side-nav">{nav_html}</nav>
    </aside>
    <div class="content"><main>{content}</main></div>
  </div>
  <script>
    document.querySelectorAll('[data-template]').forEach((button) => {{
      button.addEventListener('click', () => {{
        const target = document.querySelector('#broadcast-message');
        if (target) {{
          target.value = button.getAttribute('data-template') || '';
          target.focus();
        }}
      }});
    }});
    document.querySelectorAll('.client-filter-table').forEach((table) => {{
      const filters = Array.from(table.querySelectorAll('.column-filter'));
      const rows = Array.from(table.querySelectorAll('tbody tr[data-filter-name]'));
      const emptyRow = table.querySelector('.client-filter-empty');
      const applyFilters = () => {{
        let visibleCount = 0;
        rows.forEach((row) => {{
          const visible = filters.every((filter) => {{
            const key = filter.getAttribute('data-filter-key');
            const value = (filter.value || '').trim().toLowerCase();
            if (!value) {{
              return true;
            }}
            const rowValue = (row.getAttribute(`data-filter-${{key}}`) || '').toLowerCase();
            return key === 'name' ? rowValue.includes(value) : rowValue === value;
          }});
          row.style.display = visible ? '' : 'none';
          if (visible) {{
            visibleCount += 1;
          }}
        }});
        if (emptyRow) {{
          emptyRow.classList.toggle('hidden', visibleCount !== 0);
        }}
      }};
      filters.forEach((filter) => {{
        filter.addEventListener('input', applyFilters);
        filter.addEventListener('change', applyFilters);
      }});
    }});
  </script>
</body>
</html>"""


def main() -> None:
    settings = load_web_settings()
    app = ClubAdminWebApp(settings).build_app()
    web.run_app(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()



