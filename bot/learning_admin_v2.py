from __future__ import annotations

import html
import mimetypes
import re
import secrets
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

import aiosqlite
from aiohttp import web

from bot.database import Database


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def clean_rich_text(value: object) -> str:
    text = "" if value is None else str(value)
    allowed = r"(?i)(?:/?(?:div|p|br|strong|b|em|i|u|s|h2|h3|ul|ol|li|blockquote|a|img)(?:\s+[^>]*)?)"
    text = re.sub(r"<(?!"+allowed+r">)[^>]*>", "", text)
    text = re.sub(r'(<a\b(?![^>]*\brel=)[^>]*)>', r'\1 rel="noopener noreferrer">', text, flags=re.I)
    return text

class LearningAdmin:
    """Simple, content-first admin for the learning library."""

    def __init__(self, database_path: Path, url_builder):
        self.database_path = database_path
        self.url = url_builder
        self.schema = Database(database_path)

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
        if request.query.get("material") is not None:
            return await self.article_editor(request)
        return await self.index(request)

    async def index(self, request: web.Request) -> web.Response:
        db = await self.connect()
        try:
            categories = await self.rows(db, "SELECT * FROM mini_app_categories ORDER BY sort_order, name")
            tags = await self.rows(db, "SELECT * FROM mini_app_tags ORDER BY name")
            sql = """SELECT m.*, c.name category_name,
                     (SELECT COUNT(*) FROM mini_app_material_files f WHERE f.material_id=m.id) file_count,
                     (SELECT COUNT(*) FROM mini_app_material_blocks b WHERE b.material_id=m.id) block_count,
                     (SELECT group_concat(t.name, ', ') FROM mini_app_tags t JOIN mini_app_material_tags mt ON mt.tag_id=t.id WHERE mt.material_id=m.id) tag_names
                     FROM mini_app_materials m
                     LEFT JOIN mini_app_categories c ON c.id=m.category_id
                     WHERE 1=1"""
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
            f'''<article class="material"><div><div class="eyebrow">{esc(r["format"] or "Материал")}</div>
            <h2>{esc(r["title"])}</h2><p>{esc(r["short_description"] or "Описание ещё не добавлено")}</p>
            <small>{esc(r["tag_names"] or "Без тегов")} · {r["block_count"]} блоков · {r["file_count"]} файлов</small></div>
            <div class="actions"><a class="button" href="{self.material_url(r["id"])}">Открыть</a><form method="post" action="{self.url("/learning/material/action")}"><input type="hidden" name="action" value="material_duplicate"><input type="hidden" name="id" value="{r["id"]}"><button class="secondary">Дублировать</button></form></div></article>'''
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
            .secondary{{background:var(--soft);color:var(--ink)}}.toolbar{{display:flex;gap:10px;flex-wrap:wrap;margin:24px 0}}
            input,select{{border:1px solid var(--line);border-radius:10px;padding:11px;background:#fff;font:inherit}}
            input[name=q]{{min-width:280px;flex:1}}.material{{display:flex;justify-content:space-between;gap:20px;align-items:center;background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:20px;margin:12px 0}}
            .material p{{margin:0 0 8px}}small,.hint{{color:var(--muted)}}.eyebrow{{font-size:11px;color:var(--accent);font-weight:700;text-transform:uppercase}}
            .actions{{display:flex;gap:10px;align-items:center;flex-wrap:wrap;justify-content:flex-end}}.status{{padding:5px 9px;border-radius:8px;background:var(--soft);font-size:12px}}
            .status.published{{background:#dcefe0;color:#28653f}}.empty{{background:var(--paper);border:1px dashed var(--line);border-radius:16px;padding:45px;text-align:center;color:var(--muted)}}
            details{{background:var(--paper);border:1px solid var(--line);border-radius:12px;padding:14px;margin:14px 0}}summary{{cursor:pointer;font-weight:700}}
            @media(max-width:680px){{.top,.material{{align-items:stretch;flex-direction:column}}.actions{{justify-content:flex-start}}input[name=q]{{min-width:0;width:100%}}}}
            </style></head><body><main><p><a href="{self.url('/')}">← Админка</a></p>
            <div class="top"><div><h1>Материалы</h1><p>Создавайте уроки и добавляйте контент. Задания добавляются отдельно.</p></div>
            <a class="button" href="{self.material_url()}">+ Добавить материал</a></div>
            <form class="toolbar" method="get"><input name="q" value="{esc(query)}" placeholder="Найти материал">
            <select name="tag"><option value="">Все теги</option>{self.tag_options(tags, [tag] if tag else [])}</select><button class="secondary">Найти</button></form>
            {cards}</main></body></html>''',
            content_type="text/html",
        )

    async def article_editor(self, request: web.Request) -> web.Response:
        raw_id = str(request.query.get("material") or "new")
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
        finally:
            await db.close()

        m = material or {"id": "", "title": "", "short_description": "", "full_description": "", "cover_url": ""}
        selected_ids = {row["tag_id"] for row in selected_rows}
        tag_chips = "".join(
            f'''<span class="tag-wrap" style="--tag:{esc(tag["color"] or "#D97757")}"><input id="tag-{tag["id"]}" type="checkbox" name="tag_ids" value="{tag["id"]}" {"checked" if tag["id"] in selected_ids else ""}><label for="tag-{tag["id"]}">{esc(tag["name"])}</label><button type="button" class="tag-edit" title="Редактировать тег" onclick="document.getElementById('edit-tag-{tag["id"]}').showModal()">✎</button></span>'''
            for tag in tags
        )
        tag_dialogs = "".join(
            f'''<dialog id="edit-tag-{tag["id"]}"><form class="tag-modal-form" data-existing="{tag["id"]}" method="post" action="{self.url("/learning/material/action")}"><input type="hidden" name="action" value="tag_save"><input type="hidden" name="ajax" value="1"><input type="hidden" name="id" value="{tag["id"]}"><input type="hidden" name="return_material" value="{m["id"]}"><h2>Редактировать тег</h2><label>Название<input name="tag_name" value="{esc(tag["name"])}" required></label><label>Цвет<input type="color" name="tag_color" value="{esc(tag["color"] or "#D97757")}"></label><div class="actions"><button>Сохранить</button><button type="button" class="secondary" onclick="this.closest('dialog').close()">Отмена</button></div></form></dialog>'''
            for tag in tags
        )
        media_cards = "".join(
            f'''<form class="asset-card" method="post" action="{self.url("/learning/material/action")}"><input type="hidden" name="material_id" value="{m["id"]}"><input type="hidden" name="id" value="{block["id"]}"><input type="hidden" name="block_type" value="{esc(block["block_type"])}"><div class="asset-icon">{"▣" if block["block_type"] == "image" else "▶"}</div><div class="asset-fields"><input name="block_title" value="{esc(block["title"] or "")}" placeholder="Заголовок"><textarea name="block_description" placeholder="Краткое описание">{esc(block["description"] or "")}</textarea><input name="block_content" value="{esc(block["content"] or "")}" placeholder="Ссылка на изображение или видео"></div><div class="asset-actions"><button name="action" value="block_save" class="secondary">Сохранить</button><button name="action" value="block_delete" class="danger" onclick="return confirm('Удалить этот элемент?')">Удалить</button></div></form>'''
            for block in blocks if block["block_type"] in {"image", "video"}
        ) or '<p class="empty-note">Изображений и видео пока нет.</p>'
        file_cards = "".join(
            f'''<form class="asset-card" method="post" action="{self.url("/learning/material/action")}"><input type="hidden" name="material_id" value="{m["id"]}"><input type="hidden" name="id" value="{file["id"]}"><div class="asset-icon">↧</div><div class="asset-fields"><b>{esc(file["file_name"])}</b><input name="file_title" value="{esc(file["title"] or "")}" placeholder="Заголовок материала"><textarea name="file_description" placeholder="Кратко опишите, что внутри">{esc(file["description"] or "")}</textarea></div><div class="asset-actions"><button name="action" value="file_update" class="secondary">Сохранить</button><button name="action" value="file_delete" class="danger" onclick="return confirm('Удалить файл?')">Удалить</button></div></form>'''
            for file in files
        ) or '<p class="empty-note">Дополнительных материалов пока нет.</p>'
        title = "Новый материал" if not material else esc(material["title"])
        saved = '<div class="toast">Изменения сохранены</div>' if request.query.get("saved") else ""
        existing_controls = ""
        if material:
            existing_controls = f'''<a class="button secondary" href="{self.material_url(m["id"], preview=1)}" target="_blank">Предпросмотр</a>'''

        return web.Response(text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title} — Nastaunik</title><style>
        :root{{--bg:#f7f5f2;--paper:#fff;--ink:#292421;--muted:#817873;--line:#e7e0da;--accent:#c56349;--soft:#f3ece7}}
        *{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.55 system-ui,sans-serif}}main{{max-width:900px;margin:auto;padding:24px 20px 80px}}a{{color:inherit}}h1{{font:700 36px Georgia,serif;margin:0}}h2{{font-size:21px;margin:0 0 6px}}p{{margin:4px 0}}.topbar{{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:22px}}.top-actions,.actions{{display:flex;align-items:center;gap:9px;flex-wrap:wrap}}button,.button{{border:0;border-radius:11px;padding:11px 16px;background:var(--accent);color:white;font:700 14px system-ui;cursor:pointer;text-decoration:none}}.secondary{{background:var(--soft);color:var(--ink)}}.danger{{background:transparent;color:#a44439}}.card{{background:var(--paper);border:1px solid var(--line);border-radius:18px;padding:24px;margin:14px 0}}label.field{{display:block;margin:18px 0 0;color:var(--muted);font-size:13px}}input,textarea{{width:100%;margin-top:6px;border:1px solid var(--line);border-radius:11px;padding:12px 13px;background:#fff;font:inherit;color:var(--ink)}}textarea{{resize:vertical;min-height:92px}}.title-input{{font-size:20px;font-weight:700}}.toolbar{{display:flex;gap:5px;flex-wrap:wrap;padding:7px;background:var(--soft);border-radius:11px 11px 0 0;margin-top:7px}}.toolbar button{{padding:7px 11px;background:transparent;color:var(--ink)}}.toolbar button:hover{{background:#fff}}.editor{{min-height:330px;border:1px solid var(--line);border-top:0;border-radius:0 0 11px 11px;padding:18px;font-size:17px;line-height:1.7;outline:none}}.editor:empty:before{{content:attr(data-placeholder);color:#aaa}}.hint,.empty-note{{font-size:13px;color:var(--muted)}}.tag-list{{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}}.tag-wrap{{display:inline-flex;align-items:center;border:1px solid color-mix(in srgb,var(--tag) 50%,white);background:color-mix(in srgb,var(--tag) 12%,white);border-radius:999px;overflow:hidden}}.tag-wrap input{{display:none}}.tag-wrap label{{padding:7px 7px 7px 12px;cursor:pointer;color:var(--ink)}}.tag-wrap:has(input:checked){{background:var(--tag);border-color:var(--tag)}}.tag-wrap:has(input:checked) label{{color:#fff}}.tag-edit{{padding:6px 10px 6px 4px;background:transparent;color:inherit;opacity:0}}.tag-wrap:hover .tag-edit{{opacity:.75}}.add-tag{{border:1px dashed var(--line);background:white;color:var(--accent);border-radius:999px;padding:7px 13px}}.cover{{display:flex;align-items:center;gap:18px}}.cover-preview{{width:180px;aspect-ratio:16/9;object-fit:cover;border-radius:12px;background:var(--soft)}}.drop{{flex:1;border:1px dashed #c9b9ae;border-radius:13px;padding:18px;text-align:center;cursor:pointer}}.drop input{{display:none}}.section-head{{display:flex;justify-content:space-between;gap:12px;align-items:flex-start;margin-bottom:16px}}.asset-card{{display:grid;grid-template-columns:42px 1fr auto;gap:13px;align-items:start;border-top:1px solid var(--line);padding:16px 0}}.asset-icon{{width:42px;height:42px;border-radius:10px;background:var(--soft);display:grid;place-items:center;font-size:20px}}.asset-fields input,.asset-fields textarea{{margin:0 0 8px}}.asset-fields textarea{{min-height:68px}}.asset-actions{{display:flex;flex-direction:column;gap:5px}}.new-asset{{background:var(--soft);border-radius:14px;padding:17px;margin-top:12px}}.new-asset-grid{{display:grid;grid-template-columns:150px 1fr;gap:10px}}select{{width:100%;border:1px solid var(--line);border-radius:11px;padding:12px;background:#fff;font:inherit}}dialog{{border:0;border-radius:18px;padding:24px;box-shadow:0 20px 80px #0003;width:min(420px,90vw)}}dialog::backdrop{{background:#211b1888}}.toast{{background:#e1f2e4;color:#26613b;border-radius:11px;padding:11px 15px;margin-bottom:14px}}.save-state{{font-size:13px;color:var(--muted)}}@media(max-width:650px){{.topbar,.cover{{align-items:stretch;flex-direction:column}}.asset-card{{grid-template-columns:42px 1fr}}.asset-actions{{grid-column:2;flex-direction:row}}.new-asset-grid{{grid-template-columns:1fr}}.top-actions{{width:100%}}.top-actions>button{{flex:1}}}}
        </style></head><body><main><a href="{self.url('/learning')}">← Все материалы</a><form id="article-form" data-id="{m["id"]}" method="post" action="{self.url('/learning/material/action')}" enctype="multipart/form-data"><input type="hidden" name="action" value="material_save"><input type="hidden" name="editor" value="1"><input type="hidden" name="id" value="{m["id"]}"><div class="topbar"><h1>{title}</h1><div class="top-actions"><span id="save-state" class="save-state"></span><button>Сохранить</button>{existing_controls}</div></div>{saved}
        <section class="card"><h2>Материал</h2><p class="hint">Название и короткий анонс для карточки в приложении.</p><label class="field">Название<input class="title-input" name="title" value="{esc(m["title"])}" placeholder="Введите название" required autofocus></label><label class="field">Краткое описание<textarea name="short_description" placeholder="О чём этот материал — 1–3 предложения">{esc(m["short_description"] or "")}</textarea></label></section>
        <section class="card"><h2>Статья</h2><p class="hint">Можно вставить готовый пост — абзацы, списки, ссылки и форматирование сохранятся.</p><div class="toolbar"><button type="button" data-cmd="bold"><b>Ж</b></button><button type="button" data-cmd="italic"><i>К</i></button><button type="button" data-cmd="formatBlock" data-value="h2">Заголовок</button><button type="button" data-cmd="insertUnorderedList">• Список</button><button type="button" data-cmd="insertOrderedList">1. Список</button><button type="button" id="add-link">Ссылка</button><button type="button" data-cmd="removeFormat">Очистить</button></div><div id="content-editor" class="editor" contenteditable="true" data-placeholder="Вставьте пост из Telegram или начните писать…">{clean_rich_text(m["full_description"] or "")}</div><textarea id="content-source" name="full_description" hidden></textarea></section>
        <section class="card"><div class="section-head"><div><h2>Теги</h2><p class="hint">Нажмите на тег, чтобы выбрать. Карандаш появляется при наведении.</p></div><button type="button" class="add-tag" onclick="document.getElementById('new-tag').showModal()">＋ Новый тег</button></div><div class="tag-list">{tag_chips or '<span class="empty-note">Тегов пока нет.</span>'}</div></section>
        <section class="card"><h2>Обложка</h2><p class="hint">Необязательно. Используется как миниатюра карточки, рекомендуемый формат 16:9.</p><div class="cover">{f'<img class="cover-preview" src="{esc(m["cover_url"])}" alt="Текущая обложка">' if m["cover_url"] else '<div class="cover-preview"></div>'}<label class="drop"><b>＋ Загрузить обложку</b><br><span class="hint">JPG, PNG или WEBP</span><input type="file" name="cover_file" accept=".jpg,.jpeg,.png,.webp"></label></div></section></form>
        <section class="card"><div class="section-head"><div><h2>Изображения и видео в статье</h2><p class="hint">Добавляйте их в нужном порядке после основного текста.</p></div></div>{media_cards}<form class="new-asset" method="post" action="{self.url('/learning/material/action')}" enctype="multipart/form-data"><input type="hidden" name="action" value="block_save"><input type="hidden" name="material_id" value="{m["id"]}"><div class="new-asset-grid"><select name="block_type"><option value="image">Изображение</option><option value="video">Видео</option></select><input name="block_title" placeholder="Заголовок"></div><textarea name="block_description" placeholder="Краткое описание"></textarea><input name="block_content" placeholder="Ссылка на изображение или видео"><input type="file" name="block_file" accept=".jpg,.jpeg,.png,.webp,.mp4"><button {"" if material else "disabled"}>＋ Добавить в статью</button>{'' if material else '<span class="hint"> Сначала сохраните основной материал.</span>'}</form></section>
        <section class="card"><div class="section-head"><div><h2>Дополнительные материалы</h2><p class="hint">PDF, документ, презентация, таблица, изображение или видео.</p></div></div>{file_cards}<form class="new-asset" method="post" action="{self.url('/learning/material/action')}" enctype="multipart/form-data"><input type="hidden" name="action" value="file_add"><input type="hidden" name="material_id" value="{m["id"]}"><input name="file_title" placeholder="Заголовок материала"><textarea name="file_description" placeholder="Кратко опишите, что внутри"></textarea><label class="drop"><b>＋ Выбрать файл</b><input type="file" name="material_file" required></label><button {"" if material else "disabled"}>Добавить материал</button>{'' if material else '<span class="hint"> Сначала сохраните основной материал.</span>'}</form></section>
        {tag_dialogs}<dialog id="new-tag"><form class="tag-modal-form" method="post" action="{self.url('/learning/material/action')}"><input type="hidden" name="action" value="tag_create"><input type="hidden" name="ajax" value="1"><input type="hidden" name="return_material" value="{m["id"]}"><h2>Новый тег</h2><label class="field">Название<input name="tag_name" placeholder="Например: Методика" required></label><label class="field">Цвет<input type="color" name="tag_color" value="#D97757"></label><div class="actions"><button>Добавить</button><button type="button" class="secondary" onclick="this.closest('dialog').close()">Отмена</button></div></form></dialog>
        <script>const form=document.getElementById('article-form'),editor=document.getElementById('content-editor'),source=document.getElementById('content-source'),state=document.getElementById('save-state'),tagList=document.querySelector('.tag-list');function sync(){{source.value=editor.innerHTML}}document.querySelectorAll('[data-cmd]').forEach(b=>b.onclick=()=>{{editor.focus();document.execCommand(b.dataset.cmd,false,b.dataset.value||null);sync()}});document.getElementById('add-link').onclick=()=>{{const url=prompt('Вставьте ссылку');if(url)document.execCommand('createLink',false,url);sync()}};sync();form.addEventListener('submit',sync);let timer;function autosave(){{if(!form.dataset.id)return;sync();state.textContent='Сохраняем…';const data=new FormData(form);data.delete('cover_file');data.append('autosave','1');fetch(form.getAttribute('action'),{{method:'POST',body:data}}).then(r=>r.ok?r.json():Promise.reject()).then(()=>state.textContent='Сохранено').catch(()=>state.textContent='Не удалось сохранить')}}editor.addEventListener('input',()=>{{clearTimeout(timer);timer=setTimeout(autosave,1000)}});document.querySelectorAll('.tag-modal-form').forEach(tf=>tf.addEventListener('submit',async e=>{{e.preventDefault();const r=await fetch(tf.getAttribute('action'),{{method:'POST',body:new FormData(tf)}});if(!r.ok)return alert('Не удалось сохранить тег');const t=await r.json();let wrap=document.getElementById('tag-'+t.id)?.closest('.tag-wrap');if(wrap){{wrap.style.setProperty('--tag',t.color);wrap.querySelector('label').textContent=t.name}}else{{document.querySelector('.empty-note')?.remove();wrap=document.createElement('span');wrap.className='tag-wrap';wrap.style.setProperty('--tag',t.color);const input=document.createElement('input');input.type='checkbox';input.name='tag_ids';input.value=t.id;input.id='tag-'+t.id;input.checked=true;const label=document.createElement('label');label.htmlFor=input.id;label.textContent=t.name;wrap.append(input,label);tagList.append(wrap)}}tf.closest('dialog').close()}}));</script></main></body></html>''', content_type="text/html")

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
        return web.Response(text=f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Предпросмотр — {esc(material["title"])}</title><style>body{{margin:0;background:#f6f2ed;color:#302621;font:16px/1.65 system-ui,sans-serif}}main{{max-width:760px;margin:auto;background:#fff;padding:34px 24px;min-height:100vh}}h1{{font:700 38px Georgia,serif;line-height:1.15}}.muted,small{{color:#89776d}}.tag{{display:inline-block;background:#f0e8e1;border-radius:999px;padding:3px 10px;margin:2px;font-size:12px}}.preview-block{{border-top:1px solid #e5d9cf;padding:18px 0}}img{{max-width:100%}}</style><main><p class="muted">Предпросмотр материала</p><h1>{esc(material["title"])}</h1><p class="muted">{esc(material["short_description"] or "")}</p><div>{tag_html}</div><section>{clean_rich_text(material["full_description"] or "")}</section>{blocks_html}{("<h3>Файлы</h3><ul>" + file_html + "</ul>") if file_html else ""}</main></html>''', content_type="text/html")

    async def save_material_file(self, db, material_id: int, upload, title: str = "", description: str = "") -> None:
        if not getattr(upload, "filename", None) or not getattr(upload, "file", None):
            return
        extension = Path(upload.filename).suffix.lower()
        allowed = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".txt", ".md", ".jpg", ".jpeg", ".png", ".webp", ".mp3", ".mp4"}
        if extension not in allowed:
            raise web.HTTPBadRequest(text="Этот тип файла не поддерживается")
        media_dir = Path(__file__).resolve().parent.parent / "media" / "mini_app"
        media_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"{secrets.token_urlsafe(18)}{extension}"
        target = media_dir / stored_name
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        await db.execute(
            "INSERT INTO mini_app_material_files(material_id,file_name,stored_name,mime_type,file_size,title,description,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (material_id, Path(upload.filename).name[:250], stored_name, upload.content_type or mimetypes.guess_type(upload.filename)[0], target.stat().st_size, title.strip() or None, description.strip() or None, datetime.utcnow().isoformat(timespec="seconds")),
        )

    async def save_block_file(self, upload) -> str | None:
        if not getattr(upload, "filename", None) or not getattr(upload, "file", None):
            return None
        extension = Path(upload.filename).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp", ".mp4"}:
            raise web.HTTPBadRequest(text="Для статьи можно загрузить изображение или MP4-видео")
        media_dir = Path(__file__).resolve().parent.parent / "media" / "mini_app"
        media_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"content-{secrets.token_urlsafe(18)}{extension}"
        with (media_dir / stored_name).open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        return f"/mini-app/media/{stored_name}"

    async def save_cover(self, db, material_id: int, upload) -> None:
        if not getattr(upload, "filename", None) or not getattr(upload, "file", None):
            return
        extension = Path(upload.filename).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise web.HTTPBadRequest(text="Обложка должна быть JPG, PNG или WEBP")
        media_dir = Path(__file__).resolve().parent.parent / "media" / "mini_app"
        media_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"cover-{secrets.token_urlsafe(18)}{extension}"
        target = media_dir / stored_name
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        await db.execute("UPDATE mini_app_materials SET cover_url=?, updated_at=? WHERE id=?", (f"/mini-app/media/{stored_name}", datetime.utcnow().isoformat(timespec="seconds"), material_id))

    async def action(self, request: web.Request) -> web.Response:
        await self.schema.init()
        form = await request.post()
        action = str(form.get("action") or "")
        now = datetime.utcnow().isoformat(timespec="seconds")
        db = await self.connect()
        editor_id = None
        tag_result = None
        try:
            if action == "tag_create":
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
            elif action == "material_save":
                item_id = int(form.get("id") or 0)
                values = (str(form.get("title") or "").strip(), str(form.get("short_description") or "").strip() or None, str(form.get("full_description") or "").strip() or None, now)
                if not values[0]:
                    raise web.HTTPBadRequest(text="Название материала обязательно")
                if item_id:
                    await db.execute("UPDATE mini_app_materials SET title=?,short_description=?,full_description=?,format=NULL,status='published',updated_at=? WHERE id=?", (*values, item_id))
                else:
                    cur = await db.execute("INSERT INTO mini_app_materials(title,short_description,full_description,format,status,sort_order,created_at,updated_at) VALUES(?,?,?,NULL,'published',0,?,?)", (*values, now))
                    item_id = int(cur.lastrowid)
                await db.execute("DELETE FROM mini_app_material_tags WHERE material_id=?", (item_id,))
                for tag_id in form.getall("tag_ids", []):
                    if str(tag_id).isdigit():
                        await db.execute("INSERT OR IGNORE INTO mini_app_material_tags(material_id,tag_id) VALUES(?,?)", (item_id, int(tag_id)))
                await self.save_cover(db, item_id, form.get("cover_file"))
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
                uploaded_url = await self.save_block_file(form.get("block_file"))
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
                    target = Path(__file__).resolve().parent.parent / "media" / "mini_app" / Path(row["stored_name"]).name
                    if target.is_file():
                        target.unlink()
            elif action == "material_delete":
                item_id = int(form.get("id") or 0)
                if not item_id:
                    raise web.HTTPBadRequest(text="Материал не указан")
                await db.execute("DELETE FROM mini_app_materials WHERE id=?", (item_id,))
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
        if action in {"tag_create", "tag_save"} and form.get("ajax") == "1":
            return web.json_response(tag_result or {"ok": False}, status=200 if tag_result else 400)
        if action == "material_save" and form.get("autosave") == "1":
            return web.json_response({"ok": True, "material_id": item_id})
        if editor_id:
            raise web.HTTPSeeOther(location=self.material_url(editor_id, saved=1))
        raise web.HTTPSeeOther(location=self.url("/learning", saved=1))
