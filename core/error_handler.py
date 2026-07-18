import asyncio
import traceback
from datetime import datetime
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from core.config import ERROR_LOG_CHANNEL_ID
from core.utils import delete_later
from locales import get_text

async def handle_media_error(e: Exception, bot, status_msg, url: str, user: dict, lang: str, is_guest_mode: bool):
    """
    Centralized error handler for media downloads.
    Handles size limits, unsupported URLs (PDF fallback), and general errors.
    """
    if is_guest_mode:
        return  # Тиша при помилках в гостьовому режимі
        
    error_msg = str(e)
    
    if "SIZE_LIMIT_EXCEEDED" in error_msg:
        try:
            await bot.edit_message_text(get_text(lang, 'size_limit_exceeded'), chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            asyncio.create_task(delete_later(bot, status_msg.chat.id, status_msg.message_id, 30))
        except Exception: pass
        return
        
    if len(error_msg) > 3000:
        error_msg = error_msg[:3000] + "...\n[Error truncated]"
        
    if "unsupported url" in error_msg.lower():
        try:
            markup = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="📄 Зберегти як PDF", callback_data="article_pdf")
            ]])
            text = f"⚠️ Не знайдено відео чи аудіо за цим посиланням. Можливо, це текстова стаття? Бажаєте зберегти її як PDF для читання офлайн?\n\n🔗 {url}"
            await bot.edit_message_text(text, chat_id=status_msg.chat.id, message_id=status_msg.message_id, reply_markup=markup)
        except Exception:
            pass
        return
        
    try:
        await bot.edit_message_text(get_text(lang, 'download_error', error=error_msg), chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        asyncio.create_task(delete_later(bot, status_msg.chat.id, status_msg.message_id, 30))
    except Exception:
        pass
        
    if ERROR_LOG_CHANNEL_ID:
        try:
            tb = traceback.format_exc()
            report_content = f"# Critical Download Error\n\n"
            report_content += f"**Time:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            report_content += f"**User ID:** `{user['telegram_id']}`\n"
            report_content += f"**Username:** @{user.get('username', 'None')}\n"
            report_content += f"**Name:** {user.get('full_name', 'None')}\n"
            report_content += f"**URL:** `{url}`\n\n"
            report_content += f"## Traceback\n```python\n{tb}\n```"
            
            doc = BufferedInputFile(report_content.encode('utf-8'), filename=f"error_{user['telegram_id']}.md")
            caption = f"🚨 <b>Критична помилка завантаження!</b>\n\n👤 Користувач: <a href='tg://user?id={user['telegram_id']}'>{user.get('full_name', 'Unknown')}</a>\n🔗 Посилання: <code>{url}</code>"
            await bot.send_document(chat_id=ERROR_LOG_CHANNEL_ID, document=doc, caption=caption, parse_mode="HTML")
        except Exception:
            pass
