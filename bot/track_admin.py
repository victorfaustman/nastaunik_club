from __future__ import annotations

import json
from pathlib import Path

from aiohttp import web

from bot.course_admin import esc
from bot.tracks import LEVELS, catalog, stamp


class TrackAdmin:
    def __init__(self, owner):
        self.owner, self.db = owner, owner.schema

    def url(self, **query):
        return self.owner.url('/learning', section='tracks', **query)

    async def page(self, request):
        track_id = request.query.get('track')
        async with self.db.connect() as conn:
            tracks = [dict(r) for r in await (await conn.execute('SELECT * FROM mini_app_tracks ORDER BY sort_order,id')).fetchall()]
            materials = [dict(r) for r in await (await conn.execute("SELECT id,title FROM mini_app_materials WHERE status='published' AND library_visible=1 ORDER BY title")).fetchall()]
            courses = [dict(r) for r in await (await conn.execute("SELECT id,title FROM mini_app_courses WHERE status='published' ORDER BY sort_order,id")).fetchall()]
            steps = [dict(r) for r in await (await conn.execute('SELECT * FROM mini_app_track_steps WHERE track_id=? ORDER BY sort_order,id', (track_id,))).fetchall()]
        if track_id is None:
            cards = ''.join(f'''<article class="course-card"><div><h2>{esc(t['title'])}</h2><p>{esc(t['description'])}</p><small>{LEVELS.get(t['level'], '')} · {'Опубликован' if t['status']=='published' else 'Скрыт'}</small></div><a class="button" href="{self.url(track=t['id'])}">Открыть</a></article>''' for t in tracks)
            body = f'<div class="top"><div><h1>Треки обучения</h1><p>Соберите понятный путь из материалов и курсов клуба.</p></div><a class="button" href="{self.url(track="new")}">＋ Создать трек</a></div>{cards or "<div class=empty>Здесь будут маршруты обучения. Начните с первого трека.</div>"}'
        else:
            track = next((t for t in tracks if str(t['id']) == track_id), None)
            if track_id != 'new' and not track:
                raise web.HTTPNotFound()
            track = track or dict(id='', title='', description='', cover_url='', level='beginner', status='draft', version=0, sort_order=len(tracks))
            items = [dict(kind='material', **m) for m in materials] + [dict(kind='course', **c) for c in courses]
            selected = [dict(kind='material' if s['material_id'] else 'course', id=s['material_id'] or s['course_id']) for s in steps]
            config = json.dumps(dict(items=items, selected=selected), ensure_ascii=False).replace('<', '\\u003c')
            options = ''.join(f'<option value="{key}" {"selected" if track["level"]==key else ""}>{label}</option>' for key, label in LEVELS.items())
            preview = f'''<div class="actions"><a class="button secondary" target="_blank" href="/mini-app/preview?track={track['id']}&mode=paid">Посмотреть как оплаченный</a><a class="button secondary" target="_blank" href="/mini-app/preview?track={track['id']}&mode=unpaid">Посмотреть как неоплаченный</a></div><p class="hint">Предпросмотр показывает сохранённую версию.</p>''' if track['id'] else ''
            analytics = await self.analytics(track['id']) if track['id'] else ''
            delete_form = f'''<form method="post" action="{self.owner.course_admin.action_url}" onsubmit="return confirm('Удалить трек? Сами материалы, курсы и прогресс сохранятся.')"><input type="hidden" name="action" value="track_delete"><input type="hidden" name="track_id" value="{track['id']}"><input type="hidden" name="version" value="{track['version']}"><button class="danger">Удалить трек</button></form>''' if track['id'] else ''
            body = f'''<a class="back" href="{self.url()}">← Все треки</a><div class="top"><h1>{esc(track['title']) or 'Новый трек'}</h1></div>
            <form id="track-form" method="post" enctype="multipart/form-data" action="{self.owner.course_admin.action_url}">
              <input type="hidden" name="action" value="track_save"><input type="hidden" name="track_id" value="{track['id']}"><input type="hidden" name="version" value="{track['version']}"><input type="hidden" name="steps" id="track-steps-value">
              <div class="layout"><section class="panel"><label class="field">Название<input name="title" value="{esc(track['title'])}" required maxlength="180"></label><label class="field">Описание<textarea name="description" maxlength="3000">{esc(track['description'])}</textarea></label><h2>Путь обучения</h2><p class="hint">Добавьте готовые материалы и курсы. Перетаскивайте шаги или используйте стрелки.</p><div id="track-steps"></div><button type="button" class="secondary" id="track-add">＋ Добавить шаг</button>
              <dialog id="track-picker"><h2>Что добавить в трек?</h2><input type="search" id="track-search" placeholder="Поиск материала или курса" aria-label="Поиск"><div id="track-options"></div><button type="button" id="track-close">Готово</button></dialog></section>
              <aside class="panel"><label class="field">Уровень<select name="level">{options}</select></label><label class="field">Позиция в списке<input type="number" min="0" name="sort_order" value="{track['sort_order']}"></label>
              {f'<img class="track-cover" src="{esc(track["cover_url"])}" alt="Обложка"><label><input type="checkbox" name="remove_cover" value="1"> Убрать обложку</label>' if track['cover_url'] else ''}
              <label class="field">Обложка, необязательно<input type="file" name="cover" accept="image/jpeg,image/png,image/webp"></label><label class="checkbox"><input name="published" type="checkbox" value="1" {'checked' if track['status']=='published' else ''}>Показывать в Mini App</label><p class="hint">Доступ к каждому шагу определяется настройками самого материала или курса.</p><button type="submit">Сохранить трек</button><p id="track-save-status" role="status"></p></aside></div></form>
              {preview}{analytics}
              {delete_form}
              <script type="application/json" id="track-config">{config}</script><script src="/mini-app/static/track-admin.js?v=1" defer></script>'''
        return web.Response(text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Треки · Nastaŭnik</title><style>{self.owner.course_admin.styles()}
        .track-cover{{width:100%;aspect-ratio:16/9;object-fit:cover;border-radius:12px}}dialog{{width:min(650px,94vw);max-height:85vh;border:1px solid var(--line);border-radius:18px;padding:24px}}dialog::backdrop{{background:#20191488}}#track-options{{max-height:50vh;overflow:auto;margin:16px 0}}.track-step{{display:flex;align-items:center;gap:10px;padding:12px;border:1px solid var(--line);border-radius:12px;margin:10px 0;background:var(--paper)}}.track-step b{{flex:1;overflow-wrap:anywhere}}.track-step button{{padding:10px}}.track-option{{width:100%;text-align:left;justify-content:start;background:var(--soft);color:var(--ink);margin:4px 0}}input[type=checkbox]{{width:auto}}@media(max-width:700px){{.layout{{display:block}}.track-step{{flex-wrap:wrap}}.top{{align-items:start;flex-direction:column}}}}</style></head><body><main>{self.owner.course_admin.tabs('tracks')}{'<p class="saved">Сохранено</p>' if request.query.get('saved') else ''}{body}</main></body></html>''', content_type='text/html')

    async def analytics(self, track_id):
        async with self.db.connect() as conn:
            rows = await (await conn.execute('SELECT telegram_id,started_at FROM mini_app_track_enrollments WHERE track_id=?', (track_id,))).fetchall()
        done, total_progress, started, stops = 0, 0, 0, {}
        for row in rows:
            data = await catalog(self.db, dict(telegram_id=row['telegram_id'], state='active'), include_draft=track_id)
            track = next(t for t in data['tracks'] if t['id'] == track_id)
            done += track['completed']
            total_progress += track['progress']
            started += bool(row['started_at'])
            if row['started_at'] and track['next_step']:
                key = track['next_step']['title']
                stops[key] = stops.get(key, 0) + 1
        distribution = ''.join(f'<p>{esc(title)} — {count}</p>' for title, count in sorted(stops.items(), key=lambda x: -x[1]))
        return f'<section class="panel"><h2>Прохождение трека</h2><p>Выбрали: {len(rows)} · Начали из трека: {started} · Завершили: {done} · Средний прогресс: {round(total_progress/len(rows)) if rows else 0}%</p><h3>На каком шаге сейчас участники</h3>{distribution or "<p class=hint>Пока нет данных.</p>"}<p class="hint">Ранее пройденные материалы и курсы учитываются. Позиция — следующий непройденный шаг, а не оценка причины остановки.</p></section>'

    async def action(self, request, form):
        try:
            track_id = int(form.get('track_id') or 0)
            version = int(form.get('version') or 0)
            order = max(0, int(form.get('sort_order') or 0))
            steps = json.loads(str(form.get('steps') or '[]'))
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text='Некорректные данные трека')
        async with self.db.connect() as conn:
            await conn.execute('BEGIN IMMEDIATE')
            old = await (await conn.execute('SELECT * FROM mini_app_tracks WHERE id=?', (track_id,))).fetchone()
            if track_id and (not old or old['version'] != version):
                raise web.HTTPConflict(text='Трек уже изменён. Откройте его заново, чтобы не потерять чужие изменения.')
            if form['action'] == 'track_delete':
                await conn.execute('DELETE FROM mini_app_tracks WHERE id=?', (track_id,))
                await conn.commit()
                raise web.HTTPSeeOther(self.url())
            if form['action'] != 'track_save':
                raise web.HTTPBadRequest()
            title = str(form.get('title') or '').strip()
            description = str(form.get('description') or '').strip()
            level = str(form.get('level') or 'beginner')
            published = form.get('published') == '1'
            if not title or len(title) > 180 or len(description) > 3000 or level not in LEVELS or not isinstance(steps, list) or len(steps) > 200:
                raise web.HTTPBadRequest(text='Проверьте название, описание и шаги трека')
            keys = set()
            for step in steps:
                if not isinstance(step, dict) or step.get('kind') not in {'material', 'course'} or type(step.get('id')) is not int:
                    raise web.HTTPBadRequest(text='Некорректный шаг')
                key = (step['kind'], step['id'])
                if key in keys:
                    raise web.HTTPBadRequest(text='Один шаг не должен повторяться в треке')
                keys.add(key)
                table = 'mini_app_materials' if key[0] == 'material' else 'mini_app_courses'
                condition = ' AND library_visible=1' if key[0] == 'material' else ''
                row = await (await conn.execute(f'SELECT status FROM {table} WHERE id=?{condition}', (key[1],))).fetchone()
                if not row or (published and row['status'] != 'published'):
                    raise web.HTTPBadRequest(text='Один из шагов скрыт или удалён. Удалите его из трека перед публикацией.')
            if published and not steps:
                raise web.HTTPBadRequest(text='Добавьте хотя бы один шаг перед публикацией')
            cover_url = '' if form.get('remove_cover') else (old['cover_url'] if old else '')
            cover = form.get('cover')
            if isinstance(cover, web.FileField) and cover.filename:
                if Path(cover.filename).suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp'}:
                    raise web.HTTPBadRequest(text='Обложка должна быть JPG, PNG или WEBP')
                cover.file.seek(0, 2)
                if cover.file.tell() > 10*1024*1024:
                    raise web.HTTPBadRequest(text='Обложка должна быть меньше 10 МБ')
                cover.file.seek(0)
                cover_url = await self.owner.save_block_file(conn, cover)
            fields = (title, description, cover_url, level, 'published' if published else 'draft', order, stamp())
            if old:
                await conn.execute('UPDATE mini_app_tracks SET title=?,description=?,cover_url=?,level=?,status=?,sort_order=?,updated_at=?,version=version+1 WHERE id=?', (*fields, track_id))
            else:
                cur = await conn.execute('INSERT INTO mini_app_tracks(title,description,cover_url,level,status,sort_order,updated_at,created_at) VALUES(?,?,?,?,?,?,?,?)', (*fields, stamp()))
                track_id = cur.lastrowid
            # Keep stable step IDs when rearranging an existing track.
            old_steps = await (await conn.execute('SELECT * FROM mini_app_track_steps WHERE track_id=?', (track_id,))).fetchall()
            for s in old_steps:
                key = ('material', s['material_id']) if s['material_id'] else ('course', s['course_id'])
                if key not in keys:
                    await conn.execute('DELETE FROM mini_app_track_steps WHERE id=?', (s['id'],))
            for i, s in enumerate(steps):
                column = 'material_id' if s['kind'] == 'material' else 'course_id'
                await conn.execute(f'INSERT INTO mini_app_track_steps(track_id,{column},sort_order) VALUES(?,?,?) ON CONFLICT(track_id,{column}) DO UPDATE SET sort_order=excluded.sort_order', (track_id, s['id'], i))
            await conn.commit()
        raise web.HTTPSeeOther(self.url(track=track_id, saved=1))
