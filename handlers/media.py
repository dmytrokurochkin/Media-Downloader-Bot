import asyncio
import os
import re
import time
import uuid
from pathlib import Path
from core.utils import delete_later

import aiohttp
from bs4 import BeautifulSoup

from aiogram import Router, F, Bot
from aiogram.types import (
    Message, CallbackQuery, FSInputFile, InputMediaPhoto, InputMediaVideo, 
    InputMediaAudio, InputMediaDocument, InlineQueryResultCachedVideo,
    InlineQueryResultCachedAudio, InlineQueryResultCachedDocument, InlineQueryResultCachedPhoto, InlineQueryResultArticle, InputTextMessageContent
)

from core.config import URL_PATTERN, FORBIDDEN_URL_PATTERN, TIER_LIMITS
from core.loader import bot
from database import get_or_create_user, get_daily_download_count, add_download_record
from downloader import download_media
from locales import get_text
from keyboards.inline import get_youtube_keyboard

media_router = Router()

# State variables
download_semaphore = None
active_downloads = 0
queue_waiters = 0
active_requests = 0
user_cooldowns = set()

class ProgressTracker:
    def __init__(self, message: Message, bot: Bot, lang: str):
        self.message = message
        self.bot = bot
        self.lang = lang
        self.last_update_time = 0
        self.last_percent = -1

    async def update(self, percent: float):
        if not self.message:
            return
            
        now = time.time()
        
        # Жорсткий ліміт: ніяких оновлень частіше ніж раз на 2 секунди
        if now - self.last_update_time < 2.0:
            return
            
        # Оновлення не частіше 4 секунд, або на важливих відсотках
        important_percents = [10, 25, 50, 75, 100]
        is_important = any(abs(percent - p) < 2 for p in important_percents)
        
        if now - self.last_update_time > 4.0 or (is_important and abs(percent - self.last_percent) >= 5) or percent == 100:
            text = get_text(self.lang, 'starting_download').replace('...', f" {percent:.1f}%")
            
            # Оновлюємо стан ДО виклику API, щоб у разі помилки "Message not modified" 
            # не виникав нескінченний цикл спаму запитами
            self.last_update_time = now
            self.last_percent = percent
            
            try:
                await self.bot.edit_message_text(
                    text, 
                    chat_id=self.message.chat.id, 
                    message_id=self.message.message_id
                )
            except Exception:
                pass

async def get_page_title(url: str) -> str:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=5) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')
                    title = soup.find('title')
                    if title and title.text:
                        return title.text.strip()[:100]
    except Exception:
        pass
    return "Unknown"

@media_router.guest_message()
async def guest_text_handler(message: Message):
    caller = getattr(message, "guest_bot_caller_user", None) or message.from_user
    text = (message.text or message.caption or "").strip()
    
    bot_me = await bot.get_me()
    bot_username = f"@{bot_me.username}" if bot_me.username else ""
    if bot_username:
        text = text.replace(bot_username, "").strip()
        
    url = None
    match = URL_PATTERN.search(text)
    if match:
        url = match.group(0)
    elif message.reply_to_message and (message.reply_to_message.text or message.reply_to_message.caption):
        match = URL_PATTERN.search(message.reply_to_message.text or message.reply_to_message.caption)
        if match:
            url = match.group(0)
            
    if not url:
        return
        
    user = await get_or_create_user(caller.id, getattr(caller, "username", ""), getattr(caller, "full_name", ""))
    
    if FORBIDDEN_URL_PATTERN.search(url) or caller.id in user_cooldowns:
        if caller.id in user_cooldowns:
            try:
                result_article = InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title="⏳ Зачекайте!",
                    description=get_text(user['language_code'], 'cooldown'),
                    input_message_content=InputTextMessageContent(
                        message_text=get_text(user['language_code'], 'cooldown')
                    )
                )
                await message.answer_guest_query(result=result_article)
            except Exception as e:
                print(f"Guest cooldown error: {e}")
        return
        
    daily_count = await get_daily_download_count(caller.id)
    if daily_count >= TIER_LIMITS[user['tier']]['daily']:
        return
        
    await process_url(message, url, user, is_guest_mode=True)

