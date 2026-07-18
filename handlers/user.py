import html
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_or_create_user, get_daily_download_count, set_user_language, set_guest_yt_quality, get_top_users, get_top_domains, update_user_settings, get_user_stats
from locales import get_text
import json
from keyboards.inline import get_lang_keyboard, get_guest_quality_keyboard, get_settings_main_keyboard, get_onboarding_keyboard
from keyboards.reply import get_main_keyboard
from core.config import TIER_LIMITS, ADMIN_IDS
import asyncio
from core.utils import delete_later
from core.loader import bot

user_router = Router()

class SupportState(StatesGroup):
    waiting_for_message = State()

from core.webapp import generate_webapp_url
from aiogram.types import MenuButtonWebApp, WebAppInfo

@user_router.message(CommandStart(deep_link=True, magic=F.args == "buy_vip"))
async def start_buy_vip_handler(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    # Redirect to VIP command
    from handlers.payment import vip_command
    await vip_command(message, state)

@user_router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    stats = await get_user_stats(user['telegram_id'])
    
    # Generate Web App URL
    bot_info = await bot.get_me()
    daily_count = await get_daily_download_count(message.from_user.id)
    webapp_url = await generate_webapp_url(user, daily_count, bot_info.username)
    
    # Set the Main Menu Web App Button
    if message.chat.type == "private":
        try:
            await bot.set_chat_menu_button(
                chat_id=message.chat.id, 
                menu_button=MenuButtonWebApp(text=get_text(user['language_code'], 'menu_profile'), web_app=WebAppInfo(url=webapp_url))
            )
        except Exception as e:
            print("Failed to set menu button:", e)
            
    is_new_user = (stats and stats.get('downloads_count', 0) == 0)
    
    if is_new_user:
        msg = await message.reply(get_text(user['language_code'], 'onboarding_greeting'), reply_markup=get_onboarding_keyboard(user['language_code']))
    else:
        if message.chat.type == "private":
            reply_markup = get_main_keyboard(user['language_code'], webapp_url)
        else:
            reply_markup = get_main_keyboard(user['language_code'], None)
            
        msg = await message.reply(get_text(user['language_code'], 'start'), reply_markup=reply_markup)
        
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

from aiogram.utils.keyboard import InlineKeyboardBuilder

@user_router.callback_query(F.data == "onboarding_test_dl")
async def onboarding_test_dl_handler(callback: CallbackQuery, state: FSMContext):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    
    await callback.message.edit_text(get_text(user['language_code'], 'starting_download'))
    
    from handlers.media import start_download
    test_url = "https://www.youtube.com/shorts/xcJtL7QggTI"
    format_spec = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best'
    
    try:
        await start_download(callback.message, test_url, format_spec, user, is_callback=True)
    except Exception as e:
        print(f"Error in onboarding test download: {e}")
        
    bot_info = await bot.get_me()
    daily_count = await get_daily_download_count(user['telegram_id'])
    webapp_url = await generate_webapp_url(user, daily_count, bot_info.username)
    
    builder = InlineKeyboardBuilder()
    builder.button(text=get_text(user['language_code'], 'menu_profile'), web_app=WebAppInfo(url=webapp_url))
    
    msg = await callback.message.answer(get_text(user['language_code'], 'onboarding_success'), reply_markup=builder.as_markup())
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 120))

# Helper to check if text matches a key in any language
def text_matches(key):
    return F.text.in_([get_text(lang, key) for lang in ['uk', 'en', 'pl']])

