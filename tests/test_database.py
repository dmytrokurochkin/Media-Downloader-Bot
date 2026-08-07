import datetime

import pytest


# --- get_or_create_user ---

async def test_get_or_create_user_creates_new_user(db):
    user = await db.get_or_create_user(111, "alice", "Alice A", "en")
    assert user["telegram_id"] == 111
    assert user["username"] == "alice"
    assert user["full_name"] == "Alice A"
    assert user["language_code"] == "en"
    assert user["tier"] == "free"
    assert user["is_vip"] is False
    assert user["vip_until"] is None


async def test_get_or_create_user_is_idempotent(db):
    first = await db.get_or_create_user(111, "alice", "Alice A", "en")
    second = await db.get_or_create_user(111, "alice", "Alice A", "en")
    assert first["telegram_id"] == second["telegram_id"]

    all_users = await db.get_all_users()
    assert all_users.count(111) == 1


async def test_get_or_create_user_updates_changed_name_and_username(db):
    await db.get_or_create_user(111, "alice", "Alice A", "en")
    updated = await db.get_or_create_user(111, "alice2", "Alice B", "en")
    assert updated["username"] == "alice2"
    assert updated["full_name"] == "Alice B"


async def test_get_or_create_user_expires_vip_automatically(db):
    await db.get_or_create_user(111, "alice", "Alice A", "en")
    past = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
    await db._db_connection.execute(
        "UPDATE users SET is_vip = 1, vip_until = ?, tier = 'max' WHERE telegram_id = ?",
        (past, 111),
    )
    await db._db_connection.commit()

    user = await db.get_or_create_user(111, "alice", "Alice A", "en")
    assert user["is_vip"] == 0
    assert user["vip_until"] is None
    assert user["tier"] == "free"


async def test_get_or_create_user_keeps_active_vip(db):
    await db.get_or_create_user(111, "alice", "Alice A", "en")
    future = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=5)).isoformat()
    await db._db_connection.execute(
        "UPDATE users SET is_vip = 1, vip_until = ?, tier = 'pro' WHERE telegram_id = ?",
        (future, 111),
    )
    await db._db_connection.commit()

    user = await db.get_or_create_user(111, "alice", "Alice A", "en")
    assert user["is_vip"] == 1
    assert user["tier"] == "pro"


# --- language / guest quality settings ---

