import asyncio
import contextlib
import html
import logging
import re
import threading
import time
import uuid
from typing import Optional
from pathlib import Path
from core.utils import detect_language, extract_url, host_matches, is_forbidden_url, schedule_delete, temporary_download_session, text_matches, url_host

from aiogram import Router, F, Bot
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    Message, CallbackQuery, FSInputFile, InputMediaPhoto, InputMediaVideo,
    InputMediaAudio, InputMediaDocument, InlineQueryResultCachedVideo,
    InlineQueryResultCachedAudio, InlineQueryResultCachedDocument, InlineQueryResultCachedPhoto, InlineQueryResultArticle, InputTextMessageContent,
    ReplyParameters, LinkPreviewOptions
)

from core.config import TIER_LIMITS, TELEGRAM_UPLOAD_LIMIT, STORAGE_CHAT_ID, BOT_USERNAME
from core.loader import bot
from database import get_or_create_user, get_daily_download_count, add_download_record, add_downloaded_bytes, get_active_ad
from downloader import download_media
from locales import get_text
from keyboards.inline import get_youtube_keyboard
from core.badges import check_and_award_badges

from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext

media_router = Router()
logger = logging.getLogger(__name__)

class AudioEditorState(StatesGroup):
    waiting_for_cover = State()

# State variables
download_semaphore = None
queue_waiters = 0
active_requests = 0
user_cooldowns = set()

# Скільки чекати на завантаження файлу в Telegram (великі файли через локальний Bot API).
UPLOAD_TIMEOUT = 3600


def get_download_semaphore() -> asyncio.Semaphore:
    """Семафор паралельних завантажень, створюється ліниво в робочому event loop."""
    global download_semaphore
    if download_semaphore is None:
        from core.config import MAX_CONCURRENT_DOWNLOADS
        download_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DOWNLOADS)
    return download_semaphore

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

# Сервіси з DRM, які yt-dlp не підтримує: краще одразу сказати, ніж качати й падати.
_UNSUPPORTED_SERVICES = ('music.apple.com', 'deezer.com', 'deezer.page.link')
_AUDIO_SERVICES = ('music.youtube.com', 'spotify.com', 'soundcloud.com')


async def get_download_block_reason(user: dict, url: str) -> Optional[str]:
    """Ключ локалі з причиною відмови або None.

    Одні правила для всіх точок входу (посилання, гостьовий режим, Smart Trim,
    редактор тегів у Mini App): раніше частина з них не перевіряла денний ліміт
    і заборонені посилання взагалі.
    """
    if is_forbidden_url(url):
        return 'link_rejected'
    if host_matches(url, *_UNSUPPORTED_SERVICES):
        return 'service_not_supported'
    limits = TIER_LIMITS.get(user.get('tier', 'free'), TIER_LIMITS['free'])
    if await get_daily_download_count(user['telegram_id']) >= limits['daily']:
        return 'limit_reached'
    return None


async def _notify_download_blocked(message: Message, reason_key: str, lang: str, is_guest_mode: bool, is_callback: bool):
    """Пояснює користувачу, чому завантаження не почалось."""
    text = get_text(lang, reason_key)
    try:
        if is_guest_mode:
            # Гостьовий запит треба закрити відповіддю, інакше в користувача висить «завантаження».
            if getattr(message, "guest_query_id", None):
                plain = re.sub(r'<[^>]+>', '', text)
                await message.answer_guest_query(result=InlineQueryResultArticle(
                    id=str(uuid.uuid4()),
                    title=plain.split('\n', 1)[0][:64],
                    description=plain[:200],
                    input_message_content=InputTextMessageContent(message_text=text)
                ))
            return
        if is_callback:
            await bot.edit_message_text(text, chat_id=message.chat.id, message_id=message.message_id)
            notice = message
        else:
            notice = await message.reply(text)
        schedule_delete(bot, notice.chat.id, notice.message_id, 30)
    except Exception as e:
        logger.debug("Could not notify about blocked download: %s", e)


