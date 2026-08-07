import datetime
import types

import core.badges
from core.badges import check_and_award_badges


async def test_first_blood_badge_awarded_after_first_download(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_download_record(111, "https://x.com", "x.com", "t", 100, True)

    await check_and_award_badges(111)

    badges = await db.get_user_badges(111)
    assert "first_blood" in badges


async def test_first_blood_not_awarded_twice(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_download_record(111, "https://x.com", "x.com", "t", 100, True)

    await check_and_award_badges(111)
    await check_and_award_badges(111)

    badges = await db.get_user_badges(111)
    assert badges.count("first_blood") == 1


async def test_heavy_lifter_badge_requires_one_gb(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_download_record(111, "https://x.com", "x.com", "t", 100, True)
    await db.add_downloaded_bytes(111, 500 * 1024 * 1024)

    await check_and_award_badges(111)
    badges = await db.get_user_badges(111)
    assert "heavy_lifter" not in badges

    await db.add_downloaded_bytes(111, 600 * 1024 * 1024)
    await check_and_award_badges(111)
    badges = await db.get_user_badges(111)
    assert "heavy_lifter" in badges


async def test_check_and_award_badges_unknown_user_is_noop(db):
    # Should not raise for a user that doesn't exist in the DB.
    await check_and_award_badges(999999)


async def test_night_owl_badge_awarded_during_night_hours(db, monkeypatch):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_download_record(111, "https://x.com", "x.com", "t", 100, True)

    fake_now = datetime.datetime(2024, 1, 1, 3, 0, 0, tzinfo=datetime.timezone.utc)

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            return fake_now

    fake_module = types.SimpleNamespace(datetime=FakeDateTime, timezone=datetime.timezone)
    monkeypatch.setattr(core.badges, "datetime", fake_module)

    await check_and_award_badges(111)
    badges = await db.get_user_badges(111)
    assert "night_owl" in badges


async def test_night_owl_badge_not_awarded_during_day_hours(db, monkeypatch):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_download_record(111, "https://x.com", "x.com", "t", 100, True)

    fake_now = datetime.datetime(2024, 1, 1, 14, 0, 0, tzinfo=datetime.timezone.utc)

    class FakeDateTime:
        @staticmethod
        def now(tz=None):
            return fake_now

    fake_module = types.SimpleNamespace(datetime=FakeDateTime, timezone=datetime.timezone)
    monkeypatch.setattr(core.badges, "datetime", fake_module)

    await check_and_award_badges(111)
    badges = await db.get_user_badges(111)
    assert "night_owl" not in badges
