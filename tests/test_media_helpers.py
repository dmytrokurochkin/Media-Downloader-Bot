from handlers.user import get_progress_bar
from handlers.media import prepare_caption_with_ad


def test_progress_bar_unlimited():
    assert get_progress_bar(5, 9999) == "██████████ (БЕЗЛІМІТ)"


def test_progress_bar_empty():
    assert get_progress_bar(0, 25) == "░░░░░░░░░░"


def test_progress_bar_full():
    assert get_progress_bar(25, 25) == "██████████"


def test_progress_bar_partial():
    bar = get_progress_bar(5, 10, length=10)
    assert bar == "█████░░░░░"


def test_progress_bar_never_overfills_when_over_limit():
    bar = get_progress_bar(999, 25, length=10)
    assert bar == "██████████"


async def test_prepare_caption_with_ad_free_tier_appends_active_ad(db):
    await db.set_active_ad("Buy stuff!")
    db._ad_cache["timestamp"] = 0

    caption = await prepare_caption_with_ad("Signature", {"tier": "free"})
    assert "Buy stuff!" in caption
    assert caption.startswith("Signature")


async def test_prepare_caption_with_ad_no_active_ad_returns_plain_caption(db):
    caption = await prepare_caption_with_ad("Signature", {"tier": "free"})
    assert caption == "Signature"


async def test_prepare_caption_with_ad_paid_tier_never_shows_ad(db):
    await db.set_active_ad("Buy stuff!")
    db._ad_cache["timestamp"] = 0

    caption = await prepare_caption_with_ad("Signature", {"tier": "max"})
    assert caption == "Signature"
    assert "Buy stuff!" not in caption


async def test_prepare_caption_with_ad_truncates_long_caption_to_fit_ad(db):
    await db.set_active_ad("Ad")
    db._ad_cache["timestamp"] = 0

    long_caption = "x" * 2000
    caption = await prepare_caption_with_ad(long_caption, {"tier": "free"})
    assert len(caption) <= 1024
    assert caption.endswith("📢 Спонсор: Ad")


async def test_prepare_caption_with_ad_handles_none_caption():
    caption = await prepare_caption_with_ad(None, {"tier": "max"})
    assert caption == ""
