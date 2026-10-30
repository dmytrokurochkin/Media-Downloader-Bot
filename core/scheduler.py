import asyncio
import logging

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError, TelegramRetryAfter

from database import get_inactive_users, mark_retention_promo_received, grant_vip, purge_old_download_urls
from locales import get_text

logger = logging.getLogger(__name__)

RETENTION_INACTIVE_DAYS = 14
RETENTION_PROMO_DAYS = 3
RETENTION_PROMO_TIER = 'pro'
DOWNLOAD_URL_RETENTION_DAYS = 30


async def _send_retention_promo(bot: Bot, user: dict) -> None:
    telegram_id = user['telegram_id']
    # Позначаємо ДО видачі: якщо щось впаде посередині, користувач не отримає
    # подарунок вдруге наступної доби.
    await mark_retention_promo_received(telegram_id)
    # Раніше grant_vip викликався з тарифом за замовчуванням ('max'), хоча
    # повідомлення обіцяло Pro.
    await grant_vip(telegram_id, days=RETENTION_PROMO_DAYS, tier=RETENTION_PROMO_TIER)
    text = get_text(user.get('language_code') or 'en', 'retention_promo', days=RETENTION_PROMO_DAYS)
    try:
        await bot.send_message(chat_id=telegram_id, text=text)
    except TelegramRetryAfter as e:
        await asyncio.sleep(e.retry_after)
        await bot.send_message(chat_id=telegram_id, text=text)


async def retention_drip_campaign(bot: Bot):
    """
    Фонова задача: раз на добу дарує Pro-дні неактивним користувачам і
    прибирає старі URL з історії завантажень.
    """
    await asyncio.sleep(60)  # Затримка перед першим запуском після старту бота

    while True:
        try:
            purged = await purge_old_download_urls(DOWNLOAD_URL_RETENTION_DAYS)
            if purged:
                logger.info("Purged URLs of %d old download record(s)", purged)

            for user in await get_inactive_users(days_inactive=RETENTION_INACTIVE_DAYS):
                try:
                    await _send_retention_promo(bot, user)
                    logger.info("Sent retention promo to user %s", user['telegram_id'])
                except TelegramForbiddenError:
                    # Користувач заблокував бота — це не помилка.
                    logger.info("User %s blocked the bot, retention promo not delivered", user['telegram_id'])
                except (TelegramAPIError, ValueError) as e:
                    logger.warning("Failed to send retention promo to %s: %s", user['telegram_id'], e)

                # Затримка для уникнення FloodWait
                await asyncio.sleep(0.5)

        except Exception:
            logger.exception("Error in retention_drip_campaign loop")

        # Чекаємо 24 години до наступної перевірки
        await asyncio.sleep(86400)
