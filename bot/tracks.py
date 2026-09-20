"""Learning routes reuse library content and progress; never grant content access."""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from aiohttp import web

log = logging.getLogger(__name__)
LEVELS = {'beginner': 'Для начинающих', 'practice': 'Практика', 'advanced': 'Продвинутый'}
TEMPOS = {'calm': 1, 'regular': 2, 'intensive': 4}
DEFAULT_PREFS = dict(active_track_id=None, tempo='regular', reminders=False,
                     days=[1, 3], local_time='19:00', timezone='Europe/Minsk', snooze_until=None)
SCHEMA = """
CREATE TABLE IF NOT EXISTS mini_app_tracks(
 id INTEGER PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 cover_url TEXT NOT NULL DEFAULT '', level TEXT NOT NULL DEFAULT 'beginner',
 status TEXT NOT NULL DEFAULT 'draft', sort_order INTEGER NOT NULL DEFAULT 0,
 version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mini_app_track_steps(
 id INTEGER PRIMARY KEY, track_id INTEGER NOT NULL REFERENCES mini_app_tracks(id) ON DELETE CASCADE,
 material_id INTEGER REFERENCES mini_app_materials(id) ON DELETE CASCADE,
 course_id INTEGER REFERENCES mini_app_courses(id) ON DELETE CASCADE,
 sort_order INTEGER NOT NULL,
 CHECK((material_id IS NOT NULL)+(course_id IS NOT NULL)=1),
 UNIQUE(track_id,material_id), UNIQUE(track_id,course_id));
CREATE TABLE IF NOT EXISTS mini_app_track_preferences(
 telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
 active_track_id INTEGER REFERENCES mini_app_tracks(id) ON DELETE SET NULL,
 tempo TEXT NOT NULL DEFAULT 'regular', reminders INTEGER NOT NULL DEFAULT 0,
 days TEXT NOT NULL DEFAULT '[1,3]', local_time TEXT NOT NULL DEFAULT '19:00',
 timezone TEXT NOT NULL DEFAULT 'Europe/Minsk', snooze_until TEXT, last_activity TEXT,
 updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mini_app_track_enrollments(
 telegram_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
 track_id INTEGER NOT NULL REFERENCES mini_app_tracks(id) ON DELETE CASCADE,
 selected_at TEXT NOT NULL, started_at TEXT, PRIMARY KEY(telegram_id,track_id));
CREATE TABLE IF NOT EXISTS mini_app_track_reminders(
 telegram_id INTEGER NOT NULL REFERENCES users(telegram_id) ON DELETE CASCADE,
 local_date TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(telegram_id,local_date));
"""


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


async def preferences(db, uid):
    async with db.connect() as conn:
        row = await (await conn.execute('SELECT * FROM mini_app_track_preferences WHERE telegram_id=?', (uid,))).fetchone()
    if not row:
        return dict(DEFAULT_PREFS)
    result = dict(row)
    result['days'] = json.loads(result['days'])
    result['reminders'] = bool(result['reminders'])
    return result


async def catalog(db, user, *, include_draft=None):
    """Return only public metadata, never lesson bodies or protected media URLs."""
    from bot.learning import _course_progress
    uid = 0 if user.get('test_mode') else int(user['telegram_id'])
    async with db.connect() as conn:
        tracks = [dict(r) for r in await (await conn.execute(
            "SELECT * FROM mini_app_tracks WHERE status='published' OR id=? ORDER BY sort_order,id", (include_draft,))).fetchall()]
        rows = await (await conn.execute("""SELECT s.*,m.title mt,m.status ms,m.library_visible,
            m.is_free mf,c.title ct,c.status cs,c.is_free cf FROM mini_app_track_steps s
            LEFT JOIN mini_app_materials m ON m.id=s.material_id
            LEFT JOIN mini_app_courses c ON c.id=s.course_id ORDER BY s.sort_order,s.id""")).fetchall()
        viewed = {r[0] for r in await (await conn.execute(
            'SELECT material_id FROM mini_app_material_views WHERE telegram_id=? AND completed_at IS NOT NULL', (uid,))).fetchall()}
        done = {r[0] for r in await (await conn.execute(
            'SELECT lesson_id FROM mini_app_course_unit_progress WHERE telegram_id=? AND completed_at IS NOT NULL', (uid,))).fetchall()}
        units = [dict(r) for r in await (await conn.execute('SELECT id,course_id,is_required FROM mini_app_course_units')).fetchall()]
    by_track = {}
    for row in rows:
        material = row['material_id'] is not None
        available = (row['ms'] == 'published' and row['library_visible']) if material else row['cs'] == 'published'
        completed = row['material_id'] in viewed if material else _course_progress([u for u in units if u['course_id'] == row['course_id']], done)['completed']
        by_track.setdefault(row['track_id'], []).append(dict(
            id=row['id'], kind='material' if material else 'course',
            item_id=row['material_id'] if material else row['course_id'],
            title=(row['mt'] if material else row['ct']) if available or include_draft else 'Шаг временно недоступен',
            unavailable=not bool(available), completed=bool(completed),
            locked=not bool(available) or (user.get('state') != 'active' and not (row['mf'] if material else row['cf']))))
    for track in tracks:
        steps = by_track.get(track['id'], [])
        track['steps'] = steps
        track['completed_count'] = sum(s['completed'] for s in steps)
        track['step_count'] = len(steps)
        track['completed'] = bool(steps) and all(s['completed'] for s in steps)
        track['progress'] = round(track['completed_count'] / len(steps) * 100) if steps else 0
        track['next_step'] = next((s for s in steps if not s['completed']), None)
    return dict(tracks=tracks, preferences=await preferences(db, uid))


