import asyncio
import html
import logging
import re
import traceback
import uuid
from datetime import datetime, timezone

from aiogram.types import BufferedInputFile, InlineQueryResultArticle, InputTextMessageContent

from core.config import ERROR_LOG_CHANNEL_ID
from core.utils import delete_later
from locales import get_text

logger = logging.getLogger(__name__)


def classify_media_error(e: Exception):
    """Повертає (ключ локалі або None, чи слати звіт у канал помилок).

    Відмови за політикою (ліміт розміру, приватна мережа, таймаут) — не баги,
    тож у канал помилок їх не шлемо, а користувач отримує зрозумілий текст.
    """
    from aiogram.exceptions import TelegramEntityTooLarge
    from core.net_guard import ResponseTooLargeError, UnsafeURLError
    from downloader import DownloadTimeoutError, SizeLimitExceeded

    if isinstance(e, UnsafeURLError):
        return 'unsafe_url', False
    if isinstance(e, (SizeLimitExceeded, ResponseTooLargeError, TelegramEntityTooLarge)) or "SIZE_LIMIT_EXCEEDED" in str(e):
        return 'size_limit_exceeded', False
    if isinstance(e, DownloadTimeoutError):
        return 'download_timeout', False
    return None, True


async def _answer_guest_with_error(message, text: str) -> None:
    # Гостьовий запит треба закрити відповіддю, інакше в того, хто покликав бота, висить завантаження.
    if not message or not getattr(message, "guest_query_id", None):
        return
    plain = re.sub(r'<[^>]+>', '', text)
    try:
        await message.answer_guest_query(result=InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title=plain.split('\n', 1)[0][:64] or "⚠️",
            description=plain[:200],
            input_message_content=InputTextMessageContent(message_text=text),
        ))
    except Exception as answer_error:
        logger.debug("Could not answer guest query with error: %s", answer_error)


async def handle_media_error(e: Exception, bot, status_msg, url: str, user: dict, lang: str, is_guest_mode: bool, message=None):
    """
    Centralized error handler for media downloads.
    Handles size limits, unsafe URLs, timeouts and general errors.
    """
    key, should_report = classify_media_error(e)
    if should_report:
        logger.error("Download failed for %s (%s)", user.get('telegram_id'), url, exc_info=e)

    if key:
        text = get_text(lang, key)
    else:
        error_msg = str(e) or type(e).__name__
        if len(error_msg) > 3000:
            error_msg = error_msg[:3000] + "...\n[Error truncated]"
        text = get_text(lang, 'download_error', error=html.escape(error_msg))

    if is_guest_mode:
        await _answer_guest_with_error(message, text)
    else:
        try:
            if status_msg is not None:
                await bot.edit_message_text(text, chat_id=status_msg.chat.id, message_id=status_msg.message_id)
                notice = status_msg
            elif message is not None:
                # Статус-повідомлення могло не відправитись (флуд-ліміт тощо) — тоді відповідаємо напряму.
                notice = await message.reply(text)
            else:
                notice = None
            if notice is not None:
                asyncio.create_task(delete_later(bot, notice.chat.id, notice.message_id, 30))
        except Exception as notify_error:
            logger.debug("Could not notify user about download error: %s", notify_error)

    if should_report and ERROR_LOG_CHANNEL_ID:
        try:
            tb = "".join(traceback.format_exception(e))
            report_content = "# Critical Download Error\n\n"
            report_content += f"**Time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
            report_content += f"**User ID:** `{user['telegram_id']}`\n"
            report_content += f"**Username:** @{user.get('username', 'None')}\n"
            report_content += f"**Name:** {user.get('full_name', 'None')}\n"
            report_content += f"**URL:** `{url}`\n\n"
            report_content += f"## Traceback\n```python\n{tb}\n```"

            doc = BufferedInputFile(report_content.encode('utf-8'), filename=f"error_{user['telegram_id']}.md")
            # Ім'я та URL — дані користувача: без екранування `<` у них ламав HTML, і звіт губився.
            caption = (
                f"🚨 <b>Критична помилка завантаження!</b>\n\n"
                f"👤 Користувач: <a href='tg://user?id={user['telegram_id']}'>{html.escape(user.get('full_name') or 'Unknown')}</a>\n"
                f"🔗 Посилання: <code>{html.escape(url[:500])}</code>"
            )
            await bot.send_document(chat_id=ERROR_LOG_CHANNEL_ID, document=doc, caption=caption, parse_mode="HTML")
        except Exception as report_error:
            logger.warning("Could not send error report: %s", report_error)
