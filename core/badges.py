import datetime
import logging
from database import get_user_stats, award_badge

logger = logging.getLogger(__name__)

async def check_and_award_badges(telegram_id: int):
    """
    Перевіряє умови та видає бейджі користувачу.
    Викликається після успішного завантаження.
    """
    stats = await get_user_stats(telegram_id)
    if not stats:
        return

    downloads_count = stats.get('downloads_count', 0)
    total_bytes = stats.get('total_bytes_downloaded', 0)
    current_badges = stats.get('badges', [])

    new_badges = []

    # 1. first_blood (Перше завантаження)
    if downloads_count >= 1 and 'first_blood' not in current_badges:
        awarded = await award_badge(telegram_id, 'first_blood')
        if awarded:
            new_badges.append('first_blood')

    # 2. heavy_lifter (Завантажено понад 1 ГБ загалом)
    if total_bytes >= 1024 * 1024 * 1024 and 'heavy_lifter' not in current_badges:
        awarded = await award_badge(telegram_id, 'heavy_lifter')
        if awarded:
            new_badges.append('heavy_lifter')

    # 3. night_owl (Завантаження вночі, з 00:00 до 05:00 UTC)
    current_hour = datetime.datetime.now(datetime.timezone.utc).hour
    if 0 <= current_hour < 5 and 'night_owl' not in current_badges:
        awarded = await award_badge(telegram_id, 'night_owl')
        if awarded:
            new_badges.append('night_owl')

    if new_badges:
        logger.info(f"User {telegram_id} awarded new badges: {new_badges}")