@media_router.guest_message()
async def guest_text_handler(message: Message):
    # У guest_message from_user — це сам бот; справжній відправник — guest_bot_caller_user.
    caller = getattr(message, "guest_bot_caller_user", None) or message.from_user
    text = (message.text or message.caption or "").strip()

    bot_me = await bot.me()
    if bot_me.username:
        text = text.replace(f"@{bot_me.username}", " ").strip()

    url = extract_url(text)
    if not url and message.reply_to_message:
        url = extract_url(message.reply_to_message.text or message.reply_to_message.caption)
    if not url:
        return

    user = await get_or_create_user(
        caller.id, getattr(caller, "username", None) or "", getattr(caller, "full_name", None) or "",
        language_code=detect_language(getattr(caller, "language_code", None)),
    )
    # Ліміти, cooldown і заборонені посилання перевіряє start_download — і закриває
    # гостьовий запит поясненням (раніше відмова була мовчазною, запит «висів»).
    await process_url(message, url, user, is_guest_mode=True)

class PdfState(StatesGroup):
    waiting_for_pdf_url = State()

@media_router.message(text_matches('menu_save_pdf'))
async def btn_save_pdf(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    tier = user.get('tier', 'free').lower()
    
    if tier not in ['pro', 'max']:
        msg = await message.reply(get_text(user['language_code'], 'pdf_pro_only'))
        schedule_delete(bot, msg.chat.id, msg.message_id, 30)
        return
        
    await message.reply(get_text(user['language_code'], 'user_pdf_prompt'))
    await state.set_state(PdfState.waiting_for_pdf_url)

@media_router.message(PdfState.waiting_for_pdf_url)
async def process_pdf_url(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']
    # message.text буває None (фото, стікер) — раніше .strip() на ньому валив хендлер.
    url = extract_url(message.text)
    if not url:
        await message.reply(get_text(lang, 'pdf_invalid_url'))
        return
        
    await state.clear()
    status_msg = await message.reply(get_text(lang, 'pdf_generating'))
    
    try:
        from core.pdf_generator import generate_article_pdf
        
        session_dir = Path(f"downloads/pdf_{time.time_ns()}")
        
        async with temporary_download_session(session_dir):
            output_path = session_dir / "article.pdf"
            pdf_path, title = await generate_article_pdf(url, output_path)
            
            if pdf_path and pdf_path.exists():
                safe_title = "".join(c for c in title if c.isalnum() or c in " -_").strip()[:50]
                if not safe_title:
                    safe_title = "Article"
                    
                fs_file = FSInputFile(path=pdf_path, filename=f"{safe_title}.pdf")
                # Назва статті й URL — дані зі сторінки/від користувача: без екранування
                # `<` або `'` ламали parse_mode=HTML, і готовий PDF не відправлявся.
                caption = (
                    f"📄 <b>{html.escape(title[:900])}</b>\n\n"
                    f"🔗 <a href=\"{html.escape(url, quote=True)}\">{get_text(lang, 'pdf_source')}</a>"
                )
                
                await bot.send_document(
                    chat_id=message.chat.id,
                    document=fs_file,
                    caption=caption,
                    parse_mode="HTML"
                )
                with contextlib.suppress(TelegramAPIError):
                    await status_msg.delete()
            else:
                raise Exception("PDF файл не згенеровано.")
    except Exception as e:
        from core.net_guard import UnsafeURLError
        if isinstance(e, UnsafeURLError):
            await status_msg.edit_text(get_text(lang, 'unsafe_url'))
            return
        logger.warning("PDF generation failed for %s: %s", url, e)
        err_str = str(e) or type(e).__name__
        if len(err_str) > 500:
            err_str = err_str[:500] + "..."
        await status_msg.edit_text(get_text(lang, 'pdf_error', error=html.escape(err_str)))

@media_router.message(F.text)
async def text_handler(message: Message, state: FSMContext):
    bot_me = await bot.me()
    mention = f"@{bot_me.username}" if bot_me.username else None
    text = message.text
    if mention:
        # «@Bot https://...» або «https://...@Bot» — тег бота не частина посилання.
        text = text.replace(mention, " ")

    url = extract_url(text)
    # У групі бота можна тегнути відповіддю на повідомлення з посиланням.
    if not url and mention and mention in message.text and message.reply_to_message:
        url = extract_url(message.reply_to_message.text or message.reply_to_message.caption)
    if not url:
        return

    # Нове посилання — новий запит: незавершений діалог (підтримка, обкладинка, теги)
    # скасовуємо, інакше наступне повідомлення чи завантаження пішло б не туди.
    await state.clear()

    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    # Тег бота в групі раніше вмикав «гостьовий режим»: файл ішов в особисті, а в групі
    # була тиша (або нічого, якщо людина не запускала бота). Гостьовий режим тепер —
    # лише справжні guest_message, а в групі бот відповідає в групу.
    await process_url(message, url, user)


_YT_HEIGHTS = {'1080p': 1080, '720p': 720, '480p': 480, '360p': 360}


def youtube_format(quality: str) -> str:
    """Рядок формату yt-dlp для якості (одне місце замість чотирьох копій)."""
    if quality == 'audio':
        return 'bestaudio/best'
    height = _YT_HEIGHTS.get(quality)
    if height is None:
        return 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best'
    return (
        f'bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]'
        f'/bestvideo[height<={height}]+bestaudio'
        f'/best[height<={height}]/best'
    )


def quality_for_tier(tier: str) -> str:
    return {'free': '720p', 'pro': '1080p'}.get(tier, 'best')


async def process_url(message: Message, url: str, user: dict, is_guest_mode: bool = False, state=None):
    if host_matches(url, *_AUDIO_SERVICES):
        await start_download(message, url, 'bestaudio/best', user, is_guest_mode=is_guest_mode, state=state)
    elif host_matches(url, 'youtube.com', 'youtu.be'):
        if is_guest_mode:
            from core.webapp_data import normalize_guest_quality
            quality = normalize_guest_quality(user.get('guest_yt_quality'), user.get('tier', 'free'))
            await start_download(message, url, youtube_format(quality), user, is_guest_mode=True, state=state)
        else:
            lang = user['language_code']
            # Перевіряємо одразу, щоб не показувати вибір якості, коли завантаження однаково
            # не почнеться (остаточна перевірка — у start_download).
            block_reason = 'cooldown' if user['telegram_id'] in user_cooldowns else await get_download_block_reason(user, url)
            if block_reason:
                await _notify_download_blocked(message, block_reason, lang, False, False)
                return
            await message.reply(
                get_text(lang, 'choose_yt_quality', url=html.escape(url)),
                reply_markup=get_youtube_keyboard(url, lang),
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
    else:
        fmt = youtube_format(quality_for_tier(user.get('tier', 'free')))
        await start_download(message, url, fmt, user, is_guest_mode=is_guest_mode, state=state)

_YT_ACTIONS = {'1080': '1080p', '720': '720p', '360': '360p', 'audio': 'audio', 'best': 'best'}

@media_router.callback_query(F.data.startswith("yt_"))
async def youtube_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()

    quality = _YT_ACTIONS.get(callback.data.removeprefix("yt_"))
    message = callback.message
    # Повідомлення, старші за 48 год, приходять як InaccessibleMessage — без тексту.
    text = getattr(message, "text", None)
    url = extract_url(text.split("🔗", 1)[1]) if text and "🔗" in text else None
    if quality is None or not url:
        return

    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    lang = user['language_code']
    tier = user.get('tier', 'free')

    if (tier == 'free' and quality in ('1080p', 'best')) or (tier == 'pro' and quality == 'best'):
        msg = await message.reply(get_text(lang, 'quality_limit'))
        schedule_delete(bot, msg.chat.id, msg.message_id, 30)
        return

    await _safe_edit(message, get_text(lang, 'starting_download'))
    await start_download(message, url, youtube_format(quality), user, is_callback=True, state=state)

@media_router.message(AudioEditorState.waiting_for_cover, F.photo | F.document)
async def cover_photo_handler(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    state_data = await state.get_data()

    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('image/'):
        file_id = message.document.file_id
    else:
        await message.answer(get_text(user['language_code'], 'send_valid_photo'))
        return

    # Обкладинку тут не качаємо: зберігаємо file_id, а сам файл завантажується вже
    # всередині тимчасової сесії start_download. Раніше тека downloads/cover_*
    # створювалась тут і видалялась лише при успіху — покинутий флоу чи помилка
    # лишали її на диску назавжди.
    await state.update_data(edit_tags=True, cover_file_id=file_id)

    url = state_data.get('url')
    await state.set_state(None)

    await process_url(message, url, user, is_guest_mode=False, state=state)

async def prepare_caption_with_ad(original_caption: str, user: dict) -> str:
    original_caption = original_caption or ""
    if user.get('tier', 'free').lower() == 'free':
        ad_text = await get_active_ad()
        if ad_text:
            ad_block = f"\n\n{get_text(user.get('language_code', 'uk'), 'ad_label')} {ad_text}"
            max_len = 1024 - len(ad_block)
            # Нову рекламу адмінка обмежує AD_MAX_LENGTH, але стара в БД могла бути довшою:
            # тоді max_len ставав від'ємним, обрізання ламалось, підпис виходив > 1024
            # символів і Telegram відхиляв файл. Завелику рекламу просто пропускаємо.
            if max_len < 32:
                logger.warning("Active ad is too long for a caption (%d chars), skipping it", len(ad_text))
                return original_caption[:1024]
            if len(original_caption) > max_len:
                original_caption = original_caption[:max_len - 3] + "..."
            return original_caption + ad_block
    return original_caption[:1024]


_VIDEO_EXTS = {'.mp4', '.mkv', '.webm', '.mov'}
_PHOTO_EXTS = {'.jpg', '.jpeg', '.png', '.webp'}
_AUDIO_EXTS = {'.mp3', '.m4a', '.wav', '.opus', '.flac', '.ogg'}
# Що взагалі має сенс відправляти користувачу, коли бекенд повернув кілька файлів.
SENDABLE_EXTS = _VIDEO_EXTS | _PHOTO_EXTS | _AUDIO_EXTS | {'.zip'}


def media_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _VIDEO_EXTS:
        return 'video'
    if ext in _PHOTO_EXTS:
        return 'photo'
    if ext in _AUDIO_EXTS:
        return 'audio'
    return 'document'


def _reply_parameters(message_id: Optional[int]) -> Optional[ReplyParameters]:
    # allow_sending_without_reply: якщо повідомлення з посиланням уже видалене, файл
    # однаково дійде. Раніше це емулювалось повторною відправкою в `except`, яка
    # ковтала БУДЬ-ЯКУ помилку — і невдала доставка мовчки рахувалась як успіх.
    if message_id is None:
        return None
    return ReplyParameters(message_id=message_id, allow_sending_without_reply=True)


async def send_media_file(bot_instance, chat_id: int, path: Path, *, caption: Optional[str], reply_to: Optional[int] = None,
                          title: Optional[str] = None, performer: Optional[str] = None) -> Message:
    """Відправляє один файл відповідним методом Telegram. Помилки НЕ ковтаються."""
    file = FSInputFile(path=path, filename=path.name)
    kwargs = {'chat_id': chat_id, 'caption': caption, 'request_timeout': UPLOAD_TIMEOUT}
    reply_parameters = _reply_parameters(reply_to)
    if reply_parameters is not None:
        kwargs['reply_parameters'] = reply_parameters

    kind = media_kind(path)
    if kind == 'video':
        return await bot_instance.send_video(video=file, supports_streaming=True, **kwargs)
    if kind == 'photo':
        return await bot_instance.send_photo(photo=file, **kwargs)
    if kind == 'audio':
        return await bot_instance.send_audio(audio=file, title=title, performer=performer, **kwargs)
    return await bot_instance.send_document(document=file, **kwargs)


def _is_caption_problem(error: Exception) -> bool:
    text = str(error).lower()
    return "parse entities" in text or "caption is too long" in text or "caption_too_long" in text


async def send_with_caption_fallback(send, caption: str, plain_caption: str):
    """Викликає send(caption); якщо Telegram відхилив саме підпис з рекламою — повторює без неї.

    Повертає (результат, використаний підпис). Інші помилки пробрасуються як є.
    """
    try:
        return await send(caption), caption
    except TelegramBadRequest as e:
        if caption != plain_caption and _is_caption_problem(e):
            logger.warning("Caption with ad was rejected (%s); resending without the ad", e)
            return await send(plain_caption), plain_caption
        raise


def _build_input_media(path: Path, kind: str, caption: Optional[str], title, performer):
    file = FSInputFile(path=path, filename=path.name)
    if kind == 'video':
        return InputMediaVideo(media=file, caption=caption, supports_streaming=True)
    if kind == 'photo':
        return InputMediaPhoto(media=file, caption=caption)
    if kind == 'audio':
        return InputMediaAudio(media=file, caption=caption, title=title, performer=performer)
    return InputMediaDocument(media=file, caption=caption)


async def send_media_groups(bot_instance, chat_id: int, files: list, caption: str, plain_caption: str,
                            reply_to: Optional[int] = None, title=None, performer=None) -> None:
    """Відправляє файли альбомами по 10: фото+відео разом, аудіо й документи окремо (вимога Telegram)."""
    groups = {'visual': [], 'audio': [], 'document': []}
    for path in files:
        kind = media_kind(path)
        groups['visual' if kind in ('video', 'photo') else kind].append((path, kind))

    reply_parameters = _reply_parameters(reply_to)
    for items in groups.values():
        for start in range(0, len(items), 10):
            chunk = items[start:start + 10]

            async def send(cap, chunk=chunk, start=start):
                # Підпис — лише на першому файлі першого альбому кожного типу, як і раніше.
                first_caption = cap if start == 0 else None
                if len(chunk) == 1:
                    # sendMediaGroup за документацією вимагає 2–10 елементів.
                    path, _ = chunk[0]
                    return await send_media_file(bot_instance, chat_id, path, caption=first_caption,
                                                 reply_to=reply_to, title=title, performer=performer)
                media = [_build_input_media(path, kind, first_caption if i == 0 else None, title, performer)
                         for i, (path, kind) in enumerate(chunk)]
                kwargs = {'chat_id': chat_id, 'media': media, 'request_timeout': UPLOAD_TIMEOUT}
                if reply_parameters is not None:
                    kwargs['reply_parameters'] = reply_parameters
                return await bot_instance.send_media_group(**kwargs)

            await send_with_caption_fallback(send, caption, plain_caption)


async def _answer_guest_article(message: Message, title: str, text: str) -> None:
    await message.answer_guest_query(result=InlineQueryResultArticle(
        id=str(uuid.uuid4()),
        title=title[:64],
        description=re.sub(r'<[^>]+>', '', text)[:200],
        input_message_content=InputTextMessageContent(message_text=text),
    ))


def _cached_guest_result(sent: Message, caption: Optional[str], lang: str):
    """Кешований результат для answer_guest_query з file_id щойно завантаженого файлу.

    Тип визначаємо за тим, що повернув Telegram, а не за розширенням: .webm, надісланий
    як відео, може повернутись документом.
    """
    result_id = str(uuid.uuid4())
    if sent.video:
        return InlineQueryResultCachedVideo(id=result_id, video_file_id=sent.video.file_id, title=get_text(lang, 'guest_video_title'), caption=caption)
    if sent.photo:
        return InlineQueryResultCachedPhoto(id=result_id, photo_file_id=sent.photo[-1].file_id, caption=caption)
    if sent.audio:
        return InlineQueryResultCachedAudio(id=result_id, audio_file_id=sent.audio.file_id, caption=caption)
    document = sent.document
    return InlineQueryResultCachedDocument(
        id=result_id, document_file_id=document.file_id,
        title=(document.file_name or get_text(lang, 'guest_document_title'))[:64], caption=caption,
    )


async def _deliver_guest(bot_instance, files: list, user: dict, message: Message, caption: str, plain_caption: str,
                         lang: str, title=None, performer=None) -> None:
    caller_id = user['telegram_id']
    start_bot_text = get_text(lang, 'guest_start_bot', bot=BOT_USERNAME)

    if len(files) > 1:
        # Альбом гостьовою відповіддю не надіслати — шлемо в особисті й закриваємо запит статтею.
        try:
            await send_media_groups(bot_instance, caller_id, files, caption, plain_caption, title=title, performer=performer)
        except TelegramForbiddenError:
            await _answer_guest_article(message, get_text(lang, 'guest_start_bot_title'), start_bot_text)
            return
        await _answer_guest_article(message, get_text(lang, 'guest_album_sent_title'), get_text(lang, 'guest_album_sent'))
        return

    # Щоб віддати файл гостьовою відповіддю, потрібен його file_id, тобто файл треба
    # спершу кудись завантажити: у службовий канал (якщо налаштований) або в особисті.
    upload_chat = STORAGE_CHAT_ID or caller_id
    try:
        sent, used_caption = await send_with_caption_fallback(
            lambda cap: send_media_file(bot_instance, upload_chat, files[0], caption=cap, title=title, performer=performer),
            caption, plain_caption,
        )
    except TelegramForbiddenError:
        if STORAGE_CHAT_ID:
            raise  # бот не має доступу до каналу-сховища — це помилка конфігурації
        # Людина ще не запускала бота, тож написати їй в особисті неможливо.
        await _answer_guest_article(message, get_text(lang, 'guest_start_bot_title'), start_bot_text)
        return

    await message.answer_guest_query(result=_cached_guest_result(sent, used_caption, lang))


async def dispatch_telegram_media(bot_instance, target_chat_id: int, filepath, user: dict, is_guest_mode: bool, message: Message, lang: str, title: str = None, performer: str = None) -> int:
    """Відправляє файл(и) у Telegram і повертає їхній загальний розмір.

    Будь-яка помилка відправки пробрасується нагору, тож завантаження зараховується
    лише після реальної доставки. Раніше невдала відправка одного файлу ковталась:
    користувач нічого не отримував, а спроба з'їдала денний ліміт.
    """
    files = filepath if isinstance(filepath, list) else [filepath]
    if is_guest_mode:
        # Гостьовий режим: ліміт 10 файлів загалом
        files = files[:10]
    total_size = sum(path.stat().st_size for path in files)

    plain_caption = get_text(lang, 'caption_signature')
    caption = await prepare_caption_with_ad(plain_caption, user)

    if is_guest_mode:
        await _deliver_guest(bot_instance, files, user, message, caption, plain_caption, lang, title, performer)
        return total_size

    reply_to = message.message_id if message is not None else None
    if len(files) == 1:
        await send_with_caption_fallback(
            lambda cap: send_media_file(bot_instance, target_chat_id, files[0], caption=cap, reply_to=reply_to, title=title, performer=performer),
            caption, plain_caption,
        )
    else:
        await send_media_groups(bot_instance, target_chat_id, files, caption, plain_caption, reply_to=reply_to, title=title, performer=performer)
    return total_size


def extract_domain(url: str) -> str:
    return url_host(url) or "unknown"


async def _take_tag_request(state) -> Optional[dict]:
    """Забирає з FSM запит на редагування тегів і одразу очищає стан.

    Раніше стан чистився лише при успішному завантаженні, тож після помилки теги
    «прилипали» до наступного, вже не пов'язаного завантаження.
    """
    if state is None:
        return None
    data = await state.get_data()
    if not data.get('edit_tags'):
        return None
    await state.clear()
    return data


async def _report_cookie_state(meta: dict, url: str) -> None:
    """Успіх із куками — у статус; збій кук, який пережив запасний варіант без них, — адміну."""
    from core import cookie_monitor
    try:
        if meta.get('cookie_problem') is not None:
            await cookie_monitor.report_problem(bot, meta['cookie_problem'], url)
        elif meta.get('cookies_used'):
            await cookie_monitor.report_success(meta['cookies_used'])
    except Exception:
        logger.exception("Could not record cookie state for %s", url)


async def _record_download_stats(user_id: int, url: str, title: str, file_size: int, success: bool) -> None:
    await add_download_record(user_id, url, extract_domain(url), title, file_size, success)
    if success:
        await add_downloaded_bytes(user_id, file_size)
        await check_and_award_badges(user_id)


async def _safe_edit(status_msg: Optional[Message], text: str) -> None:
    if status_msg is None:
        return
    with contextlib.suppress(TelegramAPIError):
        await bot.edit_message_text(text, chat_id=status_msg.chat.id, message_id=status_msg.message_id)


async def start_download(message: Message, url: str, format_spec: str, user: dict, is_callback: bool = False, is_guest_mode: bool = False, state=None) -> bool:
    lang = user['language_code']
    user_id = user['telegram_id']

    # Cooldown перевіряється й захоплюється без await між ними. Раніше перевірка
    # була в хендлерах, а захоплення — тут, після кількох await-ів, тож два швидкі
    # запити (наприклад, посилання + Mini App) проходили обидва.
    if user_id in user_cooldowns:
        await _notify_download_blocked(message, 'cooldown', lang, is_guest_mode, is_callback)
        return False
    user_cooldowns.add(user_id)
    try:
        block_reason = await get_download_block_reason(user, url)
    except BaseException:
        user_cooldowns.discard(user_id)
        raise
    if block_reason:
        user_cooldowns.discard(user_id)
        await _notify_download_blocked(message, block_reason, lang, is_guest_mode, is_callback)
        return False

    global queue_waiters, active_requests
    target_chat = getattr(message, "guest_bot_caller_chat", None) or message.chat
    target_chat_id = target_chat.id if is_guest_mode else message.chat.id
    semaphore = get_download_semaphore()

    status_msg = None
    success = False
    file_size = 0
    in_queue = False
    download_meta = {}
    session_dir = Path(f"downloads/{time.time_ns()}")

    # Усі лічильники змінюються лише всередині try/finally. Раніше інкремент стояв до
    # try, і якщо відправка статусу падала (бот заблокований, кікнутий, flood 429),
    # декремент не виконувався — лічильник ріс назавжди, і всі бачили «ви в черзі».
    active_requests += 1
    try:
        tag_request = await _take_tag_request(state)

        # Черга — коли всі слоти семафора зайняті. Колись рахувалось за active_requests,
        # куди потрапляли й ті, хто вже вантажить файл у Telegram.
        if semaphore.locked():
            in_queue = True
            queue_waiters += 1
            status_text = get_text(lang, 'in_queue', pos=queue_waiters)
        else:
            status_text = get_text(lang, 'starting_download')

        if not is_guest_mode:
            if is_callback:
                status_msg = message
                if in_queue:
                    await _safe_edit(status_msg, status_text)
            else:
                status_msg = await message.reply(status_text)

        tracker = ProgressTracker(status_msg, bot, lang) if status_msg is not None else None

        async with temporary_download_session(session_dir):
            async with semaphore:
                if in_queue:
                    in_queue = False
                    queue_waiters -= 1
                    await _safe_edit(status_msg, get_text(lang, 'starting_download'))

                tracker_update = tracker.update if tracker else None
                filepath = await download_media(url, format_spec, tracker_update, tier=user['tier'], session_dir=session_dir, meta=download_meta)

            await _report_cookie_state(download_meta, url)
            await _safe_edit(status_msg, get_text(lang, 'downloaded_sending'))

            if isinstance(filepath, list):
                # Filter out metadata files
                media_files = [p for p in filepath if p.suffix.lower() in SENDABLE_EXTS]
                if len(media_files) == 1:
                    filepath = media_files[0]
                elif len(media_files) > 1:
                    filepath = media_files

            # Watermark integration
            from core.media_processor import process_watermarks
            filepath = await process_watermarks(filepath, user, bot, session_dir)

            # Audio Tags Editor integration
            audio_title, audio_performer = None, None
            if tag_request:
                audio_title = tag_request.get('title') or None
                audio_performer = tag_request.get('artist') or None
                cover_file_id = tag_request.get('cover_file_id')
                if cover_file_id:
                    cover_path = session_dir / "cover.jpg"
                    await bot.download(cover_file_id, destination=cover_path)
                    tag_request['cover_path'] = str(cover_path)
                from core.audio_tags import process_audio_tags
                filepath = await process_audio_tags(filepath, tag_request)

            # Відповідаємо на повідомлення з посиланням. Для вибору якості YouTube це
            # повідомлення, на яке відповідала клавіатура (сама вона видаляється).
            if is_callback:
                reply_target = status_msg.reply_to_message if status_msg is not None else None
            else:
                reply_target = message
            file_size = await dispatch_telegram_media(bot, target_chat_id, filepath, user, is_guest_mode, reply_target, lang, title=audio_title, performer=audio_performer)

            if status_msg is not None:
                with contextlib.suppress(TelegramAPIError):
                    await bot.delete_message(chat_id=status_msg.chat.id, message_id=status_msg.message_id)
            success = True

    except Exception as e:
        from core.error_handler import handle_media_error
        await handle_media_error(e, bot, status_msg, url, user, lang, is_guest_mode, message=message)
    finally:
        user_cooldowns.discard(user_id)
        active_requests -= 1
        if in_queue:
            queue_waiters -= 1

        # Аналітика не повинна маскувати результат завантаження.
        try:
            await _record_download_stats(user_id, url, download_meta.get('title', ''), file_size, success)
        except Exception:
            logger.exception("Could not record download stats for %s", user_id)

        if success and not is_guest_mode and message.chat.type == "private":
            with contextlib.suppress(TelegramAPIError):
                from aiogram.types import MenuButtonDefault
                await bot.set_chat_menu_button(chat_id=target_chat_id, menu_button=MenuButtonDefault())

    return success

async def process_smart_trim(message: Message, user: dict, url: str, start_sec: int, end_sec: int, status_msg: Message) -> bool:
    global queue_waiters, active_requests
    lang = user['language_code']
    user_id = user['telegram_id']
    tier = user.get('tier', 'free')

    if active_requests > 100:
        await _safe_edit(status_msg, get_text(lang, 'too_many_requests'))
        return False

    # Smart Trim раніше взагалі не дивився на cooldown: можна було паралельно
    # запускати обрізки й звичайні завантаження.
    if user_id in user_cooldowns:
        await _safe_edit(status_msg, get_text(lang, 'cooldown'))
        return False
    user_cooldowns.add(user_id)

    success = False
    file_size = 0
    active_requests += 1
    progress = ProgressTracker(status_msg, bot, lang)
    session_dir = Path("downloads") / f"session_trim_{uuid.uuid4().hex}"

    try:
        from core.net_guard import ensure_public_url
        from downloader import DownloadTimeoutError, YTDLP_JOB_TIMEOUT, download_trim_sync, enforce_size_limit

        # Обрізка йде напряму в yt-dlp, оминаючи download_media, тож SSRF-перевірка — тут.
        await ensure_public_url(url)

        async with temporary_download_session(session_dir):
            async with get_download_semaphore():
                await progress.update(5)
                cancel_event = threading.Event()
                loop = asyncio.get_running_loop()
                try:
                    output_file = await asyncio.wait_for(
                        asyncio.to_thread(download_trim_sync, url, start_sec, end_sec, session_dir, progress.update, loop, tier, cancel_event),
                        timeout=YTDLP_JOB_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    cancel_event.set()
                    raise DownloadTimeoutError("Обрізка перевищила ліміт часу.") from None

            enforce_size_limit([output_file], min(TIER_LIMITS[tier]['size'], TELEGRAM_UPLOAD_LIMIT))
            await _safe_edit(status_msg, get_text(lang, 'trim_ready'))

            plain_caption = get_text(lang, 'trim_caption', bot=BOT_USERNAME)
            caption = await prepare_caption_with_ad(plain_caption, user)
            await send_with_caption_fallback(
                lambda cap: send_media_file(bot, message.chat.id, output_file, caption=cap),
                caption, plain_caption,
            )
            file_size = output_file.stat().st_size
            success = True

            with contextlib.suppress(TelegramAPIError):
                await status_msg.delete()

    except Exception as e:
        from core.error_handler import handle_media_error
        await handle_media_error(e, bot, status_msg, url, user, lang, False, message=message)
    finally:
        active_requests -= 1
        user_cooldowns.discard(user_id)
        try:
            await _record_download_stats(user_id, url, "", file_size, success)
        except Exception:
            logger.exception("Could not record trim stats for %s", user_id)

    return success
