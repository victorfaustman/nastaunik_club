"""CRM presentation and read models, shared by local and production applications."""
import asyncio
import csv
import html
import io
import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aiohttp import web

ASSETS = Path(__file__).with_name('assets') / 'crm'
MONTHS = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь', 'Июль', 'Август', 'Сентябрь', 'Октябрь', 'Ноябрь', 'Декабрь']
STATES = {'any':'Все статусы', 'new':'Новый', 'waiting_payment':'Ожидает чек', 'waiting_confirmation':'Чек на проверке',
          'in_club':'Есть доступ', 'not_in_club':'Нет доступа', 'expired':'Доступ истёк', 'expiring':'Скоро истекает', 'rejected':'Чек отклонён'}
TYPES = {'any':'Все категории', 'regular':'Обычные', 'special_any':'Все особые', 'special_rate':'Особый тариф', 'free':'Вечные бесплатные',
         'foreign':'Не из РБ · все', 'foreign_pending':'Не из РБ · на проверке', 'foreign_approved':'Не из РБ · одобрены', 'foreign_rejected':'Не из РБ · отказ'}
STATUS_TEXT = {'active':'Доступ активен', 'grace_period':'Ожидает продления', 'expired':'Доступ истёк',
               'new':'Новый', 'waiting_payment':'Ожидает чек', 'waiting_confirmation':'Чек на проверке', 'rejected':'Чек отклонён', 'trial_active':'Пробный доступ'}


def e(value):
    return html.escape(str(value if value is not None else ''), quote=True)


def amount(value):
    match = re.search(r'\d+(?:[.,]\d+)?', str(value or ''))
    return Decimal(match.group().replace(',', '.')) if match else Decimal('0')


def money(value):
    return f'{Decimal(value):,.2f}'.replace(',', ' ').replace('.', ',') + ' BYN'


def date(value, time=False):
    if not value:
        return '—'
    try:
        return datetime.fromisoformat(str(value)).strftime('%d.%m.%Y %H:%M' if time else '%d.%m.%Y')
    except ValueError:
        return '—'


def options(items, selected):
    return ''.join(f'<option value="{e(k)}" {"selected" if str(k)==str(selected) else ""}>{e(v)}</option>' for k,v in items.items())


def field(label, name, items, selected):
    return f'<label class="field"><span>{e(label)}</span><select name="{e(name)}">{options(items,selected)}</select></label>'


def active(row):
    return bool(row.get('is_lifetime_free')) or row['current_status'] in ('active','grace_period')


def category(row):
    labels = []
    if row.get('foreign_status'):
        state = {'pending':'на проверке','approved':'одобрено','rejected':'отказ'}.get(row['foreign_status'],'')
        labels.append('Не из РБ · ' + state)
    if row.get('is_lifetime_free'):
        labels.append('Вечный бесплатный')
    elif row.get('recurring_amount_label') and row['recurring_amount_label'] != '10 BYN / месяц':
        labels.append(row['recurring_amount_label'])
    return ' · '.join(labels)


def badge(row):
    status = row['current_status']
    color = 'good' if active(row) else 'danger' if status in ('expired','rejected') else 'muted'
    if status in ('waiting_confirmation','grace_period'):
        color = 'amber'
    return f'<span class="pill {color}">{e(STATUS_TEXT.get(status,status))}</span>'


