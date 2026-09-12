from __future__ import annotations

import json
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from bot.database import Database
from bot.media_embed import youtube_thumbnail_url, youtube_video_id


class MaterialPreviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.first_image: str | None = None
        self.first_video: str | None = None
        self.first_youtube_thumbnail: str | None = None
        self._inside_video = False

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        src = values.get("src")
        if tag == "img" and src and not self.first_image:
            self.first_image = src
        elif tag == "video":
            self._inside_video = True
            if src and not self.first_video:
                self.first_video = src
        elif tag == "source" and self._inside_video and src and not self.first_video:
            self.first_video = src
        elif tag == "iframe" and src and not self.first_youtube_thumbnail:
            video_id = youtube_video_id(src)
            if video_id:
                self.first_youtube_thumbnail = youtube_thumbnail_url(video_id)

    def handle_endtag(self, tag: str) -> None:
        if tag == "video":
            self._inside_video = False


def article_preview(full_description: object) -> tuple[str | None, str | None]:
    parser = MaterialPreviewParser()
    try:
        parser.feed(str(full_description or ""))
    except (TypeError, ValueError):
        return None, None
    return parser.first_image or parser.first_youtube_thumbnail, parser.first_video


def now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


async def get_settings(db: Database) -> dict[str, str]:
    async with db.connect() as conn:
        cur = await conn.execute("SELECT key, value FROM settings WHERE key LIKE 'mini_app.%'")
        return {row["key"].removeprefix("mini_app."): row["value"] or "" for row in await cur.fetchall()}


async def set_settings(db: Database, values: dict[str, str]) -> None:
    stamp = now_iso()
    async with db.connect() as conn:
        await conn.executemany(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            [(f"mini_app.{key}", value) for key, value in values.items()],
        )
        await conn.commit()


async def get_catalog(
    db: Database, *, telegram_id: int | None = None, category_id: int | None = None, query: str = ""
) -> dict[str, list[dict[str, Any]]]:
    async with db.connect() as conn:
        category_sql = " AND m.category_id = ?" if category_id else ""
        query_sql = " AND (m.title LIKE ? OR m.short_description LIKE ?)" if query else ""
        params: list[Any] = [telegram_id or 0, telegram_id or 0]
        if category_id:
            params.append(category_id)
        if query:
            params.extend([f"%{query}%", f"%{query}%"])
        cur = await conn.execute(
            f"""SELECT m.*, c.name AS category_name,
                       (SELECT COUNT(*) FROM mini_app_material_views mv WHERE mv.material_id=m.id) AS view_count,
                       (SELECT COUNT(*) FROM mini_app_material_likes ml WHERE ml.material_id=m.id) AS like_count,
                       EXISTS(SELECT 1 FROM mini_app_material_views uv WHERE uv.material_id=m.id AND uv.telegram_id=? AND uv.completed_at IS NOT NULL) AS viewed,
                       EXISTS(SELECT 1 FROM mini_app_material_likes ul WHERE ul.material_id=m.id AND ul.telegram_id=?) AS liked
                FROM mini_app_materials m
                LEFT JOIN mini_app_categories c ON c.id=m.category_id
                WHERE m.status='published' AND m.library_visible=1{category_sql}{query_sql}
                ORDER BY m.sort_order, m.created_at DESC""",
            params,
        )
        materials = [dict(row) for row in await cur.fetchall()]
        material_ids = [material["id"] for material in materials]
        tags_by_material: dict[int, list[dict[str, Any]]] = {material_id: [] for material_id in material_ids}
        blocks_by_material: dict[int, list[dict[str, Any]]] = {material_id: [] for material_id in material_ids}
        if material_ids:
            placeholders = ",".join("?" for _ in material_ids)
            cur = await conn.execute(
                f"""SELECT mt.material_id,t.id,t.name,t.slug FROM mini_app_material_tags mt
                    JOIN mini_app_tags t ON t.id=mt.tag_id
                    WHERE mt.material_id IN ({placeholders}) ORDER BY t.name""",
                material_ids,
            )
            for row in await cur.fetchall():
                tags_by_material[row["material_id"]].append({
                    "id": row["id"], "name": row["name"], "slug": row["slug"]
                })
            cur = await conn.execute(
                f"""SELECT material_id,block_type,content FROM mini_app_material_blocks
                    WHERE material_id IN ({placeholders}) AND block_type IN ('image','video')
                    ORDER BY material_id,sort_order,id""",
                material_ids,
            )
            for row in await cur.fetchall():
                blocks_by_material[row["material_id"]].append(dict(row))
        for material in materials:
            material["tags"] = tags_by_material[material["id"]]
            preview_url = material.get("cover_url")
            preview_kind = "image" if preview_url else None
            if not preview_url:
                article_image, article_video = article_preview(material.get("full_description"))
                blocks = blocks_by_material[material["id"]]
                block_image = next((block["content"] for block in blocks if block["block_type"] == "image" and block["content"]), None)
                block_video = next((block["content"] for block in blocks if block["block_type"] == "video" and block["content"]), None)
                preview_url = article_image or block_image or article_video or block_video
                preview_kind = "image" if article_image or block_image else ("video" if preview_url else None)
            material["preview_url"] = preview_url
            material["preview_kind"] = preview_kind
            material["preview_poster_url"] = None
            material.pop("full_description", None)
            material.pop("telegram_url", None)
        video_names = {
            material["id"]: str(material["preview_url"]).split("?", 1)[0].rsplit("/", 1)[-1]
            for material in materials
            if material["preview_kind"] == "video" and material["preview_url"]
        }
        if video_names:
            names = sorted(set(video_names.values()))
            placeholders = ",".join("?" for _ in names)
            cur = await conn.execute(
                f"SELECT stored_name,poster_name FROM mini_app_video_jobs WHERE stored_name IN ({placeholders}) AND poster_name IS NOT NULL",
                names,
            )
            poster_by_video = {row["stored_name"]: row["poster_name"] for row in await cur.fetchall()}
            for material in materials:
                poster_name = poster_by_video.get(video_names.get(material["id"], ""))
                if poster_name:
                    material["preview_poster_url"] = f"/mini-app/media/{poster_name}"
        cur = await conn.execute("SELECT * FROM mini_app_categories WHERE is_visible=1 ORDER BY sort_order, name")
        categories = [dict(row) for row in await cur.fetchall()]
        cur = await conn.execute("SELECT id,name,slug FROM mini_app_tags ORDER BY name")
        tags = [dict(row) for row in await cur.fetchall()]
        return {"materials": materials, "categories": categories, "tags": tags}


