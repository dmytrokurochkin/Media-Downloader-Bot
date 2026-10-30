import asyncio
import html
import logging
import re
from typing import Optional

from aiogram import Router, F
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter
from aiogram.types import Message
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from core.config import ADMIN_IDS
from core.loader import bot
from database import get_or_create_user, get_user, get_all_users, grant_vip, revoke_vip, get_users_stats_by_tier, ban_user_bot, ban_user_support, unban_user, get_vip_users
from locales import get_text
from keyboards.reply import get_admin_keyboard, get_admin_cancel_keyboard, get_main_keyboard
from core.utils import parse_db_date, schedule_delete, spawn, text_matches

admin_router = Router()
logger = logging.getLogger(__name__)

# Межа для видачі VIP і банів: від'ємні дні раніше «продовжували» VIP у минуле,
# а випадкові 300000 днів переповнювали datetime.
MAX_ADMIN_DAYS = 3650
BROADCAST_DELAY = 0.05

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# Кнопки адмін-меню всіма мовами (крім «Без кнопки» — це валідна відповідь на кроці
# розсилки). Хендлери станів їх не приймають: aiogram перевіряє хендлери в порядку
# реєстрації, і натискання іншої кнопки посеред введення (скажімо, «Відповісти» під
# час розсилки) ставало текстом розсилки для всіх користувачів.
_ADMIN_MENU_KEYS = (
    'admin_btn_broadcast', 'admin_btn_reply', 'admin_btn_give_vip', 'admin_btn_revoke_vip',
    'admin_btn_vip_list', 'admin_btn_ban_bot', 'admin_btn_ban_support', 'admin_btn_unban',
    'admin_btn_exit', 'admin_btn_cancel', 'admin_btn_ads', 'admin_btn_add_ad',
    'admin_btn_test_ad', 'admin_btn_clear_ads',
)
NOT_ADMIN_BUTTON = ~F.text.in_({get_text(lang, key) for lang in ('uk', 'en', 'pl') for key in _ADMIN_MENU_KEYS})


def format_admin_date(value: str, forever: Optional[str] = None) -> str:
    dt = parse_db_date(value)
    if dt is None:
        return value
    if dt.year == 9999 and forever:
        return forever
    return dt.strftime("%Y-%m-%d %H:%M UTC")


def parse_id_and_days(text: Optional[str], days_required: bool):
    """(target_id, days | None) з «ID [дні]». ValueError — якщо не числа або дні поза межами."""
    args = (text or "").split()
    if not args or (days_required and len(args) < 2):
        raise ValueError("format")
    target_id = int(args[0])
    days = int(args[1]) if len(args) > 1 else None
    if days is not None and not 1 <= days <= MAX_ADMIN_DAYS:
        raise ValueError("days")
    return target_id, days

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
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id):
        return
        
    await state.clear()
    stats = await get_users_stats_by_tier()
    text = get_text(user['language_code'], 'admin_stats', total=stats['total'], free=stats['free'], pro=stats['pro'], max=stats['max'])
    
    msg = await message.reply(text, reply_markup=get_admin_keyboard(user['language_code']))
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

