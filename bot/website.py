from pathlib import Path
from aiohttp import web
from bot.website_auth import WebsiteAuth
from bot.website_pages import page_meta, security_headers
from html import escape

WEBSITE_DIR = Path(__file__).resolve().parent.parent/'website'
MINI_DIR = Path(__file__).resolve().parent.parent/'mini_app'


class Website:
    def __init__(self, mini):
        self.mini = mini
        self.auth = WebsiteAuth(mini)
        mini.website_auth = self.auth

    def register(self, app):
        self.auth.register(app)
        app.middlewares.append(security_headers)
        app.router.add_get('/site/static/{filename}', self.static)
        app.router.add_get('/site/', self.index)
        app.router.add_get('/site/{path:.*}', self.index)

    async def index(self, request):
        if request.path == '/site/' and any(k in request.query for k in ('material', 'course', 'lesson', 'section', 'analytics')):
            raise web.HTTPSeeOther('/admin/?'+request.query_string)
        meta = await page_meta(self, request)
        if isinstance(meta, web.Response):
            return meta
        html = (MINI_DIR/'index.html').read_text(encoding='utf-8')
        html = html.replace('<title>Nastaŭnik</title>', '<title>'+escape(meta['title'])+'</title>')
        html = html.replace('</head>', '<link rel="icon" type="image/png" sizes="32x32" href="/site/static/favicon-32.png?v=1"><link rel="icon" type="image/svg+xml" href="/site/static/favicon.svg?v=1"><link rel="apple-touch-icon" sizes="180x180" href="/site/static/apple-touch-icon.png?v=1"></head>')
        html = html.replace('</head>', meta['metadata']+'<script>'+meta['flags']+'</script></head>')
        if meta['body']:
            html = html.replace('<div class="loading">', '<article class="site-server-content"><h1>'+escape(meta['title'])+'</h1>'+meta['body']+'</article><div class="loading">',1)
        html = html.replace('<script src="https://telegram.org/js/telegram-web-app.js"></script>', '')
        html = html.replace('<script defer src="https://telegram.org/js/telegram-web-app.js"></script>', '')
        # BotFather's existing main-app URL may still point at the domain root.
        # Preserve Telegram's launch data and open the original Mini App there.
        html = html.replace('</head>', '<script>if(new URLSearchParams(location.hash.slice(1)).has("tgWebAppData")){location.replace("/mini-app/"+location.search+location.hash)}window.NASTAUNIK_SITE=true;</script><link rel="stylesheet" href="/site/static/site.css?v=7"></head>')
        html = html.replace('</body>', '<script defer src="/site/static/site.js?v=7"></script></body>')
        response = web.Response(text=html, status=meta['status'], content_type='text/html', headers={'Cache-Control': 'private, no-store', 'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin', 'X-Frame-Options': 'SAMEORIGIN'})
        return response

    async def static(self, request):
        filename = request.match_info['filename']
        if filename not in {'site.js', 'site.css', 'favicon.svg', 'favicon-32.png', 'apple-touch-icon.png'}:
            raise web.HTTPNotFound()
        return web.FileResponse(WEBSITE_DIR/filename, headers={'Cache-Control': 'public, max-age=31536000, immutable' if request.query.get('v') else 'no-cache'})
