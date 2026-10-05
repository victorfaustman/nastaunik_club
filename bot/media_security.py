"""Short-lived bearer URLs for media; only authorized responses issue them."""
import hashlib
import hmac
import json
import re
import time
from urllib.parse import urlencode
from aiohttp import web

MEDIA_PATTERN = re.compile(r'/mini-app/media/([A-Za-z0-9_.~-]+)(?:\?[^\s"<>]*)?')
ADMIN_COOKIE = 'nastaunik_media_admin'
TTL = 6 * 3600

def signature(secret, name, expires):
    return hmac.new(secret.encode(), f'media-v1:{name}:{expires}'.encode(), hashlib.sha256).hexdigest()

def token(secret, name):
    expires = int(time.time()) + TTL
    return str(expires), signature(secret, name, expires)

def valid(secret, name, expires, supplied):
    try:
        expires = int(expires)
    except (ValueError, TypeError):
        return False
    return int(time.time()) <= expires <= int(time.time()) + TTL and hmac.compare_digest(signature(secret, name, expires), supplied or '')

def signed_text(secret, text):
    def replace(match):
        expires, sig = token(secret, 'file:'+match[1])
        return '/mini-app/media/'+match[1]+'?'+urlencode({'expires': expires, 'sig': sig})
    return MEDIA_PATTERN.sub(replace, text)

def middleware(secret):
    trusted_fields = {'content','full_description','cover_url','preview_url','preview_poster_url','poster_url','url'}
    def sign_fields(value):
        if isinstance(value, list): return [sign_fields(item) for item in value]
        if isinstance(value, dict):
            return {key: signed_text(secret, item) if key in trusted_fields and isinstance(item, str) else sign_fields(item) for key,item in value.items()}
        return value
    @web.middleware
    async def secure_media_payload(request, handler):
        response = await handler(request)
        if isinstance(response, web.Response) and response.status == 200:
            if request.path.startswith('/mini-app/api/') and response.content_type == 'application/json':
                payload = json.loads(response.text)
                # Catalog thumbnails never grant access to a locked video's source.
                for item in payload.get('materials', []) if isinstance(payload, dict) else []:
                    if item.get('locked') and item.get('preview_kind') == 'video':
                        item['preview_url'] = None
                response.text = json.dumps(sign_fields(payload), ensure_ascii=False, separators=(',', ':'))
                response.headers['Cache-Control'] = 'private, no-store'
            elif request.path == '/mini-app/preview' and response.content_type == 'text/html':
                response.text = signed_text(secret, response.text)
        return response
    return secure_media_payload
