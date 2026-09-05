from __future__ import annotations

import html
import mimetypes
import secrets
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path

import aiosqlite
from aiohttp import web

from bot.database import Database


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


class LearningAdmin:
    """Small, deliberately server-rendered CMS surface backed by the existing SQLite DB."""

    def __init__(self, database_path: Path, url_builder):
        self.database_path = database_path
        self.url = url_builder
        self.schema = Database(database_path)

    async def connect(self):
        db = await aiosqlite.connect(self.database_path, timeout=8)
        db.row_factory = sqlite3.Row
        await db.execute("PRAGMA foreign_keys = ON")
        return db

    async def page(self, request: web.Request) -> web.Response:
        await self.schema.init()
        db = await self.connect()
        try:
            categories = await self.rows(db, "SELECT * FROM mini_app_categories ORDER BY sort_order, name")
            materials = await self.rows(db, "SELECT m.*, c.name category_name FROM mini_app_materials m LEFT JOIN mini_app_categories c ON c.id=m.category_id ORDER BY m.sort_order, m.created_at DESC")
            courses = await self.rows(db, "SELECT c.*, cat.name category_name FROM mini_app_courses c LEFT JOIN mini_app_categories cat ON cat.id=c.category_id ORDER BY c.sort_order, c.created_at DESC")
            lessons = await self.rows(db, "SELECT l.*, c.title course_title, m.title material_title FROM mini_app_course_lessons l JOIN mini_app_courses c ON c.id=l.course_id JOIN mini_app_materials m ON m.id=l.material_id ORDER BY c.sort_order, l.sort_order, l.id")
            home = await self.rows(db, "SELECT h.*, m.title material_title FROM mini_app_home_sections h LEFT JOIN mini_app_materials m ON m.id=h.item_id ORDER BY h.sort_order, h.id")
            cur = await db.execute("SELECT * FROM mini_app_consultation WHERE id=1")
            consultation = await cur.fetchone()
            settings = await self.rows(db, "SELECT key,value FROM settings WHERE key LIKE 'mini_app.%' ORDER BY key")
        finally:
            await db.close()
        notice = request.query.get("saved")
        return web.Response(text=self.render(categories, materials, courses, lessons, home, consultation, settings, notice), content_type="text/html")

    async def rows(self, db, sql, params=()):
        cur = await db.execute(sql, params)
        return await cur.fetchall()

    async def save_material_file(self, db, material_id: int, upload) -> None:
        if not getattr(upload, "filename", None) or not getattr(upload, "file", None):
            return
        extension = Path(upload.filename).suffix.lower()
        allowed_extensions = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md", ".jpg", ".jpeg", ".png", ".webp", ".mp3", ".mp4"}
        if extension not in allowed_extensions:
            raise web.HTTPBadRequest(text="Этот тип файла не поддерживается")
        media_dir = Path(__file__).resolve().parent.parent / "media" / "mini_app"
        media_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{secrets.token_urlsafe(18)}{extension}"
        target = media_dir / stored_name
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        file_size = target.stat().st_size
        await db.execute(
            "INSERT INTO mini_app_material_files(material_id,file_name,stored_name,mime_type,file_size,created_at) VALUES(?,?,?,?,?,?)",
            (material_id, Path(upload.filename).name[:250], stored_name, upload.content_type or mimetypes.guess_type(upload.filename)[0], file_size, datetime.utcnow().isoformat(timespec="seconds")),
        )

    async def action(self, request: web.Request) -> web.Response:
        await self.schema.init()
        form = await request.post()
        action = str(form.get("action") or "")
        db = await self.connect()
        now = datetime.utcnow().isoformat(timespec="seconds")
        try:
            if action == "category_save":
                item_id = str(form.get("id") or "").strip()
                values = (str(form.get("name") or "").strip(), str(form.get("slug") or "").strip(), str(form.get("icon") or "").strip() or None, str(form.get("cover_url") or "").strip() or None, int(form.get("sort_order") or 0), int(form.get("is_visible") or 0), now)
                if not values[0] or not values[1]: raise web.HTTPBadRequest(text="Название и slug категории обязательны")
                if item_id:
                    await db.execute("UPDATE mini_app_categories SET name=?,slug=?,icon=?,cover_url=?,sort_order=?,is_visible=?,updated_at=? WHERE id=?", (*values, int(item_id)))
                else:
                    await db.execute("INSERT INTO mini_app_categories(name,slug,icon,cover_url,sort_order,is_visible,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (*values, now))
            elif action == "category_delete":
                await db.execute("DELETE FROM mini_app_categories WHERE id=?", (int(form["id"]),))
            elif action == "material_save":
                item_id = str(form.get("id") or "").strip()
                values = (str(form.get("title") or "").strip(), str(form.get("short_description") or "").strip() or None, str(form.get("full_description") or "").strip() or None, str(form.get("cover_url") or "").strip() or None, str(form.get("telegram_url") or "").strip() or None, int(form.get("category_id") or 0) or None, str(form.get("format") or "").strip() or None, str(form.get("status") or "draft"), int(form.get("sort_order") or 0), now)
                if not values[0]: raise web.HTTPBadRequest(text="Название материала обязательно")
                if item_id:
                    await db.execute("UPDATE mini_app_materials SET title=?,short_description=?,full_description=?,cover_url=?,telegram_url=?,category_id=?,format=?,status=?,sort_order=?,updated_at=? WHERE id=?", (*values, int(item_id)))
                    material_id = int(item_id)
                else:
                    cur = await db.execute("INSERT INTO mini_app_materials(title,short_description,full_description,cover_url,telegram_url,category_id,format,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (*values, now))
                    material_id = int(cur.lastrowid)
                await self.save_material_file(db, material_id, form.get("material_file"))
            elif action == "material_delete":
                await db.execute("DELETE FROM mini_app_materials WHERE id=?", (int(form["id"]),))
            elif action == "course_save":
                item_id = str(form.get("id") or "").strip()
                values = (str(form.get("title") or "").strip(), str(form.get("description") or "").strip() or None, str(form.get("cover_url") or "").strip() or None, int(form.get("category_id") or 0) or None, str(form.get("status") or "draft"), int(form.get("sort_order") or 0), now)
                if not values[0]: raise web.HTTPBadRequest(text="Название курса обязательно")
                if item_id:
                    await db.execute("UPDATE mini_app_courses SET title=?,description=?,cover_url=?,category_id=?,status=?,sort_order=?,updated_at=? WHERE id=?", (*values, int(item_id)))
                else:
                    await db.execute("INSERT INTO mini_app_courses(title,description,cover_url,category_id,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)", (*values, now))
            elif action == "course_delete":
                await db.execute("DELETE FROM mini_app_courses WHERE id=?", (int(form["id"]),))
            elif action == "lesson_add":
                await db.execute("INSERT OR IGNORE INTO mini_app_course_lessons(course_id,material_id,title_override,sort_order) VALUES(?,?,?,?)", (int(form["course_id"]), int(form["material_id"]), str(form.get("title_override") or "").strip() or None, int(form.get("sort_order") or 0)))
            elif action == "lesson_delete":
                await db.execute("DELETE FROM mini_app_course_lessons WHERE id=?", (int(form["id"]),))
            elif action == "home_save":
                key = str(form.get("section_key") or "featured").strip() or "featured"
                await db.execute("INSERT INTO mini_app_home_sections(section_key,title,content_type,item_id,sort_order,is_visible) VALUES(?,?,?,?,?,?) ON CONFLICT(section_key) DO UPDATE SET title=excluded.title,content_type=excluded.content_type,item_id=excluded.item_id,sort_order=excluded.sort_order,is_visible=excluded.is_visible", (key, str(form.get("title") or "Новое").strip(), "material", int(form.get("item_id") or 0) or None, int(form.get("sort_order") or 0), int(form.get("is_visible") or 0)))
            elif action == "home_delete":
                await db.execute("DELETE FROM mini_app_home_sections WHERE id=?", (int(form["id"]),))
            elif action == "consultation_save":
                keys = ["title", "description", "body", "booking_label", "booking_url", "contact_label", "contact_url", "topic_label", "topic_url"]
                values = [str(form.get(key) or "").strip() or None for key in keys]
                await db.execute("INSERT INTO mini_app_consultation(id,title,description,body,booking_label,booking_url,contact_label,contact_url,topic_label,topic_url,show_booking,show_contact,show_topic,updated_at) VALUES(1,?,?,?,?,?,?,?,?,?,?,?, ?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,description=excluded.description,body=excluded.body,booking_label=excluded.booking_label,booking_url=excluded.booking_url,contact_label=excluded.contact_label,contact_url=excluded.contact_url,topic_label=excluded.topic_label,topic_url=excluded.topic_url,show_booking=excluded.show_booking,show_contact=excluded.show_contact,show_topic=excluded.show_topic,updated_at=excluded.updated_at", (*values, int(form.get("show_booking") or 0), int(form.get("show_contact") or 0), int(form.get("show_topic") or 0), now))
            elif action == "settings_save":
                keys = ["app_name", "guest_text", "expired_text", "join_label", "join_url", "renew_label", "renew_url"]
                for key in keys:
                    await db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f"mini_app.{key}", str(form.get(key) or "").strip()))
            else:
                raise web.HTTPBadRequest(text="Неизвестное действие")
            await db.commit()
        finally:
            await db.close()
        raise web.HTTPSeeOther(location=self.url("/learning", saved=1))

    def select_categories(self, categories, value=None):
        return ''.join(f'<option value="{r["id"]}" {"selected" if value and int(value)==r["id"] else ""}>{esc(r["name"])}</option>' for r in categories)

    def render(self, categories, materials, courses, lessons, home, consultation, settings, notice):
        settings_map = {r["key"].removeprefix("mini_app."): r["value"] for r in settings}
        c = consultation or {}
        category_options = self.select_categories(categories)
        material_options = ''.join(f'<option value="{r["id"]}">{esc(r["title"])}</option>' for r in materials)
        course_options = ''.join(f'<option value="{r["id"]}">{esc(r["title"])}</option>' for r in courses)
        action_url = self.url("/learning/action")
        def category_row(r):
            return f'''<tr><td>{esc(r["name"])}</td><td>{esc(r["slug"])}</td><td><details><summary>Изменить</summary><form method="post" action="{action_url}" class="inline-edit"><input type="hidden" name="action" value="category_save"><input type="hidden" name="id" value="{r["id"]}"><input name="name" value="{esc(r["name"])}" required><input name="slug" value="{esc(r["slug"])}" required><input name="icon" value="{esc(r["icon"] or "")}" placeholder="Иконка"><input name="sort_order" type="number" value="{r["sort_order"]}"><select name="is_visible"><option value="1" {"selected" if r["is_visible"] else ""}>Видима</option><option value="0" {"selected" if not r["is_visible"] else ""}>Скрыта</option></select><button>Сохранить</button></form></details><form method="post" action="{action_url}"><input type="hidden" name="action" value="category_delete"><input type="hidden" name="id" value="{r["id"]}"><button class="danger">Удалить</button></form></td></tr>'''
        def material_row(r):
            return f'''<tr><td><b>{esc(r["title"])}</b><small>{esc(r["short_description"] or "")}</small></td><td>{esc(r["category_name"] or "—")}</td><td>{esc(r["format"] or "—")}</td><td><span class="pill {esc(r["status"])}">{esc(r["status"])}</span></td><td><details><summary>Изменить</summary><form method="post" action="{action_url}" enctype="multipart/form-data" class="inline-edit"><input type="hidden" name="action" value="material_save"><input type="hidden" name="id" value="{r["id"]}"><input name="title" value="{esc(r["title"])}" required><input name="format" value="{esc(r["format"] or "")}" placeholder="Формат"><select name="category_id"><option value="">Без категории</option>{self.select_categories(categories, r["category_id"])}</select><textarea name="short_description">{esc(r["short_description"] or "")}</textarea><textarea name="full_description">{esc(r["full_description"] or "")}</textarea><input name="cover_url" value="{esc(r["cover_url"] or "")}" placeholder="Обложка URL"><input name="telegram_url" value="{esc(r["telegram_url"] or "")}" placeholder="Telegram URL"><label>Добавить файл<input type="file" name="material_file" accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.jpg,.jpeg,.png,.webp,.mp3,.mp4"></label><select name="status"><option value="draft" {"selected" if r["status"]=="draft" else ""}>Черновик</option><option value="published" {"selected" if r["status"]=="published" else ""}>Опубликован</option><option value="hidden" {"selected" if r["status"]=="hidden" else ""}>Скрыт</option></select><input name="sort_order" type="number" value="{r["sort_order"]}"><button>Сохранить</button></form></details><form method="post" action="{action_url}"><input type="hidden" name="action" value="material_delete"><input type="hidden" name="id" value="{r["id"]}"><button class="danger">Удалить</button></form></td></tr>'''
        def course_row(r):
            return f'''<tr><td><b>{esc(r["title"])}</b><small>{esc(r["description"] or "")}</small></td><td>{esc(r["category_name"] or "—")}</td><td><span class="pill {esc(r["status"])}">{esc(r["status"])}</span></td><td><details><summary>Изменить</summary><form method="post" action="{action_url}" class="inline-edit"><input type="hidden" name="action" value="course_save"><input type="hidden" name="id" value="{r["id"]}"><input name="title" value="{esc(r["title"])}" required><select name="category_id"><option value="">Без категории</option>{self.select_categories(categories, r["category_id"])}</select><input name="cover_url" value="{esc(r["cover_url"] or "")}" placeholder="Обложка URL"><textarea name="description">{esc(r["description"] or "")}</textarea><select name="status"><option value="draft" {"selected" if r["status"]=="draft" else ""}>Черновик</option><option value="published" {"selected" if r["status"]=="published" else ""}>Опубликован</option><option value="hidden" {"selected" if r["status"]=="hidden" else ""}>Скрыт</option></select><input name="sort_order" type="number" value="{r["sort_order"]}"><button>Сохранить</button></form></details><form method="post" action="{action_url}"><input type="hidden" name="action" value="course_delete"><input type="hidden" name="id" value="{r["id"]}"><button class="danger">Удалить</button></form></td></tr>'''
        category_rows = ''.join(category_row(r) for r in categories) or '<tr><td colspan="3" class="empty">Категорий пока нет</td></tr>'
        material_rows = ''.join(material_row(r) for r in materials) or '<tr><td colspan="5" class="empty">Материалов пока нет</td></tr>'
        course_rows = ''.join(course_row(r) for r in courses) or '<tr><td colspan="4" class="empty">Курсов пока нет</td></tr>'
        lesson_rows = ''.join(f'<tr><td>{esc(r["course_title"])}</td><td>{esc(r["material_title"])}</td><td>{r["sort_order"]}</td><td><form method="post" action="{self.url("/learning/action")}"><input type="hidden" name="action" value="lesson_delete"><input type="hidden" name="id" value="{r["id"]}"><button class="danger">Убрать из курса</button></form></td></tr>' for r in lessons) or '<tr><td colspan="4" class="empty">Уроков пока нет</td></tr>'
        home_rows = ''.join(f'<tr><td>{esc(r["title"])}</td><td>{esc(r["material_title"] or "—")}</td><td>{"да" if r["is_visible"] else "нет"}</td><td><form method="post" action="{self.url("/learning/action")}"><input type="hidden" name="action" value="home_delete"><input type="hidden" name="id" value="{r["id"]}"><button class="danger">Удалить</button></form></td></tr>' for r in home) or '<tr><td colspan="4" class="empty">Блоков главной пока нет</td></tr>'
        check = lambda key: 'checked' if c.get(key) else ''
        return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Обучение — Nastaunik</title><style>
        :root{{--bg:#f4eee5;--paper:#fffaf3;--ink:#3b2b25;--muted:#8c776b;--line:#e4d5c6;--accent:#b9654e}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:14px/1.45 system-ui,sans-serif}}main{{max-width:1200px;margin:auto;padding:24px 18px 70px}}h1,h2{{font-family:Georgia,serif}}h1{{font-size:38px;margin:0}}h2{{margin:30px 0 12px}}section,.form{{background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:16px;margin:12px 0}}form.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}}label{{color:var(--muted);font-size:12px}}input,textarea,select{{width:100%;min-height:40px;margin-top:5px;padding:9px;border:1px solid var(--line);background:#fffdf8;color:var(--ink);font:inherit}}textarea{{min-height:85px}}button{{border:0;background:var(--accent);color:white;padding:9px 13px;cursor:pointer;border-radius:9px;font-weight:700}}button.danger{{background:#98483d}}table{{width:100%;border-collapse:collapse}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}small{{display:block;color:var(--muted)}}.pill{{padding:3px 7px;border-radius:8px;background:#ead5c6;font-size:11px}}.pill.published{{background:#d7eadb;color:#28653f}}.empty{{text-align:center;color:var(--muted)}}.notice{{padding:12px;background:#d7eadb;border-radius:10px}}details{{margin-bottom:7px}}summary{{cursor:pointer;color:var(--accent);font-weight:700}}.inline-edit{{display:grid;gap:6px;min-width:220px;margin:8px 0}}.inline-edit input,.inline-edit textarea,.inline-edit select{{min-height:34px;margin:0}}.tabs{{display:flex;gap:8px;flex-wrap:wrap;margin:24px 0 8px;position:sticky;top:0;padding:10px 0;background:var(--bg);z-index:2}}.tab{{background:var(--paper);color:var(--ink);border:1px solid var(--line);font-weight:600}}.tab.active{{background:var(--accent);color:#fff}}.tab-panel{{display:none}}.tab-panel.active{{display:block}}@media(max-width:760px){{form.grid{{grid-template-columns:1fr}}table{{font-size:12px}}th,td{{padding:8px 5px}}}}
        </style></head><body><main><p><a href="{self.url('/')}">← CRM</a></p><h1>Обучение</h1><p>Здесь управляются материалы и учебные курсы. Задания добавляются отдельно и не обязательны.</p>{'<div class="notice">Сохранено</div>' if notice else ''}<nav class="tabs" aria-label="Разделы обучения"></nav>
        <h2>Настройки Mini App</h2><form class="form grid" method="post" action="{self.url('/learning/action')}"><input type="hidden" name="action" value="settings_save"><label>Название<input name="app_name" value="{esc(settings_map.get('app_name','Nastaŭnik'))}"></label><label>CTA вступления<input name="join_label" value="{esc(settings_map.get('join_label','Вступить в клуб'))}"></label><label>Ссылка вступления<input name="join_url" value="{esc(settings_map.get('join_url',''))}"></label><label>CTA продления<input name="renew_label" value="{esc(settings_map.get('renew_label','Продлить участие'))}"></label><label>Ссылка продления<input name="renew_url" value="{esc(settings_map.get('renew_url',''))}"></label><label>Текст гостю<textarea name="guest_text">{esc(settings_map.get('guest_text',''))}</textarea></label><label>Текст после окончания<textarea name="expired_text">{esc(settings_map.get('expired_text',''))}</textarea></label><button>Сохранить настройки</button></form>
        <h2>Категории</h2><form class="form grid" method="post" action="{self.url('/learning/action')}"><input type="hidden" name="action" value="category_save"><label>Название<input name="name" required></label><label>Slug<input name="slug" required></label><label>Иконка<input name="icon"></label><label>Обложка URL<input name="cover_url"></label><label>Порядок<input name="sort_order" type="number" value="0"></label><label>Видимость<select name="is_visible"><option value="1">Видима</option><option value="0">Скрыта</option></select></label><button>Создать категорию</button></form><section><table><tr><th>Название</th><th>Slug</th><th></th></tr>{category_rows}</table></section>
        <h2>Материалы</h2><form class="form grid" method="post" action="{self.url('/learning/action')}" enctype="multipart/form-data"><input type="hidden" name="action" value="material_save"><label>Название<input name="title" required></label><label>Формат<input name="format" placeholder="Видео, текст…"></label><label>Категория<select name="category_id"><option value="">Без категории</option>{category_options}</select></label><label>Короткое описание<textarea name="short_description"></textarea></label><label>Полное описание<textarea name="full_description"></textarea></label><label>Обложка URL<input name="cover_url"></label><label>Telegram-пост URL<input name="telegram_url"></label><label>Файл материала<input type="file" name="material_file" accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.jpg,.jpeg,.png,.webp,.mp3,.mp4"></label><label>Статус<select name="status"><option value="draft">Черновик</option><option value="published">Опубликован</option><option value="hidden">Скрыт</option></select></label><label>Порядок<input name="sort_order" type="number" value="0"></label><button>Создать материал</button></form><section><table><tr><th>Материал</th><th>Категория</th><th>Формат</th><th>Статус</th><th></th></tr>{material_rows}</table></section>
        <h2>Курсы</h2><form class="form grid" method="post" action="{self.url('/learning/action')}"><input type="hidden" name="action" value="course_save"><label>Название<input name="title" required></label><label>Категория<select name="category_id"><option value="">Без категории</option>{category_options}</select></label><label>Обложка URL<input name="cover_url"></label><label>Описание<textarea name="description"></textarea></label><label>Статус<select name="status"><option value="draft">Черновик</option><option value="published">Опубликован</option><option value="hidden">Скрыт</option></select></label><label>Порядок<input name="sort_order" type="number" value="0"></label><button>Создать курс</button></form><section><table><tr><th>Курс</th><th>Категория</th><th>Статус</th><th></th></tr>{course_rows}</table></section>
        <h2>Уроки курса</h2><form class="form grid" method="post" action="{self.url('/learning/action')}"><input type="hidden" name="action" value="lesson_add"><label>Курс<select name="course_id" required>{course_options}</select></label><label>Материал<select name="material_id" required>{material_options}</select></label><label>Название урока (необязательно)<input name="title_override"></label><label>Порядок<input name="sort_order" type="number" value="0"></label><button>Добавить существующий материал</button></form><section><table><tr><th>Курс</th><th>Материал</th><th>Порядок</th><th></th></tr>{lesson_rows}</table></section>
        <h2>Главная</h2><form class="form grid" method="post" action="{self.url('/learning/action')}"><input type="hidden" name="action" value="home_save"><label>Ключ блока<input name="section_key" value="featured" required></label><label>Заголовок<input name="title" value="Рекомендуем"></label><label>Материал<select name="item_id"><option value="">Без материала</option>{material_options}</select></label><label>Порядок<input name="sort_order" type="number" value="0"></label><label>Видимость<select name="is_visible"><option value="1">Видим</option><option value="0">Скрыт</option></select></label><button>Сохранить блок</button></form><section><table><tr><th>Заголовок</th><th>Материал</th><th>Видимость</th><th></th></tr>{home_rows}</table></section>
        <h2>Консультации</h2><form class="form grid" method="post" action="{self.url('/learning/action')}"><input type="hidden" name="action" value="consultation_save"><label>Заголовок<input name="title" value="{esc(c.get('title') or 'Консультации')}"></label><label>Описание<textarea name="description">{esc(c.get('description') or '')}</textarea></label><label>Текст<textarea name="body">{esc(c.get('body') or '')}</textarea></label><label>Кнопка записи<input name="booking_label" value="{esc(c.get('booking_label') or '')}"><input name="booking_url" value="{esc(c.get('booking_url') or '')}"><input type="checkbox" name="show_booking" value="1" {check('show_booking')}> Показывать</label><label>Кнопка «Написать»<input name="contact_label" value="{esc(c.get('contact_label') or '')}"><input name="contact_url" value="{esc(c.get('contact_url') or '')}"><input type="checkbox" name="show_contact" value="1" {check('show_contact')}> Показывать</label><label>Предложить тему<input name="topic_label" value="{esc(c.get('topic_label') or '')}"><input name="topic_url" value="{esc(c.get('topic_url') or '')}"><input type="checkbox" name="show_topic" value="1" {check('show_topic')}> Показывать</label><button>Сохранить консультации</button></form>
        </main><script>(function(){{const main=document.querySelector('main'),nav=document.querySelector('.tabs'),headings=[...main.querySelectorAll('h2')],labels={{'Настройки Mini App':'Настройки','Категории':'Категории','Материалы':'Материалы','Курсы':'Курсы','Уроки курса':'Уроки','Главная':'Главная','Консультации':'Консультации'}};headings.forEach((heading,index)=>{{const panel=document.createElement('div');panel.className='tab-panel';heading.parentNode.insertBefore(panel,heading);let node=heading;while(node&&node!==headings[index+1]){{const next=node.nextSibling;panel.appendChild(node);node=next}}const button=document.createElement('button');button.type='button';button.className='tab';button.textContent=labels[heading.textContent.trim()]||heading.textContent.trim();button.addEventListener('click',()=>{{document.querySelectorAll('.tab-panel').forEach(p=>p.classList.remove('active'));document.querySelectorAll('.tab').forEach(b=>b.classList.remove('active'));panel.classList.add('active');button.classList.add('active');history.replaceState(null,'','#'+index)}});nav.appendChild(button)}});let selected=Number(location.hash.slice(1));if(!Number.isInteger(selected)||selected<0||selected>=headings.length)selected=headings.findIndex(h=>h.textContent.trim()==='Материалы');if(selected<0)selected=0;nav.children[selected].click()}})();</script></body></html>'''
