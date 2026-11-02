import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest

from core import telegram_auth
from core.telegram_auth import validate_init_data

TOKEN = "123456:TEST-TOKEN-FOR-INIT-DATA"


def make_init_data(token=TOKEN, auth_date=None, **extra):
    """Підписує initData за алгоритмом Telegram (так само, як це робить клієнт)."""
    fields = {
        "auth_date": str(int(time.time()) if auth_date is None else auth_date),
        "query_id": "AAH-test",
        "user": json.dumps({"id": 42, "first_name": "Test"}, separators=(",", ":")),
        **extra,
    }
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)


@pytest.fixture(autouse=True)
def _token(monkeypatch):
    monkeypatch.setattr(telegram_auth, "BOT_TOKEN", TOKEN)


def test_valid_init_data_is_accepted():
    assert validate_init_data(make_init_data()) is True


def test_init_data_signed_with_other_token_is_rejected():
    assert validate_init_data(make_init_data(token="999:OTHER")) is False


def test_tampered_init_data_is_rejected():
    tampered = make_init_data().replace("Test", "Admin")
    assert validate_init_data(tampered) is False


def test_stale_init_data_is_rejected():
    old = int(time.time()) - telegram_auth.MAX_INIT_DATA_AGE_SECONDS - 60
    assert validate_init_data(make_init_data(auth_date=old)) is False


@pytest.mark.parametrize("value", ["", "garbage", "auth_date=1&user=x"])
def test_malformed_init_data_is_rejected(value):
    assert validate_init_data(value) is False
