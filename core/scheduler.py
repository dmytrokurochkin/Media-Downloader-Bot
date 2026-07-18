import asyncio
import logging
from aiogram import Bot
from database import get_inactive_users, mark_retention_promo_received, grant_vip

async def retention_drip_campaign(bot: Bot):
    """
    Фонова задача для відправки подарункових Pro-днів неактивним користувачам.
    Перевіряє базу раз на добу (86400 секунд).
    """
    await asyncio.sleep(60)  # Затримка перед першим запуском після старту бота
    
    while True:
        try:
            inactive_users = await get_inactive_users(days_inactive=14)
            for user in inactive_users:
                telegram_id = user['telegram_id']
                
                try:
                    # Надаємо 3 дні Pro (tier = 'max' за замовчуванням або 'pro', якщо вказати)
                    await grant_vip(telegram_id, days=3)
                    await mark_retention_promo_received(telegram_id)
                    
                    message_text = "👋 Давно не бачились! Ми скучили за тобою. Тримай 3 дні Pro-статусу абсолютно безкоштовно! Швидше скидай посилання на улюблене відео, щоб протестувати преміум-швидкість."
                    
                    await bot.send_message(chat_id=telegram_id, text=message_text)
                    logging.info(f"Sent retention promo to user {telegram_id}")
                except Exception as e:
                    logging.error(f"Failed to send retention promo to {telegram_id}: {e}")
                
                # Затримка для уникнення FloodWait
                await asyncio.sleep(0.5)
                
        except Exception as e:
            logging.error(f"Error in retention_drip_campaign loop: {e}")
            
        # Чекаємо 24 години до наступної перевірки
        await asyncio.sleep(86400)