@admin_router.message(text_matches('admin_btn_exit'))
async def exit_admin_panel(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    webapp_url = None
    if message.chat.type == "private":
        from handlers.user import webapp_url_for
        webapp_url = await webapp_url_for(user)
    msg = await message.reply(get_text(user['language_code'], 'admin_exit_msg'), reply_markup=get_main_keyboard(user['language_code'], webapp_url))
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

@admin_router.message(text_matches('admin_btn_cancel'))
async def cancel_admin_action(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    msg = await message.reply(get_text(user['language_code'], 'admin_cancel_msg'), reply_markup=get_admin_keyboard(user['language_code']))
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

# --- Broadcast ---
@admin_router.message(text_matches('admin_btn_broadcast'))
async def btn_broadcast(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    await state.clear()
    if broadcast_running():
        await message.reply(get_text(user['language_code'], 'admin_broadcast_running'))
        return
    msg = await message.reply(
        get_text(user['language_code'], 'admin_broadcast_prompt'), 
        reply_markup=get_admin_cancel_keyboard(user['language_code']),
        parse_mode="HTML"
    )
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await state.set_state(AdminState.waiting_for_broadcast_message)

@admin_router.message(AdminState.waiting_for_broadcast_message, NOT_ADMIN_BUTTON)
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

_broadcast_task: Optional[asyncio.Task] = None


def broadcast_running() -> bool:
    return _broadcast_task is not None and not _broadcast_task.done()


async def run_broadcast(user_ids, from_chat_id: int, message_id: int, reply_markup=None) -> dict:
    """Копіює повідомлення всім. Повертає лічильники sent / blocked / failed."""
    stats = {'sent': 0, 'blocked': 0, 'failed': 0}
    for uid in user_ids:
        for _attempt in range(3):
            try:
                await bot.copy_message(chat_id=uid, from_chat_id=from_chat_id, message_id=message_id, reply_markup=reply_markup)
                stats['sent'] += 1
                break
            except TelegramRetryAfter as e:
                # Флуд-ліміт: раніше помилка ковталась, і ВСІ наступні користувачі теж
                # отримували відмову. Чекаємо, скільки сказав Telegram, і повторюємо.
                await asyncio.sleep(e.retry_after + 1)
            except TelegramForbiddenError:
                stats['blocked'] += 1
                break
            except TelegramAPIError as e:
                logger.info("Broadcast to %s failed: %s", uid, e)
                stats['failed'] += 1
                break
        else:
            stats['failed'] += 1
        await asyncio.sleep(BROADCAST_DELAY)
    return stats


async def _broadcast_and_report(admin_chat_id: int, lang: str, user_ids, from_chat_id: int, message_id: int, reply_markup) -> None:
    try:
        stats = await run_broadcast(user_ids, from_chat_id, message_id, reply_markup)
    except Exception:
        logger.exception("Broadcast crashed")
        stats = None
    try:
        if stats is None:
            await bot.send_message(admin_chat_id, get_text(lang, 'admin_broadcast_crashed'))
        else:
            await bot.send_message(admin_chat_id, get_text(lang, 'admin_broadcast_report', **stats))
    except TelegramAPIError as e:
        logger.warning("Could not send broadcast report: %s", e)


@admin_router.message(AdminState.waiting_for_broadcast_button, NOT_ADMIN_BUTTON)
async def process_broadcast_button(message: Message, state: FSMContext):
    global _broadcast_task
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']
    data = await state.get_data()
    msg_id = data.get("broadcast_message_id")
    reply_markup = None
    no_btn_text = get_text(lang, 'admin_btn_no_button')
    if message.text != no_btn_text:
        text, _, url = (message.text or "").partition(" - ")
        text, url = text.strip(), url.strip()
        if not text or not url.startswith(('http://', 'https://')):
            await message.reply(get_text(lang, 'admin_broadcast_bad_button'))
            return
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        reply_markup = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=text, url=url)]
        ])

    if broadcast_running():
        await message.reply(get_text(lang, 'admin_broadcast_running'))
        return

    users = await get_all_users()
    await message.reply(get_text(lang, 'admin_broadcast_start', count=len(users)), reply_markup=get_admin_keyboard(lang))
    await state.clear()
    # У фоні: розсилка на тисячі користувачів триває хвилини, а звіт прийде окремим повідомленням.
    _broadcast_task = spawn(_broadcast_and_report(message.chat.id, lang, users, message.chat.id, msg_id, reply_markup))

