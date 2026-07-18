from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineQuery
from typing import Callable, Dict, Any, Awaitable
from database import get_or_create_user, update_last_active
from locales import get_text
import datetime

# Кеш для кулдауну повідомлень про бан (user_id -> datetime)
BANNED_NOTIFIED_CACHE = {}
BAN_NOTIFICATION_COOLDOWN = datetime.timedelta(hours=1) # 1 година кулдауну

class BanCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        
        # Get user object from event
        user = None
        if isinstance(event, (Message, CallbackQuery, InlineQuery)):
            user = event.from_user
            
        if user:
            # We fetch or create the user to check their ban status
            # Full name might be empty
            full_name = user.full_name if user.full_name else ""
            username = user.username if user.username else ""
            db_user = await get_or_create_user(user.id, username, full_name)
            
            # Update user's last activity timestamp
            await update_last_active(user.id)
            
            # Check bot ban
            if db_user.get('banned_bot_until'):
                from core.utils import parse_db_date
                try:
                    ban_until_dt = parse_db_date(db_user['banned_bot_until'])
                        
                    now_dt = datetime.datetime.now(datetime.timezone.utc)
                    if now_dt < ban_until_dt:
                        # User is banned.
                        # Stop propagation, but only notify if cooldown has passed
                        last_notified = BANNED_NOTIFIED_CACHE.get(user.id)
                        if last_notified and now_dt - last_notified < BAN_NOTIFICATION_COOLDOWN:
                            return # Ignore silently

                        # Calculate formatted string to show
                        formatted_date = ban_until_dt.strftime("%Y-%m-%d %H:%M")
                        if ban_until_dt.year == 9999:
                            formatted_date = "Назавжди / Forever"
                            
                        ban_msg = get_text(db_user['language_code'], 'banned_bot', until=formatted_date)
                        
                        if isinstance(event, Message):
                            await event.reply(ban_msg, parse_mode="HTML")
                        elif isinstance(event, CallbackQuery):
                            clean_msg = ban_msg.replace('<b>', '').replace('</b>', '')
                            await event.answer(clean_msg, show_alert=True)
                        elif isinstance(event, InlineQuery):
                            from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
                            import uuid
                            res = InlineQueryResultArticle(
                                id=str(uuid.uuid4()),
                                title="⛔️ Доступ заборонено",
                                description="Ваш акаунт заблоковано.",
                                input_message_content=InputTextMessageContent(message_text=ban_msg, parse_mode="HTML")
                            )
                            await event.answer([res])
                            
                        # Update cache
                        BANNED_NOTIFIED_CACHE[user.id] = now_dt
                        
                        # Stop propagation
                        return
                except Exception as e:
                    print(f"Помилка перевірки бану для {user.id}: {e}")
                    
        return await handler(event, data)
