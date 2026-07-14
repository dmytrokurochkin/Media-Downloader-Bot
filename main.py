import asyncio
import logging
import os
from aiogram.filters import CommandStart
from aiogram import F

from core.config import BOT_TOKEN
from core.loader import bot, dp
from database import init_db
from handlers.user import user_router
from handlers.admin import admin_router
from handlers.payment import payment_router
from handlers.media import media_router
from middlewares.ban import BanCheckMiddleware
from middlewares.throttling import ThrottlingMiddleware

logging.basicConfig(level=logging.INFO)

async def main():
    print("Ініціалізація бази даних...")
    await init_db()
    
    import handlers.media
    handlers.media.download_semaphore = asyncio.Semaphore(3)
    
    # Підключення роутерів
    dp.include_router(user_router)
    dp.include_router(admin_router)
    dp.include_router(payment_router)
    dp.include_router(media_router)
    
    # Підключення Middleware
    throttling = ThrottlingMiddleware(rate_limit=1.0)
    dp.message.outer_middleware(throttling)
    dp.callback_query.outer_middleware(throttling)
    
    ban_middleware = BanCheckMiddleware()
    dp.message.outer_middleware(ban_middleware)
    dp.callback_query.outer_middleware(ban_middleware)
    dp.inline_query.outer_middleware(ban_middleware)

    allowed = dp.resolve_used_update_types()
    if "guest_message" not in allowed:
        allowed.append("guest_message")
    await dp.start_polling(bot, allowed_updates=allowed)

if __name__ == '__main__':
    asyncio.run(main())