def validate_preferences(data):
    if data.get('tempo') not in TEMPOS:
        raise ValueError('Выберите темп обучения')
    days = data.get('days')
    if not isinstance(days, list) or any(type(d) is not int or not 0 <= d <= 6 for d in days):
        raise ValueError('Выберите дни недели')
    days = sorted(set(days))
    if len(days) > TEMPOS[data['tempo']] or (data.get('reminders') and not days):
        raise ValueError('Количество дней должно соответствовать выбранному темпу')
    time = str(data.get('local_time', ''))
    if len(time) != 5 or datetime.strptime(time, '%H:%M').strftime('%H:%M') != time:
        raise ValueError('Укажите время в формате ЧЧ:ММ')
    zone = str(data.get('timezone', ''))
    try:
        ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError('Выберите часовой пояс')
    return dict(tempo=data['tempo'], days=days, local_time=time, timezone=zone, reminders=data.get('reminders') is True)


class Tracks:
    def __init__(self, mini):
        self.mini, self.db = mini, mini.db

    def register(self, app):
        app.router.add_get('/mini-app/api/tracks', self.get)
        app.router.add_post('/mini-app/api/tracks/preferences', self.save)
        app.router.add_post('/mini-app/api/tracks/{track_id}/select', self.select)
        app.router.add_post('/mini-app/api/tracks/{track_id}/activity', self.activity)
        app.cleanup_ctx.append(self.context)

    async def get(self, request):
        _, _, user = await self.mini.authorised(request)
        return web.json_response(await catalog(self.db, user))

    async def select(self, request):
        _, _, user = await self.mini.authorised(request)
        try:
            track_id = int(request.match_info['track_id'])
        except ValueError:
            raise web.HTTPNotFound()
        async with self.db.connect() as conn:
            await conn.execute('BEGIN IMMEDIATE')
            row = await (await conn.execute("SELECT id FROM mini_app_tracks WHERE id=? AND status='published' AND EXISTS(SELECT 1 FROM mini_app_track_steps WHERE track_id=?)", (track_id, track_id))).fetchone()
            if not row:
                raise web.HTTPNotFound(text='Трек пока недоступен')
            if not user.get('test_mode'):
                await conn.execute('INSERT OR IGNORE INTO mini_app_track_enrollments(telegram_id,track_id,selected_at) VALUES(?,?,?)', (user['telegram_id'], track_id, stamp()))
                await conn.execute('''INSERT INTO mini_app_track_preferences(telegram_id,active_track_id,updated_at,last_activity)
                    VALUES(?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET active_track_id=excluded.active_track_id,
                    last_activity=excluded.last_activity,updated_at=excluded.updated_at''', (user['telegram_id'], track_id, stamp(), stamp()))
                await conn.commit()
        return web.json_response({'ok': True, 'active_track_id': track_id})

    async def activity(self, request):
        _, _, user = await self.mini.authorised(request)
        try:
            track_id = int(request.match_info['track_id'])
        except ValueError:
            raise web.HTTPNotFound()
        if not user.get('test_mode'):
            async with self.db.connect() as conn:
                await conn.execute('UPDATE mini_app_track_enrollments SET started_at=COALESCE(started_at,?) WHERE telegram_id=? AND track_id=?', (stamp(), user['telegram_id'], track_id))
                await conn.execute('UPDATE mini_app_track_preferences SET last_activity=? WHERE telegram_id=?', (stamp(), user['telegram_id']))
                await conn.commit()
        return web.json_response({'ok': True})

    async def save(self, request):
        _, _, user = await self.mini.authorised(request)
        try:
            data = await request.json()
            p = validate_preferences(data)
        except (ValueError, TypeError, AttributeError) as exc:
            raise web.HTTPBadRequest(text=str(exc))
        snooze = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat() if data.get('snooze') else None
        if not user.get('test_mode'):
            async with self.db.connect() as conn:
                await conn.execute('''INSERT INTO mini_app_track_preferences(telegram_id,tempo,reminders,days,local_time,timezone,snooze_until,updated_at)
                    VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(telegram_id) DO UPDATE SET tempo=excluded.tempo,
                    reminders=excluded.reminders,days=excluded.days,local_time=excluded.local_time,
                    timezone=excluded.timezone,snooze_until=excluded.snooze_until,updated_at=excluded.updated_at''',
                    (user['telegram_id'], p['tempo'], p['reminders'], json.dumps(p['days']), p['local_time'], p['timezone'], snooze, stamp()))
                await conn.commit()
        return web.json_response({'ok': True, 'preferences': {**p, 'snooze_until': snooze}})

    async def context(self, app):
        task = asyncio.create_task(self.worker())
        yield
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    async def worker(self):
        from aiogram import Bot
        if not self.mini.bot_token:
            return
        bot = Bot(self.mini.bot_token)
        try:
            while True:
                try:
                    await self.deliver(bot)
                except Exception:
                    log.exception('Track reminder cycle failed')
                await asyncio.sleep(30)
        finally:
            await bot.session.close()

    async def deliver(self, bot, now=None):
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        from bot.mini_app import access_state
        now = now or datetime.now(timezone.utc)
        async with self.db.connect() as conn:
            rows = [dict(r) for r in await (await conn.execute('SELECT * FROM mini_app_track_preferences WHERE reminders=1 AND active_track_id IS NOT NULL')).fetchall()]
        for p in rows:
            local = now.astimezone(ZoneInfo(p['timezone']))
            scheduled = local.replace(hour=int(p['local_time'][:2]), minute=int(p['local_time'][3:]), second=0, microsecond=0)
            if local.weekday() not in json.loads(p['days']) or not 0 <= (local - scheduled).total_seconds() < 600:
                continue  # Never backfill missed slots after a restart.
            if p['snooze_until'] and datetime.fromisoformat(p['snooze_until']) > now:
                continue
            if p['last_activity'] and now - datetime.fromisoformat(p['last_activity']) < timedelta(hours=6):
                continue
            record = await self.db.get_user(p['telegram_id'])
            data = await catalog(self.db, dict(telegram_id=p['telegram_id'], state=access_state(record)))
            track = next((t for t in data['tracks'] if t['id'] == p['active_track_id']), None)
            step = track['next_step'] if track else None
            if not step or step['locked']:
                continue
            async with self.db.connect() as conn:
                # Reserve before delivery: concurrent workers/restarts cannot send twice.
                cur = await conn.execute('''INSERT OR IGNORE INTO mini_app_track_reminders(telegram_id,local_date,status,created_at)
                    SELECT ?,?,'reserved',? WHERE EXISTS(SELECT 1 FROM mini_app_track_preferences WHERE telegram_id=? AND reminders=1 AND active_track_id=? AND updated_at=?)''',
                    (p['telegram_id'], local.date().isoformat(), now.isoformat(), p['telegram_id'], p['active_track_id'], p['updated_at']))
                await conn.commit()
                if not cur.rowcount:
                    continue
            status = 'sent'
            try:
                me = await bot.get_me()
                link = f'https://t.me/{me.username}?startapp='
                await bot.send_message(p['telegram_id'], f"Небольшой шаг в своём темпе ◇\n\n{track['title']}\nСледующий шаг: {step['title']}\n\nПродолжим?",
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text='Открыть шаг', url=link+f"track_step_{track['id']}")],
                        [InlineKeyboardButton(text='Позже', url=link+'track_snooze'), InlineKeyboardButton(text='Отключить напоминания', url=link+'track_reminders_off')]]))
            except Exception as exc:
                from aiogram.exceptions import TelegramForbiddenError
                status = 'failed'
                log.warning('Track reminder delivery failed: %s', type(exc).__name__)
                if isinstance(exc, TelegramForbiddenError):
                    async with self.db.connect() as conn:
                        await conn.execute('UPDATE mini_app_track_preferences SET reminders=0 WHERE telegram_id=?', (p['telegram_id'],))
                        await conn.commit()
            async with self.db.connect() as conn:
                await conn.execute('UPDATE mini_app_track_reminders SET status=? WHERE telegram_id=? AND local_date=?', (status, p['telegram_id'], local.date().isoformat()))
                await conn.execute("DELETE FROM mini_app_track_reminders WHERE created_at<?", ((now-timedelta(days=90)).isoformat(),))
                await conn.commit()
