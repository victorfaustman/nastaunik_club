"""Public page metadata, server-rendered free content and proper HTTP errors."""
import json
import re
from html import escape
from aiohttp import web
from bot.media_security import signed_text

ORIGIN='https://nastaunik.aiteacher.by'
PAGES={'/':('Клуб для учителей','Материалы, курсы и маршруты обучения. Учитесь в своём темпе.'),'/library':('Библиотека','Материалы и курсы для педагогической практики.'),'/tracks':('Треки обучения','Выберите маршрут обучения и удобный темп.'),'/consultations':('Консультации','Личные консультации для участников клуба.'),'/profile':('Мой профиль','Подписка, прогресс и настройки аккаунта.'),'/support':('Поддержка','Помощь со входом и работой клуба.'),'/privacy':('Обработка данных','Как используются данные аккаунта клуба.'),'/rules':('Правила клуба','Открытый контент и возможности участников клуба.')}
INFO={
 '/support':'<p>По вопросам входа, доступа, оплаты или работы сайта воспользуйтесь кнопкой «Задать вопрос» в боте клуба.</p><a href="https://t.me/nastaunik_club_bot">Открыть бота →</a>',
 '/privacy':'<p>Для входа используется Telegram. Аккаунт связан с Telegram ID; имя и username используются в профиле и для связи.</p><p>Сохраняются подписка и прогресс, а также записи на консультации, ответы на задания, отзывы и подтверждения оплаты, если вы их отправляете. Служебные cookies обеспечивают вход и защиту запросов.</p><p>Не отправляйте персональные данные учеников. По вопросам обработки своих данных или удаления аккаунта обратитесь в поддержку через бота.</p><p>Это описание работы сервиса. Юридические условия и сроки хранения требуют отдельного согласования с владельцем.</p>',
 '/rules':'<p>Открытые материалы и курсы отмечены как бесплатные. Закрытый контент и запись на консультации доступны при действующей подписке клуба.</p><p>Текущие условия вступления и инструкции по оплате находятся в профиле и боте. Доступ предоставляется после подтверждения оплаты.</p><p>Уважайте авторство. Не передавайте закрытые файлы и ссылки третьим лицам.</p>'}

@web.middleware
async def security_headers(request, handler):
    try: response=await handler(request)
    except web.HTTPException as exc: response=exc
    response.headers.update({'X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'SAMEORIGIN','Strict-Transport-Security':'max-age=86400'})
    if request.path.startswith('/site/') or (isinstance(response, web.Response) and response.content_type=='text/html' and 'NASTAUNIK_SITE' in (response.text or '')):
        response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; media-src 'self' https: blob:; font-src 'self' data:; frame-src https://www.youtube.com https://www.youtube-nocookie.com; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'"
    return response

async def page_meta(site, request):
    path=request.path.removeprefix('/site') if request.path.startswith('/site/') else request.path
    path=path.rstrip('/') or '/'
    if path=='/robots.txt':
        return web.Response(text='User-agent: *\nDisallow: /admin\nDisallow: /mini-app/api/\nDisallow: /mini-app/preview\nDisallow: /site/auth/\nDisallow: /profile\nSitemap: '+ORIGIN+'/sitemap.xml\n',content_type='text/plain')
    if path=='/sitemap.xml':
        paths=['/','/library','/tracks','/support','/rules']
        async with site.mini.db.connect() as conn:
            for table,prefix,extra in [('mini_app_materials','material',' AND library_visible=1'),('mini_app_courses','course','')]:
                rows=await (await conn.execute(f"SELECT id FROM {table} WHERE status='published' AND is_free=1{extra}")).fetchall()
                paths.extend(f'/{prefix}/{row[0]}' for row in rows)
        return web.Response(text='<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join('<url><loc>'+escape(ORIGIN+p)+'</loc></url>' for p in paths)+'</urlset>',content_type='application/xml',headers={'Cache-Control':'public, max-age=300'})
    title,description=PAGES.get(path,('Страница не найдена','Такой страницы нет. Вернитесь в библиотеку клуба.'))
    status=200 if path in PAGES else 404
    body,cover,private=INFO.get(path,''),'',path=='/profile'
    match=re.fullmatch(r'/(material|course|track)/(\d+)(?:/lesson/(\d+))?',path)
    if match:
        kind,item_id,lesson=match.groups()
        if lesson and kind!='course':
            raise web.HTTPNotFound()
        table={'material':'mini_app_materials','course':'mini_app_courses','track':'mini_app_tracks'}[kind]
        async with site.mini.db.connect() as conn:
            row=await (await conn.execute(f"SELECT * FROM {table} WHERE id=? AND status='published'",(int(item_id),))).fetchone()
            if row and kind=='material' and not row['library_visible']: row=None
            if row and lesson:
                row=await (await conn.execute('SELECT * FROM mini_app_course_units WHERE id=? AND course_id=?',(int(lesson),int(item_id)))).fetchone();private=True
        if row:
            item=dict(row);status=200;title=item['title'];description=item.get('short_description') or item.get('description') or 'Учебный контент клуба Nastaŭnik.'
            private=private or (kind!='track' and not item.get('is_free'));cover=item.get('cover_url') or ''
            if kind=='material' and item.get('is_free'):
                from bot.learning_admin_v2 import clean_rich_text
                body=signed_text(site.mini.bot_token,clean_rich_text(item.get('full_description') or ''))
            elif kind=='course' and item.get('is_free'): body='<p>'+escape(description)+'</p>'
    if status==404: body='<p>Страница не существует или больше не опубликована.</p><a href="/library">Перейти в библиотеку →</a>'
    canonical=ORIGIN+path
    if path=='/library' and request.query.get('type') in {'materials','courses'}: canonical+='?type='+request.query['type']
    title+=' — Nastaŭnik'
    meta='<meta name="description" content="'+escape(description,quote=True)+'"><link rel="canonical" href="'+escape(canonical,quote=True)+'">'
    for key,value in [('og:type','article' if path.startswith('/material/') else 'website'),('og:title',title),('og:description',description),('og:url',canonical),('og:site_name','Nastaŭnik')]: meta+='<meta property="'+key+'" content="'+escape(value,quote=True)+'">'
    if cover.startswith('/mini-app/media/'): meta+='<meta property="og:image" content="'+escape(ORIGIN+signed_text(site.mini.bot_token,cover),quote=True)+'">'
    if private or status==404: meta+='<meta name="robots" content="noindex, nofollow">'
    flags='window.NASTAUNIK_SITE_NOT_FOUND='+str(status==404).lower()+';'
    if path in INFO: flags+='window.NASTAUNIK_SITE_INFO='+json.dumps({'title':title.split(' — ')[0],'body':body},ensure_ascii=False).replace('</','<\\/')+';'
    return dict(title=title,metadata=meta,status=status,body=body,flags=flags)
