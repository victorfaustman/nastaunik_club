from __future__ import annotations

import asyncio
import html
import logging
import mimetypes
import re
import secrets
import shutil
import sqlite3
from contextlib import suppress
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import aiosqlite
from aiohttp import web

from bot.course_admin import CourseAdmin
from bot.database import Database

logger = logging.getLogger(__name__)


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


class RichTextSanitizer(HTMLParser):
    allowed_tags = {"div", "p", "br", "strong", "b", "em", "i", "u", "s", "h2", "h3", "ul", "ol", "li", "blockquote", "a", "img", "video", "source", "figure", "figcaption", "hr"}
    void_tags = {"br", "img", "source", "hr"}
    allowed_attributes = {
        "a": {"href", "title"},
        "img": {"src", "alt", "title"},
        "video": {"src", "poster", "controls", "preload", "playsinline"},
        "source": {"src", "type"},
        "figure": {"class", "draggable"},
        "figcaption": {"contenteditable"},
    }
    url_attributes = {"href", "src", "poster"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.output: list[str] = []
        self.blocked_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "form"}:
            self.blocked_depth += 1
            return
        if self.blocked_depth:
            return
        if tag not in self.allowed_tags:
            return
        safe_attrs = []
        for name, value in attrs:
            name = name.lower()
            if name not in self.allowed_attributes.get(tag, set()):
                continue
            value = "" if value is None else str(value)
            if name in self.url_attributes and not re.match(r"^(?:https?:|/|#)", value, re.I):
                continue
            if tag == "figure" and name == "class":
                value = "inline-media" if "inline-media" in value.split() else ""
                if not value:
                    continue
            safe_attrs.append(f' {name}="{html.escape(value, quote=True)}"')
        if tag == "a":
            safe_attrs.append(' rel="noopener noreferrer"')
        self.output.append(f"<{tag}{''.join(safe_attrs)}>")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "iframe", "object", "form"}:
            self.blocked_depth = max(0, self.blocked_depth - 1)
            return
        if self.blocked_depth:
            return
        if tag in self.allowed_tags and tag not in self.void_tags:
            self.output.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        if not self.blocked_depth:
            self.output.append(html.escape(data, quote=False))


def clean_rich_text(value: object) -> str:
    sanitizer = RichTextSanitizer()
    sanitizer.feed("" if value is None else str(value))
    sanitizer.close()
    cleaned = "".join(sanitizer.output)
    return re.sub(r"<figcaption(?:\s+[^>]*)?>\s*Добавьте подпись\s*</figcaption>", "", cleaned, flags=re.I)

