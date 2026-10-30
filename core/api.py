import os
from pathlib import Path

from aiohttp import web
from aiohttp.abc import AbstractAccessLogger
import aiohttp_cors

from database import search_users_query, get_public_profile
from core.telegram_auth import validate_init_data

SEARCH_MIN_LEN = 2
SEARCH_MAX_LEN = 64


def extract_init_data(request: web.Request) -> str:
    """initData з заголовка `Authorization: tma <initData>`.

    Query-параметр `initData` лишився як запасний варіант для старої закешованої
    версії Mini App, але новий фронтенд шле лише заголовок: query потрапляє в
    access-логи (сервера, ngrok), а initData дійсний 24 години.
    """
    auth = request.headers.get('Authorization', '')
    if auth.startswith('tma '):
        return auth[4:].strip()
    return request.query.get('initData', '')


def _require_valid_init_data(request: web.Request) -> bool:
    return validate_init_data(extract_init_data(request))


async def search_users_handler(request: web.Request) -> web.Response:
    if not _require_valid_init_data(request):
        return web.json_response({'error': 'Unauthorized'}, status=401)

    query = request.query.get('q', '').strip()
    if not query:
        return web.json_response({'error': 'Missing query parameter "q"'}, status=400)
    # Мінімальна довжина: інакше однією літерою можна було б вивантажувати всіх по черзі.
    if len(query) < SEARCH_MIN_LEN or len(query) > SEARCH_MAX_LEN:
        return web.json_response({'error': 'Query length must be between 2 and 64'}, status=400)

    results = await search_users_query(query)
    return web.json_response({'results': results})

async def get_profile_handler(request: web.Request) -> web.Response:
    if not _require_valid_init_data(request):
        return web.json_response({'error': 'Unauthorized'}, status=401)

    user_id_str = request.query.get('id', '')
    if not user_id_str.isdigit():
        return web.json_response({'error': 'Invalid user ID'}, status=400)

    profile = await get_public_profile(int(user_id_str))
    if not profile:
        return web.json_response({'error': 'Profile is hidden or not found'}, status=404)

    return web.json_response({'profile': profile})


class PathOnlyAccessLogger(AbstractAccessLogger):
    """Access-лог без query string: у ній бувають initData та пошукові запити користувачів."""

    def log(self, request, response, time):
        self.logger.info('%s %s %s %.3fs', request.method, request.path, response.status, time)


def create_api_app() -> web.Application:
    app = web.Application()
    app.router.add_get('/api/search_users', search_users_handler)
    app.router.add_get('/api/get_profile', get_profile_handler)

    # Serve static webapp files
    webapp_path = Path(__file__).parent.parent / 'webapp'
    if webapp_path.exists():
        app.router.add_static('/webapp', str(webapp_path))

    # Setup CORS
    allowed_origins = os.getenv("ALLOWED_CORS_ORIGINS", "https://dmytrokurochkin.github.io,https://mrmozozavr.github.io").split(",")

    defaults = {}
    for origin in allowed_origins:
        defaults[origin.strip()] = aiohttp_cors.ResourceOptions(
            allow_credentials=True,
            expose_headers="*",
            allow_headers="*",
        )

    cors = aiohttp_cors.setup(app, defaults=defaults)

    for route in list(app.router.routes()):
        cors.add(route)

    return app
