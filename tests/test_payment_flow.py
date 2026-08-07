from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import CallbackQuery, Message

from handlers.payment import (
    process_payment_selection,
    confirm_payment_selection,
    successful_payment_handler,
)


class _FakeMessage(Message):
    pass


class _FakeCallback(CallbackQuery):
    pass


def _make_callback(user_id, data, **extra):
    message = _FakeMessage.model_construct(
        chat=SimpleNamespace(id=user_id, type="private"),
        message_id=1,
        **extra,
    )
    return _FakeCallback.model_construct(
        id="cbq1",
        from_user=SimpleNamespace(id=user_id, username="u", full_name="U"),
        data=data,
        message=message,
    )


async def test_process_payment_selection_sends_invoice_for_new_purchase(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")

    send_invoice_mock = AsyncMock()
    monkeypatch.setattr("handlers.payment.bot.send_invoice", send_invoice_mock)
    monkeypatch.setattr(_FakeCallback, "answer", AsyncMock())

    callback = _make_callback(111, "pay_stars_pro_7d")
    await process_payment_selection(callback)

    send_invoice_mock.assert_awaited_once()
    _, kwargs = send_invoice_mock.call_args
    assert kwargs["currency"] == "XTR"
    assert kwargs["provider_token"] == ""
    assert kwargs["prices"][0].amount == 100  # pro_7d = 100 stars


async def test_process_payment_selection_warns_on_tier_downgrade_conflict(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    await db.grant_vip(111, 30, tier="max")

    edit_text_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "edit_text", edit_text_mock)
    send_invoice_mock = AsyncMock()
    monkeypatch.setattr("handlers.payment.bot.send_invoice", send_invoice_mock)

    callback = _make_callback(111, "pay_stars_pro_7d")
    await process_payment_selection(callback)

    # Switching from an active 'max' plan to 'pro' should show a warning instead
    # of sending an invoice right away.
    edit_text_mock.assert_awaited_once()
    send_invoice_mock.assert_not_awaited()


async def test_process_payment_selection_same_tier_renewal_skips_warning(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    await db.grant_vip(111, 30, tier="pro")

    send_invoice_mock = AsyncMock()
    monkeypatch.setattr("handlers.payment.bot.send_invoice", send_invoice_mock)
    monkeypatch.setattr(_FakeCallback, "answer", AsyncMock())

    callback = _make_callback(111, "pay_stars_pro_30d")
    await process_payment_selection(callback)

    send_invoice_mock.assert_awaited_once()


async def test_confirm_payment_selection_sends_invoice_after_warning(db, monkeypatch):
    await db.get_or_create_user(111, "u", "U", "en")
    await db.grant_vip(111, 30, tier="max")

    delete_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "delete", delete_mock)
    send_invoice_mock = AsyncMock()
    monkeypatch.setattr("handlers.payment.bot.send_invoice", send_invoice_mock)
    monkeypatch.setattr(_FakeCallback, "answer", AsyncMock())

    callback = _make_callback(111, "confirm_pay_pro_7d")
    await confirm_payment_selection(callback)

    delete_mock.assert_awaited_once()
    send_invoice_mock.assert_awaited_once()


async def test_successful_payment_vip_grants_tier(db, monkeypatch):
    await db.get_or_create_user(222, "u", "U", "en")

    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    payload = "vip_pro_7d_222"
    message = _FakeMessage.model_construct(
        chat=SimpleNamespace(id=222, type="private"),
        message_id=1,
        from_user=SimpleNamespace(id=222, username="u", full_name="U"),
        successful_payment=SimpleNamespace(invoice_payload=payload),
    )

    await successful_payment_handler(message)

    user = await db.get_or_create_user(222, "u", "U", "en")
    assert user["tier"] == "pro"
    assert user["is_vip"] == 1
    reply_mock.assert_awaited_once()


async def test_successful_payment_theme_purchase_activates_theme(db, monkeypatch):
    await db.get_or_create_user(333, "u", "U", "en")

    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    payload = "buytheme_neon_333"
    message = _FakeMessage.model_construct(
        chat=SimpleNamespace(id=333, type="private"),
        message_id=1,
        from_user=SimpleNamespace(id=333, username="u", full_name="U"),
        successful_payment=SimpleNamespace(invoice_payload=payload),
    )

    await successful_payment_handler(message)

    user = await db.get_or_create_user(333, "u", "U", "en")
    assert "neon" in user["owned_themes"].split(",")
    assert user["theme"] == "neon"
    reply_mock.assert_awaited_once()
