from __future__ import annotations

from datetime import datetime
from html.parser import HTMLParser
from typing import Any

from bot.database import Database


class MaterialPreviewParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.first_image: str | None = None
        self.first_video: str | None = None
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

    def handle_endtag(self, tag: str) -> None:
        if tag == "video":
            self._inside_video = False


def article_preview(full_description: object) -> tuple[str | None, str | None]:
    parser = MaterialPreviewParser()
    try:
        parser.feed(str(full_description or ""))
    except (TypeError, ValueError):
        return None, None
    return parser.first_image, parser.first_video


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
                WHERE m.status='published'{category_sql}{query_sql}
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
        cur = await conn.execute("SELECT * FROM mini_app_categories WHERE is_visible=1 ORDER BY sort_order, name")
        categories = [dict(row) for row in await cur.fetchall()]
        cur = await conn.execute("SELECT id,name,slug FROM mini_app_tags ORDER BY name")
        tags = [dict(row) for row in await cur.fetchall()]
        return {"materials": materials, "categories": categories, "tags": tags}


async def get_bootstrap(db: Database, user: dict[str, Any]) -> dict[str, Any]:
    settings = await get_settings(db)
    catalog = await get_catalog(db, telegram_id=int(user["telegram_id"]))
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
    return {"user": user, "settings": settings, "home": home, "materials": catalog["materials"],
            "categories": catalog["categories"], "tags": catalog["tags"], "courses": courses,
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


async def get_course(db: Database, course_id: int, telegram_id: int) -> dict[str, Any] | None:
    async with db.connect() as conn:
        cur = await conn.execute("SELECT * FROM mini_app_courses WHERE id=? AND status='published'", (course_id,))
        course = await cur.fetchone()
        if not course:
            return None
        cur = await conn.execute(
            """SELECT l.*, m.title, m.short_description, m.cover_url, m.telegram_url
               FROM mini_app_course_lessons l JOIN mini_app_materials m ON m.id=l.material_id
               WHERE l.course_id=? AND m.status='published' ORDER BY l.sort_order, l.id""", (course_id,)
        )
        lessons = [dict(row) for row in await cur.fetchall()]
        cur = await conn.execute(
            "SELECT lesson_id FROM mini_app_user_progress WHERE telegram_id=? AND lesson_id IN (SELECT id FROM mini_app_course_lessons WHERE course_id=?)",
            (telegram_id, course_id),
        )
        completed = {row["lesson_id"] for row in await cur.fetchall()}
        result = dict(course)
        result["lessons"] = [{**lesson, "completed": lesson["id"] in completed} for lesson in lessons]
        result["progress"] = round(len(completed) / len(lessons) * 100) if lessons else 0
        return result


async def complete_lesson(db: Database, telegram_id: int, lesson_id: int) -> None:
    async with db.connect() as conn:
        await conn.execute(
            "INSERT OR REPLACE INTO mini_app_user_progress(telegram_id, lesson_id, completed_at) VALUES(?,?,?)",
            (telegram_id, lesson_id, now_iso()),
        )
        await conn.commit()
