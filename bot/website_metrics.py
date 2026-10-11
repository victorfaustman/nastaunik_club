"""Anonymous website visits, independent of learning progress and Telegram IDs."""
import hashlib
import hmac
import re
from datetime import datetime, timedelta
from html import escape
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from aiohttp import web

SCHEMA = '''CREATE TABLE IF NOT EXISTS website_page_events (
 day TEXT NOT NULL, visit TEXT NOT NULL, event TEXT NOT NULL,
 path TEXT NOT NULL, source TEXT NOT NULL,
 PRIMARY KEY(day,visit,event));
 CREATE INDEX IF NOT EXISTS website_page_events_day ON website_page_events(day);'''
PATH = re.compile(r'^(?:/|/(?:library|tracks|consultations|profile|support|rules|privacy)|/(?:material|course|track)/[1-9][0-9]*(?:/lesson/[1-9][0-9]*)?)$')
TOKEN = re.compile(r'^[a-f0-9]{32}$')


async def initialize(db):
    async with db.connect() as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


def today():
    return datetime.now(ZoneInfo('Europe/Minsk')).date()


class WebsiteMetrics:
    def __init__(self, site):
        self.site = site
        self.db = site.mini.db

    def register(self, app):
        app.router.add_post('/site/metrics', self.collect)
        app.on_startup.append(self.startup)

    async def startup(self, app):
        await initialize(self.db)

    async def collect(self, request):
        if request.headers.get('Origin') != self.site.auth.origin:
            raise web.HTTPForbidden()
        if request.content_length is None or request.content_length > 2048:
            raise web.HTTPBadRequest()
        if request.headers.get('DNT') == '1' or request.headers.get('Sec-GPC') == '1' or re.search(r'bot|crawler|spider|headless', request.headers.get('User-Agent', ''), re.I):
            return web.Response(status=204)
        try:
            data = await request.json()
        except (ValueError, UnicodeError):
            raise web.HTTPBadRequest()
        if not isinstance(data, dict):
            raise web.HTTPBadRequest()
        if not all(isinstance(data.get(k), str) and TOKEN.fullmatch(data[k]) for k in ('visit', 'event')):
            raise web.HTTPBadRequest()
        path = data.get('path')
        if not isinstance(path, str) or not PATH.fullmatch(path):
            raise web.HTTPBadRequest()
        referrer = data.get('source', '')
        if not isinstance(referrer, str) or len(referrer) > 1024:
            raise web.HTTPBadRequest()
        try:
            url = urlsplit(referrer)
            source = (url.hostname or '').lower() if url.scheme in ('https', 'http') else ''
        except ValueError:
            source = ''
        if source == urlsplit(self.site.auth.origin).hostname or not re.fullmatch(r'[a-z0-9.-]{1,253}', source):
            source = 'direct'
        day = today().isoformat()
        visit = hmac.new(self.site.mini.bot_token.encode(), (day + ':' + data['visit']).encode(), hashlib.sha256).hexdigest()
        async with self.db.connect() as conn:
            await conn.execute('BEGIN IMMEDIATE')
            await conn.execute('DELETE FROM website_page_events WHERE day < ?', ((today() - timedelta(days=89)).isoformat(),))
            count = (await (await conn.execute('SELECT COUNT(*) FROM website_page_events WHERE day=? AND visit=?', (day, visit))).fetchone())[0]
            if count < 500:
                await conn.execute('INSERT OR IGNORE INTO website_page_events VALUES(?,?,?,?,?)', (day, visit, data['event'], path, source))
            await conn.commit()
        return web.Response(status=204)


