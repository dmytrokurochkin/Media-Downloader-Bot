from types import SimpleNamespace
from unittest.mock import AsyncMock

from aiogram.types import CallbackQuery, Message

import pytest

from handlers.payment import (
    process_payment_selection,
    confirm_payment_selection,
    successful_payment_handler,
    pre_checkout_handler,
    send_theme_invoice,
    parse_payment_payload,
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
    answer_mock = AsyncMock()
    monkeypatch.setattr(_FakeCallback, "answer", answer_mock)

    callback = _make_callback(111, "pay_stars_pro_7d")
    await process_payment_selection(callback)
    # Кнопка не «висить» з годинником: callback підтверджено.
    answer_mock.assert_awaited_once()

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
        successful_payment=SimpleNamespace(invoice_payload=payload, telegram_payment_charge_id="charge-vip-1", total_amount=100, currency="XTR"),
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
        successful_payment=SimpleNamespace(invoice_payload=payload, telegram_payment_charge_id="charge-theme-1", total_amount=50, currency="XTR"),
    )

    await successful_payment_handler(message)

    user = await db.get_or_create_user(333, "u", "U", "en")
    assert "neon" in user["owned_themes"].split(",")
    assert user["theme"] == "neon"
    reply_mock.assert_awaited_once()


# --- Журнал платежів, ідемпотентність, pre_checkout, повернення ---

def _payment_message(user_id, payload, charge_id, amount, name="U", username="u"):
    return _FakeMessage.model_construct(
        chat=SimpleNamespace(id=user_id, type="private"),
        message_id=1,
        from_user=SimpleNamespace(id=user_id, username=username, full_name=name),
        successful_payment=SimpleNamespace(invoice_payload=payload, telegram_payment_charge_id=charge_id, total_amount=amount, currency="XTR"),
    )


async def test_duplicate_successful_payment_is_applied_once(db, monkeypatch):
    await db.get_or_create_user(222, "alice", "Alice", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)

    message = _payment_message(222, "vip_pro_7d_222", "charge-dup", 100)
    await successful_payment_handler(message)
    first_until = (await db.get_user(222))["vip_until"]

    # Telegram доставив той самий апдейт удруге — дні не мають подвоїтись.
    await successful_payment_handler(message)
    assert (await db.get_user(222))["vip_until"] == first_until
    reply_mock.assert_awaited_once()

    payment = await db.get_payment("charge-dup")
    assert payment["status"] == "paid" and payment["amount"] == 100 and payment["beneficiary_id"] == 222


async def test_successful_payment_keeps_payer_name(db, monkeypatch):
    await db.get_or_create_user(222, "alice", "Alice", "en")
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())

    await successful_payment_handler(_payment_message(222, "vip_pro_7d_222", "charge-name", 100))

    # Раніше get_or_create_user(id, "", "") затирав ім'я платника.
    user = await db.get_user(222)
    assert user["username"] == "alice" and user["full_name"] == "Alice"


async def test_unknown_payload_reports_problem(db, monkeypatch):
    await db.get_or_create_user(222, "u", "U", "en")
    reply_mock = AsyncMock()
    monkeypatch.setattr(_FakeMessage, "reply", reply_mock)
    monkeypatch.setattr("handlers.payment.ADMIN_IDS", [])

    await successful_payment_handler(_payment_message(222, "vip_gold_9d_222", "charge-bad", 1))

    assert "/paysupport" in reply_mock.await_args.args[0]


def _pre_checkout(user_id, payload, amount, currency="XTR"):
    return SimpleNamespace(id="pcq1", from_user=SimpleNamespace(id=user_id), invoice_payload=payload, total_amount=amount, currency=currency)


@pytest.mark.parametrize("payload,amount,currency,expected_ok", [
    ("vip_pro_7d_444", 100, "XTR", True),
    ("vip_pro_7d_444", 1, "XTR", False),        # сума не збігається з тарифом
    ("vip_pro_7d_444", 100, "USD", False),      # інша валюта
    ("vip_gold_7d_444", 100, "XTR", False),     # тарифу не існує
    ("vip_pro_7d_999999", 100, "XTR", False),   # отримувача немає в БД
    ("garbage", 100, "XTR", False),
    ("buytheme_neon_444", 50, "XTR", True),
])
async def test_pre_checkout_validation(db, monkeypatch, payload, amount, currency, expected_ok):
    await db.get_or_create_user(444, "u", "U", "en")
    answer = AsyncMock()
    monkeypatch.setattr("handlers.payment.bot.answer_pre_checkout_query", answer)

    await pre_checkout_handler(_pre_checkout(444, payload, amount, currency))

    assert answer.await_args.kwargs["ok"] is expected_ok
    if not expected_ok:
        assert answer.await_args.kwargs["error_message"]


