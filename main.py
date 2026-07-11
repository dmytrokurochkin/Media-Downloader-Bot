import asyncio
import os
import re
import time
from pathlib import Path
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.types import Message, CallbackQuery, FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto, InputMediaVideo, InputMediaAudio, InputMediaDocument
from aiogram.filters import CommandStart, Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from downloader import download_media

# ВАЖЛИВО ДЛЯ КОРИСТУВАЧА:
# Для того, щоб бот зміг завантажувати найкращу якість відео+аудіо та об'єднувати їх,
# а також конвертувати музику в .mp3 (для Spotify та YouTube Music),
# у вашій системі ОБОВ'ЯЗКОВО має бути встановлений FFmpeg!
#
# На Windows:
# 1. Завантажте FFmpeg (наприклад, з https://github.com/BtbN/FFmpeg-Builds/releases)
# 2. Розпакуйте та додайте шлях до папки `bin` у змінні середовища PATH.
# 
# На Linux:
# sudo apt update && sudo apt install ffmpeg -y
# =====================================================================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
LOCAL_API_SERVER_URL = os.getenv("LOCAL_API_SERVER_URL", "http://127.0.0.1:8081")

if not BOT_TOKEN:
    raise ValueError("Не знайдено BOT_TOKEN у файлі .env!")

# Налаштування сесії для використання Local Telegram Bot API Server
# Це дозволяє надсилати файли розміром до 2 ГБ
session = AiohttpSession(
    api=TelegramAPIServer.from_base(LOCAL_API_SERVER_URL, is_local=True)
)
bot = Bot(token=BOT_TOKEN, session=session)
dp = Dispatcher()

# Регулярний вираз для пошуку посилань у тексті
URL_PATTERN = re.compile(r'https?://[^\s]+')

class ProgressTracker:
    """
    Клас для безпечного (з троттлінгом) оновлення повідомлення з прогрес-баром у Telegram.
    Telegram має ліміти на частоту редагування повідомлень.
    """
    def __init__(self, message: Message, bot: Bot):
        self.message = message
        self.bot = bot
        self.last_update_time = 0
        self.last_percent = -1

    async def update(self, percent: float):
        now = time.time()
        # Оновлюємо раз на 2 секунди, або якщо зміна більше 5%, або якщо 100%
        if now - self.last_update_time > 2.0 or percent == 100:
            if abs(percent - self.last_percent) >= 5 or percent == 100:
                text = f"⏳ Завантаження: {percent:.1f}%"
                try:
                    await self.bot.edit_message_text(
                        text, 
                        chat_id=self.message.chat.id, 
                        message_id=self.message.message_id
                    )
                    self.last_update_time = now
                    self.last_percent = percent
                except Exception:
                    pass

