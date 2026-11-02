import asyncio
import logging

from aiogram.types import ErrorEvent

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
logger = logging.getLogger(__name__)


async def on_error(event: ErrorEvent):
    # Без глобального обробника aiogram лише друкує traceback, а користувач лишається
    # без відповіді. Тут — єдине місце, де видно КОЖНУ необроблену помилку хендлера.
    logger.error("Unhandled error while processing update %s", event.update.update_id, exc_info=event.exception)
    return True


async def main():
    await init_db_connection()
    await init_db()

    # Залишки сесій, перерваних попереднім рестартом. Безпечно лише тут: жодне
    # завантаження ще не почалось.
    from core.utils import cleanup_stale_downloads
    removed = cleanup_stale_downloads()
    if removed:
        logging.info("Removed %d stale download session(s)", removed)
    
    # Підключення роутерів
    dp.include_router(user_router)
    dp.include_router(admin_router)
    dp.include_router(payment_router)
    dp.include_router(media_router)
    dp.errors.register(on_error)
    
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
    # Спершу зупиняємо API, потім закриваємо БД, якою користуються його хендлери.
    dp.shutdown.register(runner.cleanup)
    dp.shutdown.register(close_db_connection)
    logging.info("API Server started on %s:%s", API_HOST, API_PORT)
    
    # Запуск фонової задачі для retention (утримання). spawn тримає посилання на задачу,
    # інакше збирач сміття міг прибрати її посеред сну на добу.
    from core.utils import spawn
    spawn(retention_drip_campaign(bot))
    
    await dp.start_polling(bot, allowed_updates=allowed)

if __name__ == '__main__':
    asyncio.run(main())