async def test_set_user_language(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.set_user_language(111, "uk")
    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    assert user["language_code"] == "uk"


async def test_set_guest_yt_quality(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.set_guest_yt_quality(111, "720p")
    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    assert user["guest_yt_quality"] == "720p"


async def test_update_user_settings(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.update_user_settings(111, "pl", "480p", True, "neon", "top_left")
    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    assert user["language_code"] == "pl"
    assert user["guest_yt_quality"] == "480p"
    assert user["is_anonymous"] == 1
    assert user["theme"] == "neon"
    assert user["watermark_position"] == "top_left"


# --- VIP granting / revoking ---

async def test_grant_vip_new_user_sets_future_date(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    new_date = await db.grant_vip(111, 7, tier="pro")
    dt = datetime.datetime.fromisoformat(new_date)
    now = datetime.datetime.now(datetime.timezone.utc)
    assert dt > now
    assert (dt - now).days in (6, 7)

    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    assert user["tier"] == "pro"
    assert user["is_vip"] == 1


async def test_grant_vip_same_tier_extends_remaining_time(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    first_date = await db.grant_vip(111, 7, tier="pro")
    second_date = await db.grant_vip(111, 7, tier="pro")

    first_dt = datetime.datetime.fromisoformat(first_date)
    second_dt = datetime.datetime.fromisoformat(second_date)
    # Extending the same tier should add on top of the remaining time, not reset it.
    assert (second_dt - first_dt).days >= 6


async def test_grant_vip_different_tier_restarts_from_now(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.grant_vip(111, 30, tier="pro")
    second_date = await db.grant_vip(111, 7, tier="max")

    second_dt = datetime.datetime.fromisoformat(second_date)
    now = datetime.datetime.now(datetime.timezone.utc)
    # Switching tier restarts the clock from "now", so it should be ~7 days out, not ~37.
    assert (second_dt - now).days in (6, 7)


async def test_grant_vip_unknown_user_raises(db):
    with pytest.raises(ValueError):
        await db.grant_vip(999999, 7, tier="pro")


async def test_revoke_vip(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.grant_vip(111, 7, tier="max")
    await db.revoke_vip(111)
    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    assert user["is_vip"] == 0
    assert user["tier"] == "free"
    assert user["vip_until"] is None


async def test_revoke_vip_unknown_user_raises(db):
    with pytest.raises(ValueError):
        await db.revoke_vip(999999)


async def test_get_vip_users(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.get_or_create_user(222, "bob", "Bob", "en")
    await db.grant_vip(111, 7, tier="pro")

    vip_users = await db.get_vip_users()
    ids = [u["telegram_id"] for u in vip_users]
    assert 111 in ids
    assert 222 not in ids


# --- downloads / daily limits / stats ---

async def test_daily_download_count_only_counts_success_today(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_download_record(111, "https://x.com/1", "x.com", "t1", 100, True)
    await db.add_download_record(111, "https://x.com/2", "x.com", "t2", 100, False)

    count = await db.get_daily_download_count(111)
    assert count == 1


async def test_get_top_domains(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_download_record(111, "https://youtube.com/1", "youtube.com", "t", 10, True)
    await db.add_download_record(111, "https://youtube.com/2", "youtube.com", "t", 10, True)
    await db.add_download_record(111, "https://tiktok.com/1", "tiktok.com", "t", 10, True)
    await db.add_download_record(111, "https://tiktok.com/2", "tiktok.com", "t", 10, False)

    domains = await db.get_top_domains()
    lookup = {d["domain"]: d["count"] for d in domains}
    assert lookup["youtube.com"] == 2
    assert lookup["tiktok.com"] == 1


async def test_get_top_users_excludes_anonymous(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.get_or_create_user(222, "bob", "Bob", "en")
    await db.update_user_settings(222, "en", "best", True, "standard", "bottom_right")

    await db.add_download_record(111, "https://x.com", "x.com", "t", 10, True)
    await db.add_download_record(222, "https://x.com", "x.com", "t", 10, True)

    top = await db.get_top_users()
    ids = [u["telegram_id"] for u in top]
    assert 111 in ids
    assert 222 not in ids


async def test_get_users_stats_by_tier(db):
    await db.get_or_create_user(111, "a", "A", "en")
    await db.get_or_create_user(222, "b", "B", "en")
    await db.grant_vip(222, 7, tier="max")

    stats = await db.get_users_stats_by_tier()
    assert stats["total"] == 2
    assert stats["free"] == 1
    assert stats["max"] == 1


# --- bans ---

async def test_ban_user_bot_temporary_and_unban(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    ban_until = await db.ban_user_bot(111, days=1)
    user_row = await db.get_or_create_user(111, "alice", "Alice", "en")
    assert user_row["banned_bot_until"] == ban_until

    await db.unban_user(111)
    user_row = await db.get_or_create_user(111, "alice", "Alice", "en")
    assert user_row["banned_bot_until"] is None


async def test_ban_user_bot_permanent(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    ban_until = await db.ban_user_bot(111, days=None)
    assert ban_until.startswith("9999")


async def test_ban_user_support(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    ban_until = await db.ban_user_support(111, days=3)
    assert ban_until is not None


# --- badges ---

async def test_award_badge_once(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    first = await db.award_badge(111, "first_blood")
    second = await db.award_badge(111, "first_blood")
    assert first is True
    assert second is False

    badges = await db.get_user_badges(111)
    assert badges == ["first_blood"]


async def test_add_downloaded_bytes_accumulates(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_downloaded_bytes(111, 100)
    await db.add_downloaded_bytes(111, 250)

    stats = await db.get_user_stats(111)
    assert stats["total_bytes_downloaded"] == 350


# --- public profile / search ---

async def test_get_public_profile_hidden_for_anonymous(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.update_user_settings(111, "en", "best", True, "standard", "bottom_right")
    profile = await db.get_public_profile(111)
    assert profile is None


async def test_get_public_profile_visible(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    profile = await db.get_public_profile(111)
    assert profile is not None
    assert profile["telegram_id"] == 111


async def test_get_public_profile_not_found(db):
    profile = await db.get_public_profile(999999)
    assert profile is None


async def test_search_users_query_by_name_username_and_id(db):
    await db.get_or_create_user(111, "alice_wonder", "Alice Wonder", "en")
    await db.get_or_create_user(222, "bob", "Bob Builder", "en")

    by_name = await db.search_users_query("Wonder")
    assert [u["telegram_id"] for u in by_name] == [111]

    by_username = await db.search_users_query("bob")
    assert [u["telegram_id"] for u in by_username] == [222]

    by_id = await db.search_users_query("111")
    assert [u["telegram_id"] for u in by_id] == [111]


async def test_search_users_query_excludes_anonymous(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.update_user_settings(111, "en", "best", True, "standard", "bottom_right")
    results = await db.search_users_query("Alice")
    assert results == []


# --- owned themes ---

async def test_add_owned_theme_is_idempotent(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_owned_theme(111, "neon")
    await db.add_owned_theme(111, "neon")

    row = await db._db_connection.execute_fetchall(
        "SELECT owned_themes FROM users WHERE telegram_id = ?", (111,)
    )
    owned = row[0]["owned_themes"]
    assert owned.split(",").count("neon") == 1


# --- ads (with in-memory cache) ---

async def test_ad_campaign_lifecycle(db):
    assert await db.get_active_ad() is None

    await db.set_active_ad("Buy stuff!")
    db._ad_cache["timestamp"] = 0  # bypass cache TTL for the test
    assert await db.get_active_ad() == "Buy stuff!"

    await db.clear_active_ads()
    db._ad_cache["timestamp"] = 0
    assert await db.get_active_ad() is None


# --- retention / inactivity ---

async def test_get_inactive_users_only_free_unpromoted(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.get_or_create_user(222, "bob", "Bob", "en")
    await db.grant_vip(222, 7, tier="pro")  # not 'free' tier, should be excluded

    long_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat()
    await db._db_connection.execute(
        "UPDATE users SET last_active_at = ? WHERE telegram_id IN (111, 222)", (long_ago,)
    )
    await db._db_connection.commit()

    inactive = await db.get_inactive_users(days_inactive=14)
    ids = [u["telegram_id"] for u in inactive]
    assert 111 in ids
    assert 222 not in ids


async def test_mark_retention_promo_received_excludes_user(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    long_ago = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=30)).isoformat()
    await db._db_connection.execute(
        "UPDATE users SET last_active_at = ? WHERE telegram_id = ?", (long_ago, 111)
    )
    await db._db_connection.commit()

    assert len(await db.get_inactive_users(days_inactive=14)) == 1
    await db.mark_retention_promo_received(111)
    assert len(await db.get_inactive_users(days_inactive=14)) == 0


async def test_update_last_active(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.update_last_active(111)
    rows = await db._db_connection.execute_fetchall(
        "SELECT last_active_at FROM users WHERE telegram_id = ?", (111,)
    )
    assert rows[0]["last_active_at"] is not None
