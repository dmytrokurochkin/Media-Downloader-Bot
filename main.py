import asyncio
import logging

from core.loader import bot, dp
from database import init_db, init_db_connection, close_db_connection
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.payment import payment_router
from handlers.media import media_router
from middlewares.ban import BanCheckMiddleware
from core.scheduler import retention_drip_campaign
from middlewares.throttling import ThrottlingMiddleware

logging.basicConfig(level=logging.INFO)

async def main():
    await init_db_connection()
    await init_db()
    
    dp.shutdown.register(close_db_connection)
    
    from core.config import MAX_CONCURRENT_DOWNLOADS
    import handlers.media
    handlers.media.download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    
    # Підключення роутерів
    dp.include_router(user_router)
    dp.include_router(admin_router)
    dp.include_router(payment_router)
    dp.include_router(media_router)
    
    # Підключення Middleware
    throttling = ThrottlingMiddleware(rate_limit=1.0)
    dp.message.outer_middleware(throttling)
    dp.callback_query.outer_middleware(throttling)
    dp.guest_message.outer_middleware(throttling)

    # guest_message — окремий тип апдейту: без явної реєстрації бан і троттлінг
    # на гостьовий режим не діяли взагалі.
    ban_middleware = BanCheckMiddleware()
    dp.message.outer_middleware(ban_middleware)
    dp.callback_query.outer_middleware(ban_middleware)
    dp.inline_query.outer_middleware(ban_middleware)
    dp.guest_message.outer_middleware(ban_middleware)

    allowed = dp.resolve_used_update_types()
    if "guest_message" not in allowed:
        allowed.append("guest_message")
        
    # Запуск aiohttp сервера
    from core.api import create_api_app, PathOnlyAccessLogger
    from core.config import API_HOST, API_PORT
    from aiohttp import web
    app = create_api_app()
    runner = web.AppRunner(app, access_log_class=PathOnlyAccessLogger)
    await runner.setup()
    site = web.TCPSite(runner, API_HOST, API_PORT, reuse_address=True)
    await site.start()
    logging.info("API Server started on %s:%s", API_HOST, API_PORT)
    
    # Запуск фонової задачі для retention (утримання)
    asyncio.create_task(retention_drip_campaign(bot))
    
    await dp.start_polling(bot, allowed_updates=allowed)

if __name__ == '__main__':
    asyncio.run(main())