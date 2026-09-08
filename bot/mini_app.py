from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from bot.database import Database
from bot.learning import (
    complete_lesson,
    complete_material,
    get_bootstrap,
    get_course,
    get_material,
    toggle_material_like,
)

logger = logging.getLogger(__name__)
MINI_APP_DIR = Path(__file__).resolve().parent.parent / "mini_app"
MEDIA_DIR = Path(__file__).resolve().parent.parent / "media" / "mini_app"


def validate_init_data(init_data: str, bot_token: str, *, max_age: int = 86400) -> dict:
    """Validate Telegram WebApp initData and return the Telegram user object."""
    if not init_data or not bot_token:
        raise ValueError("initData is required")
    pairs = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = pairs.pop("hash", "")
    if not received_hash:
        raise ValueError("initData hash is missing")
    data_check_string = "\n".join(f"{key}={pairs[key]}" for key in sorted(pairs))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected_hash, received_hash):
        raise ValueError("initData signature is invalid")
    try:
        user = json.loads(pairs.get("user", "{}"))
        auth_date = int(pairs.get("auth_date", "0"))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("initData payload is invalid") from exc
    import time
    if not user.get("id") or auth_date <= 0 or time.time() - auth_date > max_age:
        raise ValueError("initData is expired or has no user")
    return user


def access_state(record) -> str:
    if record is None or record.current_status in {"new", "waiting_payment", "waiting_confirmation", "rejected"}:
        return "new"
    if record.current_status == "expired" or (
        record.access_end_at and not record.is_lifetime_free
        and datetime.fromisoformat(record.access_end_at) < datetime.utcnow()
    ):
        return "expired"
    if record.current_status in {"active", "grace_period", "trial_active"} or record.is_lifetime_free:
        return "active"
    return "new"