def get_youtube_keyboard() -> InlineKeyboardMarkup:
    """
    Генерує інлайн-клавіатуру для вибору якості YouTube-відео.
    Посилання ми будемо брати безпосередньо з тексту повідомлення.
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="1080p", callback_data="yt_1080")
    builder.button(text="720p", callback_data="yt_720")
    builder.button(text="360p", callback_data="yt_360")
    builder.button(text="🎵 Аудіо", callback_data="yt_audio")
    builder.button(text="🔥 Максимальна якість", callback_data="yt_best")
    builder.adjust(3, 1, 1)
    return builder.as_markup()

@dp.message(CommandStart())
async def start_handler(message: Message):
    await message.reply(
        "Привіт! Я бот для завантаження медіа.\n"
        "Підтримуються: YouTube, Instagram, TikTok, Spotify, GitHub.\n"
        "Просто надішліть мені посилання!"
    )

@dp.message(Command("download"))
async def download_command(message: Message):
    # Витягуємо URL з аргументів команди
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Використання: /download <посилання>")
        return
    
    url = args[1]
    await process_url(message, url)

@dp.message(F.text)
async def text_handler(message: Message):
    # Обробка звичайних повідомлень з посиланнями
    match = URL_PATTERN.search(message.text)
    if match:
        url = match.group(0)
        
        is_private = message.chat.type == "private"
        bot_me = await bot.get_me()
        is_mentioned = bot_me.username in message.text if bot_me.username else False
        
        # Відповідаємо, якщо це приватне повідомлення або бота тегнули в групі
        if is_private or is_mentioned:
            await process_url(message, url)

async def process_url(message: Message, url: str):
    # Замінюємо threads.com на threads.net, оскільки yt-dlp працює з .net
    if 'threads.com' in url:
        url = url.replace('threads.com', 'threads.net')
        
    is_audio_service = any(x in url for x in ['music.youtube.com', 'spotify.com', 'soundcloud.com', 'apple.com/music', 'deezer.com'])
    
    if is_audio_service:
        # Для музичних сервісів одразу завантажуємо найкраще аудіо
        await start_download(message, url, 'bestaudio/best')
    elif 'youtube.com' in url or 'youtu.be' in url:
        await message.reply(
            f"Виберіть якість для завантаження YouTube відео:\n🔗 {url}",
            reply_markup=get_youtube_keyboard(),
            disable_web_page_preview=True
        )
    else:
        # Для інших платформ починаємо пряме завантаження найкращої якості
        await start_download(message, url, 'bestvideo+bestaudio/best')

@dp.callback_query(F.data.startswith("yt_"))
async def youtube_callback(callback: CallbackQuery):
    await callback.answer()
    
    action = callback.data.split('_')[1]
    
    # Витягуємо URL з тексту повідомлення
    text_parts = callback.message.text.split("🔗 ")
    if len(text_parts) < 2:
        await callback.message.edit_text("Помилка отримання посилання")
        return
    url = text_parts[1].strip()
    
    format_spec = 'bestvideo+bestaudio/best'
    if action == '1080':
        format_spec = 'bestvideo[height<=1080]+bestaudio/best'
    elif action == '720':
        format_spec = 'bestvideo[height<=720]+bestaudio/best'
    elif action == '360':
        format_spec = 'bestvideo[height<=360]+bestaudio/best'
    elif action == 'audio':
        format_spec = 'bestaudio/best'
    elif action == 'best':
        format_spec = 'bestvideo+bestaudio/best'
        
    await callback.message.edit_text("⏳ Розпочинаю завантаження...")
    await start_download(callback.message, url, format_spec, is_callback=True)

async def start_download(message: Message, url: str, format_spec: str, is_callback: bool = False):
    status_msg = message if is_callback else await message.reply("⏳ Розпочинаю завантаження...")
    tracker = ProgressTracker(status_msg, bot)
    
    filepath = None
    try:
        filepath = await download_media(url, format_spec, tracker.update)
        
        await bot.edit_message_text("✅ Завантажено! Відправляю файл у Telegram...", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        
        # Підготовка файлу для відправки
        if isinstance(filepath, list):
            # Ділимо файли на групи за типом, оскільки Telegram не дозволяє мішати аудіо/документи з фото/відео
            visual_group = []
            audio_group = []
            document_group = []
            
            for path in filepath:
                fs_file = FSInputFile(path=path, filename=path.name)
                ext = path.suffix.lower()
                if ext in ['.mp4', '.mkv', '.webm']:
                    visual_group.append(InputMediaVideo(media=fs_file))
                elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    visual_group.append(InputMediaPhoto(media=fs_file))
                elif ext in ['.mp3', '.m4a', '.wav', '.opus']:
                    audio_group.append(InputMediaAudio(media=fs_file))
                elif ext not in ['.json', '.description', '.part', '.ytdl']:
                    # Ігноруємо технічні файли yt-dlp, інше відправляємо як документ
                    document_group.append(InputMediaDocument(media=fs_file))
            
            # Функція для відправки конкретної групи батчами по 10
            async def send_group_in_chunks(group):
                for i in range(0, len(group), 10):
                    chunk = group[i:i+10]
                    await bot.send_media_group(
                        chat_id=message.chat.id, 
                        media=chunk, 
                        reply_to_message_id=message.message_id if not is_callback else None, 
                        request_timeout=3600
                    )
            
            if visual_group:
                await send_group_in_chunks(visual_group)
            if audio_group:
                await send_group_in_chunks(audio_group)
            if document_group:
                await send_group_in_chunks(document_group)
        else:
            # Одиночний файл
            fs_file = FSInputFile(path=filepath, filename=filepath.name)
            
            if filepath.suffix in ['.mp4', '.mkv', '.webm']:
                await bot.send_video(chat_id=message.chat.id, video=fs_file, reply_to_message_id=message.message_id if not is_callback else None, request_timeout=3600)
            elif filepath.suffix in ['.mp3', '.m4a', '.wav']:
                await bot.send_audio(chat_id=message.chat.id, audio=fs_file, reply_to_message_id=message.message_id if not is_callback else None, request_timeout=3600)
            else:
                await bot.send_document(chat_id=message.chat.id, document=fs_file, reply_to_message_id=message.message_id if not is_callback else None, request_timeout=3600)
            
        # Видаляємо повідомлення зі статусом після успішної відправки
        await bot.delete_message(chat_id=status_msg.chat.id, message_id=status_msg.message_id)
        
    except Exception as e:
        error_msg = str(e)
        if len(error_msg) > 3000:
            error_msg = error_msg[:3000] + "...\n[Помилка була обрізана, бо занадто довга]"
        await bot.edit_message_text(f"❌ Помилка завантаження:\n{error_msg}", chat_id=status_msg.chat.id, message_id=status_msg.message_id)
    finally:
        # Автоматичне видалення файлу(ів) з локального диска
        if isinstance(filepath, list):
            for p in filepath:
                if p.exists():
                    try:
                        p.unlink()
                    except Exception as cleanup_error:
                        print(f"Не вдалося видалити файл {p}: {cleanup_error}")
            # Також видаляємо саму директорію, якщо вона порожня
            try:
                if len(filepath) > 0:
                    filepath[0].parent.rmdir()
            except Exception:
                pass
        elif filepath and filepath.exists():
            try:
                filepath.unlink()
            except Exception as cleanup_error:
                print(f"Не вдалося видалити файл {filepath}: {cleanup_error}")

async def main():
    print("Запуск бота...")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())