import html
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_or_create_user, get_daily_download_count, set_user_language, set_guest_yt_quality, get_top_users, get_top_domains, update_user_settings, get_user_stats, set_watermark_file_id
from locales import get_text
from keyboards.inline import get_lang_keyboard, get_guest_quality_keyboard, get_settings_main_keyboard, get_onboarding_keyboard
from keyboards.reply import get_main_keyboard
from core.config import TIER_LIMITS, ADMIN_IDS
from core.utils import schedule_delete, spawn, text_matches
from aiogram.exceptions import TelegramAPIError
from core.loader import bot

user_router = Router()
logger = logging.getLogger(__name__)

class SupportState(StatesGroup):
    waiting_for_message = State()

class WatermarkState(StatesGroup):
    waiting_for_photo = State()

from core.webapp import generate_webapp_url, merge_top_domains

@user_router.message(CommandStart(deep_link=True, magic=F.args == "buy_vip"))
async def start_buy_vip_handler(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    await state.clear()
    # Redirect to VIP command (it fetches/creates the user itself)
    from handlers.payment import vip_command
    await vip_command(message, state)

@user_router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    stats = await get_user_stats(user['telegram_id'])
    is_private = message.chat.type == "private"
    
    # Reset to default Menu Button to force users to use the Reply Keyboard WebApp button
    # which correctly supports tg.sendData() for saving settings
    if is_private:
        try:
            from aiogram.types import MenuButtonDefault
            await bot.set_chat_menu_button(
                chat_id=message.chat.id, 
                menu_button=MenuButtonDefault()
            )
        except TelegramAPIError as e:
            logger.warning("Failed to set menu button for %s: %s", message.chat.id, e)
            
    is_new_user = (stats and stats.get('downloads_count', 0) == 0)
    
    if is_new_user and is_private:
        msg = await message.reply(get_text(user['language_code'], 'onboarding_greeting'), reply_markup=get_onboarding_keyboard(user['language_code']))
    elif is_private:
        # Посилання на Mini App з лідербордами рахується лише там, де кнопка справді потрібна.
        webapp_url = await webapp_url_for(user)
        msg = await message.reply(get_text(user['language_code'], 'start'), reply_markup=get_main_keyboard(user['language_code'], webapp_url))
    else:
        # selective: у групі reply-клавіатура показується лише тому, хто написав /start, а не всім учасникам.
        msg = await message.reply(get_text(user['language_code'], 'start'), reply_markup=get_main_keyboard(user['language_code'], None, selective=True))
        
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

ONBOARDING_TEST_URL = "https://www.youtube.com/shorts/xcJtL7QggTI"


async def webapp_url_for(user: dict) -> str:
    bot_info = await bot.me()
    daily_count = await get_daily_download_count(user['telegram_id'])
    return await generate_webapp_url(user, daily_count, bot_info.username)


@user_router.callback_query(F.data == "onboarding_test_dl")
async def onboarding_test_dl_handler(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    
    await callback.message.edit_text(get_text(user['language_code'], 'starting_download'))
    
    from handlers.media import start_download, youtube_format
    ok = await start_download(callback.message, ONBOARDING_TEST_URL, youtube_format('720p'), user, is_callback=True)
    if not ok:
        # Причину вже показав start_download. Раніше «Супер, ти отримав перше відео!»
        # приходило навіть після невдалого тестового завантаження.
        return

    # Reply-клавіатура з кнопкою Mini App, а не inline-кнопка: з Mini App, відкритої
    # inline-кнопкою, Telegram не приймає sendData, і налаштування не зберігались.
    webapp_url = await webapp_url_for(user)
    msg = await callback.message.answer(
        get_text(user['language_code'], 'onboarding_success'),
        reply_markup=get_main_keyboard(user['language_code'], webapp_url),
    )
    schedule_delete(bot, msg.chat.id, msg.message_id, 120)

@user_router.message(text_matches('menu_download'))
async def guide_handler(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    msg = await message.reply(get_text(user['language_code'], 'guide_text'))
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

@user_router.message(text_matches('menu_hide_keyboard'))
async def hide_keyboard_handler(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    msg = await message.reply(get_text(user['language_code'], 'keyboard_hidden'), reply_markup=ReplyKeyboardRemove())
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

@user_router.message(Command('settings'))
async def settings_command(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    text = get_text(user['language_code'], 'settings_menu_text')
    msg = await message.reply(text, reply_markup=get_settings_main_keyboard(user['language_code']))
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

@user_router.message(Command('watermark'))
@user_router.message(text_matches('menu_watermark'))
async def watermark_button_handler(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']

    if user.get('tier') != 'max':
        msg = await message.reply(get_text(lang, 'watermark_max_only'))
        schedule_delete(bot, msg.chat.id, msg.message_id, 30)
        return

    if not user.get('watermark_file_id'):
        await state.set_state(WatermarkState.waiting_for_photo)
        msg = await message.reply(get_text(lang, 'send_watermark_photo'))
        schedule_delete(bot, msg.chat.id, msg.message_id, 60)
        return

    from core.media_processor import watermark_armed
    watermark_armed.add(message.from_user.id)
    msg = await message.reply(get_text(lang, 'watermark_armed'))
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

@user_router.message(F.web_app_data)
async def web_app_data_handler(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']

    from pydantic import ValidationError
    from core.webapp_data import parse_webapp_payload, SaveSettings, BuyTheme, SmartTrim, EditTags

    # sendData можна викликати з довільним JSON (інспектор WebView), тож спершу —
    # строга схема: типи, межі та allowlist значень (див. core/webapp_data.py).
    try:
        payload = parse_webapp_payload(message.web_app_data.data)
    except ValidationError as e:
        logger.info("Rejected web_app_data from %s: %s", message.from_user.id, e.errors(include_url=False)[:3])
        msg = await message.answer(get_text(lang, 'webapp_invalid_data'))
        schedule_delete(bot, msg.chat.id, msg.message_id, 30)
        return

    try:
        if isinstance(payload, SaveSettings):
            language = payload.language or lang
            guest_yt_quality = payload.default_quality or user.get('guest_yt_quality', 'best')
            theme = payload.theme or 'standard'
            owned_themes = (user.get('owned_themes') or 'standard').split(',')

            if message.from_user.id in ADMIN_IDS:
                owned_themes = ['standard', 'neon', 'retro']

            if theme not in owned_themes:
                theme = 'standard'
            watermark_position = payload.watermark_position or user.get('watermark_position', 'bottom_right')

            await update_user_settings(message.from_user.id, language, guest_yt_quality, int(payload.is_anonymous), theme, watermark_position)

            success_text = get_text(language, 'settings_saved_webapp')
            msg = await message.answer(success_text)
            schedule_delete(bot, msg.chat.id, msg.message_id, 60)

            if payload.watermark_updated:
                if user.get('tier') == 'max':
                    await state.set_state(WatermarkState.waiting_for_photo)
                    msg2 = await message.answer(get_text(language, 'send_watermark_photo'))
                    schedule_delete(bot, msg2.chat.id, msg2.message_id, 60)
                else:
                    msg2 = await message.answer(get_text(language, 'watermark_max_only'))
                    schedule_delete(bot, msg2.chat.id, msg2.message_id, 30)

        elif isinstance(payload, BuyTheme):
            from handlers.payment import send_theme_invoice
            await send_theme_invoice(message, payload.theme, user)

        elif isinstance(payload, SmartTrim):
            from handlers.media import process_smart_trim, get_download_block_reason
            from core.config import FREE_TRIM_MAX_SECONDS

            if user.get('tier', 'free') == 'free' and payload.duration > FREE_TRIM_MAX_SECONDS:
                msg = await message.answer(get_text(lang, 'trim_free_limit', seconds=FREE_TRIM_MAX_SECONDS))
                schedule_delete(bot, msg.chat.id, msg.message_id, 30)
                return

            # Ті самі правила, що й для звичайного посилання: заборонені URL, денний ліміт.
            block_reason = await get_download_block_reason(user, payload.url)
            if block_reason:
                msg = await message.answer(get_text(lang, block_reason))
                schedule_delete(bot, msg.chat.id, msg.message_id, 30)
                return

            msg = await message.answer(get_text(lang, 'starting_download'))
            spawn(process_smart_trim(message, user, payload.url, payload.start_sec, payload.end_sec, msg))

        elif isinstance(payload, EditTags):
            from handlers.media import AudioEditorState, process_url, get_download_block_reason

            if user.get('tier', 'free') == 'free':
                msg = await message.answer(get_text(lang, 'tags_pro_only'))
                schedule_delete(bot, msg.chat.id, msg.message_id, 30)
                return

            block_reason = await get_download_block_reason(user, payload.url)
            if block_reason:
                msg = await message.answer(get_text(lang, block_reason))
                schedule_delete(bot, msg.chat.id, msg.message_id, 30)
                return

            if payload.has_cover:
                await state.set_state(AudioEditorState.waiting_for_cover)
                await state.update_data(
                    url=payload.url,
                    title=payload.title,
                    artist=payload.artist,
                    album=payload.album
                )
                await message.answer(get_text(lang, 'send_cover_photo'))
            else:
                await state.update_data(
                    edit_tags=True,
                    title=payload.title,
                    artist=payload.artist,
                    album=payload.album,
                    cover_path=None
                )
                await process_url(message, payload.url, user, is_guest_mode=False, state=state)
    except Exception as e:
        logger.exception("Error handling web_app_data from %s", message.from_user.id)
        try:
            msg = await message.answer(get_text(lang, 'webapp_error', error=html.escape(str(e)[:300])))
            schedule_delete(bot, msg.chat.id, msg.message_id, 30)
        except Exception:
            pass

@user_router.message(WatermarkState.waiting_for_photo, F.photo | F.document)
async def watermark_photo_handler(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)

    if message.photo:
        file_id = message.photo[-1].file_id
    elif message.document and message.document.mime_type and message.document.mime_type.startswith('image/'):
        file_id = message.document.file_id
    else:
        await message.answer(get_text(user['language_code'], 'send_valid_photo'))
        return

    await set_watermark_file_id(message.from_user.id, file_id)
    await state.clear()

    msg = await message.answer(get_text(user['language_code'], 'logo_saved'))
    schedule_delete(bot, msg.chat.id, msg.message_id, 30)

    if user.get('tier') == 'max':
        from core.media_processor import watermark_armed
        watermark_armed.add(message.from_user.id)
        msg2 = await message.answer(get_text(user['language_code'], 'watermark_armed'))
        schedule_delete(bot, msg2.chat.id, msg2.message_id, 60)

@user_router.message(Command("language"))
async def language_command(message: Message):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    msg = await message.reply("Choose your language / Оберіть мову / Wybierz język:", reply_markup=get_lang_keyboard())
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

@user_router.callback_query(F.data == "set_lang")
async def settings_set_lang(callback: CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("Choose your language / Оберіть мову / Wybierz język:", reply_markup=get_lang_keyboard())

@user_router.callback_query(F.data == "set_guest_quality")
async def settings_set_guest_quality(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    current_q = user.get('guest_yt_quality', 'best')
    tier = user.get('tier', 'free')
    text = get_text(user['language_code'], 'guest_quality_text')
    await callback.answer()
    await callback.message.edit_text(text, reply_markup=get_guest_quality_keyboard(current_q, tier))

@user_router.callback_query(F.data.startswith("lang_"))
async def language_callback(callback: CallbackQuery):
    from core.webapp_data import LANGUAGES
    lang_code = callback.data.removeprefix('lang_')
    await callback.answer()
    if lang_code not in LANGUAGES:
        return
    await set_user_language(callback.from_user.id, lang_code)
    
    # Update Web App URL for the new language
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    
    if callback.message.chat.type == "private":
        try:
            from aiogram.types import MenuButtonDefault
            await bot.set_chat_menu_button(
                chat_id=callback.message.chat.id, 
                menu_button=MenuButtonDefault()
            )
        except TelegramAPIError as e:
            logger.warning("Failed to reset menu button for %s: %s", callback.message.chat.id, e)
        reply_markup = get_main_keyboard(lang_code, await webapp_url_for(user))
    else:
        reply_markup = get_main_keyboard(lang_code, None, selective=True)

    # Змінюємо мову головної клавіатури
    msg = await callback.message.answer(get_text(lang_code, 'lang_changed'), reply_markup=reply_markup)
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await callback.message.delete()

@user_router.callback_query(F.data.startswith('setyt_'))
async def set_yt_quality_callback(callback: CallbackQuery):
    from core.webapp_data import GUEST_QUALITIES
    quality = callback.data.removeprefix('setyt_')
    if quality not in GUEST_QUALITIES:
        await callback.answer()
        return
    await set_guest_yt_quality(callback.from_user.id, quality)
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    tier = user.get('tier', 'free')
    success_msg = get_text(user['language_code'], 'settings_success', quality=quality)
    clean_msg = success_msg.replace('<b>', '').replace('</b>', '')
    await callback.message.edit_reply_markup(reply_markup=get_guest_quality_keyboard(quality, tier))
    await callback.answer(clean_msg, show_alert=False)

def get_progress_bar(current, maximum, length=10, lang='uk'):
    if maximum >= 9999:
        return f"██████████ ({get_text(lang, 'unlimited_label')})"
    filled = int(length * current / maximum)
    if filled > length: filled = length
    return "█" * filled + "░" * (length - filled)

@user_router.message(Command("limits"))
@user_router.message(text_matches('menu_profile'))
async def limits_command(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    daily_count = await get_daily_download_count(message.from_user.id)
    
    is_vip = user['is_vip']
    tier = user.get('tier', 'free')
    if tier not in TIER_LIMITS:
        tier = 'free'

    
    if tier == 'free': status = "Free 🆓"
    elif tier == 'pro': status = "Pro ⚡️"
    elif tier == 'max': status = "Max 👑"
    else: status = tier.capitalize()
    
    if is_vip and user.get('vip_until'):
        from core.utils import parse_db_date
        from datetime import datetime, timezone
        try:
            dt = parse_db_date(user['vip_until'])
            formatted_date = dt.strftime("%Y-%m-%d %H:%M")
            remaining_days = (dt - datetime.now(timezone.utc)).days
            if remaining_days < 0: remaining_days = 0
            
            if user['language_code'] == 'en': status += f" (until {formatted_date}, {remaining_days} days left)"
            elif user['language_code'] == 'pl': status += f" (do {formatted_date}, pozostało {remaining_days} dni)"
            else:
                d_word = "днів"
                if remaining_days % 10 == 1 and remaining_days % 100 != 11: d_word = "день"
                elif 2 <= remaining_days % 10 <= 4 and (remaining_days % 100 < 10 or remaining_days % 100 >= 20): d_word = "дні"
                status += f" (до {formatted_date}, залишилось {remaining_days} {d_word})"
        except (TypeError, ValueError, AttributeError) as e:
            logger.warning("Bad vip_until for %s: %s", user['telegram_id'], e)

    max_d = TIER_LIMITS[tier]['daily']
    max_downloads = "∞" if max_d >= 9999 else str(max_d)
    max_size = "∞" if TIER_LIMITS[tier]['size'] >= 9999 * 1024 * 1024 else f"{TIER_LIMITS[tier]['size'] // (1024*1024)} MB"
    max_playlist = "∞" if TIER_LIMITS[tier]['playlist'] >= 9999 else str(TIER_LIMITS[tier]['playlist'])
    
    progress_bar = get_progress_bar(daily_count, max_d, lang=user['language_code'])
    
    text = get_text(
        user['language_code'], 
        'limits_status',
        status=status,
        count=daily_count,
        max_downloads=max_downloads,
        max_size=max_size,
        max_playlist=max_playlist,
        progress_bar=progress_bar
    )
    msg = await message.reply(text)
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

def support_ban_text(user: dict):
    """Текст відмови, якщо користувачу заборонено писати в підтримку, інакше None."""
    if not user.get('banned_support_until'):
        return None
    from core.utils import parse_db_date
    from datetime import datetime, timezone
    ban_until_dt = parse_db_date(user['banned_support_until'])
    if ban_until_dt is None:
        logger.warning("Bad banned_support_until for %s: %r", user['telegram_id'], user['banned_support_until'])
        return None
    if datetime.now(timezone.utc) >= ban_until_dt:
        return None
    if ban_until_dt.year == 9999:
        formatted_date = get_text(user['language_code'], 'forever_label')
    else:
        formatted_date = ban_until_dt.strftime("%Y-%m-%d %H:%M UTC")
    return get_text(user['language_code'], 'banned_support', until=formatted_date)


# Тексти кнопок меню всіма мовами: натискання кнопки під час введення звернення
# означає «передумав», а не текст для підтримки.
_MENU_KEYS = ('menu_profile', 'menu_download', 'menu_watermark', 'menu_help', 'menu_vip', 'menu_hide_keyboard')


def _is_menu_text(text: str) -> bool:
    return any(text == get_text(lang, key) for lang in ('uk', 'en', 'pl') for key in _MENU_KEYS)


@user_router.message(Command("help"))
@user_router.message(text_matches('menu_help'))
async def help_command(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    ban_text = support_ban_text(user)
    if ban_text:
        await message.reply(ban_text)
        return

    msg = await message.reply(get_text(user['language_code'], 'support_prompt'))
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await state.set_state(SupportState.waiting_for_message)

# Довший текст не вміщається в одне повідомлення разом із заголовком (ліміт 4096).
SUPPORT_INLINE_TEXT_LIMIT = 3000


async def forward_to_admins(bot: Bot, message: Message, header: str, copy_original: bool) -> int:
    """Шле адмінам заголовок і (за потреби) копію повідомлення. Повертає, скільки адмінів його отримали."""
    delivered = 0
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, header)
            if copy_original:
                await bot.copy_message(admin_id, from_chat_id=message.chat.id, message_id=message.message_id)
            delivered += 1
        except TelegramAPIError as e:
            logger.warning("Could not deliver support message to admin %s: %s", admin_id, e)
    return delivered


@user_router.message(SupportState.waiting_for_message, ~F.text.startswith('http'))
async def process_support_message(message: Message, state: FSMContext, bot: Bot):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']
    
    if message.text and (_is_menu_text(message.text) or message.text.startswith('/')):
        await state.clear()
        msg = await message.reply(get_text(lang, 'input_cancelled'))
        schedule_delete(bot, msg.chat.id, msg.message_id, 10)
        return

    # Тему (/paysupport) читаємо до clear(): clear() стирає і стан, і дані.
    data = await state.get_data()
    await state.clear()
    ban_text = support_ban_text(user)
    if ban_text:
        await message.reply(ban_text)
        return

    username_part = f"@{html.escape(message.from_user.username)}" if message.from_user.username else "без юзернейму"
    header = (
        f"🆘 <b>Звернення в підтримку</b>\n\n"
        f"<b>Від:</b> <a href='tg://user?id={message.from_user.id}'>{html.escape(message.from_user.full_name)}</a> ({username_part})\n"
        f"<b>ID:</b> <code>{message.from_user.id}</code>"
    )
    if data.get('support_topic') == 'payment':
        header += "\n<b>Тема:</b> оплата (/paysupport)"
    # Фото/голосове/документ або дуже довгий текст пересилаємо копією: раніше
    # html.escape(message.text) падав на None, і звернення без тексту губилось.
    inline_text = bool(message.text) and len(message.text) <= SUPPORT_INLINE_TEXT_LIMIT
    if inline_text:
        header += f"\n\n<b>Повідомлення:</b>\n{html.escape(message.text)}"

    if await forward_to_admins(bot, message, header, copy_original=not inline_text):
        await message.reply(get_text(lang, 'support_sent'))
    else:
        await message.reply(get_text(lang, 'support_unavailable'))

@user_router.message(Command("top", "leaderboard"))
async def top_command(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    top_users = await get_top_users(10)
    
    if not top_users:
        return
        
    lang = user['language_code']
    # HTML з екрануванням замість Markdown: ім'я з непарною `[` чи `*` ламало
    # розмітку, і Telegram відхиляв усе повідомлення («can't parse entities»).
    text = get_text(lang, 'top_users_title') + "\n\n"
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top_users):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = u['full_name'] or u['username'] or "Unknown"
        text += f"{medal} {html.escape(name[:64])} — {u['count']}\n"
        
    sorted_domains = merge_top_domains(await get_top_domains())
    if sorted_domains:
        text += "\n" + get_text(lang, 'top_domains_title') + "\n\n"
        for i, (domain, count) in enumerate(sorted_domains):
            medal = medals[i] if i < 3 else f"{i+1}."
            text += f"{medal} {html.escape(domain)} — {count}\n"
            
    msg = await message.reply(text)
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
