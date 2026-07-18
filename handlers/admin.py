import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime

from core.config import ADMIN_IDS
from core.loader import bot
from database import get_or_create_user, get_all_users, grant_vip, revoke_vip, get_users_stats_by_tier, ban_user_bot, ban_user_support, unban_user, get_vip_users
from locales import get_text
from keyboards.reply import get_admin_keyboard, get_admin_cancel_keyboard, get_main_keyboard
from core.utils import delete_later

admin_router = Router()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def text_matches(key: str):
    return F.text.in_([get_text(lang, key) for lang in ['uk', 'en', 'pl']])

class AdminState(StatesGroup):
    waiting_for_broadcast_message = State()
    waiting_for_broadcast_button = State()
    waiting_for_give_vip = State()
    waiting_for_remove_vip = State()
    waiting_for_reply = State()
    waiting_for_ban_bot = State()
    waiting_for_ban_support = State()
    waiting_for_unban = State()

@admin_router.message(Command("admin"))
async def admin_command(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id):
        return
        
    await state.clear()
    stats = await get_users_stats_by_tier()
    text = get_text(user['language_code'], 'admin_stats', total=stats['total'], free=stats['free'], pro=stats['pro'], max=stats['max'])
    
    msg = await message.reply(text, reply_markup=get_admin_keyboard(user['language_code']))
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