# --- Reply ---
@admin_router.message(text_matches('admin_btn_reply'))
async def btn_reply(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_reply_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await state.set_state(AdminState.waiting_for_reply)

@admin_router.message(AdminState.waiting_for_reply, NOT_ADMIN_BUTTON)
async def process_reply(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply(get_text(lang, 'admin_err_format_reply'))
        return
        
    try:
        target_id = int(args[0])
    except ValueError:
        await message.reply(get_text(lang, 'admin_err_id'))
        return

    # get_user, а не get_or_create_user(id, "", ""): опечатка в ID створювала в БД
    # «порожнього» користувача, якому потім ішли розсилки й retention-подарунки.
    target_user = await get_user(target_id)
    if not target_user:
        await message.reply(get_text(lang, 'admin_err_not_found'))
        return

    reply_msg = get_text(target_user['language_code'], 'reply_from_admin', text=html.escape(args[1]))
    try:
        await bot.send_message(target_id, reply_msg)
    except TelegramAPIError as e:
        # Текст помилки екрануємо: бот шле HTML, і `<` в описі ламав саме повідомлення про помилку.
        await message.reply(get_text(lang, 'admin_reply_failed', error=html.escape(str(e))))
        return
    await message.reply(get_text(lang, 'admin_reply_success', target_id=target_id), reply_markup=get_admin_keyboard(lang))
    await state.clear()

# --- Give VIP ---
@admin_router.message(text_matches('admin_btn_give_vip'))
async def btn_give_vip(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_give_vip_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await state.set_state(AdminState.waiting_for_give_vip)

@admin_router.message(AdminState.waiting_for_give_vip, NOT_ADMIN_BUTTON)
async def process_give_vip(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']
    args = (message.text or "").split()
    if len(args) < 2:
        await message.reply(get_text(lang, 'admin_err_format_vip'))
        return
        
    try:
        target_id, days = parse_id_and_days(message.text, days_required=True)
    except ValueError as e:
        key = 'admin_err_days_range' if str(e) == "days" else 'admin_err_id_days_num'
        await message.reply(get_text(lang, key, max_days=MAX_ADMIN_DAYS))
        return

    tier = args[2].lower() if len(args) > 2 else 'max'
    # Раніше невідомий рівень (опечатка «por») мовчки ставав 'max', а 'free' давав «VIP Free».
    if tier not in ('pro', 'max'):
        await message.reply(get_text(lang, 'admin_err_tier'))
        return

    target_user = await get_user(target_id)
    if not target_user:
        await message.reply(get_text(lang, 'admin_err_not_found'))
        return
            
    new_date = await grant_vip(target_id, days, tier=tier)
    formatted_date = format_admin_date(new_date)
    await message.reply(get_text(lang, 'vip_granted_admin', user_id=target_id, days=days, new_date=formatted_date, tier=tier), reply_markup=get_admin_keyboard(lang))
    
    try:
        await bot.send_message(target_id, get_text(target_user['language_code'], 'vip_granted_user', vip_until=formatted_date, tier=tier))
    except TelegramAPIError as e:
        logger.info("Could not notify %s about granted VIP: %s", target_id, e)
        
    await state.clear()

# --- Remove VIP ---
@admin_router.message(text_matches('admin_btn_revoke_vip'))
async def btn_remove_vip(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_revoke_vip_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await state.set_state(AdminState.waiting_for_remove_vip)

@admin_router.message(AdminState.waiting_for_remove_vip, NOT_ADMIN_BUTTON)
async def process_remove_vip(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    try:
        target_id = int((message.text or "").strip())
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
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    await state.clear()
    
    vip_users = await get_vip_users()
    if not vip_users:
        msg = await message.reply(get_text(user['language_code'], 'admin_vip_list_empty'))
        schedule_delete(bot, msg.chat.id, msg.message_id, 60)
        return
        
    text_lines = [f"💎 <b>VIP Користувачі ({len(vip_users)}):</b>\n"]
    for v in vip_users:
        uid = v['telegram_id']
        # Імена й юзернейми — дані користувачів: `<` чи `&` в імені раніше ламали
        # HTML, і весь список не відправлявся.
        name = html.escape(v['full_name'] or "Без імені")
        username = f"@{html.escape(v['username'])}" if v['username'] else "Без юзернейму"
        tier = html.escape((v['tier'] or '?').upper())
        
        try:
            from datetime import datetime, timezone
            dt = parse_db_date(v['vip_until'])
            if dt is None:
                raise ValueError("bad vip_until")
            formatted_date = dt.strftime("%Y-%m-%d %H:%M")
            now = datetime.now(timezone.utc)
            if dt.year == 9999:
                days_left = "назавжди"
            elif dt > now:
                days_left = f"залишилось {(dt - now).days} дн."
            else:
                days_left = "минув"
        except (TypeError, ValueError):
            formatted_date = html.escape(str(v['vip_until'] or "Невідомо"))
            days_left = "?"
            
        line = f"👤 <a href='tg://user?id={uid}'>{name}</a> ({username}) | <code>{uid}</code>\n└ {tier} до {formatted_date} ({days_left})\n"
        text_lines.append(line)
        
    full_text = "\n".join(text_lines)
    
    if len(full_text) > 4000:
        from aiogram.types import BufferedInputFile
        # У .txt HTML не рендериться — віддаємо чистий текст.
        file_content = html.unescape(re.sub(r'<[^>]+>', '', full_text)).encode('utf-8')
        doc = BufferedInputFile(file_content, filename="vip_list.txt")
        await message.reply_document(document=doc, caption=f"Всього VIP: {len(vip_users)}")
    else:
        await message.reply(full_text, parse_mode="HTML")

# --- Ban Bot ---
@admin_router.message(text_matches('admin_btn_ban_bot'))
async def btn_ban_bot(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_ban_bot_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await state.set_state(AdminState.waiting_for_ban_bot)

async def _process_ban(message: Message, state: FSMContext, ban_func, done_key: str) -> None:
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']
    try:
        target_id, days = parse_id_and_days(message.text, days_required=False)
    except ValueError as e:
        key = 'admin_err_days_range' if str(e) == "days" else 'admin_err_id_days'
        await message.reply(get_text(lang, key, max_days=MAX_ADMIN_DAYS))
        return

    # Без перевірки UPDATE для неіснуючого ID нічого не змінював, а адмін бачив «забанено».
    if not await get_user(target_id):
        await message.reply(get_text(lang, 'admin_err_not_found'))
        return

    ban_until_iso = await ban_func(target_id, days)
    formatted_date = format_admin_date(ban_until_iso, forever=get_text(lang, 'forever_label'))
    await message.reply(get_text(lang, done_key, user_id=target_id, until=formatted_date), reply_markup=get_admin_keyboard(lang))
    await state.clear()


@admin_router.message(AdminState.waiting_for_ban_bot, NOT_ADMIN_BUTTON)
async def process_ban_bot(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await _process_ban(message, state, ban_user_bot, 'admin_user_banned_bot')

# --- Ban Support ---
@admin_router.message(text_matches('admin_btn_ban_support'))
async def btn_ban_support(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_ban_support_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await state.set_state(AdminState.waiting_for_ban_support)

@admin_router.message(AdminState.waiting_for_ban_support, NOT_ADMIN_BUTTON)
async def process_ban_support(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    await _process_ban(message, state, ban_user_support, 'admin_user_banned_support')

# --- Unban ---
@admin_router.message(text_matches('admin_btn_unban'))
async def btn_unban(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_unban_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']), parse_mode="Markdown")
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await state.set_state(AdminState.waiting_for_unban)

@admin_router.message(AdminState.waiting_for_unban, NOT_ADMIN_BUTTON)
async def process_unban(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    try:
        target_id = int((message.text or "").strip())
        if not await get_user(target_id):
            await message.reply(get_text(user['language_code'], 'admin_err_not_found'))
            return
        await unban_user(target_id)
        await message.reply(get_text(user['language_code'], 'admin_user_unbanned', user_id=target_id), reply_markup=get_admin_keyboard(user['language_code']))
        await state.clear()
    except ValueError:
        await message.reply(get_text(user['language_code'], 'admin_err_id'))

# --- Refund ---
@admin_router.message(Command("refund"))
async def refund_command(message: Message):
    """Повернення Stars за платежем: спершу гроші (Telegram), потім відкат покупки в БД."""
    if not is_admin(message.from_user.id):
        return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']
    from aiogram.exceptions import TelegramBadRequest
    from database import get_payment, refund_payment

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        await message.reply(get_text(lang, 'admin_refund_usage'))
        return
    charge_id = args[1].strip()

    payment = await get_payment(charge_id)
    if not payment or payment['status'] != 'paid':
        await message.reply(get_text(lang, 'admin_refund_not_found'))
        return

    try:
        await bot.refund_star_payment(user_id=payment['payer_id'], telegram_payment_charge_id=charge_id)
    except TelegramBadRequest as e:
        await message.reply(get_text(lang, 'admin_refund_failed', error=html.escape(str(e))))
        return

    refunded = await refund_payment(charge_id)
    if refunded is None:
        await message.reply(get_text(lang, 'admin_refund_not_found'))
        return
    await message.reply(get_text(lang, 'admin_refund_done', amount=refunded['amount'], user_id=refunded['payer_id']))

# --- Ads Management ---
class AdState(StatesGroup):
    waiting_for_ad_text = State()

@admin_router.message(text_matches('admin_btn_ads'))
async def btn_ads_menu(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    await state.clear()
    from keyboards.reply import get_admin_ad_keyboard
    msg = await message.reply("📢 Управління рекламою:", reply_markup=get_admin_ad_keyboard(user['language_code']))
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

@admin_router.message(text_matches('admin_btn_add_ad'))
async def btn_add_ad(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    msg = await message.reply(get_text(user['language_code'], 'admin_ad_prompt'), reply_markup=get_admin_cancel_keyboard(user['language_code']))
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)
    await state.set_state(AdState.waiting_for_ad_text)

@admin_router.message(AdState.waiting_for_ad_text, NOT_ADMIN_BUTTON)
async def process_add_ad(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']
    ad_text = (message.text or "").strip()
    if not ad_text:
        await message.reply(get_text(lang, 'admin_ad_empty'))
        return

    # Рекламу перевіряємо ДО збереження: вона додається в підпис кожного файлу Free-
    # користувачів з parse_mode=HTML. Один незакритий тег чи задовгий текст раніше
    # ламав відправку всім Free-користувачам. Telegram сам розбирає HTML у тестовому
    # повідомленні, а довжину рахуємо по видимому тексту (в UTF-16, як Telegram).
    from aiogram.exceptions import TelegramBadRequest
    from core.config import AD_MAX_LENGTH
    try:
        preview = await message.answer(ad_text, parse_mode="HTML")
    except TelegramBadRequest as e:
        await message.reply(get_text(lang, 'admin_ad_invalid_html', error=html.escape(str(e))), parse_mode="HTML")
        return  # стан лишається: адмін може одразу надіслати виправлений текст
    visible_length = len((preview.text or "").encode("utf-16-le")) // 2
    if visible_length > AD_MAX_LENGTH:
        await message.reply(get_text(lang, 'admin_ad_too_long', length=visible_length, limit=AD_MAX_LENGTH))
        return

    from database import set_active_ad
    await set_active_ad(ad_text)
    from keyboards.reply import get_admin_ad_keyboard
    await message.reply(get_text(lang, 'admin_ad_added', text=ad_text), parse_mode=None, reply_markup=get_admin_ad_keyboard(lang))
    await state.clear()

@admin_router.message(text_matches('admin_btn_clear_ads'))
async def btn_clear_ads(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    await state.clear()
    from database import clear_active_ads
    await clear_active_ads()
    await message.reply(get_text(user['language_code'], 'admin_ad_cleared'))

@admin_router.message(text_matches('admin_btn_test_ad'))
async def btn_test_ad(message: Message, state: FSMContext):
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    if not is_admin(message.from_user.id): return
    await state.clear()
    from database import get_active_ad
    ad_text = await get_active_ad()
    if not ad_text:
        await message.reply(get_text(user['language_code'], 'admin_ad_not_found'))
        return

    # Той самий шлях, що й для справжніх файлів, — тест показує рівно те, що побачать користувачі.
    from handlers.media import prepare_caption_with_ad
    caption = await prepare_caption_with_ad("Оригінальний підпис до медіа.", {"tier": "free", "language_code": user['language_code']})

    # Картинку генеруємо локально: зовнішній сервіс заглушок (via.placeholder.com) може
    # бути недоступним, і тоді «тест реклами» падав незалежно від самої реклами.
    import io
    from PIL import Image, ImageDraw
    from aiogram.types import BufferedInputFile
    from aiogram.exceptions import TelegramBadRequest
    image = Image.new("RGB", (800, 450), (40, 44, 52))
    ImageDraw.Draw(image).text((340, 215), "Test Ad", fill=(255, 255, 255))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    try:
        await message.answer_photo(
            photo=BufferedInputFile(buffer.getvalue(), filename="test_ad.png"),
            caption=caption,
            parse_mode="HTML"
        )
    except TelegramBadRequest as e:
        await message.reply(get_text(user['language_code'], 'admin_ad_invalid_html', error=html.escape(str(e))), parse_mode="HTML")
