from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, PreCheckoutQuery, LabeledPrice
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder

from core.config import VIP_TARIFFS, PAYMENT_PROVIDER_TOKEN
from core.loader import bot
from database import get_or_create_user, grant_vip
from locales import get_text
import asyncio
from core.utils import delete_later

payment_router = Router()

def text_matches(key):
    return lambda msg: msg.text in [get_text(lang, key) for lang in ['uk', 'en', 'pl']]

@payment_router.message(Command("vip"))
@payment_router.message(text_matches('menu_vip'))
async def vip_command(message: Message, state: FSMContext):
    asyncio.create_task(delete_later(bot, message.chat.id, message.message_id, 60))
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
    asyncio.create_task(delete_later(bot, msg.chat.id, msg.message_id, 60))

@payment_router.callback_query(F.data.startswith("pay_stars_"))
async def process_payment_selection(callback: CallbackQuery):
    parts = callback.data.split('_')
    tariff_key = f"{parts[2]}_{parts[3]}"
    
    tariff = VIP_TARIFFS.get(tariff_key)
    if not tariff:
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
        return
        
    await _send_invoice(callback, tariff_key, tariff, user)

@payment_router.callback_query(F.data.startswith("confirm_pay_"))
async def confirm_payment_selection(callback: CallbackQuery):
    parts = callback.data.split('_')
    tariff_key = f"{parts[2]}_{parts[3]}"
    
    tariff = VIP_TARIFFS.get(tariff_key)
    if not tariff:
        return
        
    user = await get_or_create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
    await callback.message.delete()
    await _send_invoice(callback, tariff_key, tariff, user)

@payment_router.callback_query(F.data == "cancel_tier_change")
async def cancel_tier_change(callback: CallbackQuery):
    user = await get_or_create_user(callback.from_user.id, "", "")
    await callback.message.edit_text(get_text(user['language_code'], 'tier_change_cancelled'))

async def _send_invoice(callback: CallbackQuery, tariff_key: str, tariff: dict, user: dict):
    lang = user.get('language_code', 'en')
    
    if lang == 'uk':
        title = f"VIP на {tariff['days']} Днів"
        description = f"Придбання VIP підписки на {tariff['days']} днів"
    elif lang == 'pl':
        title = f"VIP na {tariff['days']} Dni"
        description = f"Zakup subskrypcji VIP na {tariff['days']} dni"
    else:
        title = f"VIP {tariff['days']} Days"
        description = f"Purchase VIP subscription for {tariff['days']} days"
        
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
    if theme == 'neon':
        title = "Neon Theme"
        description = "Купити Neon Theme / Buy Neon Theme"
        price = 50
    elif theme == 'retro':
        title = "Retro Theme"
        description = "Купити Retro Theme / Buy Retro Theme"
        price = 50
    else:
        return
        
    payload = f"buytheme_{theme}_{message.from_user.id}"
    prices = [LabeledPrice(label=title, amount=price)]
    
    await bot.send_invoice(
        chat_id=message.chat.id,
        title=title,
        description=description,
        payload=payload,
        provider_token="",
        currency="XTR",
        prices=prices
    )

@payment_router.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

@payment_router.message(F.successful_payment)
async def successful_payment_handler(message: Message):
    payload = message.successful_payment.invoice_payload
    if payload.startswith("vip_"):
        parts = payload.split('_')
        tariff_key = f"{parts[1]}_{parts[2]}"
        user_id = int(parts[3])
        
        tariff = VIP_TARIFFS.get(tariff_key)
        if tariff:
            new_date = await grant_vip(user_id, tariff['days'], tier=tariff['tier'])
            
            from core.utils import parse_db_date
            try:
                dt = parse_db_date(new_date)
                formatted_date = dt.strftime("%Y-%m-%d %H:%M")
            except Exception:
                formatted_date = new_date
                
            user = await get_or_create_user(user_id, "", "")
            await message.reply(get_text(user['language_code'], 'payment_success', vip_until=formatted_date))
    elif payload.startswith("buytheme_"):
        parts = payload.split('_')
        theme = parts[1]
        user_id = int(parts[2])
        
        from database import add_owned_theme, update_user_settings
        await add_owned_theme(user_id, theme)
        
        user = await get_or_create_user(user_id, "", "")
        await update_user_settings(
            user_id, 
            user['language_code'], 
            user['guest_yt_quality'], 
            user['is_anonymous'], 
            theme, 
            user['watermark_position']
        )
        
        msg_text = "🎉 Дякуємо за покупку! Нова тема активована. Відкрийте Mini App, щоб побачити зміни."
        if user['language_code'] == 'en':
            msg_text = "🎉 Thank you for your purchase! The new theme is activated. Open the Mini App to see the changes."
        elif user['language_code'] == 'pl':
            msg_text = "🎉 Dziękujemy za zakup! Nowy motyw został aktywowany. Otwórz Mini App, aby zobaczyć zmiany."
            
        await message.reply(msg_text)
