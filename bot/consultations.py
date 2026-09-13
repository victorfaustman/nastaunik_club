"""Consultation slots shared by the Mini App and learning admin."""
import sqlite3
from datetime import datetime, timedelta
from html import escape
from zoneinfo import ZoneInfo

from aiohttp import web

MINSK = ZoneInfo('Europe/Minsk')
TIMES = ('19:30', '20:00', '20:30')


class Consultations:
    def __init__(self, db, mini_app=None):
        self.db, self.app = db, mini_app

    async def initialize(self):
        async with self.db.connect() as conn:
            await conn.executescript('''
                CREATE TABLE IF NOT EXISTS consultation_bookings (
                    id INTEGER PRIMARY KEY, telegram_id INTEGER NOT NULL REFERENCES users(telegram_id),
                    starts_at TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'booked', created_at TEXT NOT NULL,
                    cancelled_at TEXT, cancelled_by TEXT
                );
                CREATE UNIQUE INDEX IF NOT EXISTS consultation_slot_unique
                    ON consultation_bookings(starts_at) WHERE status='booked';
            ''')
            await conn.commit()

    async def context(self, app):
        await self.initialize()
        yield

    def slots(self):
        now = datetime.now(MINSK)
        result = []
        for offset in range(42):
            day = now.date() + timedelta(days=offset)
            if day.weekday() not in (1, 3):
                continue
            for time in TIMES:
                start = datetime.fromisoformat(f'{day}T{time}:00').replace(tzinfo=MINSK)
                if start > now:
                    result.append(start.isoformat())
        return result

    async def member(self, request, writing=False):
        _, record, user = await self.app.authorised(request)
        if user.get('state') != 'active' or (record.current_status == 'trial_active' and not user.get('is_lifetime_free')):
            raise web.HTTPForbidden(text='Консультации доступны участникам с оплаченной подпиской.')
        if writing and user.get('test_mode'):
            raise web.HTTPForbidden(text='В тестовом режиме настоящая запись отключена.')
        return user

    async def schedule(self, request):
        _, record, user = await self.app.authorised(request)
        paid = user.get('state') == 'active' and (record.current_status != 'trial_active' or user.get('is_lifetime_free'))
        async with self.db.connect() as conn:
            rows = await (await conn.execute("SELECT id,telegram_id,starts_at,topic FROM consultation_bookings WHERE status='booked' AND starts_at>? ORDER BY starts_at", (datetime.now(MINSK).isoformat(),))).fetchall()
        occupied = {r['starts_at'] for r in rows}
        return web.json_response({'timezone':'Europe/Minsk', 'paid_access':paid, 'slots':[{'starts_at':s, 'available':s not in occupied} for s in self.slots()] if paid else [], 'bookings':[dict(r) for r in rows if r['telegram_id']==user['telegram_id'] and not user.get('test_mode')], 'test_mode':bool(user.get('test_mode'))}, headers={'Cache-Control':'no-store'})

    async def book(self, request):
        user = await self.member(request, writing=True)
        try:
            data = await request.json()
        except ValueError:
            raise web.HTTPBadRequest(text='Некорректная заявка.')
        if not isinstance(data, dict):
            raise web.HTTPBadRequest(text='Некорректная заявка.')
        start, topic = str(data.get('starts_at', '')), str(data.get('topic', '')).strip()
        if start not in self.slots():
            raise web.HTTPBadRequest(text='Выберите доступную будущую дату и время.')
        if len(topic) > 2000:
            raise web.HTTPBadRequest(text='Тема должна быть не длиннее 2000 символов.')
        async with self.db.connect() as conn:
            try:
                cur = await conn.execute('INSERT INTO consultation_bookings(telegram_id,starts_at,topic,created_at) VALUES(?,?,?,?)', (user['telegram_id'], start, topic, datetime.now(MINSK).isoformat()))
                await conn.commit()
            except sqlite3.IntegrityError:
                raise web.HTTPConflict(text='Это время уже занято. Выберите другой слот.')
        return web.json_response({'ok':True, 'id':cur.lastrowid})

    async def cancel(self, request):
        _, record, user = await self.app.authorised(request)
        if user.get('test_mode'):
            raise web.HTTPForbidden(text='В тестовом режиме отмена настоящих записей отключена.')
        async with self.db.connect() as conn:
            cur = await conn.execute("UPDATE consultation_bookings SET status='cancelled',cancelled_at=?,cancelled_by='member' WHERE id=? AND telegram_id=? AND status='booked' AND starts_at>?", (datetime.now(MINSK).isoformat(), request.match_info['booking_id'], user['telegram_id'], datetime.now(MINSK).isoformat()))
            await conn.commit()
        if not cur.rowcount:
            raise web.HTTPNotFound(text='Активная запись не найдена.')
        return web.json_response({'ok':True})

    async def admin_page(self, owner, request):
        await self.initialize()
        mode = request.query.get('view', 'upcoming')
        condition = "b.status='booked' AND b.starts_at>=?" if mode=='upcoming' else "(b.status='cancelled' OR b.starts_at<?)"
        async with self.db.connect() as conn:
            rows = await (await conn.execute(f'SELECT b.*,u.full_name,u.username FROM consultation_bookings b JOIN users u ON u.telegram_id=b.telegram_id WHERE {condition} ORDER BY b.starts_at DESC' if mode!='upcoming' else f'SELECT b.*,u.full_name,u.username FROM consultation_bookings b JOIN users u ON u.telegram_id=b.telegram_id WHERE {condition} ORDER BY b.starts_at', (datetime.now(MINSK).isoformat(),))).fetchall()
        cards = ''
        for row in rows:
            start = datetime.fromisoformat(row['starts_at'])
            contact = f'<a href="https://t.me/{escape(row["username"])}">@{escape(row["username"])}</a>' if row['username'] else f'Telegram ID: {row["telegram_id"]}'
            action = f'<form method="post" action="{escape(owner.url("/learning/action"))}" onsubmit="return confirm(\'Отменить запись?\')"><input type="hidden" name="action" value="consultation_cancel"><input type="hidden" name="booking_id" value="{row["id"]}"><button>Отменить запись</button></form>' if mode=='upcoming' else '<p>Отменена</p>' if row['status']=='cancelled' else '<p>Прошедшая консультация</p>'
            cards += f'<section class="panel"><h2>{start:%d.%m.%Y · %H:%M}–{start+timedelta(minutes=30):%H:%M}</h2><h3>{escape(row["full_name"])}</h3><p>{contact}</p><p style="white-space:pre-wrap;overflow-wrap:anywhere">{escape(row["topic"] or "Тема не указана")}</p>{action}</section>'
        return web.Response(text=f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Консультации</title><style>{owner.course_admin.styles()}</style><body><main>{owner.course_admin.tabs("consultations")}<h1>Консультации</h1><p>Вторник и четверг · 19:30–21:00 · время Минска. Длительность — 30 минут.</p><p><a href="{escape(owner.url("/learning",section="consultations"))}">Предстоящие</a> · <a href="{escape(owner.url("/learning",section="consultations",view="history"))}">История и отменённые</a></p>{cards or "<p>Записей пока нет.</p>"}</main></body></html>', content_type='text/html')

    async def admin_cancel(self, owner, form):
        await self.initialize()
        async with self.db.connect() as conn:
            await conn.execute("UPDATE consultation_bookings SET status='cancelled',cancelled_at=?,cancelled_by='admin' WHERE id=? AND status='booked' AND starts_at>?", (datetime.now(MINSK).isoformat(), str(form.get('booking_id','')), datetime.now(MINSK).isoformat()))
            await conn.commit()
        raise web.HTTPSeeOther(owner.url('/learning', section='consultations'))