@admin_router.message(text_matches('admin_btn_exit'))
async def exit_admin_panel(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    msg = await message.reply(get_text(user['language_code'], 'admin_exit_msg'), reply_markup=get_main_keyboard(user['language_code']))
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

@admin_router.message(text_matches('admin_btn_cancel'))
async def cancel_admin_action(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    msg = await message.reply(get_text(user['language_code'], 'admin_cancel_msg'), reply_markup=get_admin_keyboard(user['language_code']))
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

# --- Broadcast ---
@admin_router.message(text_matches('admin_btn_broadcast'))
async def btn_broadcast(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(
        get_text(user['language_code'], 'admin_broadcast_prompt'), 
        reply_markup=get_admin_cancel_keyboard(user['language_code']),
        parse_mode="HTML"
    )
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
    await state.set_state(AdminState.waiting_for_broadcast_message)

@admin_router.message(AdminState.waiting_for_broadcast_message)
async def process_broadcast_message(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await state.update_data(broadcast_message_id=message.message_id)
    from aiogram.utils.keyboard import ReplyKeyboardBuilder
    builder = ReplyKeyboardBuilder()
    builder.button(text=get_text(user['language_code'], 'admin_btn_no_button'))
    builder.button(text=get_text(user['language_code'], 'admin_btn_cancel'))
    builder.adjust(1)
    await message.reply(
        get_text(user['language_code'], 'admin_broadcast_button_prompt'),
        reply_markup=builder.as_markup(resize_keyboard=True),
        parse_mode="HTML"
    )
    await state.set_state(AdminState.waiting_for_broadcast_button)

@admin_router.message(AdminState.waiting_for_broadcast_button)
async def process_broadcast_button(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    data = await state.get_data()
    msg_id = data.get("broadcast_message_id")
    reply_markup = None
    no_btn_text = get_text(user['language_code'], 'admin_btn_no_button')
    if message.text and message.text != no_btn_text:
        if " - " in message.text:
            text, url = message.text.split(" - ", 1)
            if not url.strip().startswith(('http://', 'https://')):
                await message.reply("Невірний формат лінку. Має починатись з http:// або https://")
                return
            from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            reply_markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text=text.strip(), url=url.strip())]
            ])
        else:
            await message.reply(get_text(user['language_code'], 'admin_broadcast_bad_button'))
            return
            
    users = await get_all_users()
    count = 0
    await message.reply(get_text(user['language_code'], 'admin_broadcast_start', count=len(users)), reply_markup=get_admin_keyboard(user['language_code']))
    await state.clear()
    
    for uid in users:
        try:
            await bot.copy_message(
                chat_id=uid,
                from_chat_id=message.chat.id,
                message_id=msg_id,
                reply_markup=reply_markup
            )
            count += 1
            await asyncio.sleep(0.05)
        except Exception:
            pass
            
    await message.reply(get_text(user['language_code'], 'admin_broadcast_done', count=count))

# --- Reply ---
@admin_router.message(text_matches('admin_btn_reply'))
async def btn_reply(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_reply_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
    await state.set_state(AdminState.waiting_for_reply)

@admin_router.message(AdminState.waiting_for_reply)
async def process_reply(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply(get_text(user['language_code'], 'admin_err_format_reply'))
        return
        
    try:
        import html
        target_id = int(args[0])
        text = html.escape(args[1])
        
        target_user = await get_or_create_user(target_id, "", "")
        reply_msg = get_text(target_user['language_code'], 'reply_from_admin', text=text)
        
        await bot.send_message(target_id, reply_msg)
        await message.reply(get_text(user['language_code'], 'admin_reply_success', target_id=target_id), reply_markup=get_admin_keyboard(user['language_code']))
        await state.clear()
    except ValueError:
        await message.reply(get_text(user['language_code'], 'admin_err_id'))
    except Exception as e:
        await message.reply(f"Помилка надсилання: {e}")

# --- Give VIP ---
@admin_router.message(text_matches('admin_btn_give_vip'))
async def btn_give_vip(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_give_vip_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
    await state.set_state(AdminState.waiting_for_give_vip)

@admin_router.message(AdminState.waiting_for_give_vip)
async def process_give_vip(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    args = message.text.split()
    if len(args) < 2:
        await message.reply(get_text(user['language_code'], 'admin_err_format_vip'))
        return
        
    try:
        target_id = int(args[0])
        days = int(args[1])
        tier = args[2].lower() if len(args) > 2 else 'max'
        if tier not in ['free', 'pro', 'max']:
            tier = 'max'
            
        new_date = await grant_vip(target_id, days, tier=tier)
        try:
            from core.utils import parse_db_date
            dt = parse_db_date(new_date)
            formatted_date = dt.strftime("%Y-%m-%d %H:%M")
        except Exception:
            formatted_date = new_date
            
        await message.reply(get_text(user['language_code'], 'vip_granted_admin', user_id=target_id, days=days, new_date=formatted_date, tier=tier), reply_markup=get_admin_keyboard(user['language_code']))
        
        target_user = await get_or_create_user(target_id, "", "")
        try:
            await bot.send_message(target_id, get_text(target_user['language_code'], 'vip_granted_user', vip_until=formatted_date, tier=tier))
        except Exception:
            pass
            
        await state.clear()
    except ValueError as e:
        if str(e) == "User not found":
            await message.reply(get_text(user['language_code'], 'admin_err_not_found'))
        else:
            await message.reply(get_text(user['language_code'], 'admin_err_id_days_num'))

# --- Remove VIP ---
@admin_router.message(text_matches('admin_btn_revoke_vip'))
async def btn_remove_vip(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_revoke_vip_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
    await state.set_state(AdminState.waiting_for_remove_vip)

@admin_router.message(AdminState.waiting_for_remove_vip)
async def process_remove_vip(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    try:
        target_id = int(message.text.strip())
        await revoke_vip(target_id)
        await message.reply(get_text(user['language_code'], 'vip_revoked_admin', user_id=target_id), reply_markup=get_admin_keyboard(user['language_code']))
        await state.clear()
    except ValueError as e:
        if str(e) == "User not found":
            await message.reply(get_text(user['language_code'], 'admin_err_not_found'))
        else:
            await message.reply(get_text(user['language_code'], 'admin_err_id'))

# --- VIP List ---
@admin_router.message(text_matches('admin_btn_vip_list'))
async def btn_vip_list(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    
    vip_users = await get_vip_users()
    if not vip_users:
        msg = await message.reply(get_text(user['language_code'], 'admin_vip_list_empty'))
        asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
        return
        
    text_lines = [f"💎 <b>VIP Користувачі ({len(vip_users)}):</b>\n"]
    for v in vip_users:
        uid = v['telegram_id']
        name = v['full_name'] or "Без імені"
        username = f"@{v['username']}" if v['username'] else "Без юзернейму"
        tier = v['tier'].upper()
        
        try:
            from core.utils import parse_db_date
            from datetime import datetime, timezone
            dt = parse_db_date(v['vip_until'])
            formatted_date = dt.strftime("%Y-%m-%d %H:%M")
            now = datetime.now(timezone.utc)
            if dt.year == 9999:
                days_left = "назавжди"
            elif dt > now:
                days_left = f"залишилось {(dt - now).days} дн."
            else:
                days_left = "минув"
        except Exception:
            formatted_date = v['vip_until'] or "Невідомо"
            days_left = "?"
            
        line = f"👤 <a href='tg://user?id={uid}'>{name}</a> ({username}) | <code>{uid}</code>\n└ {tier} до {formatted_date} ({days_left})\n"
        text_lines.append(line)
        
    full_text = "\n".join(text_lines)
    
    if len(full_text) > 4000:
        import io
        from aiogram.types import BufferedInputFile
        file_content = full_text.encode('utf-8')
        doc = BufferedInputFile(file_content, filename="vip_list.txt")
        await message.reply_document(document=doc, caption=f"Всього VIP: {len(vip_users)}")
    else:
        await message.reply(full_text, parse_mode="HTML")

# --- Ban Bot ---
@admin_router.message(text_matches('admin_btn_ban_bot'))
async def btn_ban_bot(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_ban_bot_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
    await state.set_state(AdminState.waiting_for_ban_bot)

@admin_router.message(AdminState.waiting_for_ban_bot)
async def process_ban_bot(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    args = message.text.split()
    try:
        target_id = int(args[0])
        days = int(args[1]) if len(args) > 1 else None
        
        ban_until_iso = await ban_user_bot(target_id, days)
        try:
            from core.utils import parse_db_date
            dt = parse_db_date(ban_until_iso)
            formatted_date = dt.strftime("%Y-%m-%d %H:%M")
            if dt.year == 9999:
                formatted_date = "Назавжди"
        except Exception:
            formatted_date = ban_until_iso
            
        await message.reply(get_text(user['language_code'], 'admin_user_banned_bot', user_id=target_id, until=formatted_date), reply_markup=get_admin_keyboard(user['language_code']))
        await state.clear()
    except ValueError:
        await message.reply(get_text(user['language_code'], 'admin_err_id_days'))

# --- Ban Support ---
@admin_router.message(text_matches('admin_btn_ban_support'))
async def btn_ban_support(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_ban_support_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
    await state.set_state(AdminState.waiting_for_ban_support)

@admin_router.message(AdminState.waiting_for_ban_support)
async def process_ban_support(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    args = message.text.split()
    try:
        target_id = int(args[0])
        days = int(args[1]) if len(args) > 1 else None
        
        ban_until_iso = await ban_user_support(target_id, days)
        try:
            from core.utils import parse_db_date
            dt = parse_db_date(ban_until_iso)
            formatted_date = dt.strftime("%Y-%m-%d %H:%M")
            if dt.year == 9999:
                formatted_date = "Назавжди"
        except Exception:
            formatted_date = ban_until_iso
            
        await message.reply(get_text(user['language_code'], 'admin_user_banned_support', user_id=target_id, until=formatted_date), reply_markup=get_admin_keyboard(user['language_code']))
        await state.clear()
    except ValueError:
        await message.reply(get_text(user['language_code'], 'admin_err_id_days'))

# --- Unban ---
@admin_router.message(text_matches('admin_btn_unban'))
async def btn_unban(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_unban_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))
    await state.set_state(AdminState.waiting_for_unban)

@admin_router.message(AdminState.waiting_for_unban)
async def process_unban(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    try:
        target_id = int(message.text.strip())
        await unban_user(target_id)
        await message.reply(get_text(user['language_code'], 'admin_user_unbanned', user_id=target_id), reply_markup=get_admin_keyboard(user['language_code']))
        await state.clear()
    except ValueError:
        await message.reply(get_text(user['language_code'], 'admin_err_id'))

# --- Ads Management ---
@admin_router.message(Command("set_ad"))
async def cmd_set_ad(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.reply("Використання: /set_ad <текст у HTML або MarkdownV2>")
        return
    ad_text = args[1]
    from database import set_active_ad
    await set_active_ad(ad_text)
    await message.reply(f"✅ Рекламну кампанію активовано!\nТекст:\n{ad_text}", parse_mode=None)

@admin_router.message(Command("clear_ad"))
async def cmd_clear_ad(message: Message):
    if not is_admin(message.from_user.id): return
    from database import clear_active_ads
    await clear_active_ads()
    await message.reply("✅ Усі рекламні кампанії вимкнено.")

@admin_router.message(Command("test_ad"))
async def cmd_test_ad(message: Message):
    if not is_admin(message.from_user.id): return
    from database import get_active_ad
    ad_text = await get_active_ad()
    if not ad_text:
        await message.reply("❌ Немає активної реклами.")
        return
    
    caption = "Оригінальний підпис до медіа."
    ad_block = f"\n\n📢 Спонсор: {ad_text}"
    max_len = 1024 - len(ad_block)
    if len(caption) > max_len:
        caption = caption[:max_len - 3] + "..."
    final_caption = caption + ad_block

    await message.answer_photo(
        photo="https://via.placeholder.com/800x600.png?text=Test+Ad", 
        caption=final_caption, 
        parse_mode="HTML"
    )

