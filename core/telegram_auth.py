import hashlib
import hmac
import time
from urllib.parse import parse_qsl

from core.config import BOT_TOKEN

MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60


def validate_init_data(init_data: str) -> bool:
    """
    Verifies Telegram WebApp initData per Telegram's documented algorithm:
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    Returns True only if the hash matches and auth_date isn't stale.
    """
    if not init_data or not BOT_TOKEN:
        return False

    try:
        pairs = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError:
        return False

    received_hash = pairs.pop('hash', None)
    if not received_hash:
        return False

    auth_date = pairs.get('auth_date')
    if not auth_date or not auth_date.isdigit():
        return False
    if time.time() - int(auth_date) > MAX_INIT_DATA_AGE_SECONDS:
        return False

    data_check_string = '\n'.join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    return hmac.compare_digest(computed_hash, received_hash)