class LearningAdmin:
    """Simple, content-first admin for the learning library."""

    def __init__(self, database_path: Path, url_builder):
        self.database_path = database_path
        self.url = url_builder
        self.schema = Database(database_path)
        self.media_dir = Path(__file__).resolve().parent.parent / "media" / "mini_app"
        self.course_admin = CourseAdmin(self)

    async def connect(self):
        db = await aiosqlite.connect(self.database_path, timeout=8)
        db.row_factory = sqlite3.Row
        await db.execute("PRAGMA foreign_keys = ON")
        return db

    def material_url(self, material_id=None, **query):
        query["material"] = "new" if material_id is None else str(material_id)
        return self.url("/learning", **query)

    async def rows(self, db, sql, params=()):
        cur = await db.execute(sql, params)
        return await cur.fetchall()

    def categories_options(self, categories, selected=None):
        return "".join(
            f'<option value="{r["id"]}" {"selected" if selected and int(selected) == r["id"] else ""}>{esc(r["name"])}</option>'
            for r in categories
        )

    def tag_options(self, tags, selected_ids=()):
        selected_ids = {int(value) for value in selected_ids}
        return "".join(
            f'<option value="{tag["id"]}" {"selected" if tag["id"] in selected_ids else ""}>{esc(tag["name"])}</option>'
            for tag in tags
        )

    @staticmethod
    def tag_slug(name: str) -> str:
        slug = re.sub(r"[^a-z0-9а-яё]+", "-", name.lower()).strip("-")
        return slug or secrets.token_hex(4)

    async def page(self, request: web.Request) -> web.Response:
        await self.schema.init()
        if request.query.get("section") == "courses" or request.query.get("course") is not None or request.query.get("lesson") is not None:
            return await self.course_admin.page(request)
        if request.query.get("analytics") == "1":
            return await self.analytics(request)
        if request.query.get("material") is not None:
            return await self.article_editor(request)
        return await self.index(request)

    async def analytics(self, request: web.Request) -> web.Response:
        db = await self.connect()
        try:
            cur = await db.execute(
                """SELECT
                       (SELECT COUNT(*) FROM mini_app_materials WHERE status='published' AND library_visible=1) materials,
                       (SELECT COUNT(*) FROM mini_app_material_views) views,
                       (SELECT COUNT(*) FROM mini_app_material_views WHERE completed_at IS NOT NULL) completions,
                       (SELECT COUNT(*) FROM mini_app_material_likes) likes"""
            )
            totals = await cur.fetchone()
            materials = await self.rows(
                db,
                """SELECT m.id,m.title,m.is_free,
                          (SELECT COUNT(*) FROM mini_app_material_views v WHERE v.material_id=m.id) views,
                          (SELECT COUNT(*) FROM mini_app_material_views v WHERE v.material_id=m.id AND v.completed_at IS NOT NULL) completions,
                          (SELECT COUNT(*) FROM mini_app_material_likes l WHERE l.material_id=m.id) likes
                   FROM mini_app_materials m WHERE m.status='published' AND m.library_visible=1
                   ORDER BY views DESC,likes DESC,m.updated_at DESC""",
            )
        finally:
            await db.close()
        completion_rate = round(totals["completions"] / totals["views"] * 100) if totals["views"] else 0
        rows = "".join(
            f'''<tr><td><a href="{self.material_url(row["id"])}">{esc(row["title"])}</a>{'<span class="free">Бесплатно</span>' if row["is_free"] else ''}</td><td>{row["views"]}</td><td>{row["completions"]}</td><td>{round(row["completions"] / row["views"] * 100) if row["views"] else 0}%</td><td>{row["likes"]}</td></tr>'''
            for row in materials
        ) or '<tr><td colspan="5" class="empty">Данных пока нет.</td></tr>'
        return web.Response(text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Аналитика материалов — Nastaunik</title><style>
        :root{{--bg:#f6f2ed;--paper:#fff;--ink:#302621;--muted:#89776d;--line:#e5d9cf;--accent:#b9654e}}*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1040px;margin:auto;padding:28px 20px 70px}}a{{color:inherit}}h1{{font:700 38px Georgia,serif;margin:8px 0 24px}}.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:22px}}.metric{{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:18px}}.metric b{{display:block;font:700 30px Georgia,serif}}.metric span{{color:var(--muted)}}.table-wrap{{overflow:auto;background:var(--paper);border:1px solid var(--line);border-radius:16px}}table{{width:100%;border-collapse:collapse;min-width:650px}}th,td{{padding:14px 16px;text-align:left;border-bottom:1px solid var(--line)}}th{{color:var(--muted);font-size:12px}}td:first-child{{font-weight:700}}.free{{display:inline-block;margin-left:8px;padding:2px 7px;border-radius:99px;background:#e3f0e5;color:#326442;font-size:10px}}.empty{{text-align:center;color:var(--muted);padding:30px}}@media(max-width:700px){{.summary{{grid-template-columns:repeat(2,1fr)}}}}
        </style></head><body><main><a href="{self.url('/learning')}">← Материалы</a><h1>Аналитика материалов</h1><section class="summary"><div class="metric"><b>{totals["materials"]}</b><span>материалов</span></div><div class="metric"><b>{totals["views"]}</b><span>уникальных просмотров</span></div><div class="metric"><b>{completion_rate}%</b><span>дочитали до конца</span></div><div class="metric"><b>{totals["likes"]}</b><span>лайков</span></div></section><div class="table-wrap"><table><thead><tr><th>Материал</th><th>Просмотры</th><th>Дочитали</th><th>Завершение</th><th>Лайки</th></tr></thead><tbody>{rows}</tbody></table></div></main></body></html>''', content_type="text/html")

    async def index(self, request: web.Request) -> web.Response:
        db = await self.connect()
        try:
            categories = await self.rows(db, "SELECT * FROM mini_app_categories ORDER BY sort_order, name")
            tags = await self.rows(db, "SELECT * FROM mini_app_tags ORDER BY name")
            sql = """SELECT m.*, c.name category_name,
                     (SELECT COUNT(*) FROM mini_app_material_files f WHERE f.material_id=m.id) file_count,
                     (SELECT COUNT(*) FROM mini_app_material_blocks b WHERE b.material_id=m.id) block_count,
                     (SELECT COUNT(*) FROM mini_app_video_jobs j
                        WHERE j.status IN ('queued','processing') AND (
                          instr(COALESCE(m.full_description,''),j.stored_name)>0 OR
                          EXISTS(SELECT 1 FROM mini_app_material_files vf WHERE vf.material_id=m.id AND vf.stored_name=j.stored_name) OR
                          EXISTS(SELECT 1 FROM mini_app_material_blocks vb WHERE vb.material_id=m.id AND instr(COALESCE(vb.content,''),j.stored_name)>0)
                        )) video_busy_count,
                     (SELECT COUNT(*) FROM mini_app_video_jobs j
                        WHERE j.status='failed' AND (
                          instr(COALESCE(m.full_description,''),j.stored_name)>0 OR
                          EXISTS(SELECT 1 FROM mini_app_material_files vf WHERE vf.material_id=m.id AND vf.stored_name=j.stored_name) OR
                          EXISTS(SELECT 1 FROM mini_app_material_blocks vb WHERE vb.material_id=m.id AND instr(COALESCE(vb.content,''),j.stored_name)>0)
                        )) video_failed_count,
                     (SELECT group_concat(t.name, ', ') FROM mini_app_tags t JOIN mini_app_material_tags mt ON mt.tag_id=t.id WHERE mt.material_id=m.id) tag_names
                     FROM mini_app_materials m
                     LEFT JOIN mini_app_categories c ON c.id=m.category_id
                     WHERE m.library_visible=1"""
            params = []
            query = str(request.query.get("q") or "").strip()
            if query:
                sql += " AND (m.title LIKE ? OR m.short_description LIKE ? OR EXISTS (SELECT 1 FROM mini_app_material_tags mt JOIN mini_app_tags t ON t.id=mt.tag_id WHERE mt.material_id=m.id AND t.name LIKE ?))"
                params.extend([f"%{query}%", f"%{query}%", f"%{query}%"])
            tag = request.query.get("tag")
            if tag and tag.isdigit():
                sql += " AND EXISTS (SELECT 1 FROM mini_app_material_tags mt WHERE mt.material_id=m.id AND mt.tag_id=?)"
                params.append(int(tag))
            sql += " ORDER BY m.updated_at DESC, m.id DESC"
            materials = await self.rows(db, sql, params)
        finally:
            await db.close()
        cards = "".join(
            f'''<article class="material"><div><div class="eyebrow">{esc(r["format"] or "Материал")}{" · Бесплатно" if r["is_free"] else ""}</div>
            <h2>{esc(r["title"])}</h2><p>{esc(r["short_description"] or "Описание ещё не добавлено")}</p>
            <small>{esc(r["tag_names"] or "Без тегов")} · {r["block_count"]} блоков · {r["file_count"]} файлов</small>{f'<div class="video-badge busy">◌ Видео обрабатывается в фоне</div>' if r["video_busy_count"] else ''}{f'<div class="video-badge failed">! Ошибка обработки видео</div>' if r["video_failed_count"] else ''}</div>
            <div class="actions"><a class="button" href="{self.material_url(r["id"])}">Открыть</a><form method="post" action="{self.url("/learning/material/action")}" onsubmit="return confirm('Удалить этот материал?')"><input type="hidden" name="action" value="material_delete"><input type="hidden" name="id" value="{r["id"]}"><button class="danger">Удалить</button></form></div></article>'''
            for r in materials
        ) or '<div class="empty">Материалов пока нет. Создайте первый.</div>'
        return web.Response(
            text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
            <title>Материалы — Nastaunik</title><style>
            :root{{--bg:#f6f2ed;--paper:#fff;--ink:#302621;--muted:#89776d;--line:#e5d9cf;--accent:#b9654e;--soft:#f0e8e1}}
            *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
            main{{max-width:1040px;margin:auto;padding:28px 20px 70px}}a{{color:inherit}}h1{{font:700 38px Georgia,serif;margin:8px 0}}
            h2{{margin:0 0 6px;font-size:20px}}p{{color:var(--muted)}}.top{{display:flex;justify-content:space-between;gap:18px;align-items:center}}
            .button,button{{border:0;border-radius:10px;padding:11px 16px;background:var(--accent);color:#fff;text-decoration:none;font-weight:700;cursor:pointer}}
            .secondary{{background:var(--soft);color:var(--ink)}}.danger{{background:#fff0ed;color:#a34d43}}.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}}
            input,select{{border:1px solid var(--line);border-radius:10px;padding:11px;background:#fff;font:inherit}}
            input[name=q]{{min-width:280px;flex:1}}.material{{display:flex;justify-content:space-between;gap:20px;align-items:center;background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:20px;margin:12px 0}}
            .material p{{margin:0 0 8px}}small,.hint{{color:var(--muted)}}.eyebrow{{font-size:11px;color:var(--accent);font-weight:700;text-transform:uppercase}}
            .actions{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end}}.status{{padding:5px 9px;border-radius:8px;background:var(--soft);font-size:12px}}
            .video-badge{{display:inline-block;margin-top:9px;padding:5px 9px;border-radius:999px;font-size:12px;font-weight:700}}.video-badge.busy{{background:#fff1c9;color:#76510b}}.video-badge.failed{{background:#fff0ed;color:#a34d43}}
            .status.published{{background:#dcefe0;color:#28653f}}.empty{{background:var(--paper);border:1px dashed var(--line);border-radius:16px;padding:45px;text-align:center;color:var(--muted)}}
            .admin-tabs{{display:flex;gap:7px;margin:0 0 28px;padding:5px;width:max-content;border:1px solid var(--line);border-radius:13px;background:var(--paper)}}.admin-tabs a{{padding:8px 14px;border-radius:9px;color:var(--muted);font-weight:750;text-decoration:none}}.admin-tabs a.active{{background:var(--accent);color:#fff}}
            details{{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:14px;margin:14px 0}}summary{{cursor:pointer;font-weight:700}}
            @media(max-width:680px){{.top,.material{{align-items:stretch;flex-direction:column}}.actions{{justify-content:flex-start}}input[name=q]{{min-width:0;width:100%}}.admin-tabs{{width:100%}}.admin-tabs a{{flex:1;text-align:center}}}}
            </style></head><body><main>{self.course_admin.tabs("materials")}
            <div class="top"><div><h1>Материалы</h1><p>Создавайте уроки и добавляйте контент. Задания добавляются отдельно.</p></div>
            <div class="actions"><a class="button secondary" href="{self.url('/learning', analytics=1)}">Аналитика</a><a class="button" href="{self.material_url()}">+ Добавить материал</a></div></div>
            <form class="toolbar" method="get"><input name="q" value="{esc(query)}" placeholder="Найти материал">
            <select name="tag"><option value="">Все теги</option>{self.tag_options(tags, [tag] if tag else [])}</select><button class="secondary">Найти</button></form>
            {cards}</main></body></html>''',
            content_type="text/html",
        )

    async def article_editor(self, request: web.Request) -> web.Response:
        raw_id = str(request.query.get("material") or "new")
        return_course_id = int(request.query.get("return_course") or 0)
        return_lesson_id = int(request.query.get("return_lesson") or 0)
        return_block_id = int(request.query.get("return_block") or 0)
        is_course_material = request.query.get("course_material") == "1"
        db = await self.connect()
        try:
            material = None
            if raw_id != "new":
                if not raw_id.isdigit():
                    raise web.HTTPNotFound(text="Материал не найден")
                cur = await db.execute("SELECT * FROM mini_app_materials WHERE id=?", (int(raw_id),))
                material = await cur.fetchone()
                if not material:
                    raise web.HTTPNotFound(text="Материал не найден")
            tags = await self.rows(db, "SELECT * FROM mini_app_tags ORDER BY name")
            files = await self.rows(db, "SELECT * FROM mini_app_material_files WHERE material_id=? ORDER BY sort_order,id", (material["id"],)) if material else []
            blocks = await self.rows(db, "SELECT * FROM mini_app_material_blocks WHERE material_id=? ORDER BY sort_order,id", (material["id"],)) if material else []
            selected_rows = await self.rows(db, "SELECT tag_id FROM mini_app_material_tags WHERE material_id=?", (material["id"],)) if material else []
            if material and is_course_material:
                linked = await (await db.execute(
                    """SELECT 1 FROM mini_app_course_blocks b
                       JOIN mini_app_course_units l ON l.id=b.lesson_id
                       WHERE b.id=? AND b.material_id=? AND l.id=? AND l.course_id=?""",
                    (return_block_id, material["id"], return_lesson_id, return_course_id),
                )).fetchone()
                if not linked:
                    raise web.HTTPNotFound(text="Лонгрид курса не найден")
        finally:
            await db.close()

        m = material or {"id": "", "title": "", "short_description": "", "full_description": "", "cover_url": "", "is_free": 0}
        return_url = self.course_admin.lesson_url(return_lesson_id, return_course_id) if is_course_material else self.url("/learning")
        return_label = "← Вернуться к уроку" if is_course_material else "← Все материалы"
        return_fields = (
            f'''<input type="hidden" name="course_material" value="1"><input type="hidden" name="return_course" value="{return_course_id}"><input type="hidden" name="return_lesson" value="{return_lesson_id}"><input type="hidden" name="return_block" value="{return_block_id}">'''
            if is_course_material else ""
        )
        selected_ids = {row["tag_id"] for row in selected_rows}
        if material and request.query.get("preview"):
            return self.preview(material, blocks, files, tags, selected_ids)
        tag_chips = "".join(
            f'''<span class="tag-wrap" style="--tag:{esc(tag["color"] or "#D97757")}"><input id="tag-{tag["id"]}" type="checkbox" name="tag_ids" value="{tag["id"]}" {"checked" if tag["id"] in selected_ids else ""}><label for="tag-{tag["id"]}">{esc(tag["name"])}</label><button type="button" class="tag-edit" title="Редактировать тег" onclick="document.getElementById('edit-tag-{tag["id"]}').showModal()">✎</button></span>'''
            for tag in tags
        )
        tag_dialogs = "".join(
            f'''<dialog id="edit-tag-{tag["id"]}"><form class="tag-modal-form" data-existing="{tag["id"]}" method="post" action="{self.url("/learning/material/action")}"><input type="hidden" name="action" value="tag_save"><input type="hidden" name="ajax" value="1"><input type="hidden" name="id" value="{tag["id"]}"><input type="hidden" name="return_material" value="{m["id"]}"><h2>Редактировать тег</h2><label>Название<input name="tag_name" value="{esc(tag["name"])}" required></label><label>Цвет<input type="color" name="tag_color" value="{esc(tag["color"] or "#D97757")}"></label><div class="actions"><button>Сохранить</button><button type="button" class="danger tag-delete" data-id="{tag["id"]}">Удалить тег</button><button type="button" class="secondary" onclick="this.closest('dialog').close()">Отмена</button></div></form></dialog>'''
            for tag in tags
        )
        media_cards = "".join(
            f'''<form class="asset-card" method="post" action="{self.url("/learning/material/action")}">{return_fields}<input type="hidden" name="material_id" value="{m["id"]}"><input type="hidden" name="id" value="{block["id"]}"><input type="hidden" name="block_type" value="{esc(block["block_type"])}"><div class="asset-icon">{"▣" if block["block_type"] == "image" else "▶"}</div><div class="asset-fields"><input name="block_title" value="{esc(block["title"] or "")}" placeholder="Заголовок"><textarea name="block_description" placeholder="Краткое описание">{esc(block["description"] or "")}</textarea><input name="block_content" value="{esc(block["content"] or "")}" placeholder="Ссылка на изображение или видео"></div><div class="asset-actions"><button name="action" value="block_save" class="secondary">Сохранить</button><button name="action" value="block_delete" class="danger" onclick="return confirm('Удалить этот элемент?')">Удалить</button></div></form>'''
            for block in blocks if block["block_type"] in {"image", "video"}
        ) or '<p class="empty-note">Изображений и видео пока нет.</p>'
        file_cards = "".join(
            f'''<form class="asset-card" method="post" action="{self.url("/learning/material/action")}">{return_fields}<input type="hidden" name="material_id" value="{m["id"]}"><input type="hidden" name="id" value="{file["id"]}"><div class="asset-icon">↧</div><div class="asset-fields"><b>{esc(file["file_name"])}</b><input name="file_title" value="{esc(file["title"] or "")}" placeholder="Заголовок материала"><textarea name="file_description" placeholder="Кратко опишите, что внутри">{esc(file["description"] or "")}</textarea></div><div class="asset-actions"><button name="action" value="file_update" class="secondary">Сохранить</button><button name="action" value="file_delete" class="danger" onclick="return confirm('Удалить файл?')">Удалить</button></div></form>'''
            for file in files
        ) or '<p class="empty-note">Дополнительных материалов пока нет.</p>'
        title = "Новый материал" if not material else esc(material["title"])
        saved = '<div class="toast">Изменения сохранены</div>' if request.query.get("saved") else ""
        existing_controls = ""
        if material:
            existing_controls = f'''<a class="button secondary" href="{self.material_url(m["id"], preview=1)}" target="_blank">Предпросмотр</a><button type="button" class="danger" id="delete-material" data-id="{m["id"]}">Удалить</button>'''
        cover_preview = (
            f'<div id="cover-current" class="cover-current"><img id="cover-preview" class="cover-preview" src="{esc(m["cover_url"])}" alt="Текущая обложка">'
            '<button id="remove-cover-button" type="button" class="danger cover-remove">× Удалить обложку</button></div>'
            if m["cover_url"] else
            '<div id="cover-current" class="cover-current" hidden><img id="cover-preview" class="cover-preview" alt="Предпросмотр обложки"><button id="remove-cover-button" type="button" class="danger cover-remove">× Удалить обложку</button></div>'
        )

        return web.Response(text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — Nastaunik</title><script defer src="/mini-app/static/admin_material.js?v=7"></script><style>
        :root{{--bg:#f7f5f2;--paper:#fff;--ink:#292421;--muted:#817873;--line:#e7e0da;--accent:#c56349;--soft:#f3ece7}}
        *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}main{{max-width:900px;margin:auto;padding:24px 20px 80px}}a{{color:inherit}}h1{{font:700 36px Georgia,serif;margin:0}}h2{{font-size:21px;margin:0 0 6px}}p{{margin:4px 0}}.topbar{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:22px}}.top-actions,.actions{{display:flex;align-items:center;gap:9px;flex-wrap:wrap}}button,.button{{border:0;border-radius:11px;padding:11px 16px;background:var(--accent);color:white;font:700 14px system-ui;cursor:pointer;text-decoration:none}}.secondary{{background:var(--soft);color:var(--ink)}}.danger{{background:transparent;color:#a44439}}.card{{background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:24px;margin:14px 0}}label.field{{display:block;margin:18px 0 0;color:var(--muted);font-size:13px}}input,textarea{{width:100%;margin-top:6px;border:1px solid var(--line);border-radius:11px;padding:12px 13px;background:#fff;font:inherit;color:var(--ink)}}textarea{{resize:vertical;min-height:92px}}.title-input{{font-size:20px;font-weight:700}}.toolbar{{display:flex;gap:5px;flex-wrap:wrap;padding:7px;background:var(--soft);border-radius:11px 11px 0 0;margin-top:7px}}.toolbar button{{padding:7px 11px;background:transparent;color:var(--ink)}}.toolbar button:hover{{background:#fff}}.toolbar .media-button{{background:var(--accent);color:#fff}}.editor{{min-height:330px;border:1px solid var(--line);border-top:0;border-radius:0 0 11px 11px;padding:18px;font-size:17px;line-height:1.7;outline:none}}.editor:empty:before{{content:attr(data-placeholder);color:#aaa}}.editor figure.inline-media{{position:relative;margin:22px 0;padding:8px;border:1px solid transparent;border-radius:12px;cursor:grab}}.editor figure.inline-media:hover{{border-color:var(--line);background:var(--soft)}}.editor figure.inline-media:before{{content:'⠿ Перетащите, чтобы изменить место';display:block;color:var(--muted);font-size:12px;margin-bottom:6px}}.editor figure img,.editor figure video{{display:block;max-width:100%;max-height:520px;border-radius:10px;margin:auto}}.editor figcaption{{color:var(--muted);font-size:14px;text-align:center;padding:7px;outline:none}}.hint,.empty-note{{font-size:13px;color:var(--muted)}}.tag-list{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}.tag-wrap{{display:inline-flex;align-items:center;border:1px solid color-mix(in srgb,var(--tag) 50%,white);background:color-mix(in srgb,var(--tag) 12%,white);border-radius:999px;overflow:hidden}}.tag-wrap input{{display:none}}.tag-wrap label{{padding:7px 7px 7px 12px;cursor:pointer;color:var(--ink)}}.tag-wrap:has(input:checked){{background:var(--tag);border-color:var(--tag)}}.tag-wrap:has(input:checked) label{{color:#fff}}.tag-edit{{padding:6px 10px 6px 4px;background:transparent;color:inherit;opacity:0}}.tag-wrap:hover .tag-edit{{opacity:.75}}.add-tag{{border:1px dashed var(--line);background:white;color:var(--accent);border-radius:999px;padding:7px 13px}}.cover{{display:flex;align-items:center;gap:18px}}.cover-current{{display:grid;gap:6px;justify-items:start}}.cover-current[hidden]{{display:none}}.cover-preview{{width:180px;aspect-ratio:16/9;object-fit:cover;border-radius:12px;background:var(--soft)}}.cover-remove{{padding:6px 3px;font-size:12px}}.drop{{flex:1;border:1px dashed #c9b9ae;border-radius:13px;padding:18px;text-align:center;cursor:pointer}}.drop input{{display:none}}.section-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:16px}}.asset-card{{display:grid;grid-template-columns:42px 1fr auto;gap:13px;align-items:start;border-top:1px solid var(--line);padding:16px 0}}.asset-icon{{width:42px;height:42px;border-radius:10px;background:var(--soft);display:grid;place-items:center;font-size:20px}}.asset-fields input,.asset-fields textarea{{margin:0 0 8px}}.asset-fields textarea{{min-height:68px}}.asset-actions{{display:flex;flex-direction:column;gap:5px}}.new-asset{{background:var(--soft);border-radius:14px;padding:17px;margin-top:12px}}.new-asset-grid{{display:grid;grid-template-columns:150px 1fr;gap:10px}}select{{width:100%;border:1px solid var(--line);border-radius:11px;padding:12px;background:#fff;font:inherit}}dialog{{border:0;border-radius:18px;padding:24px;box-shadow:0 20px 80px #0003;width:min(420px,90vw)}}dialog::backdrop{{background:#211b1888}}.toast{{background:#e1f2e4;color:#26613b;border-radius:11px;padding:11px 15px;margin-bottom:14px}}.save-state{{font-size:13px;color:var(--muted)}}.loading-overlay{{position:fixed;z-index:20;inset:0;background:#261d19aa;display:none;place-items:center;padding:20px}}.loading-overlay.active{{display:grid}}.loading-box{{width:min(390px,90vw);background:#fff;border-radius:18px;padding:24px;text-align:center;box-shadow:0 24px 80px #0004}}.spinner{{width:38px;height:38px;border:4px solid var(--soft);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 14px}}.progress{{height:8px;background:var(--soft);border-radius:99px;overflow:hidden;margin-top:14px}}.progress i{{display:block;width:8%;height:100%;background:var(--accent);transition:width .2s}}@keyframes spin{{to{{transform:rotate(360deg)}}}}@media(max-width:650px){{.topbar,.cover{{align-items:stretch;flex-direction:column}}.asset-card{{grid-template-columns:42px 1fr}}.asset-actions{{grid-column:2;flex-direction:row}}.new-asset-grid{{grid-template-columns:1fr}}.top-actions{{width:100%}}.top-actions>button{{flex:1}}}}
        </style></head><body><div id="loading-overlay" class="loading-overlay"><div class="loading-box"><div class="spinner"></div><b id="loading-text">Загрузка…</b><div class="progress"><i id="loading-progress"></i></div></div></div><script>window.addEventListener('DOMContentLoaded',()=>{{const overlay=document.getElementById('loading-overlay'),loadingText=document.getElementById('loading-text'),loadingProgress=document.getElementById('loading-progress'),mainForm=document.getElementById('article-form'),uploadUrl=mainForm.getAttribute('action');function showLoading(text,percent=8){{loadingText.textContent=text;loadingProgress.style.width=percent+'%';overlay.classList.add('active')}}function hideLoading(){{overlay.classList.remove('active')}}function uploadWithProgress(data,text){{return new Promise((resolve,reject)=>{{const xhr=new XMLHttpRequest();xhr.open('POST',uploadUrl);showLoading(text);xhr.upload.onprogress=e=>{{if(e.lengthComputable){{const p=Math.max(8,Math.round(e.loaded/e.total*100));loadingProgress.style.width=p+'%';loadingText.textContent=text+' '+p+'%'}}}};xhr.upload.onload=()=>{{loadingProgress.style.width='100%';loadingText.textContent='Сохраняем загруженный файл…'}};xhr.onload=()=>xhr.status>=200&&xhr.status<300?resolve(JSON.parse(xhr.responseText)):reject();xhr.onerror=reject;xhr.send(data)}})}}const coverInput=document.getElementById('cover-input'),coverPreview=document.getElementById('cover-preview'),coverLabel=document.getElementById('cover-label');coverInput.onchange=()=>{{const file=coverInput.files[0];if(!file)return;coverPreview.src=URL.createObjectURL(file);coverPreview.style.visibility='visible';coverLabel.textContent='Выбрано: '+file.name}};mainForm.addEventListener('submit',()=>showLoading(coverInput.files.length?'Загружаем обложку…':'Сохраняем материал…',coverInput.files.length?8:35));const attachmentInput=document.getElementById('attachment-input'),attachmentLabel=document.getElementById('attachment-label');attachmentInput.onchange=()=>{{if(attachmentInput.files[0])attachmentLabel.textContent='Выбрано: '+attachmentInput.files[0].name}};document.querySelectorAll('.upload-form').forEach(f=>f.addEventListener('submit',()=>showLoading('Загружаем дополнительный материал…')));const picker=document.getElementById('inline-media-file');picker.onchange=async()=>{{const file=picker.files[0];if(!file)return;const data=new FormData();data.append('action','inline_upload');data.append('inline_file',file);let item;try{{item=await uploadWithProgress(data,'Загружаем в статью…')}}catch(e){{hideLoading();document.getElementById('save-state').textContent='Не удалось загрузить';return}}hideLoading();const ed=document.getElementById('content-editor'),fig=document.createElement('figure'),media=document.createElement(item.kind==='video'?'video':'img');fig.className='inline-media';fig.draggable=true;media.src=item.url;if(item.kind==='video'){{media.controls=true;media.preload='metadata';media.playsInline=true}}fig.append(media);if(savedRange){{savedRange.deleteContents();savedRange.insertNode(fig)}}else ed.appendChild(fig);const p=document.createElement('p');p.innerHTML='<br>';fig.after(p);wireMedia(fig.parentElement);sync();picker.value='';document.getElementById('save-state').textContent=item.waiting_save?'Видео загружено — нажмите «Сохранить»':'Медиа добавлено';if(!item.waiting_save)autosave()}}}});</script><main><a href="{return_url}">{return_label}</a><form id="article-form" data-id="{m["id"]}" data-return-url="{return_url}" method="post" action="{self.url('/learning/material/action')}" enctype="multipart/form-data">{return_fields}<input type="hidden" name="action" value="material_save"><input type="hidden" name="editor" value="1"><input type="hidden" name="id" value="{m["id"]}"><div class="topbar"><h1>{title}</h1><div class="top-actions"><span id="save-state" class="save-state"></span><button>Сохранить</button>{existing_controls}</div></div>{saved}
        <section class="card"><h2>Материал</h2><p class="hint">Название и короткий анонс для карточки в приложении.</p><label class="field">Название<input class="title-input" name="title" value="{esc(m["title"])}" placeholder="Введите название" required autofocus></label><label class="field">Краткое описание<textarea name="short_description" placeholder="О чём этот материал — 1–3 предложения">{esc(m["short_description"] or "")}</textarea></label><label style="display:flex;align-items:flex-start;gap:10px;margin-top:18px;padding:14px;border:1px solid var(--line);border-radius:12px;cursor:pointer"><input type="checkbox" name="is_free" value="1" {"checked" if m["is_free"] else ""} style="width:18px;height:18px;margin:2px 0 0;flex:none"><span><b>Доступен бесплатно</b><br><span class="hint">Материал смогут открыть пользователи без оплаченной подписки.</span></span></label></section>
        <section class="card"><h2>Статья</h2><p class="hint">Можно вставить готовый пост — абзацы, списки, ссылки и форматирование сохранятся.</p><div class="toolbar"><button type="button" data-cmd="undo" title="Отменить">↶</button><button type="button" data-cmd="redo" title="Повторить">↷</button><button type="button" data-cmd="bold"><b>Ж</b></button><button type="button" data-cmd="italic"><i>К</i></button><button type="button" data-cmd="formatBlock" data-value="h2">Заголовок</button><button type="button" data-cmd="formatBlock" data-value="blockquote">Цитата</button><button type="button" data-cmd="insertUnorderedList">• Список</button><button type="button" data-cmd="insertOrderedList">1. Список</button><button type="button" id="add-divider">Разделитель</button><button type="button" id="add-link">Ссылка</button><button type="button" class="media-button" id="insert-media">＋ Фото/видео</button><input id="inline-media-file" type="file" accept=".jpg,.jpeg,.png,.webp,.gif,.mp4" hidden><button type="button" data-cmd="removeFormat">Очистить</button></div><div id="content-editor" class="editor" contenteditable="true" data-placeholder="Вставьте пост из Telegram или начните писать…">{clean_rich_text(m["full_description"] or "")}</div><textarea id="content-source" name="full_description" hidden></textarea></section>
        <section class="card"><div class="section-head"><div><h2>Теги</h2><p class="hint">Нажмите на тег, чтобы выбрать. Карандаш появляется при наведении.</p></div><button type="button" class="add-tag" onclick="document.getElementById('new-tag').showModal()">＋ Новый тег</button></div><div class="tag-list">{tag_chips or '<span class="empty-note">Тегов пока нет.</span>'}</div></section>
        <section class="card"><h2>Обложка</h2><p class="hint">Необязательно. Если её нет, карточка возьмёт первое изображение статьи, а затем — видео.</p><input id="remove-cover" type="hidden" name="remove_cover" value="0"><div class="cover">{cover_preview}<label class="drop"><b id="cover-label">＋ Загрузить обложку</b><br><span class="hint">JPG, PNG или WEBP · 16:9</span><input id="cover-input" type="file" name="cover_file" accept=".jpg,.jpeg,.png,.webp"></label></div></section></form>
        <section class="card"><div class="section-head"><div><h2>Дополнительные материалы</h2><p class="hint">PDF, документ, презентация, таблица, изображение или видео.</p></div></div>{file_cards}<form class="new-asset upload-form" method="post" action="{self.url('/learning/material/action')}" enctype="multipart/form-data">{return_fields}<input type="hidden" name="action" value="file_add"><input type="hidden" name="material_id" value="{m["id"]}"><input name="file_title" placeholder="Заголовок материала"><textarea name="file_description" placeholder="Кратко опишите, что внутри"></textarea><label class="drop"><b id="attachment-label">＋ Выбрать файл</b><input id="attachment-input" type="file" name="material_file" required></label><button {"" if material else "disabled"}>Добавить материал</button>{'' if material else '<span class="hint"> Сначала сохраните основной материал.</span>'}</form></section>
        {tag_dialogs}<dialog id="new-tag"><form class="tag-modal-form" method="post" action="{self.url('/learning/material/action')}"><input type="hidden" name="action" value="tag_create"><input type="hidden" name="ajax" value="1"><input type="hidden" name="return_material" value="{m["id"]}"><h2>Новый тег</h2><label class="field">Название<input name="tag_name" placeholder="Например: Методика" required></label><label class="field">Цвет<input type="color" name="tag_color" value="#D97757"></label><div class="actions"><button>Добавить</button><button type="button" class="secondary" onclick="this.closest('dialog').close()">Отмена</button></div></form></dialog>
        <script>const form=document.getElementById('article-form'),editor=document.getElementById('content-editor'),source=document.getElementById('content-source'),state=document.getElementById('save-state'),tagList=document.querySelector('.tag-list'),actionUrl=form.getAttribute('action');function sync(){{const clean=editor.cloneNode(true);clean.querySelectorAll('.media-remove').forEach(button=>button.remove());source.value=clean.innerHTML}}document.querySelectorAll('[data-cmd]').forEach(b=>b.onclick=()=>{{editor.focus();document.execCommand(b.dataset.cmd,false,b.dataset.value||null);sync()}});document.getElementById('add-link').onclick=()=>{{const url=prompt('Вставьте ссылку');if(url)document.execCommand('createLink',false,url);sync()}};sync();form.addEventListener('submit',sync);let timer;function autosave(){{if(!form.dataset.id)return;sync();state.textContent='Сохраняем…';const data=new FormData(form);data.delete('cover_file');data.append('autosave','1');fetch(actionUrl,{{method:'POST',body:data}}).then(r=>r.ok?r.json():Promise.reject()).then(()=>state.textContent='Сохранено').catch(()=>state.textContent='Не удалось сохранить')}}editor.addEventListener('input',()=>{{clearTimeout(timer);timer=setTimeout(autosave,1000)}});document.querySelectorAll('.tag-modal-form').forEach(tf=>tf.addEventListener('submit',async e=>{{e.preventDefault();const r=await fetch(tf.getAttribute('action'),{{method:'POST',body:new FormData(tf)}});if(!r.ok)return alert('Не удалось сохранить тег');const t=await r.json();let wrap=document.getElementById('tag-'+t.id)?.closest('.tag-wrap');if(wrap){{wrap.style.setProperty('--tag',t.color);wrap.querySelector('label').textContent=t.name}}else{{document.querySelector('.empty-note')?.remove();wrap=document.createElement('span');wrap.className='tag-wrap';wrap.style.setProperty('--tag',t.color);const input=document.createElement('input');input.type='checkbox';input.name='tag_ids';input.value=t.id;input.id='tag-'+t.id;input.checked=true;const label=document.createElement('label');label.htmlFor=input.id;label.textContent=t.name;wrap.append(input,label);tagList.append(wrap)}}tf.closest('dialog').close()}}));document.querySelectorAll('.tag-delete').forEach(btn=>btn.onclick=async()=>{{if(!confirm('Удалить этот тег? Он исчезнет у всех материалов.'))return;const data=new FormData();data.append('action','tag_delete');data.append('ajax','1');data.append('id',btn.dataset.id);const r=await fetch(actionUrl,{{method:'POST',body:data}});if(!r.ok)return alert('Не удалось удалить тег');document.getElementById('tag-'+btn.dataset.id)?.closest('.tag-wrap')?.remove();btn.closest('dialog').close()}});const deleteMaterial=document.getElementById('delete-material');if(deleteMaterial)deleteMaterial.onclick=async()=>{{if(!confirm('Удалить материал без возможности восстановления?'))return;const data=new FormData();data.append('action','material_delete');data.append('ajax','1');data.append('id',deleteMaterial.dataset.id);const r=await fetch(actionUrl,{{method:'POST',body:data}});if(r.ok)location.href='{self.url('/learning')}';else alert('Не удалось удалить материал')}};let savedRange=null,draggedMedia=null;function rememberRange(){{const s=getSelection();if(s.rangeCount&&editor.contains(s.anchorNode))savedRange=s.getRangeAt(0).cloneRange()}}editor.addEventListener('mouseup',rememberRange);editor.addEventListener('keyup',rememberRange);const mediaPicker=document.getElementById('inline-media-file');document.getElementById('insert-media').onclick=()=>{{rememberRange();mediaPicker.click()}};function wireMedia(root=editor){{root.querySelectorAll('figure.inline-media').forEach(fig=>{{fig.draggable=true;fig.ondragstart=()=>draggedMedia=fig}})}}editor.ondragover=e=>e.preventDefault();editor.ondrop=e=>{{if(!draggedMedia)return;e.preventDefault();const range=document.caretRangeFromPoint?.(e.clientX,e.clientY);if(range)range.insertNode(draggedMedia);else editor.appendChild(draggedMedia);draggedMedia=null;sync();autosave()}};wireMedia();mediaPicker.onchange=async()=>{{const file=mediaPicker.files[0];if(!file)return;state.textContent='Загружаем медиа…';const data=new FormData();data.append('action','inline_upload');data.append('inline_file',file);const r=await fetch(actionUrl,{{method:'POST',body:data}});if(!r.ok){{state.textContent='Не удалось загрузить';return}}const item=await r.json(),fig=document.createElement('figure'),media=document.createElement(item.kind==='video'?'video':'img');fig.className='inline-media';fig.draggable=true;media.src=item.url;if(item.kind==='video')media.controls=true;fig.append(media);if(savedRange){{savedRange.deleteContents();savedRange.insertNode(fig)}}else editor.appendChild(fig);const p=document.createElement('p');p.innerHTML='<br>';fig.after(p);wireMedia(fig.parentElement);sync();mediaPicker.value='';state.textContent='Медиа добавлено';autosave()}};</script></main></body></html>''', content_type="text/html")

    async def editor(self, request: web.Request) -> web.Response:
        raw_id = str(request.query.get("material") or "")
        db = await self.connect()
        try:
            material = None
            if raw_id != "new":
                if not raw_id.isdigit():
                    raise web.HTTPNotFound(text="Материал не найден")
                cur = await db.execute("SELECT * FROM mini_app_materials WHERE id=?", (int(raw_id),))
                material = await cur.fetchone()
                if not material:
                    raise web.HTTPNotFound(text="Материал не найден")
            categories = await self.rows(db, "SELECT * FROM mini_app_categories ORDER BY sort_order, name")
            tags = await self.rows(db, "SELECT * FROM mini_app_tags ORDER BY name")
            files = await self.rows(db, "SELECT * FROM mini_app_material_files WHERE material_id=? ORDER BY sort_order, id", (material["id"],)) if material else []
            blocks = await self.rows(db, "SELECT * FROM mini_app_material_blocks WHERE material_id=? ORDER BY sort_order, id", (material["id"],)) if material else []
            material_tags = await self.rows(db, "SELECT tag_id FROM mini_app_material_tags WHERE material_id=?", (material["id"],)) if material else []
        finally:
            await db.close()
        m = material or {"id": "", "title": "", "short_description": "", "full_description": "", "cover_url": "", "category_id": None, "format": "", "status": "draft"}
        selected_tag_ids = [row["tag_id"] for row in material_tags]
        tag_chips = " ".join(f'<span class="tag">{esc(t["name"])}</span>' for t in tags if t["id"] in selected_tag_ids)
        if material and request.query.get("preview"):
            return self.preview(material, blocks, files, tags, selected_tag_ids)
        block_types = {"text": "Текст", "video": "Видео", "link": "Ссылка", "image": "Изображение"}
        block_html = "".join(
            f'''<article class="block"><div class="block-head"><b>{esc(block_types.get(b["block_type"], b["block_type"]))}</b>
            <form method="post" action="{self.url("/learning/material/action")}"><input type="hidden" name="action" value="block_delete">
            <input type="hidden" name="material_id" value="{m["id"]}"><input type="hidden" name="id" value="{b["id"]}">
            <button class="danger">Удалить</button></form></div><form method="post" action="{self.url("/learning/material/action")}">
            <input type="hidden" name="action" value="block_save"><input type="hidden" name="material_id" value="{m["id"]}">
            <input type="hidden" name="id" value="{b["id"]}"><input type="hidden" name="block_type" value="{esc(b["block_type"])}">
            <input name="block_title" value="{esc(b["title"] or "")}" placeholder="Заголовок блока">
            <textarea name="block_content" placeholder="Содержимое блока">{esc(b["content"] or "")}</textarea>
            <button class="secondary">Сохранить блок</button></form></article>'''
            for b in blocks
        ) or '<div class="empty">Добавьте первый блок содержания.</div>'
        files_html = "".join(
            f'''<div class="file"><span>📎 {esc(f["file_name"])}</span><form method="post" action="{self.url("/learning/material/action")}">
            <input type="hidden" name="action" value="file_delete"><input type="hidden" name="material_id" value="{m["id"]}">
            <input type="hidden" name="id" value="{f["id"]}"><button class="danger">Удалить</button></form></div>'''
            for f in files
        ) or '<p class="hint">Файлы ещё не добавлены.</p>'
        title = "Новый материал" if not material else esc(material["title"])
        danger_html = ""
        if material:
            danger_html = f'''<section class="panel"><h2>Опасная зона</h2><form method="post" action="{self.url("/learning/material/action")}" onsubmit="return confirm('Удалить этот материал?')"><input type="hidden" name="action" value="material_delete"><input type="hidden" name="id" value="{m["id"]}"><button class="danger">Удалить материал</button></form></section>'''
        return web.Response(
            text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
            <title>{title} — Nastaunik</title><style>
            :root{{--bg:#f6f2ed;--paper:#fff;--ink:#302621;--muted:#89776d;--line:#e5d9cf;--accent:#b9654e;--soft:#f0e8e1}}
            *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}
            main{{max-width:1040px;margin:auto;padding:24px 20px 70px}}a{{color:inherit}}h1{{font:700 34px Georgia,serif;margin:10px 0 24px}}
            h2{{font-size:20px}}.layout{{display:grid;grid-template-columns:minmax(0,1fr) 280px;gap:18px}}.panel{{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:20px;margin-bottom:16px}}
            label{{display:block;color:var(--muted);font-size:13px;margin:12px 0}}input,textarea,select{{width:100%;border:1px solid var(--line);border-radius:10px;padding:11px;background:#fff;font:inherit;margin-top:5px}}
            textarea{{min-height:115px;resize:vertical}}button,.button{{border:0;border-radius:10px;padding:10px 14px;background:var(--accent);color:#fff;font-weight:700;cursor:pointer;text-decoration:none;display:inline-block}}
            .secondary{{background:var(--soft);color:var(--ink)}}.danger{{background:transparent;color:#a34d43;padding:3px 0}}.actions{{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}}
            .hint{{color:var(--muted);font-size:13px}}.block,.file{{border:1px solid var(--line);border-radius:12px;padding:14px;margin:10px 0;background:#fffdfa}}
            .block-head,.file{{display:flex;justify-content:space-between;align-items:center;gap:10px}}.empty{{border:1px dashed var(--line);padding:22px;text-align:center;color:var(--muted);border-radius:12px}}
            @media(max-width:760px){{.layout{{grid-template-columns:1fr}}}}</style></head><body><main><p><a href="{self.url('/learning')}">← Материалы</a></p>
            <h1>{title}</h1>{f'<img src="{esc(m["cover_url"])}" alt="" style="display:block;width:100%;max-height:240px;object-fit:cover;border-radius:16px;margin-bottom:18px">' if m["cover_url"] else ''}{'<div class="panel" style="background:#dcefe0;color:#28653f">Сохранено</div>' if request.query.get("saved") else ''}
            <div class="layout"><div><form id="material-form" data-id="{m["id"]}" class="panel" method="post" action="{self.url("/learning/material/action")}" enctype="multipart/form-data">
            <input type="hidden" name="action" value="material_save"><input type="hidden" name="editor" value="1"><input type="hidden" name="id" value="{m["id"]}">
            <h2>Основная информация</h2><label>Название<input name="title" value="{esc(m["title"])}" required autofocus></label>
            <label>Краткое описание<textarea name="short_description">{esc(m["short_description"] or "")}</textarea></label>
            <label>Содержание<div class="toolbar"><button type="button" class="secondary" data-cmd="bold"><b>Ж</b></button><button type="button" class="secondary" data-cmd="italic"><i>К</i></button><button type="button" class="secondary" data-cmd="insertUnorderedList">• Список</button><button type="button" class="secondary" data-cmd="insertOrderedList">1. Список</button><button type="button" class="secondary" data-cmd="formatBlock" data-value="h2">Заголовок</button></div><div id="content-editor" class="rich-editor" contenteditable="true">{clean_rich_text(m["full_description"] or "")}</div><textarea name="full_description" id="content-source" hidden></textarea><span id="save-state" class="hint">Пишите как в редакторе статьи. Форматирование сохраняется автоматически.</span></label>
            <label>Теги<select name="tag_ids" multiple size="4">{self.tag_options(tags, selected_tag_ids)}</select><span class="hint">Можно выбрать несколько тегов.</span></label>
            <details><summary>+ Создать новый тег</summary><form method="post" action="{self.url("/learning/material/action")}" style="margin-top:10px"><input type="hidden" name="action" value="tag_create"><input type="hidden" name="return_material" value="{m["id"]}"><input name="tag_name" placeholder="Например: Методика" required><button>Создать тег</button></form></details><div class="tags">{tag_chips}</div>
            <input type="hidden" name="category_id" value="">
            <label>Тип материала<input name="format" value="{esc(m["format"] or "")}" placeholder="Статья, видео, презентация"></label>
            <label>Обложка<input type="file" name="cover_file" accept=".jpg,.jpeg,.png,.webp"></label>
            <label>Добавить файл<input type="file" name="material_file" accept=".pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.txt,.md,.jpg,.jpeg,.png,.webp,.mp3,.mp4"></label>
            <div class="actions"><button>Сохранить материал</button>{f'<a class="button secondary" href="{self.material_url(m["id"], preview=1)}" target="_blank">Предпросмотр</a>' if material else ''}<a class="button secondary" href="{self.url("/learning")}">Отмена</a></div></form>
            <section class="panel"><h2>Содержание</h2><p class="hint">Добавляйте блоки в нужном порядке. Задание можно добавить позже.</p>{block_html}
            <form method="post" action="{self.url("/learning/material/action")}" class="panel" style="background:var(--soft)">
            <input type="hidden" name="action" value="block_save"><input type="hidden" name="material_id" value="{m["id"]}">
            <label>Новый блок<select name="block_type"><option value="text">Текст</option><option value="video">Видео</option><option value="link">Ссылка</option><option value="image">Изображение</option></select></label>
            <label>Заголовок<input name="block_title" placeholder="Например: Основная идея"></label>
            <label>Содержимое<textarea name="block_content" placeholder="Текст, ссылка или описание"></textarea></label>
            <button {"disabled" if not material else ""}>+ Добавить блок</button>{'<p class="hint">Сначала сохраните материал.</p>' if not material else ''}</form></section></div>
            <aside><section class="panel"><h2>Публикация</h2><label>Статус<select name="status" form="material-form">
            <option value="draft" {"selected" if m["status"]=="draft" else ""}>Черновик</option><option value="published" {"selected" if m["status"]=="published" else ""}>Опубликован</option>
            <option value="hidden" {"selected" if m["status"]=="hidden" else ""}>Скрыт</option></select></label><p class="hint">Сначала сохраняйте как черновик, а публикуйте готовый материал.</p></section>
            <section class="panel"><h2>Файлы</h2>{files_html}</section>{danger_html}</aside></div></main><script>
            const form=document.getElementById('material-form'),editor=document.getElementById('content-editor'),source=document.getElementById('content-source'),saveState=document.getElementById('save-state');function sync(){{source.value=editor.innerHTML}}document.querySelectorAll('[data-cmd]').forEach(b=>b.onclick=()=>{{editor.focus();document.execCommand(b.dataset.cmd,false,b.dataset.value||null);sync()}});sync();let timer;function autosave(){{if(!form.dataset.id)return;sync();saveState.textContent='Сохраняем…';const data=new FormData(form);data.delete('material_file');data.delete('cover_file');data.append('autosave','1');fetch(form.action,{{method:'POST',body:data}}).then(r=>r.ok?r.json():Promise.reject()).then(()=>saveState.textContent='Сохранено').catch(()=>saveState.textContent='Ошибка сохранения')}}editor.addEventListener('input',()=>{{clearTimeout(timer);timer=setTimeout(autosave,900)}});form.addEventListener('change',()=>{{clearTimeout(timer);timer=setTimeout(autosave,900)}});</script></body></html>''',
            content_type="text/html",
        )

    def preview(self, material, blocks, files, tags, selected_tag_ids):
        block_types = {"text": "Текст", "video": "Видео", "link": "Ссылка", "image": "Изображение"}
        blocks_html = "".join(
            f'<article class="preview-block"><small>{esc(block_types.get(b["block_type"], b["block_type"]))}</small>'
            f'{("<h2>" + esc(b["title"]) + "</h2>") if b["title"] else ""}{clean_rich_text(b["content"] or "")}'
            for b in blocks
        )
        file_html = "".join(f'<li>{esc(f["file_name"])}</li>' for f in files)
        tag_html = " ".join(f'<span class="tag">{esc(t["name"])}</span>' for t in tags if t["id"] in selected_tag_ids)
        return web.Response(text=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Предпросмотр — {esc(material["title"])}</title><style>*{{box-sizing:border-box}}html,body{{max-width:100%;overflow-x:hidden}}body{{margin:0;background:#f6f2ed;color:#302621;font:16px/1.65 system-ui,sans-serif}}main{{width:100%;max-width:760px;margin:auto;background:#fff;padding:34px 24px;min-height:100vh;overflow:hidden}}main section,.preview-block{{min-width:0;max-width:100%}}h1{{font:700 38px Georgia,serif;line-height:1.15}}.muted,small{{color:#89776d}}.tag{{display:inline-block;background:#f0e8e1;border-radius:999px;padding:3px 10px;margin:2px;font-size:12px}}.preview-block{{border-top:1px solid #e5d9cf;padding:18px 0}}figure{{display:block;width:100%;max-width:100%;margin:18px 0;padding:0;overflow:hidden}}img,video,picture,iframe,svg,canvas{{display:block!important;width:100%!important;max-width:100%!important;height:auto!important;max-height:75vh;object-fit:contain;margin:14px auto;box-sizing:border-box}}figcaption{{color:#89776d;font-size:13px;text-align:center;padding-top:6px}}</style><main><p class="muted">Предпросмотр материала</p><h1>{esc(material["title"])}</h1><p class="muted">{esc(material["short_description"] or "")}</p><div>{tag_html}</div><section>{clean_rich_text(material["full_description"] or "")}</section>{blocks_html}{("<h3>Файлы</h3><ul>" + file_html + "</ul>") if file_html else ""}</main></html>''', content_type="text/html")

    async def optimize_video(self, target: Path) -> tuple[bool, int, str | None]:
        """Create a smaller, streamable H.264 copy and replace the upload atomically."""
        ffmpeg = shutil.which("ffmpeg")
        if not target.is_file():
            return False, 0, "Исходный файл не найден"
        original_size = target.stat().st_size
        if not ffmpeg:
            return False, original_size, "FFmpeg не установлен"
        if target.suffix.lower() != ".mp4":
            return True, original_size, None
        optimized = target.with_name(f"{target.stem}.optimized.mp4")
        command = (
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y", "-i", str(target),
            "-vf", "scale=w='min(1280,iw)':h='min(1280,ih)':force_original_aspect_ratio=decrease",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-maxrate", "900k", "-bufsize", "1800k",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "96k", "-ac", "2",
            "-threads", "1", str(optimized),
        )
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=900)
            if process.returncode == 0 and optimized.is_file() and optimized.stat().st_size < target.stat().st_size:
                optimized.replace(target)
                return True, target.stat().st_size, None
            else:
                optimized.unlink(missing_ok=True)
                if process.returncode:
                    error = stderr.decode(errors="replace")[-1000:] or "FFmpeg завершился с ошибкой"
                    logger.warning("Video optimization failed for %s: %s", target.name, error)
                    return False, original_size, error
                return True, original_size, None
        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            optimized.unlink(missing_ok=True)
            raise
        except (OSError, asyncio.TimeoutError):
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            optimized.unlink(missing_ok=True)
            logger.exception("Video optimization failed for %s", target.name)
            return False, original_size, "Не удалось обработать видео"

    async def create_video_poster(self, target: Path) -> str | None:
        """Create a lightweight static frame so catalog cards never load the video."""
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg or not target.is_file() or target.suffix.lower() != ".mp4":
            return None
        poster = target.with_name(f"{target.stem}.poster.webp")
        temporary = poster.with_name(f"{poster.stem}.temporary.webp")
        command = (
            ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
            "-ss", "0.3", "-i", str(target), "-frames:v", "1",
            "-vf", "scale=w='min(640,iw)':h=-2", "-c:v", "libwebp", "-quality", "76",
            str(temporary),
        )
        process = None
        try:
            process = await asyncio.create_subprocess_exec(
                *command, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE
            )
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=90)
            if process.returncode == 0 and temporary.is_file() and temporary.stat().st_size:
                temporary.replace(poster)
                return poster.name
            temporary.unlink(missing_ok=True)
            logger.warning("Video poster failed for %s: %s", target.name, stderr.decode(errors="replace")[-500:])
        except asyncio.CancelledError:
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            temporary.unlink(missing_ok=True)
            raise
        except (OSError, asyncio.TimeoutError):
            if process and process.returncode is None:
                process.kill()
                await process.wait()
            temporary.unlink(missing_ok=True)
            logger.exception("Video poster failed for %s", target.name)
        return None

    async def enqueue_video(self, db, target: Path, status: str = "queued") -> None:
        if target.suffix.lower() != ".mp4":
            return
        now = datetime.utcnow().isoformat(timespec="seconds")
        await db.execute(
            """INSERT INTO mini_app_video_jobs(stored_name,status,original_size,created_at,updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(stored_name) DO UPDATE SET
                   status=excluded.status, original_size=excluded.original_size,
                   optimized_size=NULL, poster_name=NULL, error=NULL, started_at=NULL, completed_at=NULL,
                   updated_at=excluded.updated_at""",
            (target.name, status, target.stat().st_size, now, now),
        )

    @staticmethod
    def media_names(value: object) -> set[str]:
        return {
            Path(url.split("?", 1)[0]).name
            for url in re.findall(r"/mini-app/media/[A-Za-z0-9_.~?=&-]+", str(value or ""))
        }

    async def activate_saved_videos(self, db, content: object) -> None:
        names = sorted(name for name in self.media_names(content) if name.lower().endswith(".mp4"))
        if not names:
            return
        placeholders = ",".join("?" for _ in names)
        now = datetime.utcnow().isoformat(timespec="seconds")
        await db.execute(
            f"UPDATE mini_app_video_jobs SET status='queued',updated_at=? WHERE status='waiting_save' AND stored_name IN ({placeholders})",
            (now, *names),
        )

    async def material_video_jobs(self, db, material_id: int) -> list[dict]:
        if not material_id:
            return []
        cur = await db.execute("SELECT full_description FROM mini_app_materials WHERE id=?", (material_id,))
        material = await cur.fetchone()
        names = self.media_names(material["full_description"] if material else "")
        cur = await db.execute("SELECT stored_name FROM mini_app_material_files WHERE material_id=?", (material_id,))
        names.update(row["stored_name"] for row in await cur.fetchall())
        cur = await db.execute("SELECT content FROM mini_app_material_blocks WHERE material_id=?", (material_id,))
        for row in await cur.fetchall():
            names.update(self.media_names(row["content"]))
        names = {Path(name).name for name in names if str(name).lower().endswith(".mp4")}
        if not names:
            return []
        placeholders = ",".join("?" for _ in names)
        rows = await self.rows(
            db,
            f"SELECT stored_name,status,original_size,optimized_size,poster_name,error,created_at,started_at,completed_at FROM mini_app_video_jobs WHERE stored_name IN ({placeholders}) ORDER BY id DESC",
            tuple(sorted(names)),
        )
        return [dict(row) for row in rows]

    async def claim_video_job(self) -> dict | None:
        db = await self.connect()
        try:
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute("SELECT id,stored_name FROM mini_app_video_jobs WHERE status='queued' ORDER BY id LIMIT 1")
            row = await cur.fetchone()
            if not row:
                await db.commit()
                return None
            now = datetime.utcnow().isoformat(timespec="seconds")
            await db.execute(
                "UPDATE mini_app_video_jobs SET status='processing',attempts=attempts+1,started_at=?,updated_at=? WHERE id=? AND status='queued'",
                (now, now, row["id"]),
            )
            await db.commit()
            return dict(row)
        finally:
            await db.close()

    async def finish_video_job(self, job_id: int, ok: bool, size: int, error: str | None, poster_name: str | None = None) -> None:
        db = await self.connect()
        try:
            now = datetime.utcnow().isoformat(timespec="seconds")
            await db.execute(
                "UPDATE mini_app_video_jobs SET status=?,optimized_size=?,poster_name=?,error=?,completed_at=?,updated_at=? WHERE id=?",
                ("ready" if ok else "failed", size or None, poster_name, (error or "")[-1000:] or None, now, now, job_id),
            )
            if ok:
                await db.execute(
                    "UPDATE mini_app_material_files SET file_size=? WHERE stored_name=(SELECT stored_name FROM mini_app_video_jobs WHERE id=?)",
                    (size, job_id),
                )
            await db.commit()
        finally:
            await db.close()

    async def video_worker(self) -> None:
        while True:
            job = await self.claim_video_job()
            if not job:
                await asyncio.sleep(1.5)
                continue
            target = self.media_dir / Path(job["stored_name"]).name
            try:
                ok, size, error = await self.optimize_video(target)
                poster_name = await self.create_video_poster(target)
                await self.finish_video_job(job["id"], ok, size, error, poster_name)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Background video processing failed for %s", target.name)
                await self.finish_video_job(job["id"], False, target.stat().st_size if target.is_file() else 0, str(exc))

    async def cleanup_orphan_uploads(self, *, minimum_age_hours: int = 24) -> int:
        """Remove abandoned content uploads while preserving every saved reference and active job."""
        cutoff = datetime.utcnow() - timedelta(hours=minimum_age_hours)
        removed = 0
        db = await self.connect()
        try:
            referenced: set[str] = set()
            for sql in (
                "SELECT cover_url AS value FROM mini_app_materials WHERE cover_url IS NOT NULL",
                "SELECT full_description AS value FROM mini_app_materials WHERE full_description IS NOT NULL",
                "SELECT content AS value FROM mini_app_material_blocks WHERE content IS NOT NULL",
            ):
                for row in await self.rows(db, sql):
                    referenced.update(self.media_names(row["value"]))
            for row in await self.rows(db, "SELECT stored_name FROM mini_app_material_files"):
                referenced.add(Path(row["stored_name"]).name)
            for row in await self.rows(db, "SELECT stored_name,poster_name FROM mini_app_video_jobs WHERE poster_name IS NOT NULL"):
                if Path(row["stored_name"]).name in referenced:
                    referenced.add(Path(row["poster_name"]).name)
            active = {
                Path(row["stored_name"]).name
                for row in await self.rows(db, "SELECT stored_name FROM mini_app_video_jobs WHERE status IN ('queued','processing')")
            }
            stale_waiting = await self.rows(
                db,
                "SELECT id,stored_name,poster_name FROM mini_app_video_jobs WHERE status='waiting_save' AND created_at<?",
                (cutoff.isoformat(timespec="seconds"),),
            )
            for row in stale_waiting:
                name = Path(row["stored_name"]).name
                if name in referenced:
                    continue
                candidates = {name, f"{Path(name).stem}.optimized.mp4", f"{Path(name).stem}.poster.webp"}
                if row["poster_name"]:
                    candidates.add(Path(row["poster_name"]).name)
                for candidate in candidates:
                    target = self.media_dir / candidate
                    if target.is_file():
                        target.unlink()
                        removed += 1
                await db.execute("DELETE FROM mini_app_video_jobs WHERE id=?", (row["id"],))
            if self.media_dir.is_dir():
                for target in self.media_dir.glob("content-*"):
                    if not target.is_file() or target.name in referenced or target.name in active:
                        continue
                    modified = datetime.utcfromtimestamp(target.stat().st_mtime)
                    if modified < cutoff:
                        target.unlink()
                        removed += 1
            await db.commit()
        finally:
            await db.close()
        if removed:
            logger.info("Removed %s abandoned Mini App uploads", removed)
        return removed

    async def backfill_video_posters(self) -> int:
        """Create missing posters for videos that were uploaded before poster support."""
        db = await self.connect()
        try:
            names: set[str] = set()
            for sql in (
                "SELECT full_description AS value FROM mini_app_materials WHERE full_description IS NOT NULL",
                "SELECT content AS value FROM mini_app_material_blocks WHERE content IS NOT NULL",
            ):
                for row in await self.rows(db, sql):
                    names.update(self.media_names(row["value"]))
            for row in await self.rows(db, "SELECT stored_name FROM mini_app_material_files"):
                names.add(Path(row["stored_name"]).name)
            names = {name for name in names if name.lower().endswith(".mp4")}
            jobs = {
                row["stored_name"]: dict(row)
                for row in await self.rows(db, "SELECT id,stored_name,status,poster_name FROM mini_app_video_jobs")
            }
            created = 0
            for name in sorted(names):
                job = jobs.get(name)
                if job and job["status"] in {"queued", "processing", "waiting_save"}:
                    continue
                if job and job["poster_name"] and (self.media_dir / Path(job["poster_name"]).name).is_file():
                    continue
                target = self.media_dir / Path(name).name
                poster_name = await self.create_video_poster(target)
                if not poster_name:
                    continue
                now = datetime.utcnow().isoformat(timespec="seconds")
                await db.execute(
                    """INSERT INTO mini_app_video_jobs(
                           stored_name,status,original_size,optimized_size,poster_name,created_at,completed_at,updated_at
                       ) VALUES(?,'ready',?,?,?,?,?,?)
                       ON CONFLICT(stored_name) DO UPDATE SET poster_name=excluded.poster_name,updated_at=excluded.updated_at""",
                    (name, target.stat().st_size, target.stat().st_size, poster_name, now, now, now),
                )
                await db.commit()
                created += 1
            if created:
                logger.info("Created %s missing Mini App video posters", created)
            return created
        finally:
            await db.close()

    async def cleanup_worker(self) -> None:
        try:
            await self.backfill_video_posters()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Failed to backfill Mini App video posters")
        while True:
            await asyncio.sleep(3600)
            try:
                await self.cleanup_orphan_uploads()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Failed to clean abandoned Mini App uploads")

    async def video_worker_context(self, app):
        await self.schema.init()
        db = await self.connect()
        try:
            now = datetime.utcnow().isoformat(timespec="seconds")
            await db.execute("UPDATE mini_app_video_jobs SET status='queued',updated_at=? WHERE status='processing'", (now,))
            await db.commit()
        finally:
            await db.close()
        try:
            await self.cleanup_orphan_uploads()
        except Exception:
            logger.exception("Initial abandoned upload cleanup failed")
        task = asyncio.create_task(self.video_worker(), name="mini-app-video-worker")
        cleanup_task = asyncio.create_task(self.cleanup_worker(), name="mini-app-upload-cleanup")
        try:
            yield
        finally:
            task.cancel()
            cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            with suppress(asyncio.CancelledError):
                await cleanup_task

    async def save_material_file(self, db, material_id: int, upload, title: str = "", description: str = "") -> None:
        if not getattr(upload, "filename", None) or not getattr(upload, "file", None):
            return
        extension = Path(upload.filename).suffix.lower()
        allowed = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md", ".jpg", ".jpeg", ".png", ".webp", ".mp3", ".mp4"}
        if extension not in allowed:
            raise web.HTTPBadRequest(text="Этот тип файла не поддерживается")
        self.media_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{secrets.token_urlsafe(18)}{extension}"
        target = self.media_dir / stored_name
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        await self.enqueue_video(db, target)
        await db.execute(
            "INSERT INTO mini_app_material_files(material_id,file_name,stored_name,mime_type,file_size,title,description,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (material_id, Path(upload.filename).name[:250], stored_name, upload.content_type or mimetypes.guess_type(upload.filename)[0], target.stat().st_size, title.strip() or None, description.strip() or None, datetime.utcnow().isoformat(timespec="seconds")),
        )

    async def save_block_file(self, db, upload, *, wait_for_material_save: bool = False) -> str | None:
        if not getattr(upload, "filename", None) or not getattr(upload, "file", None):
            return None
        extension = Path(upload.filename).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".mp4"}:
            raise web.HTTPBadRequest(text="Для статьи можно загрузить изображение или MP4-видео")
        self.media_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"content-{secrets.token_urlsafe(18)}{extension}"
        target = self.media_dir / stored_name
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        await self.enqueue_video(db, target, "waiting_save" if wait_for_material_save else "queued")
        return f"/mini-app/media/{stored_name}"

    async def save_cover(self, db, material_id: int, upload) -> None:
        if not getattr(upload, "filename", None) or not getattr(upload, "file", None):
            return
        extension = Path(upload.filename).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise web.HTTPBadRequest(text="Обложка должна быть JPG, PNG или WEBP")
        self.media_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"cover-{secrets.token_urlsafe(18)}{extension}"
        target = self.media_dir / stored_name
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        cur = await db.execute("SELECT cover_url FROM mini_app_materials WHERE id=?", (material_id,))
        previous = await cur.fetchone()
        await db.execute("UPDATE mini_app_materials SET cover_url=?, updated_at=? WHERE id=?", (f"/mini-app/media/{stored_name}", datetime.utcnow().isoformat(timespec="seconds"), material_id))
        previous_url = str(previous["cover_url"] or "") if previous else ""
        if previous_url.startswith("/mini-app/media/"):
            previous_target = self.media_dir / Path(previous_url.split("?", 1)[0]).name
            if previous_target != target and previous_target.is_file():
                previous_target.unlink()

    async def remove_cover(self, db, material_id: int) -> None:
        cur = await db.execute("SELECT cover_url FROM mini_app_materials WHERE id=?", (material_id,))
        row = await cur.fetchone()
        await db.execute(
            "UPDATE mini_app_materials SET cover_url=NULL,updated_at=? WHERE id=?",
            (datetime.utcnow().isoformat(timespec="seconds"), material_id),
        )
        cover_url = str(row["cover_url"] or "") if row else ""
        if cover_url.startswith("/mini-app/media/"):
            target = self.media_dir / Path(cover_url.split("?", 1)[0]).name
            if target.is_file():
                target.unlink()

    async def action(self, request: web.Request) -> web.Response:
        await self.schema.init()
        form = await request.post()
        action = str(form.get("action") or "")
        if action.startswith("course_"):
            return await self.course_admin.action(request, form)
        now = datetime.utcnow().isoformat(timespec="seconds")
        return_course_id = int(form.get("return_course") or 0)
        return_lesson_id = int(form.get("return_lesson") or 0)
        return_block_id = int(form.get("return_block") or 0)
        is_course_material = form.get("course_material") == "1"
        db = await self.connect()
        editor_id = None
        tag_result = None
        inline_result = None
        video_status_result = None
        try:
            if action == "video_status":
                material_id = int(form.get("material_id") or 0)
                video_status_result = await self.material_video_jobs(db, material_id)
            elif action == "tag_create":
                name = str(form.get("tag_name") or "").strip()
                if not name:
                    raise web.HTTPBadRequest(text="Укажите название тега")
                slug = self.tag_slug(name)
                color = str(form.get("tag_color") or "#D97757")
                color = color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#D97757"
                await db.execute("INSERT OR IGNORE INTO mini_app_tags(name,slug,color,created_at,updated_at) VALUES(?,?,?,?,?)", (name, slug, color, now, now))
                cur = await db.execute("SELECT id,name,color FROM mini_app_tags WHERE name=?", (name,))
                tag_row = await cur.fetchone()
                tag_result = dict(tag_row) if tag_row else None
                editor_id = int(form.get("return_material") or 0) or None
                if editor_id and tag_row:
                    await db.execute("INSERT OR IGNORE INTO mini_app_material_tags(material_id,tag_id) VALUES(?,?)", (editor_id, tag_row["id"]))
            elif action == "tag_save":
                tag_id = int(form.get("id") or 0)
                name = str(form.get("tag_name") or "").strip()
                color = str(form.get("tag_color") or "#D97757")
                color = color if re.fullmatch(r"#[0-9a-fA-F]{6}", color) else "#D97757"
                if not tag_id or not name:
                    raise web.HTTPBadRequest(text="Укажите название тега")
                await db.execute("UPDATE mini_app_tags SET name=?,slug=?,color=?,updated_at=? WHERE id=?", (name, self.tag_slug(name), color, now, tag_id))
                tag_result = {"id": tag_id, "name": name, "color": color}
                editor_id = int(form.get("return_material") or 0) or None
            elif action == "tag_delete":
                tag_id = int(form.get("id") or 0)
                if not tag_id:
                    raise web.HTTPBadRequest(text="Тег не указан")
                await db.execute("DELETE FROM mini_app_tags WHERE id=?", (tag_id,))
                tag_result = {"ok": True, "id": tag_id}
            elif action == "inline_upload":
                url = await self.save_block_file(db, form.get("inline_file"), wait_for_material_save=True)
                if not url:
                    raise web.HTTPBadRequest(text="Файл не выбран")
                is_video = url.lower().endswith(".mp4")
                inline_result = {"ok": True, "url": url, "kind": "video" if is_video else "image", "waiting_save": is_video}
            elif action == "material_save":
                item_id = int(form.get("id") or 0)
                values = (str(form.get("title") or "").strip(), str(form.get("short_description") or "").strip() or None, str(form.get("full_description") or "").strip() or None, 1 if form.get("is_free") == "1" else 0, now)
                if not values[0]:
                    raise web.HTTPBadRequest(text="Название материала обязательно")
                if item_id:
                    await db.execute("UPDATE mini_app_materials SET title=?,short_description=?,full_description=?,is_free=?,format=NULL,status='published',updated_at=? WHERE id=?", (*values, item_id))
                else:
                    cur = await db.execute("INSERT INTO mini_app_materials(title,short_description,full_description,is_free,format,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,NULL,'published',0,?,?)", (*values, now))
                    item_id = int(cur.lastrowid)
                await db.execute("DELETE FROM mini_app_material_tags WHERE material_id=?", (item_id,))
                for tag_id in form.getall("tag_ids", []):
                    if str(tag_id).isdigit():
                        await db.execute("INSERT OR IGNORE INTO mini_app_material_tags(material_id,tag_id) VALUES(?,?)", (item_id, int(tag_id)))
                if form.get("remove_cover") == "1" and form.get("autosave") != "1":
                    await self.remove_cover(db, item_id)
                await self.save_cover(db, item_id, form.get("cover_file"))
                if form.get("autosave") != "1":
                    await self.activate_saved_videos(db, values[2])
                editor_id = item_id if form.get("editor") == "1" else None
            elif action == "file_add":
                editor_id = int(form.get("material_id") or 0)
                if not editor_id:
                    raise web.HTTPBadRequest(text="Сначала сохраните материал")
                await self.save_material_file(db, editor_id, form.get("material_file"), str(form.get("file_title") or ""), str(form.get("file_description") or ""))
            elif action == "file_update":
                editor_id = int(form.get("material_id") or 0)
                await db.execute("UPDATE mini_app_material_files SET title=?,description=? WHERE id=? AND material_id=?", (str(form.get("file_title") or "").strip() or None, str(form.get("file_description") or "").strip() or None, int(form.get("id") or 0), editor_id))
            elif action == "block_save":
                editor_id = int(form.get("material_id") or 0)
                if not editor_id:
                    raise web.HTTPBadRequest(text="Сначала сохраните материал")
                block_id = int(form.get("id") or 0)
                uploaded_url = await self.save_block_file(db, form.get("block_file"))
                values = (str(form.get("block_type") or "image"), str(form.get("block_title") or "").strip() or None, uploaded_url or str(form.get("block_content") or "").strip() or None, str(form.get("block_description") or "").strip() or None)
                if values[0] not in {"text", "video", "link", "image"}:
                    raise web.HTTPBadRequest(text="Неизвестный тип блока")
                if block_id:
                    await db.execute("UPDATE mini_app_material_blocks SET block_type=?,title=?,content=?,description=? WHERE id=? AND material_id=?", (*values, block_id, editor_id))
                else:
                    if not values[2]:
                        raise web.HTTPBadRequest(text="Добавьте файл или ссылку")
                    await db.execute("INSERT INTO mini_app_material_blocks(material_id,block_type,title,content,description,sort_order,created_at) VALUES(?,?,?,?,?,0,?)", (editor_id, *values, now))
            elif action == "block_delete":
                editor_id = int(form.get("material_id") or 0)
                await db.execute("DELETE FROM mini_app_material_blocks WHERE id=? AND material_id=?", (int(form["id"]), editor_id))
            elif action == "file_delete":
                editor_id = int(form.get("material_id") or 0)
                cur = await db.execute("SELECT stored_name FROM mini_app_material_files WHERE id=? AND material_id=?", (int(form["id"]), editor_id))
                row = await cur.fetchone()
                if row:
                    await db.execute("DELETE FROM mini_app_material_files WHERE id=?", (int(form["id"]),))
                    target = self.media_dir / Path(row["stored_name"]).name
                    if target.is_file():
                        target.unlink()
                    if target.suffix.lower() == ".mp4":
                        target.with_name(f"{target.stem}.poster.webp").unlink(missing_ok=True)
                        await db.execute("DELETE FROM mini_app_video_jobs WHERE stored_name=?", (target.name,))
            elif action == "material_delete":
                item_id = int(form.get("id") or 0)
                if not item_id:
                    raise web.HTTPBadRequest(text="Материал не указан")
                cur = await db.execute("SELECT cover_url,full_description FROM mini_app_materials WHERE id=?", (item_id,))
                material_row = await cur.fetchone()
                cur = await db.execute("SELECT stored_name FROM mini_app_material_files WHERE material_id=?", (item_id,))
                stored_names = [row["stored_name"] for row in await cur.fetchall()]
                cur = await db.execute("SELECT content FROM mini_app_material_blocks WHERE material_id=? AND content LIKE '/mini-app/media/%'", (item_id,))
                stored_names.extend(Path(row["content"]).name for row in await cur.fetchall())
                if material_row and str(material_row["cover_url"] or "").startswith("/mini-app/media/"):
                    stored_names.append(Path(material_row["cover_url"]).name)
                if material_row:
                    stored_names.extend(Path(url).name for url in re.findall(r'/mini-app/media/[A-Za-z0-9_.~-]+', str(material_row["full_description"] or "")))
                await db.execute("DELETE FROM mini_app_course_blocks WHERE material_id=?", (item_id,))
                await db.execute("DELETE FROM mini_app_materials WHERE id=?", (item_id,))
                for stored_name in stored_names:
                    target = self.media_dir / Path(stored_name).name
                    if target.is_file():
                        target.unlink()
                    if target.suffix.lower() == ".mp4":
                        target.with_name(f"{target.stem}.poster.webp").unlink(missing_ok=True)
            elif action == "material_duplicate":
                source_id = int(form.get("id") or 0)
                cur = await db.execute("SELECT * FROM mini_app_materials WHERE id=?", (source_id,))
                source = await cur.fetchone()
                if not source:
                    raise web.HTTPNotFound(text="Материал не найден")
                cur = await db.execute("INSERT INTO mini_app_materials(title,short_description,full_description,cover_url,telegram_url,category_id,format,status,sort_order,created_at,updated_at) SELECT title || ' — копия',short_description,full_description,cover_url,telegram_url,category_id,format,'draft',sort_order,?,? FROM mini_app_materials WHERE id=?", (now, now, source_id))
                editor_id = int(cur.lastrowid)
                await db.execute("INSERT INTO mini_app_material_tags(material_id,tag_id) SELECT ?,tag_id FROM mini_app_material_tags WHERE material_id=?", (editor_id, source_id))
                await db.execute("INSERT INTO mini_app_material_blocks(material_id,block_type,title,content,sort_order,created_at) SELECT ?,block_type,title,content,sort_order,? FROM mini_app_material_blocks WHERE material_id=?", (editor_id, now, source_id))
            else:
                raise web.HTTPBadRequest(text="Неизвестное действие")
            await db.commit()
        finally:
            await db.close()
        if action in {"tag_create", "tag_save", "tag_delete"} and form.get("ajax") == "1":
            return web.json_response(tag_result or {"ok": False}, status=200 if tag_result else 400)
        if action == "video_status":
            return web.json_response({"ok": True, "jobs": video_status_result or []})
        if action == "inline_upload":
            return web.json_response(inline_result or {"ok": False}, status=200 if inline_result else 400)
        if action == "material_delete" and form.get("ajax") == "1":
            return web.json_response({"ok": True})
        if action == "material_save" and form.get("autosave") == "1":
            return web.json_response({"ok": True, "material_id": item_id})
        if editor_id:
            if is_course_material:
                raise web.HTTPSeeOther(location=self.material_url(
                    editor_id,
                    saved=1,
                    course_material=1,
                    return_course=return_course_id,
                    return_lesson=return_lesson_id,
                    return_block=return_block_id,
                ))
            raise web.HTTPSeeOther(location=self.material_url(editor_id, saved=1))
        raise web.HTTPSeeOther(location=self.url("/learning", saved=1))
