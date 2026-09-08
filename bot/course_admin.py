from __future__ import annotations

import html
import json
import secrets
import shutil
from datetime import datetime
from pathlib import Path

from aiohttp import web


def esc(value: object) -> str:
    return html.escape("" if value is None else str(value), quote=True)


class CourseAdmin:
    """A simple course builder with optional modules and independent lesson blocks."""

    block_labels = {"longread": "Лонгрид", "video": "Видео", "image": "Изображение", "test": "Тест"}

    def __init__(self, learning_admin):
        self.owner = learning_admin

    @property
    def action_url(self) -> str:
        return self.owner.url("/learning/material/action")

    def courses_url(self, **query) -> str:
        return self.owner.url("/learning", section="courses", **query)

    def course_url(self, course_id: int | None = None, **query) -> str:
        return self.courses_url(course="new" if course_id is None else course_id, **query)

    def lesson_url(self, lesson_id: int, course_id: int, **query) -> str:
        return self.courses_url(course=course_id, lesson=lesson_id, **query)

    def course_material_url(self, material_id: int, course_id: int, lesson_id: int, block_id: int) -> str:
        return self.owner.material_url(
            material_id,
            course_material=1,
            return_course=course_id,
            return_lesson=lesson_id,
            return_block=block_id,
        )

    def tabs(self, active: str) -> str:
        return f'''<nav class="admin-tabs"><a class="{"active" if active == "materials" else ""}" href="{self.owner.url('/learning')}">Материалы</a><a class="{"active" if active == "courses" else ""}" href="{self.courses_url()}">Курсы</a></nav>'''

    @staticmethod
    def styles() -> str:
        return '''
        :root{--bg:#f7f5f2;--paper:#fff;--ink:#292421;--muted:#817873;--line:#e7e0da;--accent:#c56349;--soft:#f3ece7;--success:#2f7147}
        *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}main{max-width:1340px;margin:auto;padding:26px 20px 80px}a{color:inherit}.admin-tabs{display:flex;gap:7px;margin:0 0 28px;padding:5px;width:max-content;border:1px solid var(--line);border-radius:13px;background:var(--paper)}.admin-tabs a{padding:8px 14px;border-radius:9px;color:var(--muted);font-weight:750;text-decoration:none}.admin-tabs a.active{background:var(--accent);color:#fff}.top,.row,.section-head,.lesson-line{display:flex;align-items:center;justify-content:space-between;gap:14px}.top{margin-bottom:22px}.top h1{margin:0;font:700 38px/1.08 Georgia,serif}.top p,.hint{color:var(--muted)}h2{margin:0 0 6px;font-size:21px}h3{margin:0;font-size:16px}.button,button{display:inline-flex;align-items:center;justify-content:center;border:0;border-radius:10px;padding:10px 15px;background:var(--accent);color:#fff;font:700 14px system-ui;cursor:pointer;text-decoration:none}.secondary{background:var(--soft);color:var(--ink)}.danger{background:#fff0ed;color:#a44439}.ghost{padding:7px 9px;background:transparent;color:var(--muted)}.panel,.course-card,.module-card,.block-card{background:var(--paper);border:1px solid var(--line);border-radius:17px;padding:20px;margin:12px 0}.course-card{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:20px;align-items:center}.course-card p{margin:5px 0;color:var(--muted)}.meta{font-size:12px;color:var(--muted)}.course-workspace{display:grid;grid-template-columns:270px minmax(0,1fr);gap:18px;align-items:start}.layout{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:18px}.sticky{position:sticky;top:16px}.field{display:block;margin:15px 0;color:var(--muted);font-size:13px}input,textarea,select{width:100%;margin-top:6px;padding:11px 12px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink);font:inherit}textarea{min-height:92px;resize:vertical}.checkbox{display:flex;gap:10px;align-items:flex-start;padding:13px;border:1px solid var(--line);border-radius:12px}.checkbox input{width:18px;height:18px;margin:2px 0}.actions,.lesson-actions,.block-actions{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.empty{padding:30px;border:1px dashed var(--line);border-radius:14px;text-align:center;color:var(--muted)}.module-card{padding:0;overflow:hidden;scroll-margin-top:18px}.module-head{padding:17px 18px;background:var(--soft)}.module-head form{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.4fr) auto auto;gap:8px;align-items:center}.module-head input{margin:0}.lesson-list{padding:7px 17px 13px}.lesson-line{padding:12px 0;border-bottom:1px solid var(--line)}.lesson-line:last-child{border-bottom:0}.lesson-line p{margin:3px 0 0;color:var(--muted);font-size:12px}.ungrouped{margin-bottom:18px}.add-box{padding:16px;border:1px dashed #cdbdb2;border-radius:14px;background:color-mix(in srgb,var(--soft) 55%,white)}.add-grid{display:grid;grid-template-columns:minmax(0,1fr) 220px auto;gap:9px;align-items:end}.add-grid input,.add-grid select{margin:0}.back{display:inline-block;margin-bottom:17px;color:var(--muted);text-decoration:none}.block-card{position:relative}.block-type{display:inline-flex;padding:4px 8px;border-radius:999px;background:var(--soft);color:var(--accent);font-size:11px;font-weight:800}.block-preview{margin:12px 0}.block-preview img,.block-preview video{display:block;width:100%;max-height:480px;object-fit:contain;border-radius:12px;background:#181513}.test-options{display:grid;grid-template-columns:1fr 1fr;gap:8px}.saved{margin:0 0 14px;padding:11px 14px;border-radius:11px;background:#e2f1e6;color:var(--success)}.format-hint{padding:9px 11px;border-radius:9px;background:var(--soft);color:var(--muted);font-size:12px}.course-toolbar{display:flex;gap:5px;flex-wrap:wrap;padding:7px;background:var(--soft);border-radius:11px 11px 0 0;margin-top:14px}.course-toolbar button{padding:7px 10px;background:transparent;color:var(--ink)}.course-toolbar button:hover{background:#fff}.course-toolbar .media-button{background:var(--accent);color:#fff}.course-editor{min-height:330px;border:1px solid var(--line);border-top:0;border-radius:0 0 11px 11px;padding:18px;font-size:17px;line-height:1.7;outline:none}.course-editor:empty:before{content:attr(data-placeholder);color:#aaa}.course-editor figure.inline-media{position:relative;margin:22px 0;padding:8px;border:1px solid transparent;border-radius:12px;cursor:grab}.course-editor figure.inline-media:hover{border-color:var(--line);background:var(--soft)}.course-editor figure.inline-media:before{content:'⠿ Перетащите, чтобы изменить место';display:block;color:var(--muted);font-size:12px;margin-bottom:6px}.course-editor figure img,.course-editor figure video{display:block;max-width:100%;max-height:520px;border-radius:10px;margin:auto}.media-remove{position:absolute;top:10px;right:10px;width:34px;height:34px;padding:0;border-radius:50%;background:#fff;color:#a44439;box-shadow:0 3px 14px #0003;font-size:22px}.editor-status{min-height:21px;margin-top:7px;color:var(--muted);font-size:12px}.file-drop{display:block;margin-top:14px;padding:18px;border:1px dashed #c9b9ae;border-radius:13px;text-align:center;cursor:pointer}.file-drop input{display:none}.add-block{margin-top:18px;padding:20px;border:1px dashed #cdbdb2;border-radius:17px;background:var(--paper)}.block-kind-tabs{display:flex;gap:7px;flex-wrap:wrap;margin:13px 0}.block-kind-tabs button{background:var(--soft);color:var(--ink)}.block-kind-tabs button.active{background:var(--accent);color:#fff}.block-add-form{display:none;padding-top:3px}.block-add-form.active{display:block}.course-outline{position:sticky;top:16px;max-height:calc(100vh - 32px);overflow:auto;margin:0;padding:12px;border:1px solid var(--line);border-radius:17px;background:var(--paper)}.outline-course{display:flex;gap:9px;align-items:center;padding:10px;border-radius:10px;text-decoration:none;font-weight:850}.outline-course.active,.outline-course:hover{background:var(--soft)}.outline-course span{color:var(--accent)}.outline-label{padding:13px 9px 5px;color:var(--muted);font-size:10px;font-weight:850;letter-spacing:.08em;text-transform:uppercase}.tree-module{margin-top:5px;border-radius:10px}.tree-module-title,.tree-lesson{display:flex;gap:7px;align-items:center;min-width:0;border-radius:9px;color:var(--ink);text-decoration:none}.tree-module-title{padding:8px 8px;font-size:13px;font-weight:800}.tree-lesson{margin:2px 0 2px 20px;padding:7px 8px;color:var(--muted);font-size:12px}.tree-module-title:hover,.tree-lesson:hover,.tree-lesson.active{background:var(--soft);color:var(--ink)}.tree-grip{flex:none;color:#b6a79d;cursor:grab}.tree-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.tree-drop{min-height:8px;border-radius:7px}.tree-drop.drag-over,.tree-module-title.drag-over,.tree-lesson.drag-over{outline:2px solid var(--accent);background:var(--soft)}.outline-add{margin:8px 0 3px;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}.outline-add details+details{border-top:1px solid var(--line)}.outline-add summary{padding:10px 8px;cursor:pointer;color:var(--accent);font-size:12px;font-weight:800}.outline-add form{padding:0 7px 11px}.outline-add .field{margin:8px 0}.outline-add input,.outline-add select{padding:8px;font-size:12px}.outline-add button{width:100%;padding:8px;font-size:12px}
        .outline-actions{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin:9px 0 12px}.outline-actions button{width:100%;padding:8px 6px;background:var(--soft);color:var(--accent);font-size:11px}.outline-actions button:hover{background:var(--accent);color:#fff}.tree-item{position:relative;min-width:0}.tree-item>.tree-lesson,.tree-item>.tree-module-title{padding-right:34px}.tree-delete{position:absolute;z-index:3;right:3px;top:50%;transform:translateY(-50%);opacity:0;pointer-events:none}.tree-item:hover>.tree-delete,.tree-item:focus-within>.tree-delete{opacity:1;pointer-events:auto}.tree-delete button{width:27px;height:27px;padding:0;border-radius:8px;background:#fff0ed;color:#a44439;font-size:16px}.course-upload-overlay{position:fixed;z-index:50;inset:0;display:none;place-items:center;background:#261d19aa;padding:20px}.course-upload-overlay.active{display:grid}.course-upload-box{width:min(390px,90vw);padding:24px;border-radius:18px;background:#fff;text-align:center;box-shadow:0 24px 80px #0004}.course-upload-track{height:8px;margin-top:14px;border-radius:99px;overflow:hidden;background:var(--soft)}.course-upload-track i{display:block;width:8%;height:100%;background:var(--accent);transition:width .2s}
        @media(max-width:1000px){.course-workspace{grid-template-columns:230px minmax(0,1fr)}.layout{grid-template-columns:1fr}.sticky{position:static}}
        @media(max-width:760px){.course-workspace{grid-template-columns:1fr}.course-outline{position:static;max-height:none}.top,.course-card{align-items:stretch;grid-template-columns:1fr;flex-direction:column}.course-card{display:flex}.module-head form,.add-grid{grid-template-columns:1fr}.lesson-line{align-items:flex-start}.test-options{grid-template-columns:1fr}.top h1{font-size:32px}.admin-tabs{width:100%}.admin-tabs a{flex:1;text-align:center}}
        '''

    def course_outline(self, course, modules, lessons, active_lesson_id: int | None = None) -> str:
        if not course or not course["id"]:
            return '''<aside class="course-outline"><div class="outline-label">Структура курса</div><div class="hint" style="padding:10px">Сначала сохраните курс. Затем здесь появятся модули и уроки.</div></aside>'''

        course_id = int(course["id"])
        grouped = {int(module["id"]): [] for module in modules}
        ungrouped = []
        for lesson in lessons:
            module_id = lesson["module_id"]
            if module_id in grouped:
                grouped[module_id].append(lesson)
            else:
                ungrouped.append(lesson)

        def lesson_node(row) -> str:
            active = " active" if int(row["id"]) == active_lesson_id else ""
            module_id = "" if row["module_id"] is None else str(row["module_id"])
            return f'''<div class="tree-item"><a class="tree-lesson{active}" draggable="true" data-tree-kind="lesson" data-tree-id="{row["id"]}" data-tree-module="{module_id}" href="{self.lesson_url(row["id"], course_id)}"><span class="tree-grip" title="Перетащить">⋮⋮</span><span class="tree-name">{esc(row["title"])}</span></a><form class="tree-delete" method="post" action="{self.action_url}" onsubmit="return confirm('Удалить урок?')"><input type="hidden" name="action" value="course_lesson_delete"><input type="hidden" name="course_id" value="{course_id}"><input type="hidden" name="lesson_id" value="{row["id"]}"><button title="Удалить урок" aria-label="Удалить урок">🗑</button></form></div>'''

        ungrouped_html = "".join(lesson_node(row) for row in ungrouped)
        modules_html = "".join(
            f'''<div class="tree-module"><div class="tree-item"><a class="tree-module-title" draggable="true" data-tree-kind="module" data-tree-id="{module["id"]}" href="{self.course_url(course_id)}#module-{module["id"]}"><span class="tree-grip" title="Перетащить">⋮⋮</span><span class="tree-name">{esc(module["title"])}</span></a><form class="tree-delete" method="post" action="{self.action_url}" onsubmit="return confirm('Удалить модуль? Уроки останутся в курсе без модуля.')"><input type="hidden" name="action" value="course_module_save"><input type="hidden" name="course_id" value="{course_id}"><input type="hidden" name="module_id" value="{module["id"]}"><input type="hidden" name="delete" value="1"><button title="Удалить модуль" aria-label="Удалить модуль">🗑</button></form></div><div class="tree-drop" data-tree-drop data-tree-module="{module["id"]}">{"".join(lesson_node(row) for row in grouped[int(module["id"])])}</div></div>'''
            for module in modules
        )
        add_controls = f'''<div class="outline-actions"><form method="post" action="{self.action_url}"><input type="hidden" name="action" value="course_lesson_add"><input type="hidden" name="course_id" value="{course_id}"><button>＋ Новый урок</button></form><form method="post" action="{self.action_url}"><input type="hidden" name="action" value="course_module_add"><input type="hidden" name="course_id" value="{course_id}"><button>＋ Новый модуль</button></form></div>'''
        return f'''<aside class="course-outline"><a class="outline-course {"active" if active_lesson_id is None else ""}" href="{self.course_url(course_id)}"><span>◆</span><span class="tree-name">{esc(course["title"])}</span></a>{add_controls}<div class="tree-drop" data-tree-drop data-tree-module="">{ungrouped_html}</div>{modules_html}<p class="hint" style="padding:10px 8px 0;font-size:11px">Перетаскивайте уроки и модули, чтобы изменить структуру.</p></aside>'''

    def tree_script(self, course_id: int) -> str:
        return f'''<script>(()=>{{
        let dragged=null;
        const actionUrl={json.dumps(self.action_url)};
        const courseId={int(course_id)};
        document.querySelectorAll('[data-tree-kind]').forEach(el=>{{
          el.addEventListener('dragstart',event=>{{dragged={{kind:el.dataset.treeKind,id:el.dataset.treeId}};event.dataTransfer.effectAllowed='move';el.style.opacity='.45';}});
          el.addEventListener('dragend',()=>{{el.style.opacity='';document.querySelectorAll('.drag-over').forEach(node=>node.classList.remove('drag-over'));}});
        }});
        document.querySelectorAll('[data-tree-drop],[data-tree-kind]').forEach(target=>{{
          target.addEventListener('dragover',event=>{{if(!dragged)return;event.preventDefault();event.stopPropagation();target.classList.add('drag-over');event.dataTransfer.dropEffect='move';}});
          target.addEventListener('dragleave',event=>{{if(!target.contains(event.relatedTarget))target.classList.remove('drag-over');}});
          target.addEventListener('drop',async event=>{{
            if(!dragged)return;
            event.preventDefault();event.stopPropagation();target.classList.remove('drag-over');
            const kind=target.dataset.treeKind||'';
            const form=new FormData();
            form.set('action','course_tree_move');form.set('ajax','1');form.set('course_id',courseId);
            form.set('item_type',dragged.kind);form.set('item_id',dragged.id);
            if(dragged.kind==='lesson'){{
              const moduleId=kind==='lesson'?(target.dataset.treeModule||''):(kind==='module'?target.dataset.treeId:(target.dataset.treeModule||''));
              form.set('target_module_id',moduleId);
              if(kind==='lesson')form.set('before_id',target.dataset.treeId);
            }}else if(dragged.kind==='module'&&kind==='module'){{
              form.set('before_id',target.dataset.treeId);
            }}else{{return;}}
            if(form.get('before_id')===dragged.id)return;
            try{{
              const response=await fetch(actionUrl,{{method:'POST',body:form,credentials:'same-origin'}});
              if(!response.ok)throw new Error(await response.text());
              location.reload();
            }}catch(error){{alert('Не удалось изменить порядок. Попробуйте ещё раз.');}}
          }});
        }});
        }})();</script>'''

    async def page(self, request: web.Request) -> web.Response:
        if request.query.get("lesson"):
            return await self.lesson_editor(request)
        if request.query.get("course") is not None:
            return await self.course_editor(request)
        return await self.index(request)

    async def index(self, request: web.Request) -> web.Response:
        db = await self.owner.connect()
        try:
            courses = await self.owner.rows(
                db,
                """SELECT c.*,
                          (SELECT COUNT(*) FROM mini_app_course_modules m WHERE m.course_id=c.id) module_count,
                          (SELECT COUNT(*) FROM mini_app_course_units l WHERE l.course_id=c.id) lesson_count
                   FROM mini_app_courses c ORDER BY c.updated_at DESC,c.id DESC""",
            )
        finally:
            await db.close()
        cards = "".join(
            f'''<article class="course-card"><div><div class="meta">{row["module_count"]} модулей · {row["lesson_count"]} уроков</div><h2>{esc(row["title"])}</h2><p>{esc(row["description"] or "Описание ещё не добавлено")}</p></div><div class="actions"><a class="button" href="{self.course_url(row["id"])}">Открыть</a><form method="post" action="{self.action_url}" onsubmit="return confirm('Удалить курс со всеми уроками?')"><input type="hidden" name="action" value="course_delete"><input type="hidden" name="course_id" value="{row["id"]}"><button class="danger">Удалить</button></form></div></article>'''
            for row in courses
        ) or '<div class="empty">Курсов пока нет. Создайте первый курс.</div>'
        return web.Response(
            text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Курсы — Nastaunik</title><style>{self.styles()}</style></head><body><main>{self.tabs("courses")}<div class="top"><div><h1>Курсы</h1><p>Собирайте программу из уроков — с модулями или без них.</p></div><a class="button" href="{self.course_url()}">＋ Создать курс</a></div>{cards}</main></body></html>''',
            content_type="text/html",
        )

    async def course_editor(self, request: web.Request) -> web.Response:
        raw_id = str(request.query.get("course") or "new")
        db = await self.owner.connect()
        try:
            course = None
            if raw_id != "new":
                if not raw_id.isdigit():
                    raise web.HTTPNotFound(text="Курс не найден")
                course = await (await db.execute("SELECT * FROM mini_app_courses WHERE id=?", (int(raw_id),))).fetchone()
                if not course:
                    raise web.HTTPNotFound(text="Курс не найден")
            modules = await self.owner.rows(db, "SELECT * FROM mini_app_course_modules WHERE course_id=? ORDER BY sort_order,id", (course["id"],)) if course else []
            lessons = await self.owner.rows(db, "SELECT * FROM mini_app_course_units WHERE course_id=? ORDER BY sort_order,id", (course["id"],)) if course else []
        finally:
            await db.close()
        c = course or {"id": "", "title": "", "description": "", "outcome": "", "duration_label": "", "cover_url": "", "is_visible": 0}
        grouped = {module["id"]: [] for module in modules}
        ungrouped = []
        for lesson in lessons:
            (grouped.get(lesson["module_id"]) if lesson["module_id"] in grouped else ungrouped).append(lesson)

        def lesson_rows(rows) -> str:
            return "".join(
                f'''<div class="lesson-line"><div><h3>{esc(row["title"])}</h3><p>{"Обязательный урок" if row["is_required"] else "Дополнительный урок"}</p></div><div class="lesson-actions"><a class="button secondary" href="{self.lesson_url(row["id"], c["id"])}">Открыть</a><form method="post" action="{self.action_url}" onsubmit="return confirm('Удалить урок?')"><input type="hidden" name="action" value="course_lesson_delete"><input type="hidden" name="course_id" value="{c["id"]}"><input type="hidden" name="lesson_id" value="{row["id"]}"><button class="ghost">×</button></form></div></div>'''
                for row in rows
            ) or '<div class="hint" style="padding:12px 0">В этом разделе пока нет уроков.</div>'

        module_html = "".join(
            f'''<section class="module-card" id="module-{module["id"]}"><div class="module-head"><form method="post" action="{self.action_url}"><input type="hidden" name="action" value="course_module_save"><input type="hidden" name="course_id" value="{c["id"]}"><input type="hidden" name="module_id" value="{module["id"]}"><input name="title" value="{esc(module["title"])}" aria-label="Название модуля" required><input name="description" value="{esc(module["description"] or "")}" placeholder="Краткое описание"><button class="secondary">Сохранить</button><button class="danger" name="delete" value="1" onclick="return confirm('Удалить модуль? Уроки останутся без модуля.')">Удалить</button></form></div><div class="lesson-list">{lesson_rows(grouped[module["id"]])}</div></section>'''
            for module in modules
        )
        program = '<div class="empty">Сохраните курс — после этого здесь появится конструктор программы.</div>'
        if course:
            flat_lessons = f'''<section class="ungrouped"><div class="panel">{lesson_rows(ungrouped)}</div></section>''' if ungrouped else ""
            program = flat_lessons + module_html or '<div class="empty">Нажмите «Новый урок» или «Новый модуль» в колонке слева.</div>'
        return web.Response(
            text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(c["title"] or "Новый курс")} — Nastaunik</title><style>{self.styles()}</style></head><body><main>{self.tabs("courses")}<a class="back" href="{self.courses_url()}">← Все курсы</a>{'<div class="saved">Изменения сохранены</div>' if request.query.get('saved') else ''}<div class="top"><div><h1>{esc(c["title"] or "Новый курс")}</h1><p>Модули необязательны — уроки можно добавлять сразу.</p></div></div><div class="course-workspace">{self.course_outline(c, modules, lessons)}<div class="layout"><div><section class="panel"><h2>Программа курса</h2><p class="hint">Выберите урок слева, чтобы открыть его. Структуру можно менять перетаскиванием.</p>{program}</section></div><aside><form class="panel sticky" method="post" action="{self.action_url}" enctype="multipart/form-data"><input type="hidden" name="action" value="course_save"><input type="hidden" name="course_id" value="{c["id"]}"><h2>О курсе</h2><label class="field">Название<input name="title" value="{esc(c["title"])}" required autofocus></label><label class="field">Краткое описание<textarea name="description">{esc(c["description"] or "")}</textarea></label><label class="field">Результат обучения<textarea name="outcome" placeholder="После курса участник сможет…">{esc(c["outcome"] or "")}</textarea></label><label class="field">Продолжительность<input name="duration_label" value="{esc(c["duration_label"] or "")}" placeholder="Например: 4 недели"></label><label class="field">Обложка 16:9<input type="file" name="cover_file" accept=".jpg,.jpeg,.png,.webp"></label>{f'<img src="{esc(c["cover_url"])}" alt="" style="width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:11px">' if c["cover_url"] else ''}<div class="checkbox" style="opacity:.68"><input type="checkbox" disabled><span><b>Публикация в Mini App</b><br><span class="hint">Подключим после того, как утвердим внешний вид урока.</span></span></div><div class="actions" style="margin-top:15px"><button>Сохранить курс</button></div></form></aside></div></div>{self.tree_script(c["id"]) if course else ""}</main></body></html>''',
            content_type="text/html",
        )

    async def lesson_editor(self, request: web.Request) -> web.Response:
        lesson_id = int(request.query.get("lesson") or 0)
        course_id = int(request.query.get("course") or 0)
        db = await self.owner.connect()
        try:
            lesson = await (await db.execute("SELECT * FROM mini_app_course_units WHERE id=? AND course_id=?", (lesson_id, course_id))).fetchone()
            if not lesson:
                raise web.HTTPNotFound(text="Урок не найден")
            course = await (await db.execute("SELECT title FROM mini_app_courses WHERE id=?", (course_id,))).fetchone()
            modules = await self.owner.rows(db, "SELECT id,title FROM mini_app_course_modules WHERE course_id=? ORDER BY sort_order,id", (course_id,))
            lessons = await self.owner.rows(db, "SELECT * FROM mini_app_course_units WHERE course_id=? ORDER BY sort_order,id", (course_id,))
            blocks = await self.owner.rows(
                db,
                """SELECT b.*,m.title material_title,m.short_description material_description
                   FROM mini_app_course_blocks b
                   LEFT JOIN mini_app_materials m ON m.id=b.material_id
                   WHERE b.lesson_id=? ORDER BY b.sort_order,b.id""",
                (lesson_id,),
            )
        finally:
            await db.close()
        module_options = '<option value="">Без модуля</option>' + "".join(f'<option value="{row["id"]}" {"selected" if row["id"] == lesson["module_id"] else ""}>{esc(row["title"])}</option>' for row in modules)
        block_html = "".join(self.block_card(block, lesson_id, course_id) for block in blocks) or '<div class="empty">В уроке пока нет блоков. Добавьте первый ниже.</div>'
        return web.Response(
            text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(lesson["title"])} — Nastaunik</title><script defer src="/mini-app/static/admin_course.js?v=1"></script><style>{self.styles()}</style></head><body><main>{self.tabs("courses")}<a class="back" href="{self.course_url(course_id)}">← {esc(course["title"] if course else "Курс")}</a>{'<div class="saved">Изменения сохранены</div>' if request.query.get('saved') else ''}<div class="top"><div><h1>{esc(lesson["title"])}</h1><p>Соберите урок из блоков в нужном порядке.</p></div></div><div class="course-workspace">{self.course_outline({"id": course_id, "title": course["title"] if course else "Курс"}, modules, lessons, lesson_id)}<div class="layout"><div><section><div class="section-head"><div><h2>Содержание урока</h2><div class="hint">Видео, текст, изображения и тесты можно сочетать.</div></div></div>{block_html}{self.add_block_form(lesson_id, course_id)}</section></div><aside><form class="panel sticky" method="post" action="{self.action_url}"><input type="hidden" name="action" value="course_lesson_save"><input type="hidden" name="course_id" value="{course_id}"><input type="hidden" name="lesson_id" value="{lesson_id}"><h2>Настройки урока</h2><label class="field">Название<input name="title" value="{esc(lesson["title"])}" required></label><label class="field">Краткое описание<textarea name="description">{esc(lesson["description"] or "")}</textarea></label><label class="field">Раздел<select name="module_id">{module_options}</select></label><label class="checkbox"><input type="checkbox" name="is_required" value="1" {"checked" if lesson["is_required"] else ""}><span><b>Обязательный урок</b><br><span class="hint">Учитывается в прогрессе курса.</span></span></label><button style="margin-top:15px">Сохранить урок</button></form></aside></div></div>{self.tree_script(course_id)}</main></body></html>''',
            content_type="text/html",
        )

    def block_card(self, block, lesson_id: int, course_id: int) -> str:
        from bot.learning_admin_v2 import clean_rich_text

        block_type = block["block_type"]
        settings = json.loads(block["settings_json"] or "{}") if block["settings_json"] else {}
        preview = ""
        if block_type == "video" and block["content"]:
            preview = f'<div class="block-preview"><video src="{esc(block["content"])}" controls preload="metadata"></video></div>'
        elif block_type == "image" and block["content"]:
            preview = f'<div class="block-preview"><img src="{esc(block["content"])}" alt=""></div>'
        if block_type == "longread" and block["material_id"]:
            material_title = block["material_title"] or "Лонгрид"
            material_description = block["material_description"] or "Откройте, чтобы добавить текст, обложку, теги и дополнительные файлы."
            fields = f'''<div style="padding:18px 0 8px"><h2>{esc(material_title)}</h2><p class="hint">{esc(material_description)}</p><a class="button" href="{self.course_material_url(block["material_id"], course_id, lesson_id, block["id"])}">Открыть редактор лонгрида</a></div>'''
            return f'''<article class="block-card"><span class="block-type">Лонгрид</span>{fields}<form method="post" action="{self.action_url}" style="position:absolute;right:16px;top:16px" onsubmit="return confirm('Удалить лонгрид?')"><input type="hidden" name="action" value="course_block_delete"><input type="hidden" name="course_id" value="{course_id}"><input type="hidden" name="lesson_id" value="{lesson_id}"><input type="hidden" name="block_id" value="{block["id"]}"><button class="ghost" title="Удалить блок">×</button></form></article>'''
        if block_type == "longread":
            fields = f'''<div class="course-longread"><p class="hint">Можно вставить готовый пост — абзацы, списки, ссылки и форматирование сохранятся.</p><div class="course-toolbar"><button type="button" data-cmd="undo" title="Отменить">↶</button><button type="button" data-cmd="redo" title="Повторить">↷</button><button type="button" data-cmd="bold"><b>Ж</b></button><button type="button" data-cmd="italic"><i>К</i></button><button type="button" data-cmd="formatBlock" data-value="h2">Заголовок</button><button type="button" data-cmd="formatBlock" data-value="blockquote">Цитата</button><button type="button" data-cmd="insertUnorderedList">• Список</button><button type="button" data-cmd="insertOrderedList">1. Список</button><button type="button" data-divider>Разделитель</button><button type="button" data-link>Ссылка</button><button type="button" class="media-button" data-media>＋ Фото/видео</button><input class="inline-media-file" type="file" accept=".jpg,.jpeg,.png,.webp,.gif,.mp4" hidden><button type="button" data-cmd="removeFormat">Очистить</button></div><div class="course-editor" contenteditable="true" data-placeholder="Вставьте пост из Telegram или начните писать…">{clean_rich_text(block["content"] or "")}</div><textarea class="course-editor-source" name="content" hidden></textarea><div class="editor-status"></div></div>'''
        elif block_type == "test":
            options = list(settings.get("options") or ["", "", "", ""])
            options += [""] * (4 - len(options))
            correct = int(settings.get("correct", 0))
            fields = f'<label class="field">Вопрос<textarea name="content">{esc(block["content"] or "")}</textarea></label><div class="test-options">' + "".join(f'<label class="field">Вариант {i + 1}<input name="option_{i}" value="{esc(options[i])}"></label>' for i in range(4)) + f'</div><label class="field">Правильный ответ<select name="correct_option">' + "".join(f'<option value="{i}" {"selected" if correct == i else ""}>Вариант {i + 1}</option>' for i in range(4)) + '</select></label>'
        else:
            media_name = "видео" if block_type == "video" else "изображение"
            accept = "video/mp4" if block_type == "video" else "image/*"
            fields = f'''{preview}<label class="field">Описание<textarea name="description" placeholder="Коротко опишите {media_name}">{esc(block["description"] or "")}</textarea></label><label class="file-drop"><b>＋ Заменить {media_name}</b><br><span class="hint">Выбранный файл загрузится после сохранения</span><input type="file" name="block_file" accept="{accept}"></label>'''
        form_class = "course-block-form course-file-form" if block_type in {"video", "image"} else "course-block-form"
        return f'''<article class="block-card"><span class="block-type">{esc(self.block_labels.get(block_type, block_type))}</span><form class="{form_class}" method="post" action="{self.action_url}" enctype="multipart/form-data"><input type="hidden" name="action" value="course_block_save"><input type="hidden" name="course_id" value="{course_id}"><input type="hidden" name="lesson_id" value="{lesson_id}"><input type="hidden" name="block_id" value="{block["id"]}">{fields}<div class="block-actions"><button>Сохранить</button></div></form><form method="post" action="{self.action_url}" style="position:absolute;right:16px;top:16px" onsubmit="return confirm('Удалить блок?')"><input type="hidden" name="action" value="course_block_delete"><input type="hidden" name="course_id" value="{course_id}"><input type="hidden" name="lesson_id" value="{lesson_id}"><input type="hidden" name="block_id" value="{block["id"]}"><button class="ghost" title="Удалить блок">×</button></form></article>'''

    def add_block_form(self, lesson_id: int, course_id: int) -> str:
        hidden = f'''<input type="hidden" name="action" value="course_block_add"><input type="hidden" name="course_id" value="{course_id}"><input type="hidden" name="lesson_id" value="{lesson_id}">'''
        return f'''<section class="add-block"><h3>Добавить в урок</h3><p class="hint">Выберите, что должно идти следующим.</p><div class="block-kind-tabs"><button type="button" class="active" data-add-kind="longread">Статья</button><button type="button" data-add-kind="video">Видео</button><button type="button" data-add-kind="image">Изображение</button><button type="button" data-add-kind="test">Тест</button></div><form class="block-add-form active" data-add-form="longread" method="post" action="{self.action_url}">{hidden}<input type="hidden" name="block_type" value="longread"><p>Создайте лонгрид, а затем вставьте текст или готовый пост в полноценный редактор.</p><button>＋ Создать статью</button></form><form class="block-add-form course-file-form" data-add-form="video" method="post" action="{self.action_url}" enctype="multipart/form-data">{hidden}<input type="hidden" name="block_type" value="video"><label class="file-drop"><b>＋ Выбрать видео</b><br><span class="hint">MP4</span><input type="file" name="block_file" accept="video/mp4" required></label><label class="field">Описание<textarea name="description" placeholder="Коротко опишите видео"></textarea></label><button>Загрузить видео</button></form><form class="block-add-form course-file-form" data-add-form="image" method="post" action="{self.action_url}" enctype="multipart/form-data">{hidden}<input type="hidden" name="block_type" value="image"><label class="file-drop"><b>＋ Выбрать изображение</b><input type="file" name="block_file" accept="image/*" required></label><label class="field">Описание<textarea name="description" placeholder="Коротко опишите изображение"></textarea></label><button>Загрузить изображение</button></form><form class="block-add-form" data-add-form="test" method="post" action="{self.action_url}">{hidden}<input type="hidden" name="block_type" value="test"><label class="field">Вопрос<textarea name="content" placeholder="Введите вопрос" required></textarea></label><p class="hint">Варианты ответов появятся сразу после создания.</p><button>＋ Создать тест</button></form></section>'''

    async def save_course_cover(self, db, course_id: int, upload) -> None:
        if not getattr(upload, "filename", None) or not getattr(upload, "file", None):
            return
        extension = Path(upload.filename).suffix.lower()
        if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise web.HTTPBadRequest(text="Обложка должна быть JPG, PNG или WEBP")
        self.owner.media_dir.mkdir(parents=True, exist_ok=True)
        target = self.owner.media_dir / f"course-cover-{secrets.token_urlsafe(18)}{extension}"
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        row = await (await db.execute("SELECT cover_url FROM mini_app_courses WHERE id=?", (course_id,))).fetchone()
        await db.execute("UPDATE mini_app_courses SET cover_url=? WHERE id=?", (f"/mini-app/media/{target.name}", course_id))
        old = str(row["cover_url"] or "") if row else ""
        if old.startswith("/mini-app/media/"):
            previous = self.owner.media_dir / Path(old).name
            if previous != target:
                previous.unlink(missing_ok=True)

    async def save_block_upload(self, db, upload, block_type: str) -> tuple[str | None, str | None]:
        if not getattr(upload, "filename", None) or not getattr(upload, "file", None):
            return None, None
        extension = Path(upload.filename).suffix.lower()
        allowed = {"video": {".mp4"}, "image": {".jpg", ".jpeg", ".png", ".webp", ".gif"}}
        if extension not in allowed.get(block_type, set()):
            raise web.HTTPBadRequest(text="Выберите подходящий файл")
        self.owner.media_dir.mkdir(parents=True, exist_ok=True)
        stored_name = f"course-{secrets.token_urlsafe(18)}{extension}"
        target = self.owner.media_dir / stored_name
        with target.open("wb") as output:
            shutil.copyfileobj(upload.file, output)
        await self.owner.enqueue_video(db, target)
        return f"/mini-app/media/{stored_name}", stored_name

    async def action(self, request: web.Request, form) -> web.Response:
        action = str(form.get("action") or "")
        now = datetime.utcnow().isoformat(timespec="seconds")
        course_id = int(form.get("course_id") or 0)
        lesson_id = int(form.get("lesson_id") or 0)
        material_id = 0
        inline_result = None
        db = await self.owner.connect()
        try:
            if action == "course_inline_upload":
                lesson = await (await db.execute(
                    "SELECT id FROM mini_app_course_units WHERE id=? AND course_id=?",
                    (lesson_id, course_id),
                )).fetchone()
                if not lesson:
                    raise web.HTTPNotFound(text="Урок не найден")
                url = await self.owner.save_block_file(db, form.get("inline_file"), wait_for_material_save=True)
                if not url:
                    raise web.HTTPBadRequest(text="Файл не выбран")
                inline_result = {
                    "ok": True,
                    "url": url,
                    "kind": "video" if url.lower().endswith(".mp4") else "image",
                }
            elif action == "course_save":
                title = str(form.get("title") or "").strip()
                if not title:
                    raise web.HTTPBadRequest(text="Введите название курса")
                visible = 1 if form.get("is_visible") == "1" else 0
                values = (title, str(form.get("description") or "").strip() or None, str(form.get("outcome") or "").strip() or None, str(form.get("duration_label") or "").strip() or None, visible, "published" if visible else "draft", now)
                if course_id:
                    await db.execute("UPDATE mini_app_courses SET title=?,description=?,outcome=?,duration_label=?,is_visible=?,status=?,updated_at=? WHERE id=?", (*values, course_id))
                else:
                    cur = await db.execute("INSERT INTO mini_app_courses(title,description,outcome,duration_label,is_visible,status,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,0,?,?)", (*values[:-1], now, now))
                    course_id = int(cur.lastrowid)
                await self.save_course_cover(db, course_id, form.get("cover_file"))
            elif action == "course_delete":
                if course_id:
                    rows = await self.owner.rows(db, "SELECT stored_name,material_id FROM mini_app_course_blocks b JOIN mini_app_course_units l ON l.id=b.lesson_id WHERE l.course_id=?", (course_id,))
                    cover = await (await db.execute("SELECT cover_url FROM mini_app_courses WHERE id=?", (course_id,))).fetchone()
                    await db.execute("DELETE FROM mini_app_courses WHERE id=?", (course_id,))
                    for material_id_to_delete in {row["material_id"] for row in rows if row["material_id"]}:
                        await db.execute("DELETE FROM mini_app_materials WHERE id=? AND library_visible=0", (material_id_to_delete,))
                    for row in rows:
                        if not row["stored_name"]:
                            continue
                        target = self.owner.media_dir / Path(row["stored_name"]).name
                        target.unlink(missing_ok=True)
                        if target.suffix.lower() == ".mp4":
                            target.with_name(f"{target.stem}.poster.webp").unlink(missing_ok=True)
                    if cover and str(cover["cover_url"] or "").startswith("/mini-app/media/"):
                        (self.owner.media_dir / Path(cover["cover_url"]).name).unlink(missing_ok=True)
            elif action == "course_module_add":
                title = str(form.get("title") or "").strip()
                if not course_id:
                    raise web.HTTPBadRequest(text="Курс не указан")
                if not title:
                    existing = {row["title"] for row in await self.owner.rows(db, "SELECT title FROM mini_app_course_modules WHERE course_id=?", (course_id,))}
                    number = 1
                    while f"Модуль {number}" in existing:
                        number += 1
                    title = f"Модуль {number}"
                cur = await db.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM mini_app_course_modules WHERE course_id=?", (course_id,))
                order = (await cur.fetchone())[0]
                await db.execute("INSERT INTO mini_app_course_modules(course_id,title,description,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?)", (course_id, title, str(form.get("description") or "").strip() or None, order, now, now))
            elif action == "course_module_save":
                module_id = int(form.get("module_id") or 0)
                if form.get("delete") == "1":
                    await db.execute("DELETE FROM mini_app_course_modules WHERE id=? AND course_id=?", (module_id, course_id))
                else:
                    await db.execute("UPDATE mini_app_course_modules SET title=?,description=?,updated_at=? WHERE id=? AND course_id=?", (str(form.get("title") or "").strip(), str(form.get("description") or "").strip() or None, now, module_id, course_id))
            elif action == "course_lesson_add":
                title = str(form.get("title") or "").strip()
                if not course_id:
                    raise web.HTTPBadRequest(text="Курс не указан")
                if not title:
                    existing = {row["title"] for row in await self.owner.rows(db, "SELECT title FROM mini_app_course_units WHERE course_id=?", (course_id,))}
                    number = 1
                    while f"Урок {number}" in existing:
                        number += 1
                    title = f"Урок {number}"
                module_id = int(form.get("module_id") or 0) or None
                cur = await db.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM mini_app_course_units WHERE course_id=? AND module_id IS ?", (course_id, module_id))
                order = (await cur.fetchone())[0]
                cur = await db.execute("INSERT INTO mini_app_course_units(course_id,module_id,title,is_required,sort_order,created_at,updated_at) VALUES(?,?,?,1,?,?,?)", (course_id, module_id, title, order, now, now))
                lesson_id = int(cur.lastrowid)
            elif action == "course_lesson_save":
                module_id = int(form.get("module_id") or 0) or None
                await db.execute("UPDATE mini_app_course_units SET title=?,description=?,module_id=?,is_required=?,updated_at=? WHERE id=? AND course_id=?", (str(form.get("title") or "").strip(), str(form.get("description") or "").strip() or None, module_id, 1 if form.get("is_required") == "1" else 0, now, lesson_id, course_id))
            elif action == "course_lesson_delete":
                linked_materials = await self.owner.rows(
                    db,
                    "SELECT material_id FROM mini_app_course_blocks WHERE lesson_id=? AND material_id IS NOT NULL",
                    (lesson_id,),
                )
                await db.execute("DELETE FROM mini_app_course_units WHERE id=? AND course_id=?", (lesson_id, course_id))
                for linked in linked_materials:
                    await db.execute("DELETE FROM mini_app_materials WHERE id=? AND library_visible=0", (linked["material_id"],))
            elif action == "course_tree_move":
                item_type = str(form.get("item_type") or "")
                item_id = int(form.get("item_id") or 0)
                before_id = int(form.get("before_id") or 0)
                if not course_id or not item_id or item_type not in {"lesson", "module"}:
                    raise web.HTTPBadRequest(text="Не удалось определить перемещаемый элемент")
                if item_type == "lesson":
                    item = await (await db.execute(
                        "SELECT module_id FROM mini_app_course_units WHERE id=? AND course_id=?",
                        (item_id, course_id),
                    )).fetchone()
                    if not item:
                        raise web.HTTPNotFound(text="Урок не найден")
                    old_module_id = item["module_id"]
                    target_module_id = int(form.get("target_module_id") or 0) or None
                    if target_module_id:
                        target_module = await (await db.execute(
                            "SELECT id FROM mini_app_course_modules WHERE id=? AND course_id=?",
                            (target_module_id, course_id),
                        )).fetchone()
                        if not target_module:
                            raise web.HTTPBadRequest(text="Модуль не найден")
                    target_rows = await self.owner.rows(
                        db,
                        "SELECT id FROM mini_app_course_units WHERE course_id=? AND module_id IS ? AND id<>? ORDER BY sort_order,id",
                        (course_id, target_module_id, item_id),
                    )
                    target_ids = [int(row["id"]) for row in target_rows]
                    insert_at = target_ids.index(before_id) if before_id in target_ids else len(target_ids)
                    target_ids.insert(insert_at, item_id)
                    for order, target_id in enumerate(target_ids):
                        await db.execute(
                            "UPDATE mini_app_course_units SET module_id=?,sort_order=?,updated_at=? WHERE id=? AND course_id=?",
                            (target_module_id, order, now, target_id, course_id),
                        )
                    if old_module_id != target_module_id:
                        old_rows = await self.owner.rows(
                            db,
                            "SELECT id FROM mini_app_course_units WHERE course_id=? AND module_id IS ? ORDER BY sort_order,id",
                            (course_id, old_module_id),
                        )
                        for order, row in enumerate(old_rows):
                            await db.execute(
                                "UPDATE mini_app_course_units SET sort_order=? WHERE id=? AND course_id=?",
                                (order, row["id"], course_id),
                            )
                else:
                    item = await (await db.execute(
                        "SELECT id FROM mini_app_course_modules WHERE id=? AND course_id=?",
                        (item_id, course_id),
                    )).fetchone()
                    if not item:
                        raise web.HTTPNotFound(text="Модуль не найден")
                    module_rows = await self.owner.rows(
                        db,
                        "SELECT id FROM mini_app_course_modules WHERE course_id=? AND id<>? ORDER BY sort_order,id",
                        (course_id, item_id),
                    )
                    module_ids = [int(row["id"]) for row in module_rows]
                    insert_at = module_ids.index(before_id) if before_id in module_ids else len(module_ids)
                    module_ids.insert(insert_at, item_id)
                    for order, module_id in enumerate(module_ids):
                        await db.execute(
                            "UPDATE mini_app_course_modules SET sort_order=?,updated_at=? WHERE id=? AND course_id=?",
                            (order, now, module_id, course_id),
                        )
            elif action in {"course_block_add", "course_block_save"}:
                block_id = int(form.get("block_id") or 0)
                block_type = str(form.get("block_type") or "")
                if action == "course_block_save":
                    row = await (await db.execute("SELECT block_type,content,stored_name FROM mini_app_course_blocks WHERE id=? AND lesson_id=?", (block_id, lesson_id))).fetchone()
                    if not row:
                        raise web.HTTPNotFound(text="Блок не найден")
                    block_type = row["block_type"]
                if block_type not in self.block_labels:
                    raise web.HTTPBadRequest(text="Неизвестный тип блока")
                upload_url, stored_name = await self.save_block_upload(db, form.get("block_file"), block_type)
                content = str(form.get("content") or "").strip() or None
                if block_type == "longread":
                    from bot.learning_admin_v2 import clean_rich_text

                    content = clean_rich_text(content or "").strip() or None
                settings = None
                if block_type == "test":
                    settings = json.dumps({"options": [str(form.get(f"option_{i}") or "").strip() for i in range(4)], "correct": int(form.get("correct_option") or 0)}, ensure_ascii=False)
                if action == "course_block_add":
                    if block_type in {"video", "image"} and not upload_url:
                        raise web.HTTPBadRequest(text="Выберите файл")
                    cur = await db.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM mini_app_course_blocks WHERE lesson_id=?", (lesson_id,))
                    order = (await cur.fetchone())[0]
                    if block_type == "longread":
                        count = await (await db.execute(
                            "SELECT COUNT(*) FROM mini_app_course_blocks WHERE lesson_id=? AND block_type='longread'",
                            (lesson_id,),
                        )).fetchone()
                        material_title = str(form.get("title") or "").strip() or f"Лонгрид {int(count[0]) + 1}"
                        cur = await db.execute(
                            """INSERT INTO mini_app_materials(
                                   title,short_description,full_description,is_free,library_visible,status,sort_order,created_at,updated_at
                               ) VALUES(?,?,?,0,0,'published',0,?,?)""",
                            (material_title, str(form.get("description") or "").strip() or None, content, now, now),
                        )
                        material_id = int(cur.lastrowid)
                    cur = await db.execute("INSERT INTO mini_app_course_blocks(lesson_id,block_type,title,content,description,settings_json,stored_name,material_id,sort_order,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (lesson_id, block_type, str(form.get("title") or "").strip() or None, upload_url or content, str(form.get("description") or "").strip() or None, settings, stored_name, material_id or None, order, now, now))
                    block_id = int(cur.lastrowid)
                else:
                    old_content, old_name = row["content"], row["stored_name"]
                    next_content = upload_url or old_content if block_type in {"video", "image"} else content
                    await db.execute("UPDATE mini_app_course_blocks SET title=?,content=?,description=?,settings_json=?,stored_name=?,updated_at=? WHERE id=? AND lesson_id=?", (str(form.get("title") or "").strip() or None, next_content, str(form.get("description") or "").strip() or None, settings if block_type == "test" else None, stored_name or old_name, now, block_id, lesson_id))
                    if stored_name and old_name and old_name != stored_name:
                        (self.owner.media_dir / Path(old_name).name).unlink(missing_ok=True)
                if block_type == "longread" and content:
                    await self.owner.activate_saved_videos(db, content)
            elif action == "course_block_delete":
                block_id = int(form.get("block_id") or 0)
                row = await (await db.execute("SELECT stored_name,material_id FROM mini_app_course_blocks WHERE id=? AND lesson_id=?", (block_id, lesson_id))).fetchone()
                await db.execute("DELETE FROM mini_app_course_blocks WHERE id=? AND lesson_id=?", (block_id, lesson_id))
                if row and row["material_id"]:
                    await db.execute("DELETE FROM mini_app_materials WHERE id=? AND library_visible=0", (row["material_id"],))
                if row and row["stored_name"]:
                    target = self.owner.media_dir / Path(row["stored_name"]).name
                    target.unlink(missing_ok=True)
                    if target.suffix.lower() == ".mp4":
                        target.with_name(f"{target.stem}.poster.webp").unlink(missing_ok=True)
            else:
                raise web.HTTPBadRequest(text="Неизвестное действие курса")
            await db.commit()
        finally:
            await db.close()
        if action == "course_delete":
            raise web.HTTPSeeOther(location=self.courses_url())
        if action == "course_inline_upload":
            return web.json_response(inline_result or {"ok": False}, status=200 if inline_result else 400)
        if action == "course_tree_move" and form.get("ajax") == "1":
            return web.json_response({"ok": True})
        if action == "course_block_save" and form.get("ajax") == "1":
            return web.json_response({"ok": True})
        if action == "course_block_add" and material_id:
            raise web.HTTPSeeOther(location=self.course_material_url(material_id, course_id, lesson_id, block_id))
        if action == "course_lesson_add" or action.startswith("course_block_") or action == "course_lesson_save":
            raise web.HTTPSeeOther(location=self.lesson_url(lesson_id, course_id, saved=1))
        raise web.HTTPSeeOther(location=self.course_url(course_id, saved=1))
