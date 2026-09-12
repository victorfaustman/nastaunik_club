from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from bot.database import Database
from bot.learning import (
    answer_course_test,
    complete_course_lesson,
    complete_lesson,
    complete_material,
    get_bootstrap,
    get_course,
    get_course_lesson,
    record_course_video_event,
    get_material,
    submit_course_assignment,
    submit_course_review,
    toggle_course_like,
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
        app.router.add_get("/mini-app/api/course/{course_id}/lesson/{lesson_id}", self.course_lesson)
        app.router.add_post("/mini-app/api/course/{course_id}/lesson/{lesson_id}/complete", self.course_lesson_complete)
        app.router.add_post("/mini-app/api/course/{course_id}/lesson/{lesson_id}/test/{block_id}", self.course_test_answer)
        app.router.add_post("/mini-app/api/course/{course_id}/lesson/{lesson_id}/video/{block_id}/event", self.course_video_event)
        app.router.add_post("/mini-app/api/course/{course_id}/lesson/{lesson_id}/assignment/{block_id}", self.course_assignment_submit)
        app.router.add_post("/mini-app/api/course/{course_id}/like", self.course_like)
        app.router.add_post("/mini-app/api/course/{course_id}/review", self.course_review)
        app.router.add_post("/mini-app/api/lesson/{lesson_id}/complete", self.lesson_complete)

    async def index(self, request: web.Request) -> web.StreamResponse:
        return web.FileResponse(MINI_APP_DIR / "index.html", headers={"Cache-Control": "no-store"})

    async def preview(self, request: web.Request) -> web.StreamResponse:
        mode = "unpaid" if request.query.get("mode") == "unpaid" else "paid"
        try:
            course_id = int(request.query.get("course") or 0)
            lesson_id = int(request.query.get("lesson") or 0)
        except ValueError:
            raise web.HTTPNotFound()
        user = {
            "telegram_id": 0,
            "username": "preview",
            "first_name": "участник",
            "last_name": "",
            "full_name": "Предпросмотр",
            "state": "active" if mode == "paid" else "new",
            "status": "active" if mode == "paid" else "new",
            "access_end_at": None,
            "amount_label": None,
            "is_lifetime_free": mode == "paid",
            "test_mode_available": False,
            "test_mode": mode,
        }
        payload = await get_bootstrap(self.db, user)
        preview_courses: dict[str, dict] = {}
        preview_lessons: dict[str, dict] = {}
        preview_test_answers: dict[str, dict] = {}
        if course_id and (mode == "paid" or lesson_id):
            preview_ids = [course_id]
            course = await get_course(self.db, course_id, 0)
            if course and course.get("next_course_id"):
                preview_ids.append(int(course["next_course_id"]))
            for preview_course_id in dict.fromkeys(preview_ids):
                preview_course = await get_course(self.db, preview_course_id, 0)
                if not preview_course:
                    continue
                preview_courses[str(preview_course_id)] = preview_course
                for lesson in preview_course["lessons"]:
                    detail = await get_course_lesson(
                        self.db,
                        preview_course_id,
                        int(lesson["id"]),
                        0,
                        track=False,
                        ignore_lock=True,
                    )
                    if detail:
                        preview_lessons[f"{preview_course_id}:{lesson['id']}"] = detail
            async with self.db.connect() as conn:
                placeholders = ",".join("?" for _ in preview_ids)
                cur = await conn.execute(
                    f"""SELECT b.id,b.settings_json FROM mini_app_course_blocks b
                        JOIN mini_app_course_units l ON l.id=b.lesson_id
                        WHERE l.course_id IN ({placeholders}) AND b.block_type='test'""",
                    tuple(preview_ids),
                )
                for row in await cur.fetchall():
                    try:
                        settings = json.loads(row["settings_json"] or "{}")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        settings = {}
                    preview_test_answers[str(row["id"])] = {
                        "correct_option": int(settings.get("correct", 0)),
                        "explanation": str(settings.get("explanation") or ""),
                    }
        if mode == "unpaid":
            payload["courses"] = []
            payload["consultation"] = {}
        values = {
            "data": payload,
            "courses": preview_courses,
            "lessons": preview_lessons,
            "testAnswers": preview_test_answers,
            "courseId": course_id,
            "lessonId": lesson_id,
        }
        injected = json.dumps(values, ensure_ascii=False).replace("</", "<\\/")
        html = (MINI_APP_DIR / "index.html").read_text(encoding="utf-8")
        html = html.replace("</head>", f"<script>window.NASTAUNIK_PREVIEW={injected}</script></head>")
        return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

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
        requested_test_mode = request.headers.get("X-Nastaunik-Test-Mode", "").strip().lower()
        if requested_test_mode == "1":
            requested_test_mode = "unpaid"
        test_mode = requested_test_mode if test_mode_available and requested_test_mode in {"unpaid", "paid"} else None
        user["test_mode_available"] = test_mode_available
        user["test_mode"] = test_mode
        if test_mode == "unpaid":
            user.update({
                "state": "new",
                "status": "new",
                "access_end_at": None,
                "amount_label": None,
                "is_lifetime_free": False,
            })
        elif test_mode == "paid":
            user.update({
                "state": "active",
                "status": "active",
                "access_end_at": None,
                "amount_label": None,
                "is_lifetime_free": True,
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
        detail = await get_material(self.db, material_id, tracking_id)
        for related in detail.get("related_materials", []):
            related["locked"] = user["state"] != "active" and not bool(related.get("is_free"))
        return web.json_response(detail)

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
        tracking_id = 0 if user.get("test_mode") else user["telegram_id"]
        course = await get_course(self.db, course_id, tracking_id)
        if not course:
            raise web.HTTPNotFound()
        return web.json_response(course)

    async def course_lesson(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        if user["state"] != "active":
            raise web.HTTPForbidden(text="Active membership is required")
        try:
            course_id = int(request.match_info["course_id"])
            lesson_id = int(request.match_info["lesson_id"])
        except ValueError:
            raise web.HTTPNotFound()
        tracking_id = 0 if user.get("test_mode") else user["telegram_id"]
        lesson = await get_course_lesson(
            self.db,
            course_id,
            lesson_id,
            tracking_id,
            track=not bool(user.get("test_mode")),
            ignore_lock=bool(user.get("test_mode")),
        )
        if not lesson:
            raise web.HTTPNotFound()
        return web.json_response(lesson)

    async def course_lesson_complete(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        if user["state"] != "active":
            raise web.HTTPForbidden(text="Active membership is required")
        try:
            course_id = int(request.match_info["course_id"])
            lesson_id = int(request.match_info["lesson_id"])
        except ValueError:
            raise web.HTTPNotFound()
        if user.get("test_mode"):
            lesson = await get_course_lesson(self.db, course_id, lesson_id, 0, track=False, ignore_lock=True)
            if not lesson:
                raise web.HTTPNotFound()
            return web.json_response({
                "ok": True,
                "lesson_id": lesson_id,
                "next_lesson_id": lesson["next_lesson_id"],
                "is_last": lesson["next_lesson_id"] is None,
                "progress": lesson["course"]["progress"],
                "completed": False,
                "completed_count": 0,
                "required_count": 0,
                "test_mode": user["test_mode"],
            })
        result = await complete_course_lesson(self.db, course_id, lesson_id, user["telegram_id"])
        if not result:
            raise web.HTTPNotFound()
        if result.get("blocked"):
            return web.json_response(result, status=409)
        return web.json_response(result)

    async def course_video_event(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        if user["state"] != "active":
            raise web.HTTPForbidden(text="Active membership is required")
        try:
            payload = await request.json()
            course_id = int(request.match_info["course_id"])
            lesson_id = int(request.match_info["lesson_id"])
            block_id = int(request.match_info["block_id"])
            event_type = str(payload.get("event_type") or "")
            position = float(payload.get("position_seconds") or 0)
            duration = float(payload.get("duration_seconds") or 0)
        except (ValueError, TypeError, json.JSONDecodeError):
            raise web.HTTPBadRequest(text="Некорректное событие видео")
        if user.get("test_mode"):
            return web.json_response({"ok": True, "test_mode": user["test_mode"]})
        ok = await record_course_video_event(self.db, course_id, lesson_id, block_id, user["telegram_id"], event_type, position, duration)
        return web.json_response({"ok": ok})

    async def course_test_answer(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        if user["state"] != "active":
            raise web.HTTPForbidden(text="Active membership is required")
        try:
            course_id = int(request.match_info["course_id"])
            lesson_id = int(request.match_info["lesson_id"])
            block_id = int(request.match_info["block_id"])
            selected_option = int((await request.json()).get("selected_option"))
        except (ValueError, TypeError, json.JSONDecodeError):
            raise web.HTTPBadRequest(text="Выберите вариант ответа")
        if not user.get("test_mode"):
            lesson = await get_course_lesson(self.db, course_id, lesson_id, user["telegram_id"], track=False)
            if not lesson:
                raise web.HTTPForbidden(text="Сначала пройдите предыдущий урок")
        result = await answer_course_test(
            self.db,
            course_id,
            lesson_id,
            block_id,
            user["telegram_id"],
            selected_option,
            record=not bool(user.get("test_mode")),
        )
        if not result:
            raise web.HTTPBadRequest(text="Не удалось проверить ответ")
        return web.json_response(result)

    async def course_like(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        if user["state"] != "active":
            raise web.HTTPForbidden(text="Active membership is required")
        try:
            course_id = int(request.match_info["course_id"])
        except ValueError:
            raise web.HTTPNotFound()
        if user.get("test_mode"):
            course = await get_course(self.db, course_id, 0)
            if not course:
                raise web.HTTPNotFound()
            return web.json_response({"ok": True, "liked": True, "like_count": course["like_count"] + 1, "test_mode": True})
        result = await toggle_course_like(self.db, course_id, user["telegram_id"])
        if not result:
            raise web.HTTPNotFound()
        return web.json_response(result)

    async def course_review(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        if user["state"] != "active":
            raise web.HTTPForbidden(text="Active membership is required")
        try:
            course_id = int(request.match_info["course_id"])
            review_text = str((await request.json()).get("review_text") or "")
        except (ValueError, TypeError, json.JSONDecodeError):
            raise web.HTTPBadRequest(text="Введите отзыв")
        if user.get("test_mode"):
            return web.json_response({"ok": True, "status": "pending", "test_mode": True})
        result = await submit_course_review(self.db, course_id, user["telegram_id"], review_text)
        if not result:
            raise web.HTTPBadRequest(text="Отзыв должен содержать от 1 до 2000 символов")
        return web.json_response(result)

    async def course_assignment_submit(self, request: web.Request) -> web.Response:
        _, _, user = await self.authorised(request)
        if user["state"] != "active":
            raise web.HTTPForbidden(text="Active membership is required")
        try:
            course_id = int(request.match_info["course_id"])
            lesson_id = int(request.match_info["lesson_id"])
            block_id = int(request.match_info["block_id"])
        except ValueError:
            raise web.HTTPNotFound()
        if not user.get("test_mode"):
            lesson = await get_course_lesson(self.db, course_id, lesson_id, user["telegram_id"], track=False)
            if not lesson:
                raise web.HTTPForbidden(text="Сначала пройдите предыдущий урок")
        form = await request.post()
        response_text = str(form.get("response_text") or "")
        upload = form.get("assignment_file")
        stored_name = None
        original_name = None
        target = None
        if getattr(upload, "filename", None) and getattr(upload, "file", None):
            original_name = Path(upload.filename).name[:180]
            extension = Path(original_name).suffix.lower()
            if extension not in {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".zip", ".jpg", ".jpeg", ".png"}:
                raise web.HTTPBadRequest(text="Неподдерживаемый формат файла")
            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            stored_name = f"assignment-{secrets.token_urlsafe(18)}{extension}"
            target = MEDIA_DIR / stored_name
            with target.open("wb") as output:
                shutil.copyfileobj(upload.file, output)
        if user.get("test_mode"):
            if target:
                target.unlink(missing_ok=True)
            return web.json_response({"ok": True, "status": "submitted", "original_name": original_name, "test_mode": True})
        result = await submit_course_assignment(
            self.db,
            course_id,
            lesson_id,
            block_id,
            user["telegram_id"],
            response_text,
            stored_name,
            original_name,
        )
        if not result:
            if target:
                target.unlink(missing_ok=True)
            raise web.HTTPBadRequest(text="Заполните ответ в выбранном формате")
        previous = result.pop("previous_stored_name", None)
        if previous and previous != stored_name:
            (MEDIA_DIR / Path(previous).name).unlink(missing_ok=True)
        return web.json_response(result)

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
