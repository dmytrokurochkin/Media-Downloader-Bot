from aiohttp import web
import aiohttp_cors
from database import search_users_query, get_public_profile

async def search_users_handler(request: web.Request) -> web.Response:
    query = request.query.get('q', '').strip()
    if not query:
        return web.json_response({'error': 'Missing query parameter "q"'}, status=400)
    
    results = await search_users_query(query)
    return web.json_response({'results': results})

async def get_profile_handler(request: web.Request) -> web.Response:
    user_id_str = request.query.get('id', '')
    if not user_id_str.isdigit():
        return web.json_response({'error': 'Invalid user ID'}, status=400)
        
    profile = await get_public_profile(int(user_id_str))
    if not profile:
        return web.json_response({'error': 'Профіль приховано або не знайдено'}, status=404)
        
    return web.json_response({'profile': profile})

def create_api_app() -> web.Application:
    app = web.Application()
    app.router.add_get('/api/search_users', search_users_handler)
    app.router.add_get('/api/get_profile', get_profile_handler)
    
    # Serve static webapp files
    from pathlib import Path
    webapp_path = Path(__file__).parent.parent / 'webapp'
    if webapp_path.exists():
        app.router.add_static('/webapp', str(webapp_path))
    
    # Setup CORS
    import os
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
