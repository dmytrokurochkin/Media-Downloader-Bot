import datetime
import html
import logging
import re
from dataclasses import dataclass
from typing import Optional

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import VIP_TARIFFS, THEME_PRICES, ADMIN_IDS
from core.loader import bot
from database import (
    get_or_create_user, get_user, apply_vip_purchase, apply_theme_purchase, get_user_payments,
)
from locales import get_text
from core.utils import schedule_delete, text_matches

payment_router = Router()
logger = logging.getLogger(__name__)


@dataclass
class PaymentItem:
    kind: str            # 'vip' | 'theme'
    item: str            # ключ тарифу (pro_30d) або назва теми
    beneficiary_id: int  # кому зараховується покупка


_VIP_PAYLOAD_RE = re.compile(r'vip_([a-z]+_\d+d)_(\d+)')
_THEME_PAYLOAD_RE = re.compile(r'buytheme_([a-z]+)_(\d+)')


def parse_payment_payload(payload: str) -> Optional[PaymentItem]:
    """Розбирає payload інвойсу, який сформував сам бот. Будь-що інше — None."""
    if match := _VIP_PAYLOAD_RE.fullmatch(payload or ''):
        return PaymentItem('vip', match.group(1), int(match.group(2)))
    if match := _THEME_PAYLOAD_RE.fullmatch(payload or ''):
        return PaymentItem('theme', match.group(1), int(match.group(2)))
    return None


def expected_price(item: PaymentItem) -> Optional[int]:
    if item.kind == 'vip':
        tariff = VIP_TARIFFS.get(item.item)
        return tariff['stars'] if tariff else None
    if item.kind == 'theme':
        return THEME_PRICES.get(item.item)
    return None


def _is_banned_in_bot(user: dict) -> bool:
    from core.utils import parse_db_date
    ban_until = parse_db_date(user.get('banned_bot_until'))
    return bool(ban_until and ban_until > datetime.datetime.now(datetime.timezone.utc))


async def validate_purchase(payload: str, payer_id: int, amount: int, currency: str) -> Optional[str]:
    """Перевірка в pre_checkout. Повертає ключ локалі з причиною відмови або None.

    Раніше pre_checkout завжди відповідав ok=True: старий інвойс (тарифи змінились,
    тема вже куплена) успішно оплачувався, а successful_payment мовчки нічого не
    видавав. Відмова тут означає, що гроші просто не спишуться.
    """
    item = parse_payment_payload(payload)
    if item is None:
        return 'payment_invalid'
    price = expected_price(item)
    if price is None or currency != 'XTR' or amount != price:
        return 'payment_invalid'

    beneficiary = await get_user(item.beneficiary_id)
    if beneficiary is None:
        return 'payment_invalid'

    payer = await get_user(payer_id)
    if payer is not None and _is_banned_in_bot(payer):
        return 'payment_banned'

    if item.kind == 'theme' and item.item in (beneficiary.get('owned_themes') or '').split(','):
        return 'theme_already_owned'
    return None


@payment_router.message(Command("vip"))
@payment_router.message(text_matches('menu_vip'))
async def vip_command(message: Message, state: FSMContext):
    schedule_delete(bot, message.chat.id, message.message_id, 60)
    await state.clear()
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']

    builder = InlineKeyboardBuilder()

    days_list = [7, 30, 365]
    for days in days_list:
        for tier in ['pro', 'max']:
            t_key = f"{tier}_{days}d"
            if t_key in VIP_TARIFFS:
                tariff = VIP_TARIFFS[t_key]
                tier_name = tariff['tier'].capitalize()

                days_str = f"{days} Days"
                if lang == 'uk':
                    days_str = f"{days} Дні" if days == 3 else f"{days} Днів"
                elif lang == 'pl':
                    days_str = f"{days} Dni"

                price_text = f"{tariff['stars']}⭐️"

                btn_text = f"{tier_name} {days_str} - {price_text}"
                builder.button(text=btn_text, callback_data=f"pay_stars_{t_key}")

    builder.adjust(2)
    msg = await message.reply(get_text(lang, 'vip_menu'), reply_markup=builder.as_markup(), parse_mode="HTML")
    schedule_delete(bot, msg.chat.id, msg.message_id, 60)

