from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from cachetools import TTLCache
import time
from locales import get_text
from core.utils import get_event_user

class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, rate_limit: float = 1.0):
        self.rate_limit = rate_limit
        self.cache = TTLCache(maxsize=10000, ttl=rate_limit)

    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:

        # Повідомлення про оплату не можна відкидати: якщо користувач надіслав будь-що
        # за секунду до нього, throttling «з'їдав» successful_payment — гроші списані,
        # а покупка не видана.
        if isinstance(event, Message) and event.successful_payment:
            return await handler(event, data)

        user_id = None
        if isinstance(event, (Message, CallbackQuery)):
            # Для guest_message рахуємо того, хто покликав бота, а не самого бота.
            user = get_event_user(event)
            user_id = user.id if user else None

        if user_id:
            if user_id in self.cache:
                # Spam detected, ignore the event
                if isinstance(event, CallbackQuery):
                    from database import get_or_create_user
                    user = await get_or_create_user(user_id, event.from_user.username, event.from_user.full_name)
                    lang = user.get('language_code', 'en')
                    await event.answer(get_text(lang, 'too_fast'), show_alert=False)
                return
            else:
                self.cache[user_id] = time.time()

        return await handler(event, data)