@media_router.message(F.text)
async def text_handler(message: Message):
    bot_me = await bot.get_me()
    username = f"@{bot_me.username}" if bot_me.username else ""
    is_guest_mode = username in message.text if username else False
    
    url = None
    match = URL_PATTERN.search(message.text)
    if match:
        url = match.group(0)
    elif is_guest_mode and message.reply_to_message and message.reply_to_message.text:
        match = URL_PATTERN.search(message.reply_to_message.text)
        if match:
            url = match.group(0)
            
    if url:
        
        is_private = message.chat.type == "private"
        
        # Очищуємо URL, якщо користувач прикріпив тег бота без пробілу
        if bot_me.username and url.endswith(f"@{bot_me.username}"):
            url = url[:-len(f"@{bot_me.username}")]
        
        user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        
        if not is_guest_mode:
            if FORBIDDEN_URL_PATTERN.search(url):
                msg = await message.reply(get_text(user['language_code'], 'link_rejected'))
                asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
                return
            if message.from_user.id in user_cooldowns:
                msg = await message.reply(get_text(user['language_code'], 'cooldown'))
                asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
                return
            daily_count = await get_daily_download_count(message.from_user.id)
            if daily_count >= TIER_LIMITS[user['tier']]['daily']:
                msg = await message.reply(get_text(user['language_code'], 'limit_reached'))
                asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
                return
        else:
            if FORBIDDEN_URL_PATTERN.search(url) or message.from_user.id in user_cooldowns:
                if message.from_user.id in user_cooldowns:
                    try:
                        msg = await message.reply(get_text(user['language_code'], 'cooldown'))
                        asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
                    except Exception: pass
                return
            daily_count = await get_daily_download_count(message.from_user.id)
            if daily_count >= TIER_LIMITS[user['tier']]['daily']:
                return
                
        await process_url(message, url, user, is_guest_mode=is_guest_mode)

async def process_url(message: Message, url: str, user: dict, is_guest_mode: bool = False):
    if 'threads.com' in url:
        url = url.replace('threads.com', 'threads.net')
        
    is_audio_service = any(x in url for x in ['music.youtube.com', 'spotify.com', 'soundcloud.com', 'apple.com/music', 'deezer.com'])
    
    if is_audio_service:
        await start_download(message, url, 'bestaudio/best', user, is_guest_mode=is_guest_mode)
    elif 'youtube.com' in url or 'youtu.be' in url:
        if is_guest_mode:
            quality = user.get('guest_yt_quality', 'best')
            tier = user.get('tier', 'free')
            if tier == 'free' and quality in ['best', '1080p']:
                quality = '720p'
            elif tier == 'pro' and quality == 'best':
                quality = '1080p'
                
            if quality == '1080p':
                fmt = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best'
            elif quality == '720p':
                fmt = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best'
            elif quality == '480p':
                fmt = 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480][ext=mp4]/best'
            elif quality == '360p':
                fmt = 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360][ext=mp4]/best'
            elif quality == 'audio':
                fmt = 'bestaudio/best'
            else:
                fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
            await start_download(message, url, fmt, user, is_guest_mode=True)
        else:
            await message.reply(
                get_text(user['language_code'], 'choose_yt_quality', url=url),
                reply_markup=get_youtube_keyboard(url, user['language_code']),
                disable_web_page_preview=True
            )
    else:
        tier = user.get('tier', 'free')
        if tier == 'free':
            fmt = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best'
        elif tier == 'pro':
            fmt = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[height<=1080][ext=mp4]/best'
        else:
            fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
        await start_download(message, url, fmt, user, is_guest_mode=is_guest_mode)

@media_router.callback_query(F.data.startswith("yt_"))
async def youtube_callback(callback: CallbackQuery):
    await callback.answer()
    
    action = callback.data.split('_')[1]
    
    text_parts = callback.message.text.split("🔗 ")
    if len(text_parts) < 2:
        await callback.message.edit_text("URL Error")
        return
    url = text_parts[1].strip()
    
    format_spec = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    if action == '1080':
        format_spec = 'bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4][height<=1080]/best'
    elif action == '720':
        format_spec = 'bestvideo[ext=mp4][height<=720]+bestaudio[ext=m4a]/best[ext=mp4][height<=720]/best'
    elif action == '360':
        format_spec = 'bestvideo[ext=mp4][height<=360]+bestaudio[ext=m4a]/best[ext=mp4][height<=360]/best'
    elif action == 'audio':
        format_spec = 'bestaudio/best'
        
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    tier = user.get('tier', 'free')
    
    if tier == 'free' and action in ['1080', 'best']:
        msg = await callback.message.reply(get_text(user['language_code'], 'quality_limit'))
        asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
        return
    if tier == 'pro' and action == 'best':
        msg = await callback.message.reply(get_text(user['language_code'], 'quality_limit'))
        asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
        return
        
    if callback.from_user.id in user_cooldowns:
        msg = await callback.message.reply(get_text(user['language_code'], 'cooldown'))
        asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
        return
        
    daily_count = await get_daily_download_count(callback.from_user.id)
    if daily_count >= TIER_LIMITS[user['tier']]['daily']:
        msg = await callback.message.reply(get_text(user['language_code'], 'limit_reached'))
        asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
        return
        
    await callback.message.edit_text(get_text(user['language_code'], 'starting_download'))
    await start_download(callback.message, url, format_spec, user, is_callback=True)

