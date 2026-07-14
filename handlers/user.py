import html
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from database import get_or_create_user, get_daily_download_count, set_user_language, set_guest_yt_quality, get_top_users, get_top_domains
from locales import get_text
from keyboards.inline import get_lang_keyboard, get_guest_quality_keyboard, get_settings_main_keyboard
from keyboards.reply import get_main_keyboard
from core.config import TIER_LIMITS, ADMIN_IDS
import asyncio
from core.utils import delete_later
from core.loader import bot

user_router = Router()

class SupportState(StatesGroup):
    waiting_for_message = State()

@user_router.message(CommandStart())
async def start_handler(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    msg = await message.reply(get_text(user['language_code'], 'start'), reply_markup=get_main_keyboard(user['language_code']))
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

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
    # Змінюємо мову головної клавіатури
    msg = await callback.message.answer(get_text(lang_code, 'lang_changed'), reply_markup=get_main_keyboard(lang_code))
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
        from datetime import datetime, timezone
        try:
            dt = datetime.fromisoformat(user['vip_until'].replace(' ', 'T'))
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
        import datetime
        try:
            ban_date_str = user['banned_support_until'].replace(' ', 'T')
            ban_until_dt = datetime.datetime.fromisoformat(ban_date_str)
            if ban_until_dt.tzinfo is None:
                ban_until_dt = ban_until_dt.replace(tzinfo=datetime.timezone.utc)
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
    
    if user.get('banned_support_until'):
        import datetime
        try:
            ban_date_str = user['banned_support_until'].replace(' ', 'T')
            ban_until_dt = datetime.datetime.fromisoformat(ban_date_str)
            if ban_until_dt.tzinfo is None:
                ban_until_dt = ban_until_dt.replace(tzinfo=datetime.timezone.utc)
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