async def test_pre_checkout_rejects_already_owned_theme(db, monkeypatch):
    await db.get_or_create_user(444, "u", "U", "en")
    await db.add_owned_theme(444, "neon")
    answer = AsyncMock()
    monkeypatch.setattr("handlers.payment.bot.answer_pre_checkout_query", answer)

    await pre_checkout_handler(_pre_checkout(444, "buytheme_neon_444", 50))
    assert answer.await_args.kwargs["ok"] is False


async def test_pre_checkout_rejects_banned_payer(db, monkeypatch):
    await db.get_or_create_user(444, "u", "U", "en")
    await db.ban_user_bot(444, days=3)
    answer = AsyncMock()
    monkeypatch.setattr("handlers.payment.bot.answer_pre_checkout_query", answer)

    await pre_checkout_handler(_pre_checkout(444, "vip_pro_7d_444", 100))
    assert answer.await_args.kwargs["ok"] is False


async def test_theme_invoice_not_sent_for_owned_theme(db, monkeypatch):
    await db.get_or_create_user(555, "u", "U", "en")
    await db.add_owned_theme(555, "retro")
    user = await db.get_user(555)
    send_invoice = AsyncMock()
    monkeypatch.setattr("handlers.payment.bot.send_invoice", send_invoice)
    monkeypatch.setattr(_FakeMessage, "answer", AsyncMock(return_value=SimpleNamespace(chat=SimpleNamespace(id=555), message_id=2)))

    message = _FakeMessage.model_construct(chat=SimpleNamespace(id=555, type="private"), message_id=1,
                                           from_user=SimpleNamespace(id=555, username="u", full_name="U"))
    await send_theme_invoice(message, "retro", user)
    send_invoice.assert_not_awaited()


async def test_refund_reverts_vip_purchase(db, monkeypatch):
    await db.get_or_create_user(666, "u", "U", "en")
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())
    await successful_payment_handler(_payment_message(666, "vip_pro_7d_666", "charge-refund", 100))
    assert (await db.get_user(666))["tier"] == "pro"

    refunded = await db.refund_payment("charge-refund")

    assert refunded["payer_id"] == 666
    user = await db.get_user(666)
    assert user["tier"] == "free" and user["vip_until"] is None
    assert (await db.get_payment("charge-refund"))["status"] == "refunded"
    # Повторне повернення того самого платежу неможливе.
    assert await db.refund_payment("charge-refund") is None


async def test_refund_reverts_theme_purchase(db, monkeypatch):
    await db.get_or_create_user(777, "u", "U", "en")
    monkeypatch.setattr(_FakeMessage, "reply", AsyncMock())
    await successful_payment_handler(_payment_message(777, "buytheme_neon_777", "charge-theme-refund", 50))

    await db.refund_payment("charge-theme-refund")

    user = await db.get_user(777)
    assert "neon" not in user["owned_themes"].split(",")
    assert user["theme"] == "standard"


@pytest.mark.parametrize("payload,expected", [
    ("vip_max_30d_12", ("vip", "max_30d", 12)),
    ("buytheme_retro_7", ("theme", "retro", 7)),
    ("vip_max_30d_12_extra", None),
    ("", None),
])
def test_parse_payment_payload(payload, expected):
    item = parse_payment_payload(payload)
    assert (item and (item.kind, item.item, item.beneficiary_id)) == expected or (item is None and expected is None)


async def test_throttling_never_drops_successful_payment():
    from middlewares.throttling import ThrottlingMiddleware

    mw = ThrottlingMiddleware(rate_limit=60)
    handler = AsyncMock(return_value="ok")
    regular = _FakeMessage.model_construct(from_user=SimpleNamespace(id=1, username="u", full_name="U"))
    payment = _payment_message(1, "vip_pro_7d_1", "charge-throttle", 100)

    await mw(handler, regular, {})
    assert await mw(handler, payment, {}) == "ok"
