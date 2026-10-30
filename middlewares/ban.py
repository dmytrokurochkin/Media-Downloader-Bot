import logging
from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, InlineQuery
from typing import Callable, Dict, Any, Awaitable
from cachetools import TTLCache
from database import get_or_create_user, update_last_active
from locales import get_text
from core.utils import detect_language, get_event_user
import datetime

logger = logging.getLogger(__name__)

# Кеші з TTL замість звичайних dict: ті росли з кожним новим користувачем і ніколи
# не чистились. Запис живе рівно стільки, скільки триває відповідний кулдаун.
BAN_NOTIFICATION_COOLDOWN = datetime.timedelta(hours=1)
BANNED_NOTIFIED_CACHE = TTLCache(maxsize=10_000, ttl=BAN_NOTIFICATION_COOLDOWN.total_seconds())

# Кеш для зменшення навантаження на БД при оновленні last_active_at
ACTIVE_UPDATE_COOLDOWN = datetime.timedelta(minutes=5)
LAST_ACTIVE_CACHE = TTLCache(maxsize=100_000, ttl=ACTIVE_UPDATE_COOLDOWN.total_seconds())

class BanCheckMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[Any, Dict[str, Any]], Awaitable[Any]],
        event: Any,
        data: Dict[str, Any]
    ) -> Any:
        
        # Оплата вже відбулась (pre_checkout відхиляє покупки забанених) — її треба
        # зарахувати, а не відкинути разом з іншими повідомленнями забаненого.
        if isinstance(event, Message) and event.successful_payment:
            return await handler(event, data)

        # Get user object from event
        user = None
        if isinstance(event, (Message, CallbackQuery, InlineQuery)):
            # guest_message — теж Message, але from_user там сам бот (див. get_event_user):
            # без цього забанений користувач спокійно качав через гостьовий режим.
            user = get_event_user(event)
        is_guest = bool(getattr(event, "guest_query_id", None))
            
        if user:
            # We fetch or create the user to check their ban status
            # Full name might be empty
            full_name = user.full_name if user.full_name else ""
            username = user.username if user.username else ""
            # Мова нового користувача — з його Telegram-клієнта, а не завжди англійська.
            language = detect_language(getattr(user, "language_code", None))
            db_user = await get_or_create_user(user.id, username, full_name, language)
            
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            
            # Update user's last activity timestamp (із захистом від спаму запитів у БД)
            if user.id not in LAST_ACTIVE_CACHE:
                await update_last_active(user.id)
                LAST_ACTIVE_CACHE[user.id] = now_dt
            
            # Check bot ban
            ban_until_dt = None
            if db_user.get('banned_bot_until'):
                from core.utils import parse_db_date
                ban_until_dt = parse_db_date(db_user['banned_bot_until'])  # None, якщо дата бита

            if ban_until_dt and now_dt < ban_until_dt:
                # Користувач забанений: апдейт далі не йде НІКОЛИ. Раніше збій відправки
                # сповіщення (застарілий callback, бот заблокований) ловився спільним
                # except, і хендлер виконувався для забаненого.
                if user.id not in BANNED_NOTIFIED_CACHE:
                    BANNED_NOTIFIED_CACHE[user.id] = now_dt
                    try:
                        await self._notify_banned(event, db_user, ban_until_dt, is_guest)
                    except Exception as e:
                        logger.info("Could not notify banned user %s: %s", user.id, e)
                return

        return await handler(event, data)

    @staticmethod
    async def _notify_banned(event, db_user: dict, ban_until_dt: datetime.datetime, is_guest: bool) -> None:
        lang = db_user['language_code']
        formatted_date = ban_until_dt.strftime("%Y-%m-%d %H:%M UTC")
        if ban_until_dt.year == 9999:
            formatted_date = get_text(lang, 'forever_label')

        ban_msg = get_text(lang, 'banned_bot', until=formatted_date)
        plain_ban_msg = ban_msg.replace('<b>', '').replace('</b>', '')

        if is_guest or isinstance(event, InlineQuery):
            from aiogram.types import InlineQueryResultArticle, InputTextMessageContent
            import uuid
            res = InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="⛔️",
                description=plain_ban_msg[:200],
                input_message_content=InputTextMessageContent(message_text=ban_msg, parse_mode="HTML")
            )
            if is_guest:
                # У гостьовому режимі звичайна відповідь неможлива — лише answer_guest_query.
                await event.answer_guest_query(result=res)
            else:
                await event.answer([res], cache_time=0, is_personal=True)
        elif isinstance(event, Message):
            await event.reply(ban_msg, parse_mode="HTML")
        elif isinstance(event, CallbackQuery):
            await event.answer(plain_ban_msg[:200], show_alert=True)