class MiniApp:
    def __init__(
        self,
        db: Database,
        bot_token: str,
        allowed_ids: set[int] | None = None,
        test_mode_ids: set[int] | None = None,
    ):
        self.db = db
        self.bot_token = bot_token
        self.allowed_ids = allowed_ids or set()
        self.test_mode_ids = test_mode_ids or set()

    def register(self, app: web.Application) -> None:
        app.router.add_get("/mini-app/", self.index)
        app.router.add_get("/mini-app/preview", self.preview)
        app.router.add_get("/mini-app/media/{filename}", self.media)
        app.router.add_get("/mini-app/static/{filename:.*}", self.static)
        app.router.add_get("/mini-app/api/bootstrap", self.bootstrap)
        app.router.add_get("/mini-app/api/material/{material_id}", self.material)
        app.router.add_post("/mini-app/api/material/{material_id}/complete", self.material_complete)
        app.router.add_post("/mini-app/api/material/{material_id}/like", self.material_like)
        app.router.add_get("/mini-app/api/course/{course_id}", self.course)
        app.router.add_post("/mini-app/api/lesson/{lesson_id}/complete", self.lesson_complete)

    async def index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(MINI_APP_DIR / "index.html", headers={"Cache-Control": "no-store"})

    async def preview(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(MINI_APP_DIR / "index.html", headers={"Cache-Control": "no-store"})

    async def media(self, request: web.Request) -> web.StreamResponse:
        filename = Path(request.match_info["filename"]).name
        target = (MEDIA_DIR / filename).resolve()
        if MEDIA_DIR.resolve() not in target.parents or not target.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(target)

    async def static(self, request: web.Request) -> web.StreamResponse:
        filename = request.match_info["filename"]
        target = (MINI_APP_DIR / "static" / filename).resolve()
        if MINI_APP_DIR.joinpath("static").resolve() not in target.parents or not target.is_file():
            raise web.HTTPNotFound()
        return web.FileResponse(target, headers={"Cache-Control": "no-cache"})

    def init_user(self, request: web.Request) -> dict:
        raw = request.headers.get("X-Telegram-Init-Data", "") or request.query.get("initData", "")
        return validate_init_data(raw, self.bot_token)

    async def authorised(self, request: web.Request):
        try:
            tg_user = self.init_user(request)
        except ValueError as exc:
            raise web.HTTPUnauthorized(text=str(exc)) from exc
        await self.db.upsert_user(tg_user["id"], tg_user.get("username"),
                                  " ".join(filter(None, [tg_user.get("first_name"), tg_user.get("last_name")])) or "Telegram user")
        record = await self.db.get_user(tg_user["id"])
        state = access_state(record)
        user = {
            "telegram_id": tg_user["id"], "username": tg_user.get("username"),
            "first_name": tg_user.get("first_name", ""), "last_name": tg_user.get("last_name", ""),
            "full_name": record.full_name if record else "Telegram user", "state": state,
            "status": record.current_status if record else "new",
            "access_end_at": record.access_end_at if record else None,
            "amount_label": record.recurring_amount_label if record else None,
            "is_lifetime_free": bool(record.is_lifetime_free) if record else False,
        }
        test_mode_available = int(tg_user["id"]) in self.test_mode_ids
        test_mode = test_mode_available and request.headers.get("X-Nastaunik-Test-Mode") == "1"
        user["test_mode_available"] = test_mode_available
        user["test_mode"] = test_mode
        if test_mode:
            user.update({
                "state": "new",
                "status": "new",
                "access_end_at": None,
                "amount_label": None,
                "is_lifetime_free": False,
            })
        return tg_user, record, user

    async def bootstrap(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        payload = await get_bootstrap(self.db, user)
        if user["state"] != "active":
            payload["courses"] = []
            payload["consultation"] = {}
        return web.json_response(payload)

    async def material(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        try:
            material_id = int(request.match_info["material_id"])
        except ValueError:
            raise web.HTTPNotFound()
        item = await get_material(self.db, material_id)
        if not item:
            raise web.HTTPNotFound()
        if user["state"] != "active" and not item.get("is_free"):
            raise web.HTTPForbidden(text="Этот материал доступен участникам клуба")
        tracking_id = None if user.get("test_mode") else user["telegram_id"]
        return web.json_response(await get_material(self.db, material_id, tracking_id))

    async def material_complete(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        try:
            material_id = int(request.match_info["material_id"])
        except ValueError:
            raise web.HTTPNotFound()
        item = await get_material(self.db, material_id)
        if not item:
            raise web.HTTPNotFound()
        if user["state"] != "active" and not item.get("is_free"):
            raise web.HTTPForbidden(text="Этот материал доступен участникам клуба")
        if user.get("test_mode"):
            return web.json_response({"ok": True, "viewed": True, "view_count": item.get("view_count", 0), "test_mode": True})
        return web.json_response(await complete_material(self.db, material_id, user["telegram_id"]))

    async def material_like(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        try:
            material_id = int(request.match_info["material_id"])
        except ValueError:
            raise web.HTTPNotFound()
        item = await get_material(self.db, material_id)
        if not item:
            raise web.HTTPNotFound()
        if user["state"] != "active" and not item.get("is_free"):
            raise web.HTTPForbidden(text="Этот материал доступен участникам клуба")
        if user.get("test_mode"):
            return web.json_response({"ok": True, "liked": True, "like_count": item.get("like_count", 0), "test_mode": True})
        return web.json_response(await toggle_material_like(self.db, material_id, user["telegram_id"]))

    async def course(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        if user["state"] != "active":
            raise web.HTTPForbidden(text="Active membership is required")
        try:
            course_id = int(request.match_info["course_id"])
        except ValueError:
            raise web.HTTPNotFound()
        course = await get_course(self.db, course_id, user["telegram_id"])
        if not course:
            raise web.HTTPNotFound()
        return web.json_response(course)

    async def lesson_complete(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        if user["state"] != "active":
            raise web.HTTPForbidden(text="Active membership is required")
        try:
            lesson_id = int(request.match_info["lesson_id"])
        except ValueError:
            raise web.HTTPNotFound()
        await complete_lesson(self.db, user["telegram_id"], lesson_id)
        return web.json_response({"ok": True})