@user_router.message(text_matches('menu_download'))
async def guide_handler(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    msg = await message.reply(get_text(user['language_code'], 'guide_text'))
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

@user_router.message(text_matches('menu_hide_keyboard'))
async def hide_keyboard_handler(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    msg = await message.reply(get_text(user['language_code'], 'keyboard_hidden'), reply_markup=ReplyKeyboardRemove())
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

@user_router.message(Command('settings'))
@user_router.message(text_matches('menu_settings'))
async def settings_command(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    text = get_text(user['language_code'], 'settings_menu_text')
    msg = await message.reply(text, reply_markup=get_settings_main_keyboard(user['language_code']))
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

@user_router.message(F.web_app_data)
async def web_app_data_handler(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    try:
        data = json.loads(message.web_app_data.data)
        if data.get('action') == 'save_settings':
            language = data.get('language', user['language_code'])
            guest_yt_quality = data.get('default_quality', user.get('guest_yt_quality', 'best'))
            is_anonymous = int(data.get('is_anonymous', 0))
            theme = data.get('theme', 'standard')
            owned_themes = user.get('owned_themes', 'standard').split(',')
            
            if message.from_user.id in ADMIN_IDS:
                owned_themes = ['standard', 'neon', 'retro']
                
            if theme not in owned_themes:
                theme = 'standard'
            watermark_position = data.get('watermark_position', 'bottom_right')
            
            await update_user_settings(message.from_user.id, language, guest_yt_quality, is_anonymous, theme, watermark_position)
            
            success_text = get_text(language, 'settings_saved_webapp')
            msg = await message.answer(success_text)
            asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
            
            if data.get('watermark_updated'):
                msg2 = await message.answer(get_text(language, 'send_watermark_photo'))
                asyncio.create_task(delete_later(bot, msg2.chat.id, msg2.message_id, 60))
        elif data.get('action') == 'buy_theme':
            theme = data.get('theme')
            from handlers.payment import send_theme_invoice
            await send_theme_invoice(message, theme, user)
        elif data.get('action') == 'smart_trim':
            from handlers.media import process_smart_trim
            url = data.get('url')
            start_sec = data.get('start_sec')
            end_sec = data.get('end_sec')
            
            duration = end_sec - start_sec
            tier = user.get('tier', 'free')
            
            if tier == 'free' and duration > 30:
                text = "⚠️ Безкоштовний тариф дозволяє нарізати фрагменти до 30 секунд. Придбайте Pro або зменшіть тривалість."
                if user['language_code'] == 'en':
                    text = "⚠️ Free tier allows trimming up to 30 seconds. Buy Pro or reduce duration."
                elif user['language_code'] == 'pl':
                    text = "⚠️ Darmowy plan pozwala na wycinanie do 30 sekund. Kup Pro lub zmniejsz czas."
                msg = await message.answer(text)
                asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
                return
            
            msg = await message.answer(get_text(user['language_code'], 'starting_download'))
            asyncio.create_task(process_smart_trim(message, user, url, start_sec, end_sec, msg))
        elif data.get('action') == 'edit_tags':
            from handlers.media import AudioEditorState, process_url
            url = data.get('url')
            title = data.get('title', '')
            artist = data.get('artist', '')
            album = data.get('album', '')
            has_cover = data.get('has_cover', False)
            
            tier = user.get('tier', 'free')
            if tier == 'free':
                text = "⚠️ Редагування тегів доступне лише для тарифів Pro та Max."
                if user['language_code'] == 'en':
                    text = "⚠️ Tag editing is only available for Pro and Max tiers."
                elif user['language_code'] == 'pl':
                    text = "⚠️ Edycja tagów jest dostępna tylko dla planów Pro i Max."
                msg = await message.answer(text)
                asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 30))
                return
                
            if has_cover:
                await state.set_state(AudioEditorState.waiting_for_cover)
                await state.update_data(
                    url=url,
                    title=title,
                    artist=artist,
                    album=album
                )
                text = "🖼 Надішліть фотографію для обкладинки треку (як звичайне фото, не файл)."
                if user['language_code'] == 'en':
                    text = "🖼 Send a photo for the track cover (as a photo, not a file)."
                elif user['language_code'] == 'pl':
                    text = "🖼 Wyślij zdjęcie na okładkę utworu (jako zdjęcie, nie jako plik)."
                await message.answer(text)
            else:
                message.text = url # Hack to reuse process_url logic but we need to pass metadata
                # Since process_url uses message.text to find url, we will just call process_url with url
                # Wait, process_url doesn't take metadata yet. We need a way to pass metadata.
                # Let's use a temporary state or pass kwargs. For now, since process_url is complex,
                # we can store metadata in state and pass the state, or add kwargs to process_url.
                # Let's store metadata in state and clear state after download starts.
                await state.update_data(
                    edit_tags=True,
                    title=title,
                    artist=artist,
                    album=album,
                    cover_path=None
                )
                await process_url(message, url, user, is_guest_mode=False, state=state)
    except Exception as e:
        print("Error handling web_app_data:", e)

@user_router.callback_query(F.data == "set_lang")
async def settings_set_lang(callback: CallbackQuery):
    await callback.message.edit_text("Choose your language / Оберіть мову / Wybierz język:", reply_markup=get_lang_keyboard())

@user_router.callback_query(F.data == "set_guest_quality")
async def settings_set_guest_quality(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    current_q = user.get('guest_yt_quality', 'best')
    tier = user.get('tier', 'free')
    text = get_text(user['language_code'], 'guest_quality_text')
    await callback.message.edit_text(text, reply_markup=get_guest_quality_keyboard(current_q, tier))

@user_router.callback_query(F.data.startswith("lang_"))
async def language_callback(callback: CallbackQuery):
    lang_code = callback.data.split('_')[1]
    await set_user_language(callback.from_user.id, lang_code)
    
    # Update Web App URL for the new language
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    bot_info = await bot.get_me()
    daily_count = await get_daily_download_count(callback.from_user.id)
    webapp_url = await generate_webapp_url(user, daily_count, bot_info.username)
    
    if callback.message.chat.type == "private":
        try:
            await bot.set_chat_menu_button(
                chat_id=callback.message.chat.id, 
                menu_button=MenuButtonWebApp(text=get_text(lang_code, 'menu_profile'), web_app=WebAppInfo(url=webapp_url))
            )
        except: pass
        reply_markup = get_main_keyboard(lang_code, webapp_url)
    else:
        reply_markup = get_main_keyboard(lang_code, None)

    # Змінюємо мову головної клавіатури
    msg = await callback.message.answer(get_text(lang_code, 'lang_changed'), reply_markup=reply_markup)
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
    await callback.message.delete()

@user_router.callback_query(F.data.startswith('setyt_'))
async def set_yt_quality_callback(callback: CallbackQuery):
    quality = callback.data.split('_')[1]
    await set_guest_yt_quality(callback.from_user.id, quality)
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    tier = user.get('tier', 'free')
    success_msg = get_text(user['language_code'], 'settings_success', quality=quality)
    clean_msg = success_msg.replace('<b>', '').replace('</b>', '')
    await callback.message.edit_reply_markup(reply_markup=get_guest_quality_keyboard(quality, tier))
    await callback.answer(clean_msg, show_alert=False)

def get_progress_bar(current, maximum, length=10):
    if maximum >= 9999:
        return "██████████ (БЕЗЛІМІТ)"
    filled = int(length * current / maximum)
    if filled > length: filled = length
    return "█" * filled + "░" * (length - filled)

@user_router.message(Command("limits"))
@user_router.message(text_matches('menu_profile'))
async def limits_command(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    daily_count = await get_daily_download_count(message.from_user.id)
    
    is_vip = user['is_vip']
    tier = user.get('tier', 'free')
    
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
        except: pass

    max_d = TIER_LIMITS[tier]['daily']
    max_downloads = "∞" if max_d >= 9999 else str(max_d)
    max_size = "∞" if TIER_LIMITS[tier]['size'] >= 9999 * 1024 * 1024 else f"{TIER_LIMITS[tier]['size'] // (1024*1024)} MB"
    if max_size == "2048 MB": max_size = "2 GB"
    max_playlist = "∞" if TIER_LIMITS[tier]['playlist'] >= 9999 else str(TIER_LIMITS[tier]['playlist'])
    
    progress_bar = get_progress_bar(daily_count, max_d)
    
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
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

@user_router.message(Command("help"))
@user_router.message(text_matches('menu_help'))
async def help_command(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    if user.get('banned_support_until'):
        from core.utils import parse_db_date
        import datetime
        try:
            ban_until_dt = parse_db_date(user['banned_support_until'])
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            if now_dt < ban_until_dt:
                formatted_date = ban_until_dt.strftime("%Y-%m-%d %H:%M")
                if ban_until_dt.year == 9999:
                    formatted_date = "Назавжди / Forever"
                await message.reply(get_text(user['language_code'], 'banned_support', until=formatted_date))
                return
        except Exception:
            pass

    msg = await message.reply(get_text(user['language_code'], 'support_prompt'))
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
    await state.set_state(SupportState.waiting_for_message)

@user_router.message(SupportState.waiting_for_message, ~F.text.startswith('http'))
async def process_support_message(message: Message, state: FSMContext, bot: Bot):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    
    # Check if user pressed a menu button or sent a command
    known_buttons = []
    for lang in ['uk', 'en', 'pl']:
        known_buttons.extend([
            get_text(lang, 'menu_profile'),
            get_text(lang, 'menu_download'),
            get_text(lang, 'menu_settings'),
            get_text(lang, 'menu_help'),
            get_text(lang, 'menu_vip'),
            get_text(lang, 'menu_hide_keyboard')
        ])
        
    if message.text and (message.text in known_buttons or message.text.startswith('/')):
        await state.clear()
        cancel_msg = "❌ Введення скасовано. Натисніть кнопку ще раз." if user['language_code'] == 'uk' else "❌ Input cancelled. Please press the button again."
        msg = await message.reply(cancel_msg)
        asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 10))
        return

    if user.get('banned_support_until'):
        from core.utils import parse_db_date
        import datetime
        try:
            ban_until_dt = parse_db_date(user['banned_support_until'])
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            if now_dt < ban_until_dt:
                formatted_date = ban_until_dt.strftime("%Y-%m-%d %H:%M")
                if ban_until_dt.year == 9999:
                    formatted_date = "Назавжди / Forever"
                await message.reply(get_text(user['language_code'], 'banned_support', until=formatted_date))
                await state.clear()
                return
        except Exception:
            pass
            
    # Send message to all admins
    support_text = f"🆘 <b>Звернення в підтримку</b>\n\n<b>Від:</b> <a href='tg://user?id={message.from_user.id}'>{html.escape(message.from_user.full_name)}</a> (@{message.from_user.username})\n<b>ID:</b> <code>{message.from_user.id}</code>\n\n<b>Повідомлення:</b>\n{html.escape(message.text)}"
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, support_text)
        except:
            pass
            
    await state.clear()
    await message.reply(get_text(user['language_code'], 'support_sent'))

@user_router.message(Command("top", "leaderboard"))
async def top_command(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    top_users = await get_top_users(10)
    
    if not top_users:
        return
        
    text = "🏆 **Лідерборд завантажень** 🏆\n\n"
    if user['language_code'] == 'en': text = "🏆 **Downloads Leaderboard** 🏆\n\n"
    elif user['language_code'] == 'pl': text = "🏆 **Ranking pobrań** 🏆\n\n"
        
    medals = ["🥇", "🥈", "🥉"]
    for i, u in enumerate(top_users):
        medal = medals[i] if i < 3 else f"{i+1}."
        name = u['full_name'] or u['username'] or "Unknown"
        name = name.replace('*', '').replace('_', '').replace('`', '')
        text += f"{medal} {name} — {u['count']}\n"
        
    top_domains = await get_top_domains()
    if top_domains:
        if user['language_code'] == 'en': text += "\n🌐 **Top Sources** 🌐\n\n"
        elif user['language_code'] == 'pl': text += "\n🌐 **Najpopularniejsze źródła** 🌐\n\n"
        else: text += "\n🌐 **Популярні джерела** 🌐\n\n"
            
        domain_mapping = {
            'YouTube': ['youtube.com', 'youtu.be', 'music.youtube.com', 'www.youtube.com', 'm.youtube.com', 'youtube'],
            'Instagram': ['instagram.com', 'www.instagram.com', 'm.instagram.com'],
            'TikTok': ['tiktok.com', 'www.tiktok.com', 'vm.tiktok.com', 'm.tiktok.com'],
            'Spotify': ['spotify.com', 'open.spotify.com'],
            'SoundCloud': ['soundcloud.com', 'on.soundcloud.com', 'm.soundcloud.com'],
            'Threads': ['threads.net', 'www.threads.net', 'threads.com'],
            'Facebook': ['facebook.com', 'www.facebook.com', 'fb.watch', 'm.facebook.com'],
            'GitHub': ['github.com', 'www.github.com']
        }
        
        merged_counts = {}
        for d in top_domains:
            raw_domain = d['domain'].lower()
            mapped = False
            for nice_name, variants in domain_mapping.items():
                if raw_domain in variants or any(v in raw_domain for v in variants):
                    merged_counts[nice_name] = merged_counts.get(nice_name, 0) + d['count']
                    mapped = True
                    break
            if not mapped:
                merged_counts[raw_domain] = merged_counts.get(raw_domain, 0) + d['count']
                
        sorted_domains = sorted(merged_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        for i, (domain, count) in enumerate(sorted_domains):
            medal = medals[i] if i < 3 else f"{i+1}."
            text += f"{medal} {domain} — {count}\n"
            
    msg = await message.reply(text, parse_mode="Markdown")
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