async def admin_page(owner, request):
    await initialize(owner.schema)
    days = request.query.get('days', '7')
    days = int(days) if days in {'1', '7', '30', '90'} else 7
    start = (today() - timedelta(days=days - 1)).isoformat()
    async with owner.schema.connect() as conn:
        total = await (await conn.execute('SELECT COUNT(*) FROM website_page_events WHERE day>=?', (start,))).fetchone()
        visits = await (await conn.execute('SELECT COUNT(*) FROM (SELECT day,visit FROM website_page_events WHERE day>=? GROUP BY day,visit)', (start,))).fetchone()
        daily = await (await conn.execute('SELECT day,COUNT(DISTINCT visit),COUNT(*) FROM website_page_events WHERE day>=? GROUP BY day ORDER BY day DESC', (start,))).fetchall()
        pages = await (await conn.execute('SELECT path,COUNT(*) FROM website_page_events WHERE day>=? GROUP BY path ORDER BY COUNT(*) DESC,path LIMIT 30', (start,))).fetchall()
        sources = await (await conn.execute('SELECT source,COUNT(*) FROM website_page_events WHERE rowid IN (SELECT MIN(rowid) FROM website_page_events WHERE day>=? GROUP BY day,visit) GROUP BY source ORDER BY COUNT(*) DESC,source', (start,))).fetchall()
        first = (await (await conn.execute('SELECT MIN(day) FROM website_page_events')).fetchone())[0]
    def table(headers, rows):
        return '<div class="table"><table><thead><tr>' + ''.join('<th>'+escape(h)+'</th>' for h in headers) + '</tr></thead><tbody>' + (''.join('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in row)+'</tr>' for row in rows) or '<tr><td colspan="3">Пока нет данных.</td></tr>') + '</tbody></table></div>'
    filters = ''.join(f'<a class="period {"active" if n == days else ""}" href="{escape(owner.url("/learning", section="visitors", days=n), quote=True)}">{label}</a>' for n,label in [(1,'Сегодня'),(7,'7 дней'),(30,'30 дней'),(90,'90 дней')])
    return web.Response(text=f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex"><title>Посещаемость — Nastaŭnik</title><style>
    *{{box-sizing:border-box}}body{{margin:0;background:#f7f5f0;color:#302924;font:16px/1.5 system-ui}}main{{max-width:1040px;margin:auto;padding:24px 16px}}a{{color:#854332}}nav,.periods{{display:flex;flex-wrap:wrap;gap:10px;margin:20px 0}}nav a,.period{{padding:10px;border-radius:10px}}.active{{background:#854332;color:white}}h1{{font:36px Georgia}}.summary{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}.metric,.table{{background:white;border:1px solid #e5ddd3;border-radius:16px;padding:16px}}.metric b{{display:block;font-size:32px}}.table{{overflow:auto}}table{{border-collapse:collapse;width:100%}}th,td{{padding:10px;text-align:left;border-bottom:1px solid #e5ddd3;overflow-wrap:anywhere}}p{{color:#6e625a}}@media(max-width:500px){{th,td{{padding:8px;font-size:14px}}}}
    </style></head><body><main><nav><a href="{escape(owner.url('/learning'), quote=True)}">← Материалы</a><a href="{escape(owner.url('/learning',section='courses'), quote=True)}">Курсы</a></nav><h1>Посещаемость сайта</h1><div class="periods">{filters}</div><div class="summary"><div class="metric"><b>{visits[0]}</b>визитов</div><div class="metric"><b>{total[0]}</b>просмотров страниц</div></div><p>Визит — открытие сайта в одной вкладке браузера за день. Это не число уникальных людей: разные вкладки и устройства могут считаться отдельно. Данные за последние 90 дней, даты по Минску. Начало сбора: {escape(first or 'данных пока нет')}. Прошлые посещения восстановить нельзя.</p><h2>По дням</h2>{table(['Дата','Визиты','Просмотры'],daily)}<h2>Популярные страницы</h2>{table(['Страница','Просмотры'],pages)}<h2>Источники визитов</h2>{table(['Источник','Визиты'],[(('Прямой / источник не определён' if r[0]=='direct' else r[0]),r[1]) for r in sources])}<p>Счётчик не сохраняет IP, Telegram ID, содержимое страниц или параметры ссылок. Боты, админка и Mini App не учитываются. Блокировщики, DNT и запрет хранилища могут уменьшать показатели. Источник определяется браузером и может быть неизвестен.</p></main></body></html>''', content_type='text/html', headers={'Cache-Control':'no-store'})