def period(query, now=None):
    """Independent month/year selectors; explicit dates take precedence."""
    now = now or datetime.utcnow()
    mode = query.get('mode', 'month')
    month = query.get('month', f'{now.month:02}' if mode=='month' else '')
    year = query.get('year', str(now.year) if mode in ('month','year') else '')
    if re.fullmatch(r'\d{4}-\d{2}', month):
        year, month = year or month[:4], month[5:]
    try:
        m = int(month) if month else None
        y = int(year) if year else None
        if (m is not None and not 1 <= m <= 12) or (y is not None and not 1900 <= y <= 9998):
            raise ValueError()
        start = datetime.fromisoformat(query['from']) if query.get('from') else None
        end = datetime.fromisoformat(query['to']) + timedelta(days=1) if query.get('to') else None
        if start and end and start >= end:
            raise ValueError()
    except (ValueError, TypeError):
        raise web.HTTPBadRequest(text='Проверьте период: начальная дата должна быть не позже конечной.')
    day = now.replace(hour=0,minute=0,second=0,microsecond=0)
    if start or end:
        m=y=None
    elif mode=='today':
        start,end=day,day+timedelta(days=1); m=y=None
    elif mode=='week':
        start,end=day-timedelta(days=6),day+timedelta(days=1); m=y=None
    elif mode=='quarter':
        start=day.replace(month=((day.month-1)//3)*3+1,day=1)
        end=start.replace(year=start.year+1,month=1) if start.month==10 else start.replace(month=start.month+3)
        m=y=None
    elif mode=='year':
        m=None; y=y or now.year
    if start or end:
        label=f'{date(start.isoformat()) if start else "Начало учёта"} — {date((end-timedelta(days=1)).isoformat()) if end else "сегодня и далее"}'
    else:
        label=(MONTHS[m-1] if m else 'Все месяцы')+' · '+(str(y) if y else 'все годы')
    def matches(value):
        if not value: return False
        try: dt=datetime.fromisoformat(str(value))
        except ValueError: return False
        return (not start or dt>=start) and (not end or dt<end) and (not m or dt.month==m) and (not y or dt.year==y)
    return matches,label


class ModernCRM:
    def build_app(self):
        app=super().build_app()
        @web.middleware
        async def crm_headers(request,handler):
            response=await handler(request)
            if request.path in ('/','/clients','/finance','/broadcasts','/audience-count') or request.path.startswith('/user/'):
                response.headers['Cache-Control']='no-store'
            return response
        app.middlewares.append(crm_headers)
        app.router.add_get('/audience-count',self.audience_count)
        app.router.add_post('/user/{telegram_id}/access',self.edit_access)
        app.router.add_get('/ui/{filename}',self.ui_asset)
        if not any(r.resource.canonical=='/payment/{payment_id}/receipt' for r in app.router.routes()):
            app.router.add_get('/payment/{payment_id}/receipt',self.payment_receipt)
        return app

    async def payment_receipt(self,request):
        from aiohttp import ClientSession, ClientTimeout
        try: pid=int(request.match_info['payment_id'])
        except ValueError: raise web.HTTPNotFound()
        async with self.connect() as db:
            row=await (await db.execute('SELECT * FROM payments WHERE id=?',(pid,))).fetchone()
        if not row or row['telegram_id'] in self.settings.excluded_ids: raise web.HTTPNotFound()
        if hasattr(super(),'payment_receipt'):
            try: return await super().payment_receipt(request)
            except web.HTTPNotFound: pass
            except Exception as exc:
                # Older databases may not have the MiniApp uploads table yet.
                import sqlite3
                if not isinstance(exc,sqlite3.OperationalError): raise
        if not row['receipt_file_id'] or not self.settings.bot_token: raise web.HTTPNotFound(text='Файл чека недоступен.')
        async with ClientSession(timeout=ClientTimeout(total=20)) as session:
            async with session.post(f'https://api.telegram.org/bot{self.settings.bot_token}/getFile',json={'file_id':row['receipt_file_id']}) as response:
                data=await response.json()
            info=data.get('result') or {}; path=info.get('file_path','')
            if not data.get('ok') or not re.fullmatch(r'[\w/.-]+',path) or '..' in path:
                raise web.HTTPBadGateway(text='Telegram не предоставил файл чека. Повторите позже.')
            if info.get('file_size',0)>20*1024*1024: raise web.HTTPBadRequest(text='Файл слишком большой для предпросмотра.')
            async with session.get(f'https://api.telegram.org/file/bot{self.settings.bot_token}/{path}') as response:
                if response.status!=200: raise web.HTTPBadGateway(text='Не удалось загрузить чек.')
                chunks=[]; size=0
                async for chunk in response.content.iter_chunked(65536):
                    size+=len(chunk)
                    if size>20*1024*1024: raise web.HTTPBadRequest(text='Файл слишком большой.')
                    chunks.append(chunk)
        suffix=Path(path).suffix.lower()
        mime={'.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.pdf':'application/pdf'}.get(suffix,'application/octet-stream')
        return web.Response(body=b''.join(chunks),content_type=mime,headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Content-Disposition':f'inline; filename="receipt-{pid}{suffix}"'})

    async def ui_asset(self,request):
        name=request.match_info['filename']
        if name not in ('crm.css','crm.js'): raise web.HTTPNotFound()
        return web.FileResponse(ASSETS/name,headers={'Cache-Control':'no-cache'})

    def page(self,title,content,*,active='dashboard'):
        nav=[('dashboard','Главная','/','01'),('clients','Клиенты','/clients','02'),('finance','Финансы','/finance','03'),('broadcasts','Рассылки','/broadcasts','04')]
        links=''.join(f'<a {"aria-current=page" if active==key else ""} href="{e(self.url(path))}"><span>{num}</span>{label}</a>' for key,label,path,num in nav)
        return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
        <meta name="color-scheme" content="light"><title>{e(title)} · Nastaŭnik</title>
        <link rel="stylesheet" href="{e(self.url('/ui/crm.css'))}?v=20260920"><script defer src="{e(self.url('/ui/crm.js'))}?v=20260920"></script></head>
        <body><a class="skip" href="#main">К содержимому</a><aside class="sidebar"><a class="brand" href="{e(self.url('/'))}"><span class="brand-mark">N</span><span>Nastaŭnik<small>Управление клубом</small></span></a>
        <button class="menu-toggle" aria-expanded="false" aria-controls="navigation">Меню</button><nav id="navigation" aria-label="Главное меню">{links}</nav><div class="sidebar-note">Клуб для учителей<small>Люди. Знания. Развитие.</small></div></aside>
        <div class="workspace"><header class="topbar"><span>Рабочее пространство / <b>{e(dict((k,l) for k,l,_,_ in nav).get(active,'Клуб'))}</b></span><span class="admin-dot">Администратор</span></header>
        <main id="main">{content}</main><footer>Nastaŭnik Club <span>CRM · 2026</span></footer></div><div id="toast" role="status" aria-live="polite"></div></body></html>'''

    def heading(self,title,description='',actions=''):
        return f'<section class="hero"><div><p class="eyebrow">NASTAŬNIK / CLUB</p><h1>{e(title)}</h1><p class="muted">{e(description)}</p></div><div class="hero-actions">{actions}</div></section>'

    def link(self,label,path,kind='button',**query):
        return f'<a class="{e(kind)}" href="{e(self.url(path,**query))}">{e(label)}</a>'

    async def records(self):
        await self.ensure_admin_tables()
        exclusion,params=self.exclusion_condition('u')
        async with self.connect() as db:
            cur=await db.execute(f'SELECT u.*, f.status AS foreign_status, f.created_at AS foreign_created_at, f.decided_at AS foreign_decided_at FROM users u LEFT JOIN foreign_requests f ON f.telegram_id=u.telegram_id WHERE {exclusion or "1=1"}',params)
            users=[dict(r) for r in await cur.fetchall()]
            cur=await db.execute(f'SELECT p.*, u.full_name,u.username FROM payments p JOIN users u ON u.telegram_id=p.telegram_id WHERE {exclusion or "1=1"} ORDER BY p.confirmed_at DESC,p.id DESC',params)
            payments=[dict(r) for r in await cur.fetchall()]
        index={r['telegram_id']:r for r in users}
        for row in users:
            row.update(ltc=Decimal('0'),payments_count=0,last_paid_at=None,pending=False)
        for p in payments:
            row=index[p['telegram_id']]
            if p['status']=='approved':
                row['ltc']+=amount(p['amount_label']); row['payments_count']+=1
                if p['confirmed_at'] and (not row['last_paid_at'] or p['confirmed_at']>row['last_paid_at']): row['last_paid_at']=p['confirmed_at']
            if p['status']=='pending': row['pending']=True
        return users,payments

    def filter_clients(self,users,q):
        state=q.get('status_filter','any'); kind=q.get('type_filter','any')
        text=q.get('q','').strip().casefold(); paid=q.get('payment','any'); bot=q.get('bot','any')
        try: days=int(q.get('days','7'))
        except ValueError: days=7
        today=datetime.utcnow().date()
        result=[]
        for r in users:
            if text and text not in f"{r['full_name']} @{r['username'] or ''} {r['telegram_id']}".casefold(): continue
            if state=='in_club' and not active(r): continue
            if state=='not_in_club' and active(r): continue
            if state=='expiring':
                if not active(r) or not r['access_end_at'] or r['is_lifetime_free']: continue
                if not today<=datetime.fromisoformat(r['access_end_at']).date()<=today+timedelta(days=days): continue
            elif state not in ('any','in_club','not_in_club') and r['current_status']!=state: continue
            special=bool(category(r))
            if kind=='regular' and special: continue
            if kind=='special_any' and not special: continue
            if kind=='free' and not r['is_lifetime_free']: continue
            if kind=='special_rate' and (r['is_lifetime_free'] or not r['recurring_amount_label'] or r['recurring_amount_label']=='10 BYN / месяц'): continue
            if kind=='foreign' and not r['foreign_status']: continue
            if kind.startswith('foreign_') and r['foreign_status']!=kind[8:]: continue
            if paid=='yes' and not r['payments_count']: continue
            if paid=='no' and r['payments_count']: continue
            if paid=='pending' and not r['pending']: continue
            if bot=='yes' and not r['created_at']: continue
            if bot=='no' and r['created_at']: continue
            result.append(r)
        return result

    async def membership(self,users):
        cache=getattr(self,'_crm_membership',{})
        self._crm_membership=cache
        sem=asyncio.Semaphore(6)
        async def check(row):
            uid=row['telegram_id']; cached=cache.get(uid)
            if cached and (datetime.utcnow()-cached[0]).total_seconds()<300: return uid,cached[1]
            async with sem:
                try: value=await asyncio.wait_for(self.get_club_member_status(uid),timeout=4)
                except asyncio.TimeoutError: value='не удалось проверить'
                cache[uid]=(datetime.utcnow(),value)
                return uid,value
        tasks=[asyncio.create_task(check(r)) for r in users]
        done,pending=await asyncio.wait(tasks,timeout=12) if tasks else (set(),set())
        for t in pending: t.cancel()
        if pending: await asyncio.gather(*pending,return_exceptions=True)
        return dict(t.result() for t in done if not t.cancelled() and t.exception() is None)

    async def clients(self,request):
        users,_=await self.records(); q=dict(request.query)
        rows=self.filter_clients(users,q)
        membership=q.get('membership','any')
        unknown=0
        if membership!='any':
            states=await self.membership(rows)
            known={'в клубе','в клубе, владелец','в клубе, админ','в клубе, ограничен','не в клубе','удален или заблокирован'}
            unknown=sum(1 for r in rows if states.get(r['telegram_id']) not in known)
            rows=[r for r in rows if (states.get(r['telegram_id'],'').startswith('в клубе') if membership=='yes' else states.get(r['telegram_id']) in ('не в клубе','удален или заблокирован'))]
        keys={'name':lambda r:(r['full_name'] or '').casefold(),'status':lambda r:STATUS_TEXT.get(r['current_status'],''),'payment':lambda r:r['last_paid_at'] or '',
              'ltc':lambda r:r['ltc'],'access':lambda r:r['access_end_at'] or '', 'special':category,'bot':lambda r:r['created_at'] or ''}
        sort=q.get('sort','name'); direction=q.get('direction','asc')
        rows.sort(key=lambda r:(keys.get(sort,keys['name'])(r),r['telegram_id']),reverse=direction=='desc')
        total=len(rows)
        try: page=max(1,min(int(q.get('page','1')),max(1,(total+29)//30)))
        except ValueError: page=1
        shown=rows[(page-1)*30:page*30]
        selected=sum(v not in ('','any') for k,v in q.items() if k in ('q','status_filter','type_filter','membership','payment','bot'))
        form=f'''<form class="filters" method="get" action="{e(self.url('/clients'))}"><div class="search-row"><label class="search"><span class="sr-only">Поиск клиента</span><input name="q" value="{e(q.get('q',''))}" placeholder="Имя, @username или Telegram ID" type="search"></label><button>Найти</button><a class="button secondary" href="{e(self.url('/clients'))}">Сбросить</a></div>
        <details class="filter-details" {"open" if selected else ""}><summary>Фильтры <span class="counter">{selected}</span></summary><div class="filter-grid">
        {field('Статус доступа','status_filter',STATES,q.get('status_filter','any'))}{field('Категория','type_filter',TYPES,q.get('type_filter','any'))}
        {field('В Telegram-клубе','membership',{'any':'Не проверять','yes':'Состоит','no':'Не состоит'},membership)}
        {field('Оплата','payment',{'any':'Любая','yes':'Есть подтверждённая','no':'Без подтверждённых оплат','pending':'Чек на проверке'},q.get('payment','any'))}
        {field('Запись о запуске бота','bot',{'any':'Все','yes':'Есть','no':'Нет'},q.get('bot','any'))}
        {field('Скоро истекает: дней','days',{str(n):str(n) for n in (1,3,5,7,14,30)},q.get('days','7'))}</div>
        <div class="form-foot"><p class="muted">Участие в Telegram проверяется отдельно от права доступа. Проверка может занять несколько секунд.</p><button>Применить фильтры</button></div></details></form>'''
        heads=[]
        for key,label in [('name','Участник'),('status','Статус'),('payment','Последняя оплата'),('ltc','Всего оплатил'),('access','Доступ до'),('special','Категория'),('bot','Бот с')]:
            params={**q,'sort':key,'direction':'desc' if sort==key and direction=='asc' else 'asc','page':1}
            arrow=('↑' if direction=='asc' else '↓') if sort==key else '↕'
            heads.append(f'<th aria-sort="{("ascending" if direction=="asc" else "descending") if sort==key else "none"}"><a class="table-sort" href="{e(self.url("/clients",**params))}">{label} <span>{arrow}</span></a></th>')
        body=''.join(self.client_row(r) for r in shown)
        pages=max(1,(total+29)//30)
        paging=f'<div class="pagination"><span>Найдено: {total} · Страница {page} из {pages}</span><div>'
        if page>1: paging+=self.link('Назад','/clients','button secondary',**{**q,'page':page-1})
        if page<pages: paging+=self.link('Далее','/clients','button secondary',**{**q,'page':page+1})
        paging+='</div></div>'
        warning=f'<div class="notice">Не удалось проверить участие {unknown} клиентов. Они не включены в результат проверки Telegram.</div>' if unknown else ''
        content=self.heading('Клиенты','Все участники и заявки в одном месте.',self.link('Создать рассылку','/broadcasts'))
        content+=f'<div class="segments">{self.link("Все клиенты","/clients","chip")}{self.link("Чеки на проверке","/clients","chip",payment="pending")}{self.link("Истекают за 7 дней","/clients","chip",status_filter="expiring",days=7)}{self.link("Не из РБ","/clients","chip",type_filter="foreign")}</div>'
        content+=form+warning+f'<section class="panel"><div class="section-head"><h2>Клиентская база</h2><span class="counter">{total}</span></div><div class="table-wrap"><table class="clients-table"><thead><tr>{"".join(heads)}</tr></thead><tbody>{body or self.empty(7,"Клиентов по этим условиям нет. Измените фильтры или сбросьте поиск.")}</tbody></table></div>{paging}</section>'
        return web.Response(text=self.page('Клиенты',content,active='clients'),content_type='text/html')

    def empty(self,span,text):
        return f'<tr><td colspan="{span}" class="empty">{e(text)}</td></tr>'

    def client_row(self,r):
        special=category(r)
        return f'''<tr><td><a class="name" href="{e(self.url('/user/'+str(r['telegram_id'])))}">{'<span class="star" title="Особый участник">★</span> ' if special else ''}{e(r['full_name'])}</a><span class="sub">{e('@'+r['username'] if r['username'] else 'Без username')} · {r['telegram_id']}</span></td>
        <td>{badge(r)}</td><td>{date(r['last_paid_at'])}<span class="sub">{r['payments_count']} подтверждённых</span></td><td class="numeric"><b>{money(r['ltc'])}</b></td>
        <td>{date(r['access_end_at']) if r['access_end_at'] else ('Без срока' if active(r) else '—')}</td><td><span class="category">{e(special or 'Обычный')}</span></td><td>{date(r['created_at'])}</td></tr>'''

    def metric(self,label,value,detail='',path=None,**query):
        tag='a' if path else 'div'
        href=f' href="{e(self.url(path,**query))}"' if path else ''
        return f'<{tag} class="metric"{href}><span>{e(label)}</span><strong>{e(value)}</strong><small>{e(detail)}</small></{tag}>'

    def chart(self,payments,months=6):
        current=datetime.utcnow().replace(day=1,hour=0,minute=0,second=0,microsecond=0)
        bins={}
        for _ in range(months):
            bins[current.strftime('%Y-%m')]=Decimal('0')
            current=(current-timedelta(days=1)).replace(day=1)
        for p in payments:
            key=(p.get('confirmed_at') or '')[:7]
            if key in bins and p['status']=='approved': bins[key]+=amount(p['amount_label'])
        maximum=max(bins.values()) or Decimal('1')
        bars=''.join(f'<div class="chart-col"><span>{e(money(value))}</span><div class="bar-track"><div class="bar" style="height:{max(0,float(value/maximum)*100):.1f}%"></div></div><small>{MONTHS[int(key[5:])-1][:3]} {key[:4]}</small></div>' for key,value in sorted(bins.items()))
        return f'<div class="chart" role="img" aria-label="Поступления по месяцам">{bars}</div>'

    async def load_recent_activity(self,limit=6):
        await self.ensure_admin_tables()
        excluded,params=self.exclusion_condition('a')
        exclusion=f'AND (a.telegram_id IS NULL OR {excluded})' if excluded else ''
        async with self.connect() as db:
            cursor=await db.execute(f'''SELECT a.created_at,a.title,a.details,u.full_name
                FROM action_logs a LEFT JOIN users u ON u.telegram_id=a.telegram_id
                WHERE a.action_type!='broadcast_received' {exclusion}
                ORDER BY a.created_at DESC,a.id DESC LIMIT ?''',params+[limit])
            events=[dict(row) for row in await cursor.fetchall()]
            cursor=await db.execute('SELECT created_at,sent_count,failed_count FROM broadcast_logs ORDER BY created_at DESC,id DESC LIMIT ?',(limit,))
            for row in await cursor.fetchall():
                events.append({'created_at':row['created_at'],'title':'Рассылка завершена','details':f'Доставлено: {row["sent_count"]}. Ошибок: {row["failed_count"]}.'})
        for event in events:
            if event.get('full_name'): event['title']+=' · '+event['full_name']
        return sorted(events,key=lambda r:r['created_at'],reverse=True)[:limit]

    async def dashboard(self,request):
        users,payments=await self.records()
        now=datetime.utcnow(); month=now.strftime('%Y-%m')
        approved=[p for p in payments if p['status']=='approved' and (p['confirmed_at'] or '').startswith(month)]
        pending=[p for p in payments if p['status']=='pending']
        expiring=self.filter_clients(users,{'status_filter':'expiring','days':'7'})
        foreign=[r for r in users if r['foreign_status']=='pending']
        actions=self.link('Проверить чеки','/finance')+self.link('Новая рассылка','/broadcasts','button secondary')
        content=self.heading('Клуб сегодня',now.strftime('%d.%m.%Y')+' · Главное для вашей работы',actions)
        content+='<section class="metrics">'+self.metric('Клиенты',len(users),'в клиентской базе','/clients')+self.metric('Активный доступ',sum(active(r) for r in users),'включая бесплатных','/clients',status_filter='in_club')+self.metric('Поступления',money(sum((amount(p['amount_label']) for p in approved),Decimal('0'))),MONTHS[now.month-1],'/finance')+self.metric('Новые клиенты',sum((r['created_at'] or '').startswith(month) for r in users),'за текущий месяц','/clients',sort='bot',direction='desc')+'</section>'
        attention=[('Чеки на проверке',len(pending),'/finance',{}),('Доступ истекает за 7 дней',len(expiring),'/clients',{'status_filter':'expiring','days':7}),('Заявки «Не из РБ»',len(foreign),'/clients',{'type_filter':'foreign_pending'}),('Оплатили, но не вступили','Проверить','/clients',{'payment':'yes','membership':'no'})]
        content+='<section class="panel attention"><div class="section-head"><div><p class="eyebrow">Следующий шаг</p><h2>Требует внимания</h2></div><span class="status-dot">Рабочая очередь</span></div><div class="attention-grid">'+''.join(f'<a href="{e(self.url(path,**q))}"><span>{e(label)}</span><strong>{e(count)} <i>↗</i></strong></a>' for label,count,path,q in attention)+'</div></section>'
        channel=await self.load_public_channel_count()
        content+='<div class="dashboard-grid"><section class="panel"><div class="section-head"><div><p class="eyebrow">Аудитория</p><h2>Путь к клубу</h2></div></div><ol class="funnel">'
        for n,(label,value,note) in enumerate([('Публичный канал',channel,'Данные Telegram'),('Клиентская база',len(users),'Записи пользователей бота'),('Активный доступ',sum(active(r) for r in users),'Право участия, включая бесплатных')],1):
            content+=f'<li><span class="step-number">0{n}</span><div><b>{label}</b><small>{note}</small></div><strong>{value if value is not None else "Нет данных"}</strong></li>'
        content+='<p class="muted small">Это общие аудитории, а не подтверждённые переходы одних и тех же людей. Фактическое вступление проверяется в карточке клиента и фильтрах Telegram.</p></ol></section>'
        content+='<section class="panel"><div class="section-head"><div><p class="eyebrow">Динамика</p><h2>Поступления</h2></div>'+self.link('Все финансы','/finance','text-link')+'</div>'+self.chart(payments)+'</section></div>'
        recent=await self.load_recent_activity(limit=6)
        content+='<div class="dashboard-grid"><section class="panel"><div class="section-head"><h2>Последние события</h2></div>'+self.timeline([dict(r) for r in recent])+'</section><section class="panel"><div class="section-head"><h2>Быстрые действия</h2></div><div class="quick-actions">'+self.link('Найти клиента и внести оплату','/clients','quick-link')+self.link('Просмотреть истёкшие доступы','/clients','quick-link',status_filter='expired')+self.link('Написать участникам','/broadcasts','quick-link')+'</div></section></div>'
        return web.Response(text=self.page('Главная',content),content_type='text/html')

    async def finance_data(self,query):
        _,payments=await self.records()
        matches,label=period(query)
        selected=[p for p in payments if p['status']=='approved' and matches(p['confirmed_at'])]
        return payments,selected,label

    async def finance_page(self,request):
        q=dict(request.query)
        try: payments,selected,label=await self.finance_data(q)
        except web.HTTPBadRequest as error:
            return web.Response(status=400,text=self.page('Проверьте период',self.heading('Проверьте период',error.text,self.link('Вернуться к финансам','/finance')),active='finance'),content_type='text/html')
        now=datetime.utcnow(); mode=q.get('mode','month')
        month=q.get('month',f'{now.month:02}' if mode=='month' else '')
        year=q.get('year',str(now.year) if mode in ('month','year') else '')
        if re.fullmatch(r'\d{4}-\d{2}',month): year,month=year or month[:4],month[5:]
        years=sorted({str(now.year),year,*[p['confirmed_at'][:4] for p in payments if p['confirmed_at']]},reverse=True)
        years=[v for v in years if v]
        presets=''.join(self.link(text,'/finance','chip'+(' selected' if mode==key else ''),mode=key) for key,text in [('today','Сегодня'),('week','7 дней'),('quarter','Квартал'),('year','Год'),('all','Всё время')])
        filters=f'''<section class="panel period-panel"><div class="section-head"><h2>Период</h2><span class="period-label">{e(label)}</span></div>
        <form class="period-form" method="get"><input type="hidden" name="mode" value="range">
        {field('Месяц','month',{'':'— Все месяцы',**{f'{i:02}':name for i,name in enumerate(MONTHS,1)}},month)}
        {field('Год','year',{'':'— Все годы',**{v:v for v in years}},year)}
        <label class="field"><span>С даты</span><input type="date" name="from" value="{e(q.get('from',''))}"></label>
        <label class="field"><span>По дату</span><input type="date" name="to" value="{e(q.get('to',''))}"></label><button>Применить</button></form><p class="muted small">Если заданы даты, используем диапазон. Без дат учитываем выбранные месяц и год. «—» снимает ограничение.</p></section>'''
        total=sum((amount(p['amount_label']) for p in selected),Decimal('0'))
        people=len({p['telegram_id'] for p in selected})
        content=self.heading('Финансы','Подтверждённые оплаты и очередь чеков.',self.link('Скачать CSV','/finance/export.csv','button secondary',**q))
        if request.query.get('payment_done'): content+='<div class="notice success" role="status">Решение по чеку сохранено.</div>'
        content+=filters+'<div class="metrics">'+self.metric('Поступило',money(total),'за выбранный период')+self.metric('Оплаты',len(selected),'подтверждённых')+self.metric('Средний платёж',money(total/len(selected)) if selected else '—','среди подтверждённых')+self.metric('Плательщики',people,'уникальных участников')+'</div>'
        pending=[p for p in payments if p['status']=='pending']
        content+=self.render_pending_payments(pending)
        content+='<section class="panel"><div class="section-head"><h2>Динамика поступлений</h2><form class="inline-form" method="get">'+''.join(f'<input type="hidden" name="{e(k)}" value="{e(v)}">' for k,v in q.items() if k!='chart')+field('Месяцев','chart',{'6':'6 месяцев','12':'12 месяцев'},q.get('chart','6'))+'<button class="secondary">Показать</button></form></div>'+self.chart(payments,12 if q.get('chart')=='12' else 6)+'<p class="muted small">Общая динамика за последние месяцы. Операции ниже соответствуют выбранному периоду.</p></section>'
        rows=''.join(f'<tr><td>{date(p["confirmed_at"],True)}</td><td>{self.link(p["full_name"],"/user/"+str(p["telegram_id"]),"name")}</td><td class="numeric">{money(amount(p["amount_label"]))}</td><td>{e(p["admin_comment"] or "—")}</td></tr>' for p in selected)
        content+=f'<section class="panel"><div class="section-head"><h2>Операции</h2><span class="counter">{len(selected)}</span></div><p class="muted">{e(label)} · По дате подтверждения или вручную внесённой оплаты</p><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Участник</th><th>Сумма</th><th>Комментарий</th></tr></thead><tbody>{rows or self.empty(4,"За выбранный период оплат нет.")}</tbody></table></div></section>'
        return web.Response(text=self.page('Финансы',content,active='finance'),content_type='text/html')

    async def export_finance_csv(self,request):
        _,selected,_=await self.finance_data(request.query)
        output=io.StringIO(); writer=csv.writer(output)
        writer.writerow(['Дата','Участник','Telegram ID','Сумма BYN','Комментарий'])
        def safe(value):
            value=str(value or '')
            return "'"+value if value.lstrip().startswith(('=','+','-','@')) else value
        for p in selected: writer.writerow([p['confirmed_at'],safe(p['full_name']),p['telegram_id'],str(amount(p['amount_label'])),safe(p['admin_comment'])])
        return web.Response(body=output.getvalue().encode('utf-8-sig'),content_type='text/csv',headers={'Content-Disposition':'attachment; filename="club-finance.csv"'})

    def render_pending_payments(self,payments,*,compact=False):
        items=[]
        for raw in payments:
            p=dict(raw); pid=int(p['id'])
            receipt=self.link('Открыть чек',f'/payment/{pid}/receipt','button secondary') if p.get('receipt_file_id') else f'<p class="receipt-text">{e(p.get("receipt_text") or "Текст чека не указан")}</p>'
            items.append(f'''<article class="receipt"><div><span class="pill amber">На проверке</span><h3>{self.link(p['full_name'],'/user/'+str(p['telegram_id']),'name')}</h3><p class="muted">{date(p['created_at'],True)}</p><strong>{e(p['amount_label'])}</strong></div><div>{receipt}<p class="muted small">{e(p.get('receipt_text') or '') if p.get('receipt_file_id') else ''}</p></div><div class="receipt-actions">
            <form method="post" action="{e(self.url(f'/payment/{pid}/approve'))}" data-confirm="Подтвердить оплату и открыть доступ этому участнику?"><label class="field"><span>Комментарий к решению</span><input name="comment" placeholder="Необязательно"></label><button>Подтвердить</button><button class="danger" formaction="{e(self.url(f'/payment/{pid}/reject'))}" data-confirm="Отклонить этот чек? Участнику придёт уведомление.">Отклонить</button></form></div></article>''')
        return f'<section class="panel" id="pending"><div class="section-head"><div><p class="eyebrow">Рабочая очередь</p><h2>Чеки на проверке</h2></div><span class="counter">{len(payments)}</span></div>{"".join(items) or "<div class=empty>Все чеки разобраны. Новые заявки появятся здесь.</div>"}</section>'

    def timeline(self,events):
        items=''.join(f'<li><time>{date(r.get("created_at"),True)}</time><div><b>{e(r.get("title","Событие"))}</b><p>{e(r.get("details") or "")}</p></div></li>' for r in events)
        return f'<ol class="timeline">{items}</ol>' if events else '<p class="empty">Событий пока нет.</p>'

    async def user_detail(self,request):
        users,payments=await self.records()
        try: uid=int(request.match_info['telegram_id'])
        except ValueError: raise web.HTTPNotFound()
        user=next((r for r in users if r['telegram_id']==uid),None)
        if not user: raise web.HTTPNotFound()
        logs=[dict(r) for r in await self.load_action_logs(uid,limit=100)]
        member=await self.get_club_member_status(uid)
        flags={k:v for k,v in request.query.items() if k in ('saved','access_saved','restore_sent','restore_failed','message_sent','message_failed')}
        body=self.render_user_detail(user,[p for p in payments if p['telegram_id']==uid],logs,club_status=member,**flags)
        return web.Response(text=body,content_type='text/html')

    def render_user_detail(self,user,payments,action_logs,*,club_status='не проверено',**flags):
        u=dict(user); uid=u['telegram_id']; base=f'/user/{uid}'
        content=self.link('← Все клиенты','/clients','back')
        actions=f'<a class="button" href="#messages" data-tab-link="messages">Написать</a><a class="button secondary" href="#payments" data-tab-link="payments">Внести оплату</a>'
        content+=self.heading(u['full_name'],('@'+u['username'] if u['username'] else 'Без username'),actions)
        content+=f'<div class="profile-meta">{badge(u)}<span class="category">{e(category(u) or "Обычный участник")}</span><button class="copy secondary" data-copy="{uid}">ID {uid} · копировать</button></div>'
        if flags.get('saved') or flags.get('access_saved'): content+='<div class="notice success" role="status">Изменения сохранены.</div>'
        if flags.get('restore_sent') is not None: content+=f'<div class="notice">Отправка ссылки: доставлено {e(flags.get("restore_sent"))}, ошибок {e(flags.get("restore_failed",0))}.</div>'
        if flags.get('message_sent') is not None: content+=f'<div class="notice">Сообщение: доставлено {e(flags.get("message_sent"))}, ошибок {e(flags.get("message_failed",0))}.</div>'
        content+='<nav class="tabs" aria-label="Разделы карточки">'+''.join(f'<a href="#{key}" data-tab-link="{key}">{label}</a>' for key,label in [('overview','Обзор'),('payments','Оплаты'),('access','Доступ'),('history','История'),('messages','Сообщения')])+'</nav>'
        overview=[('В Telegram-клубе',club_status),('Запись о запуске бота',date(u['created_at'],True)),('Тариф',u.get('recurring_amount_label') or '10 BYN / месяц'),('Доступ до',date(u['access_end_at']) if u['access_end_at'] else ('Без срока' if active(u) else 'Нет доступа')),('Последняя оплата',date(u.get('last_paid_at'))),('Комментарий',u.get('admin_comment') or '—')]
        content+=f'<section class="tab-panel" id="overview"><div class="metrics">{self.metric("Всего оплатил · LTC",money(u.get("ltc",0)),"подтверждённые платежи за всё время")}{self.metric("Количество оплат",u.get("payments_count",0),"подтверждённых")}</div><div class="panel"><h2>Об участнике</h2><dl class="detail-grid">'+''.join(f'<div><dt>{e(k)}</dt><dd>{e(v)}</dd></div>' for k,v in overview)+'</dl></div></section>'
        rows=''.join(f'<tr><td>{date(p["confirmed_at"] or p["created_at"],True)}</td><td><span class="pill {"good" if p["status"]=="approved" else "amber" if p["status"]=="pending" else "danger"}">{e({"approved":"Подтверждена","pending":"На проверке","rejected":"Отклонена"}.get(p["status"],p["status"]))}</span></td><td>{e(p["amount_label"])}</td><td>{e(p["admin_comment"] or p["receipt_text"] or "—")}</td></tr>' for p in payments)
        content+=f'''<section class="tab-panel" id="payments"><div class="panel"><h2>Внести оплату вручную</h2><p class="muted">Создаёт подтверждённую оплату и обновляет срок доступа.</p><form class="form-grid" method="post" action="{e(self.url(base+'/manual-payment'))}" data-confirm="Записать оплату и обновить доступ участника?">
        <label class="field"><span>Дата оплаты</span><input type="date" name="paid_at" value="{datetime.utcnow().date().isoformat()}" required></label><label class="field"><span>Сумма / тариф</span><input name="amount_label" value="{e(u.get('recurring_amount_label') or '10 BYN / месяц')}" required></label><label class="field"><span>Дней доступа</span><input type="number" name="access_days" min="1" max="370" value="30" required></label><label class="field"><span>Комментарий</span><input name="note" placeholder="Например: перевод по договорённости"></label><button>Записать оплату</button></form></div>
        {self.render_pending_payments([p for p in payments if p['status']=='pending'])}<div class="panel"><h2>История оплат</h2><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Решение</th><th>Сумма</th><th>Комментарий</th></tr></thead><tbody>{rows or self.empty(4,'Платежей пока нет.')}</tbody></table></div></div></section>'''
        content+=f'''<section class="tab-panel" id="access"><div class="panel"><h2>Управление доступом</h2><p>В Telegram: <b>{e(club_status)}</b></p><form method="post" action="{e(self.url(base+'/restore-access'))}" data-confirm="Отправить участнику ссылку для входа в клуб?"><button>Отправить ссылку в клуб</button></form><hr>
        <h3>Продлить без оплаты</h3><p class="muted">Продление не попадает в финансовую статистику.</p><form class="form-grid" method="post" action="{e(self.url(base+'/access'))}" data-confirm="Продлить доступ без создания оплаты?"><input type="hidden" name="action" value="extend"><label class="field"><span>На сколько дней</span><input type="number" name="days" min="1" max="370" value="30" required></label><label class="field"><span>Причина</span><input name="note" required placeholder="Укажите причину"></label><button>Продлить доступ</button></form><hr>
        <h3>Отключить доступ</h3><p class="muted">Участник будет удалён из Telegram-клуба. История оплат сохранится.</p><form class="form-grid" method="post" action="{e(self.url(base+'/access'))}" data-confirm="Отключить доступ и удалить этого участника из Telegram-клуба?"><input type="hidden" name="action" value="disable"><label class="field"><span>Причина отключения</span><input name="note" required></label><button class="danger">Отключить доступ</button></form></div></section>'''
        events=[{'created_at':u['created_at'],'title':'Создана карточка пользователя','details':''}]+[dict(r) for r in action_logs]
        for p in payments:
            for key,title in [('created_at','Платёж зарегистрирован'),('confirmed_at','Оплата подтверждена'),('rejected_at','Оплата отклонена')]:
                if p[key]: events.append({'created_at':p[key],'title':title,'details':f'№{p["id"]} · {p["amount_label"]}'})
        if u.get('foreign_created_at'): events.append({'created_at':u['foreign_created_at'],'title':'Заявка «Не из РБ»','details':'Заявка зарегистрирована'})
        if u.get('foreign_decided_at'): events.append({'created_at':u['foreign_decided_at'],'title':'Решение по заявке «Не из РБ»','details':category(u)})
        events.sort(key=lambda r:r.get('created_at') or '',reverse=True)
        content+='<section class="tab-panel" id="history"><div class="panel"><h2>История участника</h2>'+self.timeline(events)+'</div></section>'
        messages=[r for r in action_logs if any(key in r.get('action_type','') for key in ('message','broadcast'))]
        content+=f'<section class="tab-panel" id="messages"><div class="panel"><h2>Личное сообщение</h2><form method="post" action="{e(self.url(base+"/message/preview"))}"><label class="field"><span>Текст от имени клубного бота</span><textarea name="message" maxlength="4096" rows="7" required placeholder="Напишите участнику…"></textarea></label><div class="form-foot"><small class="muted">Сначала покажем предпросмотр.</small><button>Предпросмотр</button></div></form></div><div class="panel"><h2>История сообщений</h2>{self.timeline(messages)}<p class="muted small">Показаны события, сохранённые системой. Это не полный Telegram-чат.</p></div></section>'
        return self.page(u['full_name'],content,active='clients')

    async def edit_access(self,request):
        from aiohttp import ClientSession, ClientTimeout
        await self.ensure_admin_tables()
        try: uid=int(request.match_info['telegram_id'])
        except ValueError: raise web.HTTPNotFound()
        if uid in self.settings.excluded_ids: raise web.HTTPNotFound()
        u=await self.load_user(uid)
        if not u: raise web.HTTPNotFound()
        form=await request.post(); action=form.get('action'); note=str(form.get('note','')).strip()
        if not note or len(note)>1000: raise web.HTTPBadRequest(text='Укажите причину до 1000 символов.')
        now=datetime.utcnow()
        if action=='extend':
            try: days=int(form.get('days',''))
            except ValueError: raise web.HTTPBadRequest(text='Укажите число дней.')
            if not 1<=days<=370: raise web.HTTPBadRequest(text='Допустимо от 1 до 370 дней.')
            async with self.connect() as db:
                await db.execute('BEGIN IMMEDIATE')
                cur=await db.execute('SELECT * FROM users WHERE telegram_id=?',(uid,))
                current=dict(await cur.fetchone())
                if current['is_lifetime_free'] or (active(current) and not current['access_end_at']):
                    raise web.HTTPBadRequest(text='У этого участника уже есть доступ без срока окончания.')
                end=datetime.fromisoformat(current['access_end_at']) if current['access_end_at'] and active(current) else now
                end=max(end,now)+timedelta(days=days)
                await db.execute("UPDATE users SET current_status='active',access_start_at=COALESCE(access_start_at,?),access_end_at=?,grace_end_at=?,reminder_5_sent_at=NULL,expiry_notice_sent_at=NULL,updated_at=? WHERE telegram_id=?",
                                 (now.isoformat(),end.isoformat(),(end+timedelta(days=5)).isoformat(),now.isoformat(),uid))
                await db.commit()
            await self.log_action(telegram_id=uid,action_type='manual_extension',title='Доступ продлён без оплаты',details=f'{days} дней. {note}')
        elif action=='disable':
            if not self.settings.bot_token or not self.settings.club_chat_id:
                raise web.HTTPServiceUnavailable(text='Не настроено управление Telegram-клубом.')
            async with ClientSession(timeout=ClientTimeout(total=15)) as session:
                async with session.post(f'https://api.telegram.org/bot{self.settings.bot_token}/banChatMember',json={'chat_id':self.settings.club_chat_id,'user_id':uid}) as response:
                    result=await response.json()
                if not result.get('ok'):
                    raise web.HTTPBadGateway(text='Telegram не подтвердил удаление. Доступ в базе не изменён. Проверьте права бота.')
                try:
                    async with session.post(f'https://api.telegram.org/bot{self.settings.bot_token}/unbanChatMember',json={'chat_id':self.settings.club_chat_id,'user_id':uid,'only_if_banned':True}) as response:
                        unbanned=await response.json()
                except Exception:
                    unbanned={'ok':False}
            async with self.connect() as db:
                await db.execute("UPDATE users SET current_status='expired',is_lifetime_free=0,access_end_at=?,grace_end_at=?,updated_at=? WHERE telegram_id=?",(now.isoformat(),now.isoformat(),now.isoformat(),uid))
                await db.commit()
            await self.log_action(telegram_id=uid,action_type='manual_disable',title='Доступ отключён; участник удалён из клуба',details=note+(' · Для возврата потребуется снять блокировку.' if not unbanned.get('ok') else ''))
        else: raise web.HTTPBadRequest(text='Неизвестное действие.')
        raise web.HTTPSeeOther(location=self.url(f'/user/{uid}',access_saved=1)+'#access')

    def broadcast_states(self):
        return {'any':'Все пользователи бота','in_club':'Есть доступ к клубу','not_in_club':'Нет доступа к клубу',
                'telegram_in':'Состоит в Telegram-клубе','telegram_out':'Запустил бота, но не состоит в Telegram-клубе',
                'waiting_confirmation':'Чек на проверке','expired':'Доступ истёк','expiring_7':'Доступ истекает за 7 дней'}

    def validate_broadcast_payload(self,status_filter,type_filter,message):
        if status_filter not in self.broadcast_states() or type_filter not in TYPES:
            raise web.HTTPBadRequest(text='Выберите существующий сегмент.')
        if not message.strip() or len(message)>4096:
            raise web.HTTPBadRequest(text='Текст сообщения должен содержать от 1 до 4096 символов.')

    def broadcast_filter_label(self,status_filter,type_filter):
        return self.broadcast_states().get(status_filter,status_filter)+' · '+TYPES.get(type_filter,type_filter)

    async def load_broadcast_recipients(self,audience=None,*,status_filter='any',type_filter='any'):
        if audience:
            status_filter,type_filter={'all':('any','any'),'regular':('any','regular'),'special':('any','special_any'),'free':('any','free'),'expired':('expired','any')}.get(audience,(status_filter,type_filter))
        self.validate_broadcast_payload(status_filter,type_filter,'validation')
        users,_=await self.records()
        state='expiring' if status_filter=='expiring_7' else 'any' if status_filter.startswith('telegram_') else status_filter
        rows=self.filter_clients(users,{'status_filter':state,'type_filter':type_filter,'days':'7'})
        if status_filter.startswith('telegram_'):
            states=await self.membership(rows)
            if any(states.get(r['telegram_id']) not in ('в клубе','в клубе, владелец','в клубе, админ','в клубе, ограничен','не в клубе','удален или заблокирован') for r in rows):
                raise web.HTTPServiceUnavailable(text='Telegram не позволил проверить всю аудиторию. Повторите проверку позже.')
            rows=[r for r in rows if states[r['telegram_id']].startswith('в клубе')==(status_filter=='telegram_in')]
        return [r['telegram_id'] for r in rows]

    async def audience_count(self,request):
        try:
            recipients=await self.load_broadcast_recipients(status_filter=request.query.get('status_filter','any'),type_filter=request.query.get('type_filter','any'))
        except web.HTTPException as exc:
            return web.json_response({'error':exc.text},status=exc.status)
        return web.json_response({'count':len(recipients)},headers={'Cache-Control':'no-store'})

    async def broadcasts_page(self,request):
        await self.ensure_admin_tables()
        history=await self.load_broadcast_logs(limit=30)
        templates=await self.load_broadcast_templates()
        content=self.heading('Рассылки','Сообщения участникам от имени клубного бота.')
        for key,label in [('broadcast_sent','Рассылка завершена. Доставлено'),('test_sent','Тестовое сообщение отправлено')]:
            if key in request.query:
                failed=request.query.get('broadcast_failed' if key=='broadcast_sent' else 'test_failed','0')
                content+=f'<div class="notice" role="status">{label}: {e(request.query[key])}. Ошибок: {e(failed)}.</div>'
        if request.query.get('template_saved'): content+='<div class="notice success">Шаблон сохранён.</div>'
        content+=f'''<div class="compose-grid"><section class="panel"><form id="broadcast-form" action="{e(self.url('/broadcast/preview'))}" method="post" data-audience-url="{e(self.url('/audience-count'))}">
        <div class="section-head"><h2><span class="step-number">01</span> Кому отправить</h2></div><div class="filter-grid">{field('Состояние','status_filter',self.broadcast_states(),'any')}{field('Категория','type_filter',TYPES,'any')}</div>
        <p id="audience-count" class="audience-count" role="status" aria-live="polite">Выберите аудиторию. Количество также будет проверено на шаге предпросмотра.</p>
        <hr><h2><span class="step-number">02</span> Сообщение</h2><label class="field"><span>Текст сообщения</span><textarea id="broadcast-message" name="message" rows="9" maxlength="4096" required placeholder="Напишите новость или приглашение…"></textarea></label><p class="muted small" id="message-count">0 / 4096</p>
        <div class="form-foot"><button class="secondary" formaction="{e(self.url('/broadcast/test'))}">Тест себе</button><button id="preview-submit">Предпросмотр →</button></div><p class="muted small">Отправка участникам начнётся только после подтверждения на следующем экране.</p></form></section>
        <aside class="panel compose-help"><p class="eyebrow">Под рукой</p><h2>Шаблоны</h2><p class="muted">Выберите заготовку и отредактируйте её перед отправкой.</p>'''
        content+=''.join(f'<button class="template-button" type="button" data-template="{e(t["message"])}">{e(t["title"])} <span>↗</span></button>' for t in templates)
        content+=f'''<details><summary>Сохранить новый шаблон</summary><form method="post" action="{e(self.url('/broadcast/template'))}"><label class="field"><span>Название</span><input name="title" required maxlength="100"></label><label class="field"><span>Текст</span><textarea name="message" required maxlength="4096" rows="4"></textarea></label><button>Сохранить</button></form></details></aside></div>'''
        content+=self.render_broadcast_history(history)
        return web.Response(text=self.page('Рассылки',content,active='broadcasts'),content_type='text/html')

    def render_broadcast_preview(self,*,status_filter,type_filter,message,recipients_count,**kwargs):
        return self.page('Проверка рассылки',self.heading('Проверьте перед отправкой','Сообщение получат выбранные участники.')+f'''<section class="panel narrow"><p class="eyebrow">03 / Подтверждение</p><h2>{recipients_count} получателей</h2><p class="muted">{e(self.broadcast_filter_label(status_filter,type_filter))}</p><div class="message-preview">{e(message)}</div><form method="post" action="{e(self.url('/broadcast'))}" data-confirm="Отправить сообщение выбранной аудитории?"><input type="hidden" name="status_filter" value="{e(status_filter)}"><input type="hidden" name="type_filter" value="{e(type_filter)}"><input type="hidden" name="message" value="{e(message)}"><input type="hidden" name="confirm" value="1"><div class="form-foot"><button type="button" class="secondary" data-back>Изменить</button><button {"disabled" if not recipients_count else ""}>Отправить рассылку</button></div></form>{'<p class="notice">Аудитория пуста. Измените фильтры.</p>' if not recipients_count else ''}</section>''',active='broadcasts')

    async def broadcast(self,request):
        form=await request.post()
        if not await self.load_broadcast_recipients(status_filter=str(form.get('status_filter') or 'any'),type_filter=str(form.get('type_filter') or 'any')):
            raise web.HTTPBadRequest(text='Аудитория пуста. Измените фильтры.')
        return await super().broadcast(request)

    def render_broadcast_history(self,logs):
        rows=[]
        for raw in logs:
            r=dict(raw); sent=int(r.get('sent_count') or 0); failed=int(r.get('failed_count') or 0)
            label='Доставлено' if not failed else 'Частично доставлено' if sent else 'Не доставлено'
            rows.append(f'<tr><td>{date(r.get("created_at"),True)}</td><td><details><summary>{e(str(r.get("message") or "")[:80])}</summary><p class="receipt-text">{e(r.get("message"))}</p></details><span class="sub">{e(r.get("audience"))}</span></td><td><span class="pill {"good" if not failed else "amber"}">{label}</span></td><td>{sent}</td><td>{failed}</td></tr>')
        return f'<section class="panel"><div class="section-head"><h2>История рассылок</h2><span class="muted small">Последние 30</span></div><div class="table-wrap"><table><thead><tr><th>Дата</th><th>Сообщение и аудитория</th><th>Результат</th><th>Доставлено</th><th>Ошибки</th></tr></thead><tbody>{"".join(rows) or self.empty(5,"Рассылок пока нет. Первая отправка появится здесь.")}</tbody></table></div></section>'