@payment_router.callback_query(F.data.startswith("pay_stars_"))
async def process_payment_selection(callback: CallbackQuery):
    tariff_key = callback.data.removeprefix("pay_stars_")

    tariff = VIP_TARIFFS.get(tariff_key)
    if not tariff:
        await callback.answer()
        return

    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    lang = user['language_code']

    if user['is_vip'] and user['tier'] != 'free' and user['tier'] != tariff['tier']:
        builder = InlineKeyboardBuilder()
        builder.button(text=get_text(lang, 'btn_continue'), callback_data=f"confirm_pay_{tariff_key}")
        builder.button(text=get_text(lang, 'btn_cancel'), callback_data="cancel_tier_change")
        builder.adjust(1)

        await callback.message.edit_text(
            get_text(lang, 'tier_change_warning', old_tier=user['tier'].capitalize(), new_tier=tariff['tier'].capitalize()),
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    await _send_invoice(callback, tariff_key, tariff, user)

@payment_router.callback_query(F.data.startswith("confirm_pay_"))
async def confirm_payment_selection(callback: CallbackQuery):
    tariff_key = callback.data.removeprefix("confirm_pay_")

    tariff = VIP_TARIFFS.get(tariff_key)
    if not tariff:
        await callback.answer()
        return

    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    await callback.message.delete()
    await _send_invoice(callback, tariff_key, tariff, user)

@payment_router.callback_query(F.data == "cancel_tier_change")
async def cancel_tier_change(callback: CallbackQuery):
    user = await get_user(callback.from_user.id)
    lang = user['language_code'] if user else 'en'
    await callback.message.edit_text(get_text(lang, 'tier_change_cancelled'))
    await callback.answer()

async def _send_invoice(callback: CallbackQuery, tariff_key: str, tariff: dict, user: dict):
    lang = user.get('language_code', 'en')
    tier_name = tariff['tier'].capitalize()
    title = get_text(lang, 'invoice_vip_title', tier=tier_name, days=tariff['days'])
    description = get_text(lang, 'invoice_vip_description', tier=tier_name, days=tariff['days'])

    payload = f"vip_{tariff_key}_{callback.from_user.id}"

    prices = [LabeledPrice(label="XTR", amount=tariff['stars'])]
    await bot.send_invoice(
        chat_id=callback.message.chat.id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=prices
    )
    await callback.answer()

async def send_theme_invoice(message: Message, theme: str, user: dict):
    price = THEME_PRICES.get(theme)
    if price is None:
        return

    lang = user.get('language_code', 'en')
    # Не продаємо тему вдруге: раніше за ту саму тему можна було заплатити кілька разів.
    if theme in (user.get('owned_themes') or 'standard').split(','):
        msg = await message.answer(get_text(lang, 'theme_already_owned'))
        schedule_delete(bot, msg.chat.id, msg.message_id, 30)
        return

    title = f"{theme.capitalize()} Theme"
    payload = f"buytheme_{theme}_{message.from_user.id}"
    prices = [LabeledPrice(label=title, amount=price)]

    await bot.send_invoice(
        chat_id=message.chat.id,
        title=title,
        description=get_text(lang, 'invoice_theme_description', theme=theme.capitalize()),
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=prices
    )

@payment_router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    # Telegram чекає відповідь до 10 секунд — тут лише швидкі перевірки по БД.
    try:
        error_key = await validate_purchase(
            pre_checkout_query.invoice_payload,
            pre_checkout_query.from_user.id,
            pre_checkout_query.total_amount,
            pre_checkout_query.currency,
        )
    except Exception:
        logger.exception("pre_checkout validation failed for %s", pre_checkout_query.invoice_payload)
        error_key = 'payment_invalid'

    if error_key is None:
        await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)
        return

    payer = await get_user(pre_checkout_query.from_user.id)
    lang = payer['language_code'] if payer else 'en'
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=False, error_message=get_text(lang, error_key))