async def get_bootstrap(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    settings = await get_settings(db)
    catalog_telegram_id = 0 if user.get("test_mode") else int(user["telegram_id"])
    catalog = await get_catalog(db, telegram_id=catalog_telegram_id)
    has_full_access = user.get("state") == "active"
    for material in catalog["materials"]:
        material["locked"] = not has_full_access and not bool(material.get("is_free"))
        if material["locked"] and not material.get("cover_url"):
            material["preview_url"] = None
            material["preview_kind"] = None
            material["preview_poster_url"] = None
    async with db.connect() as conn:
        cur = await conn.execute(
            """SELECT c.*, cat.name AS category_name FROM mini_app_courses c
               LEFT JOIN mini_app_categories cat ON cat.id=c.category_id
               WHERE c.status='published' ORDER BY c.sort_order, c.created_at DESC"""
        )
        courses = [dict(row) for row in await cur.fetchall()]
        cur = await conn.execute(
            """SELECT h.*, m.title AS material_title FROM mini_app_home_sections h
               LEFT JOIN mini_app_materials m ON m.id=h.item_id
               WHERE h.is_visible=1 ORDER BY h.sort_order, h.id"""
        )
        home = [dict(row) for row in await cur.fetchall()]
        cur = await conn.execute("SELECT * FROM mini_app_consultation WHERE id=1")
        consultation = dict(await cur.fetchone() or {})
    course_telegram_id = 0 if user.get("test_mode") else int(user["telegram_id"])
    course_summaries = []
    for course in courses:
        detail = await get_course(db, int(course["id"]), course_telegram_id)
        if detail:
            detail.pop("lessons", None)
            course_summaries.append(detail)
    return {"user": user, "settings": settings, "home": home, "materials": catalog["materials"],
            "categories": catalog["categories"], "tags": catalog["tags"], "courses": course_summaries,
            "consultation": consultation}


async def get_material(db: Database, material_id: int, telegram_id: int | None = None) -> dict[str, Any] | None:
    async with db.connect() as conn:
        cur = await conn.execute(
            """SELECT m.*, c.name AS category_name FROM mini_app_materials m
               LEFT JOIN mini_app_categories c ON c.id=m.category_id
               WHERE m.id=? AND m.status='published'""", (material_id,)
        )
        row = await cur.fetchone()
        if not row:
            return None
        result = dict(row)
        if telegram_id:
            await conn.execute(
                """INSERT INTO mini_app_material_views(telegram_id,material_id,first_viewed_at)
                   VALUES(?,?,?) ON CONFLICT(telegram_id,material_id) DO NOTHING""",
                (telegram_id, material_id, now_iso()),
            )
            await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM mini_app_material_views WHERE material_id=?", (material_id,))
        result["view_count"] = (await cur.fetchone())[0]
        cur = await conn.execute("SELECT COUNT(*) FROM mini_app_material_likes WHERE material_id=?", (material_id,))
        result["like_count"] = (await cur.fetchone())[0]
        if telegram_id:
            cur = await conn.execute(
                "SELECT completed_at FROM mini_app_material_views WHERE material_id=? AND telegram_id=?",
                (material_id, telegram_id),
            )
            view = await cur.fetchone()
            result["viewed"] = bool(view and view["completed_at"])
            cur = await conn.execute(
                "SELECT 1 FROM mini_app_material_likes WHERE material_id=? AND telegram_id=?",
                (material_id, telegram_id),
            )
            result["liked"] = bool(await cur.fetchone())
        else:
            result["viewed"] = False
            result["liked"] = False
        cur = await conn.execute(
            "SELECT id, file_name, stored_name, mime_type, file_size, title, description, sort_order FROM mini_app_material_files WHERE material_id=? ORDER BY sort_order, id",
            (material_id,),
        )
        result["files"] = [dict(file) | {"url": f"/mini-app/media/{file['stored_name']}"} for file in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT id, block_type, title, content, description, sort_order FROM mini_app_material_blocks WHERE material_id=? ORDER BY sort_order, id",
            (material_id,),
        )
        result["blocks"] = [dict(block) for block in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT t.id, t.name, t.slug, t.color FROM mini_app_tags t JOIN mini_app_material_tags mt ON mt.tag_id=t.id WHERE mt.material_id=? ORDER BY t.name",
            (material_id,),
        )
        result["tags"] = [dict(tag) for tag in await cur.fetchall()]
        cur = await conn.execute(
            """SELECT r.related_material_id AS id,m.title,m.short_description,m.cover_url,m.full_description,m.is_free
               FROM mini_app_material_relations r
               JOIN mini_app_materials m ON m.id=r.related_material_id
               WHERE r.material_id=? AND m.status='published' AND m.library_visible=1
               ORDER BY r.sort_order,r.related_material_id""",
            (material_id,),
        )
        related = []
        for related_row in await cur.fetchall():
            item = dict(related_row)
            if not item.get("cover_url"):
                image, video = article_preview(item.get("full_description"))
                item["cover_url"] = image or video
                if video:
                    video_name = Path(video.split("?", 1)[0]).name
                    poster = await (await conn.execute(
                        "SELECT poster_name FROM mini_app_video_jobs WHERE stored_name=? AND poster_name IS NOT NULL",
                        (video_name,),
                    )).fetchone()
                    if poster:
                        item["cover_url"] = f"/mini-app/media/{Path(poster['poster_name']).name}"
            item.pop("full_description", None)
            related.append(item)
        result["related_materials"] = related
        return result


async def complete_material(db: Database, material_id: int, telegram_id: int) -> dict[str, Any]:
    stamp = now_iso()
    async with db.connect() as conn:
        await conn.execute(
            """INSERT INTO mini_app_material_views(telegram_id,material_id,first_viewed_at,completed_at)
               VALUES(?,?,?,?)
               ON CONFLICT(telegram_id,material_id) DO UPDATE SET
                   completed_at=COALESCE(mini_app_material_views.completed_at,excluded.completed_at)""",
            (telegram_id, material_id, stamp, stamp),
        )
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM mini_app_material_views WHERE material_id=?", (material_id,))
        return {"ok": True, "viewed": True, "view_count": (await cur.fetchone())[0]}


async def toggle_material_like(db: Database, material_id: int, telegram_id: int) -> dict[str, Any]:
    async with db.connect() as conn:
        cur = await conn.execute(
            "SELECT 1 FROM mini_app_material_likes WHERE material_id=? AND telegram_id=?",
            (material_id, telegram_id),
        )
        liked = bool(await cur.fetchone())
        if liked:
            await conn.execute(
                "DELETE FROM mini_app_material_likes WHERE material_id=? AND telegram_id=?",
                (material_id, telegram_id),
            )
        else:
            await conn.execute(
                "INSERT INTO mini_app_material_likes(telegram_id,material_id,created_at) VALUES(?,?,?)",
                (telegram_id, material_id, now_iso()),
            )
        await conn.commit()
        cur = await conn.execute("SELECT COUNT(*) FROM mini_app_material_likes WHERE material_id=?", (material_id,))
        return {"ok": True, "liked": not liked, "like_count": (await cur.fetchone())[0]}


async def _course_lessons(conn, course_id: int) -> list[dict[str, Any]]:
    cur = await conn.execute(
        """SELECT l.*,m.title AS module_title,m.sort_order AS module_sort_order
           FROM mini_app_course_units l
           LEFT JOIN mini_app_course_modules m ON m.id=l.module_id
           WHERE l.course_id=?
           ORDER BY CASE WHEN l.module_id IS NULL THEN 0 ELSE 1 END,
                    COALESCE(m.sort_order,-1),l.sort_order,l.id""",
        (course_id,),
    )
    return [dict(row) for row in await cur.fetchall()]


def _course_progress(lessons: list[dict[str, Any]], completed: set[int]) -> dict[str, Any]:
    required = [lesson for lesson in lessons if lesson.get("is_required")]
    counted = required or lessons
    completed_count = sum(1 for lesson in counted if lesson["id"] in completed)
    total = len(counted)
    return {
        "progress": round(completed_count / total * 100) if total else 0,
        "completed": bool(total and completed_count == total),
        "completed_count": completed_count,
        "required_count": total,
    }


async def _completed_course_units(conn, course_id: int, telegram_id: int) -> set[int]:
    if not telegram_id:
        return set()
    cur = await conn.execute(
        """SELECT p.lesson_id FROM mini_app_course_unit_progress p
           JOIN mini_app_course_units l ON l.id=p.lesson_id
           WHERE p.telegram_id=? AND l.course_id=? AND p.completed_at IS NOT NULL""",
        (telegram_id, course_id),
    )
    return {int(row["lesson_id"]) for row in await cur.fetchall()}


async def get_course(db: Database, course_id: int, telegram_id: int) -> dict[str, Any] | None:
    async with db.connect() as conn:
        cur = await conn.execute(
            """SELECT c.*,n.title AS next_course_title
               FROM mini_app_courses c
               LEFT JOIN mini_app_courses n ON n.id=c.next_course_id AND n.status='published'
               WHERE c.id=? AND c.status='published'""",
            (course_id,),
        )
        course = await cur.fetchone()
        if not course:
            return None
        lessons = await _course_lessons(conn, course_id)
        completed = await _completed_course_units(conn, course_id, telegram_id)
        state = None
        if telegram_id:
            cur = await conn.execute(
                "SELECT * FROM mini_app_course_user_state WHERE telegram_id=? AND course_id=?",
                (telegram_id, course_id),
            )
            state = await cur.fetchone()
        lesson_ids = {lesson["id"] for lesson in lessons}
        last_lesson_id = int(state["last_lesson_id"]) if state and state["last_lesson_id"] in lesson_ids else None
        if last_lesson_id in completed:
            last_lesson_id = None
        resume_lesson_id = last_lesson_id
        if resume_lesson_id is None:
            resume_lesson_id = next((lesson["id"] for lesson in lessons if lesson["is_required"] and lesson["id"] not in completed), None)
        if resume_lesson_id is None:
            resume_lesson_id = next((lesson["id"] for lesson in lessons if lesson["id"] not in completed), None)
        if resume_lesson_id is None and lessons:
            resume_lesson_id = lessons[0]["id"]
        progress = _course_progress(lessons, completed)
        result = dict(course)
        result.update(progress)
        result["started"] = bool(state or completed)
        result["resume_lesson_id"] = resume_lesson_id
        result["lesson_count"] = len(lessons)
        previous_lesson_incomplete = False
        result["lessons"] = []
        for index, lesson in enumerate(lessons):
            lesson_completed = lesson["id"] in completed
            result["lessons"].append({
                **lesson,
                "position": index + 1,
                "completed": lesson_completed,
                "locked": bool(result.get("sequential_access") and previous_lesson_incomplete),
            })
            if not lesson_completed:
                previous_lesson_incomplete = True
        if result.get("sequential_access"):
            unlocked_ids = {lesson["id"] for lesson in result["lessons"] if not lesson["locked"]}
            if result["resume_lesson_id"] not in unlocked_ids:
                result["resume_lesson_id"] = next(
                    (lesson["id"] for lesson in result["lessons"] if not lesson["locked"] and not lesson["completed"]),
                    result["lessons"][0]["id"] if result["lessons"] else None,
                )
        cur = await conn.execute(
            "SELECT COUNT(*) FROM mini_app_course_feedback WHERE course_id=? AND liked=1",
            (course_id,),
        )
        result["like_count"] = int((await cur.fetchone())[0])
        result["liked"] = False
        result["review_status"] = None
        if telegram_id:
            cur = await conn.execute(
                "SELECT liked,review_status FROM mini_app_course_feedback WHERE course_id=? AND telegram_id=?",
                (course_id, telegram_id),
            )
            feedback = await cur.fetchone()
            if feedback:
                result["liked"] = bool(feedback["liked"])
                result["review_status"] = feedback["review_status"] if feedback["review_status"] != "none" else None
        cur = await conn.execute(
            """SELECT f.review_text,u.full_name FROM mini_app_course_feedback f
               JOIN users u ON u.telegram_id=f.telegram_id
               WHERE f.course_id=? AND f.review_status='approved' AND f.review_text IS NOT NULL
               ORDER BY f.updated_at DESC LIMIT 20""",
            (course_id,),
        )
        result["reviews"] = [dict(row) for row in await cur.fetchall()]
        return result


async def get_course_lesson(
    db: Database,
    course_id: int,
    lesson_id: int,
    telegram_id: int,
    *,
    track: bool = True,
    ignore_lock: bool = False,
) -> dict[str, Any] | None:
    course = await get_course(db, course_id, telegram_id)
    if not course:
        return None
    lesson = next((item for item in course["lessons"] if item["id"] == lesson_id), None)
    if not lesson or (lesson.get("locked") and not ignore_lock):
        return None
    if track and telegram_id:
        stamp = now_iso()
        async with db.connect() as conn:
            await conn.execute(
                """INSERT INTO mini_app_course_unit_progress(telegram_id,lesson_id,started_at)
                   VALUES(?,?,?) ON CONFLICT(telegram_id,lesson_id) DO NOTHING""",
                (telegram_id, lesson_id, stamp),
            )
            await conn.execute(
                """INSERT INTO mini_app_course_user_state(telegram_id,course_id,last_lesson_id,started_at,updated_at)
                   VALUES(?,?,?,?,?) ON CONFLICT(telegram_id,course_id) DO UPDATE SET
                   last_lesson_id=excluded.last_lesson_id,updated_at=excluded.updated_at""",
                (telegram_id, course_id, lesson_id, stamp, stamp),
            )
            await conn.commit()
    async with db.connect() as conn:
        cur = await conn.execute(
            """SELECT b.*,m.title AS material_title,m.short_description AS material_description,
                      m.full_description AS material_content,j.poster_name AS video_poster_name,
                      j.status AS video_status
               FROM mini_app_course_blocks b
               LEFT JOIN mini_app_materials m ON m.id=b.material_id
               LEFT JOIN mini_app_video_jobs j ON j.stored_name=b.stored_name
               WHERE b.lesson_id=? ORDER BY b.sort_order,b.id""",
            (lesson_id,),
        )
        blocks = []
        for row in await cur.fetchall():
            block = dict(row)
            if block["block_type"] == "longread" and block.get("material_id"):
                block["title"] = block.get("material_title") or block.get("title")
                block["description"] = block.get("material_description") or block.get("description")
                block["content"] = block.get("material_content") or block.get("content") or ""
            if block["block_type"] == "video" and block.get("video_poster_name"):
                block["poster_url"] = f"/mini-app/media/{Path(block['video_poster_name']).name}"
            if block["block_type"] == "video":
                block["video_status"] = block.get("video_status") or "ready"
                block["video_ready"] = block["video_status"] == "ready"
            if block["block_type"] == "test":
                try:
                    settings = json.loads(block.get("settings_json") or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    settings = {}
                block["settings"] = {"options": list(settings.get("options") or []), "required": settings.get("required", True)}
            elif block["block_type"] == "assignment":
                try:
                    settings = json.loads(block.get("settings_json") or "{}")
                except (TypeError, ValueError, json.JSONDecodeError):
                    settings = {}
                block["settings"] = {"response_type": settings.get("response_type") or "text"}
                block["submission"] = None
                if telegram_id:
                    submission_cur = await conn.execute(
                        """SELECT response_type,response_text,original_name,updated_at
                           FROM mini_app_course_assignment_submissions
                           WHERE telegram_id=? AND block_id=?""",
                        (telegram_id, block["id"]),
                    )
                    submission = await submission_cur.fetchone()
                    if submission:
                        block["submission"] = dict(submission)
            for key in ("settings_json", "stored_name", "material_title", "material_description", "material_content", "video_poster_name"):
                block.pop(key, None)
            blocks.append(block)
    lessons = course["lessons"]
    index = next(index for index, item in enumerate(lessons) if item["id"] == lesson_id)
    lesson["blocks"] = blocks
    lesson["previous_lesson_id"] = lessons[index - 1]["id"] if index else None
    lesson["next_lesson_id"] = lessons[index + 1]["id"] if index + 1 < len(lessons) else None
    lesson["total_lessons"] = len(lessons)
    lesson["course"] = {
        "id": course["id"],
        "title": course["title"],
        "progress": course["progress"],
        "completed": course["completed"],
    }
    return lesson


async def complete_course_lesson(db: Database, course_id: int, lesson_id: int, telegram_id: int) -> dict[str, Any] | None:
    course = await get_course(db, course_id, telegram_id)
    lesson = next((item for item in course["lessons"] if item["id"] == lesson_id), None) if course else None
    if not lesson or lesson.get("locked"):
        return None
    stamp = now_iso()
    async with db.connect() as conn:
        cur = await conn.execute(
            """SELECT l.id FROM mini_app_course_units l JOIN mini_app_courses c ON c.id=l.course_id
               WHERE l.id=? AND l.course_id=? AND c.status='published'""",
            (lesson_id, course_id),
        )
        if not await cur.fetchone():
            return None
        test_cur = await conn.execute(
            """SELECT id,settings_json FROM mini_app_course_blocks
               WHERE lesson_id=? AND block_type='test' ORDER BY sort_order,id""",
            (lesson_id,),
        )
        for test in await test_cur.fetchall():
            try:
                test_settings = json.loads(test["settings_json"] or "{}")
            except (TypeError, ValueError, json.JSONDecodeError):
                test_settings = {}
            if not test_settings.get("required", True):
                continue
            passed_cur = await conn.execute(
                """SELECT 1 FROM mini_app_course_test_attempts
                   WHERE telegram_id=? AND block_id=? AND is_correct=1 LIMIT 1""",
                (telegram_id, test["id"]),
            )
            if not await passed_cur.fetchone():
                return {"ok": False, "blocked": True, "reason": "Сначала ответьте на все обязательные вопросы правильно."}
        await conn.execute(
            """INSERT INTO mini_app_course_unit_progress(telegram_id,lesson_id,started_at,completed_at)
               VALUES(?,?,?,?) ON CONFLICT(telegram_id,lesson_id) DO UPDATE SET
               completed_at=COALESCE(mini_app_course_unit_progress.completed_at,excluded.completed_at)""",
            (telegram_id, lesson_id, stamp, stamp),
        )
        await conn.commit()
        lessons = await _course_lessons(conn, course_id)
        completed = await _completed_course_units(conn, course_id, telegram_id)
        progress = _course_progress(lessons, completed)
        index = next(index for index, lesson in enumerate(lessons) if lesson["id"] == lesson_id)
        next_lesson_id = lessons[index + 1]["id"] if index + 1 < len(lessons) else None
        await conn.execute(
            """INSERT INTO mini_app_course_user_state(
                   telegram_id,course_id,last_lesson_id,started_at,updated_at,completed_at
               ) VALUES(?,?,?,?,?,?) ON CONFLICT(telegram_id,course_id) DO UPDATE SET
                   last_lesson_id=excluded.last_lesson_id,updated_at=excluded.updated_at,
                   completed_at=COALESCE(mini_app_course_user_state.completed_at,excluded.completed_at)""",
            (telegram_id, course_id, lesson_id, stamp, stamp, stamp if progress["completed"] else None),
        )
        await conn.commit()
        return {
            "ok": True,
            "lesson_id": lesson_id,
            "next_lesson_id": next_lesson_id,
            "is_last": next_lesson_id is None,
            **progress,
        }


async def record_course_video_event(
    db: Database,
    course_id: int,
    lesson_id: int,
    block_id: int,
    telegram_id: int,
    event_type: str,
    position_seconds: float = 0,
    duration_seconds: float = 0,
) -> bool:
    if event_type not in {"start", "progress", "pause", "complete", "error"} or not telegram_id:
        return False
    async with db.connect() as conn:
        row = await (await conn.execute(
            """SELECT 1 FROM mini_app_course_blocks b JOIN mini_app_course_units l ON l.id=b.lesson_id
               WHERE b.id=? AND b.lesson_id=? AND l.course_id=? AND b.block_type='video'""",
            (block_id, lesson_id, course_id),
        )).fetchone()
        if not row:
            return False
        await conn.execute(
            """INSERT INTO mini_app_course_video_events(
                telegram_id,course_id,lesson_id,block_id,event_type,position_seconds,duration_seconds,created_at
            ) VALUES(?,?,?,?,?,?,?,?)""",
            (telegram_id, course_id, lesson_id, block_id, event_type,
             max(0, float(position_seconds or 0)), max(0, float(duration_seconds or 0)), now_iso()),
        )
        await conn.commit()
    return True


async def answer_course_test(
    db: Database,
    course_id: int,
    lesson_id: int,
    block_id: int,
    telegram_id: int,
    selected_option: int,
    *,
    record: bool = True,
) -> dict[str, Any] | None:
    async with db.connect() as conn:
        cur = await conn.execute(
            """SELECT b.settings_json FROM mini_app_course_blocks b
               JOIN mini_app_course_units l ON l.id=b.lesson_id
               JOIN mini_app_courses c ON c.id=l.course_id
               WHERE b.id=? AND b.lesson_id=? AND b.block_type='test'
                 AND l.course_id=? AND c.status='published'""",
            (block_id, lesson_id, course_id),
        )
        row = await cur.fetchone()
        if not row:
            return None
        try:
            settings = json.loads(row["settings_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            settings = {}
        options = list(settings.get("options") or [])
        if selected_option < 0 or selected_option >= len(options) or not str(options[selected_option]).strip():
            return None
        correct_option = int(settings.get("correct", 0))
        is_correct = selected_option == correct_option
        if record and telegram_id:
            await conn.execute(
                """INSERT INTO mini_app_course_test_attempts(
                       telegram_id,block_id,selected_option,is_correct,created_at
                   ) VALUES(?,?,?,?,?)""",
                (telegram_id, block_id, selected_option, int(is_correct), now_iso()),
            )
            await conn.commit()
        return {
            "ok": True,
            "correct": is_correct,
            "selected_option": selected_option,
            "correct_option": correct_option,
            "explanation": str(settings.get("explanation") or "").strip(),
            "can_retry": True,
        }


async def toggle_course_like(db: Database, course_id: int, telegram_id: int) -> dict[str, Any] | None:
    stamp = now_iso()
    async with db.connect() as conn:
        cur = await conn.execute("SELECT id FROM mini_app_courses WHERE id=? AND status='published'", (course_id,))
        if not await cur.fetchone():
            return None
        cur = await conn.execute(
            "SELECT liked FROM mini_app_course_feedback WHERE course_id=? AND telegram_id=?",
            (course_id, telegram_id),
        )
        row = await cur.fetchone()
        liked = not bool(row["liked"]) if row else True
        await conn.execute(
            """INSERT INTO mini_app_course_feedback(
                   telegram_id,course_id,liked,review_status,created_at,updated_at
               ) VALUES(?,?,?,'none',?,?) ON CONFLICT(telegram_id,course_id) DO UPDATE SET
                   liked=excluded.liked,updated_at=excluded.updated_at""",
            (telegram_id, course_id, int(liked), stamp, stamp),
        )
        await conn.commit()
        cur = await conn.execute(
            "SELECT COUNT(*) FROM mini_app_course_feedback WHERE course_id=? AND liked=1",
            (course_id,),
        )
        return {"ok": True, "liked": liked, "like_count": int((await cur.fetchone())[0])}


async def submit_course_review(db: Database, course_id: int, telegram_id: int, review_text: str) -> dict[str, Any] | None:
    review_text = review_text.strip()
    if not review_text or len(review_text) > 2000:
        return None
    stamp = now_iso()
    async with db.connect() as conn:
        cur = await conn.execute("SELECT id FROM mini_app_courses WHERE id=? AND status='published'", (course_id,))
        if not await cur.fetchone():
            return None
        await conn.execute(
            """INSERT INTO mini_app_course_feedback(
                   telegram_id,course_id,liked,review_text,review_status,created_at,updated_at
               ) VALUES(?,?,0,?,'pending',?,?) ON CONFLICT(telegram_id,course_id) DO UPDATE SET
                   review_text=excluded.review_text,review_status='pending',updated_at=excluded.updated_at""",
            (telegram_id, course_id, review_text, stamp, stamp),
        )
        await conn.commit()
        return {"ok": True, "status": "pending"}


async def submit_course_assignment(
    db: Database,
    course_id: int,
    lesson_id: int,
    block_id: int,
    telegram_id: int,
    response_text: str | None,
    stored_name: str | None,
    original_name: str | None,
) -> dict[str, Any] | None:
    async with db.connect() as conn:
        cur = await conn.execute(
            """SELECT b.settings_json FROM mini_app_course_blocks b
               JOIN mini_app_course_units l ON l.id=b.lesson_id
               JOIN mini_app_courses c ON c.id=l.course_id
               WHERE b.id=? AND b.lesson_id=? AND b.block_type='assignment'
                 AND l.course_id=? AND c.status='published'""",
            (block_id, lesson_id, course_id),
        )
        block = await cur.fetchone()
        if not block:
            return None
        try:
            settings = json.loads(block["settings_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            settings = {}
        response_type = settings.get("response_type") or "text"
        clean_text = (response_text or "").strip() or None
        if response_type == "file" and not stored_name:
            return None
        if response_type in {"text", "link"} and not clean_text:
            return None
        if response_type == "link" and not clean_text.lower().startswith(("https://", "http://")):
            return None
        cur = await conn.execute(
            "SELECT stored_name FROM mini_app_course_assignment_submissions WHERE telegram_id=? AND block_id=?",
            (telegram_id, block_id),
        )
        old = await cur.fetchone()
        stamp = now_iso()
        await conn.execute(
            """INSERT INTO mini_app_course_assignment_submissions(
                   telegram_id,block_id,response_type,response_text,stored_name,original_name,created_at,updated_at
               ) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(telegram_id,block_id) DO UPDATE SET
                   response_type=excluded.response_type,response_text=excluded.response_text,
                   stored_name=excluded.stored_name,original_name=excluded.original_name,updated_at=excluded.updated_at""",
            (telegram_id, block_id, response_type, clean_text, stored_name, original_name, stamp, stamp),
        )
        await conn.commit()
        return {
            "ok": True,
            "response_type": response_type,
            "response_text": clean_text,
            "original_name": original_name,
            "previous_stored_name": old["stored_name"] if old else None,
        }


async def complete_lesson(db: Database, telegram_id: int, lesson_id: int) -> None:
    """Compatibility path for courses created with the original material-based builder."""
    async with db.connect() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO mini_app_user_progress(telegram_id, lesson_id, completed_at) VALUES(?,?,?)",
            (telegram_id, lesson_id, now_iso()),
        )
        await conn.commit()