async def start_download(message: Message, url: str, format_spec: str, user: dict, is_callback: bool = False, is_guest_mode: bool = False):
    lang = user['language_code']
    target_chat = getattr(message, "guest_bot_caller_chat", None) or message.chat
    target_chat_id = target_chat.id if is_guest_mode else message.chat.id
    
    global queue_waiters, active_requests
    
    in_queue = False
    in_queue_cleared = False
    
    if active_requests >= 3:
        in_queue = True
        queue_waiters += 1
        pos = queue_waiters
        status_text = get_text(lang, 'in_queue', pos=pos)
    else:
        status_text = get_text(lang, 'starting_download')
        
    active_requests += 1
    
    status_msg = None
    if not is_guest_mode:
        if is_callback:
            status_msg = message
            if in_queue:
                try:
                    await bot.edit_message_text(status_text, chat_id=status_msg.chat.id, message_id=status_msg.message_id)
                except Exception:
                    pass
        else:
            try:
                status_msg = await message.reply(status_text)
            except Exception:
                status_msg = await bot.send_message(target_chat_id, status_text)
            
    tracker = ProgressTracker(status_msg, bot, lang) if not is_guest_mode else None
    
    user_cooldowns.add(user['telegram_id'])
    
    filepath = None
    success = False
    file_size = 0
    domain = re.search(r'https?://([^/]+)', url).group(1) if re.search(r'https?://([^/]+)', url) else "unknown"
    page_title = await get_page_title(url)
    
    try:
        async with download_semaphore:
            if in_queue:
                in_queue_cleared = True
                queue_waiters -= 1
                if not is_guest_mode:
                    try:
                        await bot.edit_message_text(get_text(lang, 'starting_download'), chat_id=status_msg.chat.id, message_id=status_msg.message_id)
                    except Exception:
                        pass
                    
            tracker_update = tracker.update if tracker else None
            filepath = await download_media(url, format_spec, tracker_update, tier=user['tier'])
        
        if not is_guest_mode:
            try:
                await asyncio.sleep(2.0)
                await bot.edit_message_text(get_text(lang, 'downloaded_sending'), chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            except Exception:
                pass
                
        if isinstance(filepath, list):
            # Filter out metadata files before checking if it's a single item
            valid_exts = ['.mp4', '.mkv', '.webm', '.jpg', '.jpeg', '.png', '.webp', '.mp3', '.m4a', '.wav', '.opus']
            media_files = [p for p in filepath if p.suffix.lower() in valid_exts]
            if len(media_files) == 1:
                filepath = media_files[0]
            elif len(media_files) > 1:
                filepath = media_files
                
        if isinstance(filepath, list):
            visual_group = []
            audio_group = []
            document_group = []
            
            # Гостьовий режим: ліміт 10 файлів загалом
            if is_guest_mode:
                filepath = filepath[:10]
            
            caption = get_text(lang, 'caption_signature')

            for path in filepath:
                file_size += path.stat().st_size
                fs_file = FSInputFile(path=path, filename=path.name)
                ext = path.suffix.lower()
                if ext in ['.mp4', '.mkv', '.webm']:
                    visual_group.append(InputMediaVideo(media=fs_file, caption=caption if not visual_group else None))
                elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    visual_group.append(InputMediaPhoto(media=fs_file, caption=caption if not visual_group else None))
                elif ext in ['.mp3', '.m4a', '.wav', '.opus']:
                    audio_group.append(InputMediaAudio(media=fs_file, caption=caption if not audio_group else None))
                elif ext not in ['.json', '.description', '.part', '.ytdl', '.spotdl']:
                    document_group.append(InputMediaDocument(media=fs_file, caption=caption if not document_group else None))
            
            async def send_group_in_chunks(group):
                if is_guest_mode:
                    group = group[:10]
                    try:
                        caller_id = user['telegram_id']
                        print(f"Guest mode: sending media group to caller DM {caller_id}...")
                        await bot.send_media_group(chat_id=caller_id, media=group)
                        
                        # Answer guest query with article
                        try:
                            result_article = InlineQueryResultArticle(
                                id=str(uuid.uuid4()),
                                title="✅ Альбом завантажено!",
                                description="Файли відправлено вам в особисті повідомлення.",
                                input_message_content=InputTextMessageContent(
                                    message_text="✅ Медіа успішно завантажено!\n👉 Перевірте ваші приватні повідомлення з ботом.",
                                    
                                )
                            )
                            await message.answer_guest_query(result=result_article)
                        except Exception as e:
                            print(f"Guest answer error: {e}")
                        print("Guest mode group sent to DM and answered query.")
                    except Exception as e:
                        print(f"Guest mode group send failed: {e}")
                    return

                for i in range(0, len(group), 10):
                    chunk = group[i:i+10]
                    try:
                        await bot.send_media_group(
                            chat_id=target_chat_id, 
                            media=chunk, 
                            reply_to_message_id=message.message_id if not is_callback else None, 
                            request_timeout=3600
                        )
                    except Exception:
                        await bot.send_media_group(chat_id=target_chat_id, media=chunk, request_timeout=3600)
            
            if visual_group: await send_group_in_chunks(visual_group)
            if audio_group: await send_group_in_chunks(audio_group)
            if document_group: await send_group_in_chunks(document_group)
            
        else:
            file_size = filepath.stat().st_size
            fs_file = FSInputFile(path=filepath, filename=filepath.name)
            if is_guest_mode:
                try:
                    caller_id = user['telegram_id']
                    print(f"Guest mode: uploading single file to caller DM {caller_id} to get file_id...")
                    caption = get_text(lang, 'caption_signature')
                    if filepath.suffix in ['.mp4', '.mkv', '.webm']:
                        res = await bot.send_video(chat_id=caller_id, video=fs_file, request_timeout=3600, caption=caption)
                        file_id = res.video.file_id
                        result_media = InlineQueryResultCachedVideo(id=str(uuid.uuid4()), video_file_id=file_id, title="Відео", caption=caption)
                    elif filepath.suffix in ['.jpg', '.jpeg', '.png', '.webp']:
                        res = await bot.send_photo(chat_id=caller_id, photo=fs_file, request_timeout=3600, caption=caption)
                        file_id = res.photo[-1].file_id
                        result_media = InlineQueryResultCachedPhoto(id=str(uuid.uuid4()), photo_file_id=file_id, caption=caption)
                    elif filepath.suffix in ['.mp3', '.m4a', '.wav']:
                        res = await bot.send_audio(chat_id=caller_id, audio=fs_file, request_timeout=3600, caption=caption)
                        file_id = res.audio.file_id
                        result_media = InlineQueryResultCachedAudio(id=str(uuid.uuid4()), audio_file_id=file_id, caption=caption)
                    else:
                        res = await bot.send_document(chat_id=caller_id, document=fs_file, request_timeout=3600, caption=caption)
                        file_id = res.document.file_id
                        result_media = InlineQueryResultCachedDocument(id=str(uuid.uuid4()), document_file_id=file_id, title="Документ", caption=caption)
                    
                    await message.answer_guest_query(result=result_media)
                    print(f"Guest mode single file sent successfully via answer_guest_query!")
                except Exception as e:
                    print(f"Guest mode single send failed: {e}")
            else:
                caption = get_text(lang, 'caption_signature')
                try:
                    if filepath.suffix in ['.mp4', '.mkv', '.webm']:
                        await bot.send_video(chat_id=target_chat_id, video=fs_file, reply_to_message_id=message.message_id if not is_callback else None, request_timeout=3600, caption=caption)
                    elif filepath.suffix in ['.mp3', '.m4a', '.wav']:
                        await bot.send_audio(chat_id=target_chat_id, audio=fs_file, reply_to_message_id=message.message_id if not is_callback else None, request_timeout=3600, caption=caption)
                    elif filepath.suffix in ['.jpg', '.jpeg', '.png', '.webp']:
                        await bot.send_photo(chat_id=target_chat_id, photo=fs_file, reply_to_message_id=message.message_id if not is_callback else None, request_timeout=3600, caption=caption)
                    else:
                        await bot.send_document(chat_id=target_chat_id, document=fs_file, reply_to_message_id=message.message_id if not is_callback else None, request_timeout=3600, caption=caption)
                except Exception as e:
                    try:
                        if filepath.suffix in ['.mp4', '.mkv', '.webm']:
                            await bot.send_video(chat_id=target_chat_id, video=fs_file, request_timeout=3600, caption=caption)
                        elif filepath.suffix in ['.mp3', '.m4a', '.wav']:
                            await bot.send_audio(chat_id=target_chat_id, audio=fs_file, request_timeout=3600, caption=caption)
                        elif filepath.suffix in ['.jpg', '.jpeg', '.png', '.webp']:
                            await bot.send_photo(chat_id=target_chat_id, photo=fs_file, request_timeout=3600, caption=caption)
                        else:
                            await bot.send_document(chat_id=target_chat_id, document=fs_file, request_timeout=3600, caption=caption)
                    except Exception as e2: pass
            
        if not is_guest_mode:
            try:
                await bot.delete_message(chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            except Exception:
                pass
        success = True
        
    except Exception as e:
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
        try:
            await bot.edit_message_text(get_text(lang, 'download_error', error=error_msg), chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            asyncio.create_task(delete_later(bot, status_msg.chat.id, status_msg.message_id, 30))
        except Exception:
            pass
            
        from core.config import ERROR_LOG_CHANNEL_ID
        if ERROR_LOG_CHANNEL_ID:
            try:
                import traceback
                import io
                from aiogram.types import BufferedInputFile
                from datetime import datetime
                
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
            except Exception as log_e:
                print(f"Failed to send error log: {log_e}")
    finally:
        user_cooldowns.discard(user['telegram_id'])

        active_requests -= 1
        
        if in_queue and not in_queue_cleared:
            queue_waiters -= 1
        
        # Аналітика (якщо це музичний сервіс і скачано плейлист - рахуємо кожен трек окремо)
        is_audio_service = any(x in url for x in ['music.youtube.com', 'spotify.com', 'soundcloud.com', 'apple.com/music', 'deezer.com'])
        
        if success and is_audio_service and isinstance(filepath, list):
            for p in filepath:
                if p.exists():
                    await add_download_record(user['telegram_id'], url, domain, page_title, p.stat().st_size, True)
        else:
            await add_download_record(user['telegram_id'], url, domain, page_title, file_size, success)
            
        if success and not is_guest_mode:
            # Update Menu Button Web App URL silently
            try:
                from core.webapp import generate_webapp_url
                from aiogram.types import MenuButtonWebApp, WebAppInfo
                
                bot_info = await bot.get_me()
                daily_count_updated = await get_daily_download_count(user['telegram_id'])
                webapp_url = await generate_webapp_url(user, daily_count_updated, bot_info.username)
                
                await bot.set_chat_menu_button(
                    chat_id=target_chat_id, 
                    menu_button=MenuButtonWebApp(
                        text=get_text(lang, 'menu_profile'), 
                        web_app=WebAppInfo(url=webapp_url)
                    )
                )
            except Exception as e:
                print(f"Failed to update menu button after download: {e}")
        
        import shutil
        
        def safe_rmtree(path: Path):
            try:
                if path.exists() and path.is_dir():
                    shutil.rmtree(path)
            except Exception:
                pass

        # Cleanup the session_dir in downloads
        if isinstance(filepath, list) and len(filepath) > 0:
            curr = filepath[0]
            while curr.parent.name != 'downloads' and curr.name != '':
                curr = curr.parent
            if curr.parent.name == 'downloads':
                safe_rmtree(curr)
            else:
                for p in filepath:
                    if p.exists():
                        try: p.unlink()
                        except: pass
                try: filepath[0].parent.rmdir()
                except: pass
        elif filepath and filepath.exists():
            curr = filepath
            while curr.parent.name != 'downloads' and curr.name != '':
                curr = curr.parent
            if curr.parent.name == 'downloads':
                safe_rmtree(curr)
            else:
                try: filepath.unlink()
                except: pass
                try: filepath.parent.rmdir()
                except: pass
                
        # Also clean up old gallery-dl folder from root if it exists
        safe_rmtree(Path('gallery-dl'))