async def _notify_admins_about_payment_problem(message: Message, charge_id: str, payload: str) -> None:
    text = (
        f"⚠️ <b>Платіж не оброблено</b>\n\nВід: <code>{message.from_user.id}</code>\n"
        f"Payload: <code>{html.escape(payload)}</code>\nCharge ID: <code>{html.escape(charge_id)}</code>"
    )
    for admin_id in ADMIN_IDS:
        try:
            await bot.send_message(admin_id, text)
        except Exception as e:
            logger.warning("Could not notify admin %s about payment: %s", admin_id, e)


@payment_router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payment = message.successful_payment
    payload = payment.invoice_payload
    charge_id = payment.telegram_payment_charge_id
    payer = await get_user(message.from_user.id)
    lang = payer['language_code'] if payer else 'en'

    item = parse_payment_payload(payload)
    try:
        if item and item.kind == 'vip' and item.item in VIP_TARIFFS:
            tariff = VIP_TARIFFS[item.item]
            new_date = await apply_vip_purchase(
                charge_id, message.from_user.id, item.beneficiary_id, item.item,
                tariff['tier'], tariff['days'], payment.total_amount, payment.currency, payload,
            )
            if new_date is None:
                # Той самий charge_id уже зараховано — повторна доставка апдейту.
                logger.info("Duplicate successful_payment %s ignored", charge_id)
                return

            from core.utils import parse_db_date
            dt = parse_db_date(new_date)
            formatted_date = dt.strftime("%Y-%m-%d %H:%M") if dt else new_date
            await message.reply(get_text(lang, 'payment_success', vip_until=formatted_date))
            return

        if item and item.kind == 'theme' and item.item in THEME_PRICES:
            applied = await apply_theme_purchase(
                charge_id, message.from_user.id, item.beneficiary_id, item.item,
                payment.total_amount, payment.currency, payload,
            )
            if not applied:
                logger.info("Duplicate successful_payment %s ignored", charge_id)
                return
            await message.reply(get_text(lang, 'theme_purchased'))
            return

        raise ValueError(f"Unknown payment payload: {payload}")
    except Exception:
        # Гроші вже списані: користувач має знати, куди звернутись, а адмін — що виправити.
        logger.exception("Could not apply payment %s (%s)", charge_id, payload)
        await message.reply(get_text(lang, 'payment_problem'))
        await _notify_admins_about_payment_problem(message, charge_id, payload)


@payment_router.message(Command("paysupport"))
async def paysupport_command(message: Message, state: FSMContext):
    """Підтримка з оплатами: Telegram очікує /paysupport від ботів, що приймають Stars."""
    user = await get_or_create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    lang = user['language_code']

    payments = await get_user_payments(message.from_user.id)
    if payments:
        lines = "\n".join(
            f"• {(p['created_at'] or '')[:16]} — {html.escape(p['item'])} — {p['amount']} ⭐ — "
            f"{'↩️' if p['status'] == 'refunded' else '✅'} <code>{html.escape(p['charge_id'])}</code>"
            for p in payments
        )
    else:
        lines = get_text(lang, 'paysupport_no_payments')

    from handlers.user import SupportState, support_ban_text
    ban_text = support_ban_text(user)
    if ban_text:
        # Список платежів показуємо й тут: charge_id знадобиться для звернення до @PremiumBot.
        await message.reply(get_text(lang, 'paysupport_no_support', payments=lines) + "\n\n" + ban_text)
        return

    await message.reply(get_text(lang, 'paysupport_prompt', payments=lines))
    # Наступне повідомлення піде адміністрації тим самим шляхом, що й звичайна підтримка.
    await state.clear()
    await state.set_state(SupportState.waiting_for_message)
    await state.update_data(support_topic='payment')
