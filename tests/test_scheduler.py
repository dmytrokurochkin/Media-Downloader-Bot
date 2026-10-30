from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramForbiddenError

from core.scheduler import RETENTION_PROMO_DAYS, _send_retention_promo
from locales import get_text


async def test_retention_promo_grants_pro_in_user_language(db):
    await db.get_or_create_user(111, "u", "U", "pl")
    bot = AsyncMock()

    await _send_retention_promo(bot, {"telegram_id": 111, "language_code": "pl"})

    user = await db.get_user(111)
    # Повідомлення обіцяє Pro — раніше видавався MAX (тариф grant_vip за замовчуванням).
    assert user["tier"] == "pro"
    assert user["retention_promo_received"] == 1
    bot.send_message.assert_awaited_once_with(
        chat_id=111, text=get_text("pl", "retention_promo", days=RETENTION_PROMO_DAYS)
    )


async def test_retention_promo_is_marked_even_if_user_blocked_bot(db):
    await db.get_or_create_user(111, "u", "U", "en")
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramForbiddenError(method=None, message="blocked")

    try:
        await _send_retention_promo(bot, {"telegram_id": 111, "language_code": "en"})
    except TelegramForbiddenError:
        pass

    # Наступної доби подарунок повторно не видається.
    assert (await db.get_user(111))["retention_promo_received"] == 1
