from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery
from typing import Callable, Dict, Any, Awaitable
from cachetools import TTLCache
import time

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
        
        user_id = None
        if isinstance(event, (Message, CallbackQuery)):
            user_id = event.from_user.id
            
        if user_id:
            if user_id in self.cache:
                # Spam detected, ignore the event
                if isinstance(event, CallbackQuery):
                    await event.answer("⚠️ Занадто швидко!", show_alert=False)
                return
            else:
                self.cache[user_id] = time.time()
                
        return await handler(event, data)
