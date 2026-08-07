import urllib.parse

from core.webapp import generate_webapp_url


def _params(url: str) -> dict:
    query = url.split("?", 1)[1]
    parsed = urllib.parse.parse_qs(query)
    return {k: v[0] for k, v in parsed.items()}


async def test_generate_webapp_url_basic_fields(db):
    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    url = await generate_webapp_url(user, used_downloads=3, bot_username="TestBot")

    assert url.startswith("https://dmytrokurochkin.github.io/Media-Downloader-Bot/webapp/index.html?")
    params = _params(url)
    assert params["l"] == "en"
    assert params["t"] == "free"
    assert params["u"] == "3"
    assert params["lmd"] == "25"  # free tier daily limit
    assert params["b"] == "TestBot"
    assert params["nm"] == "Alice"


async def test_generate_webapp_url_includes_leaderboards(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.get_or_create_user(222, "bob", "Bob", "en")
    await db.add_download_record(111, "https://youtube.com/x", "youtube.com", "t", 10, True)
    await db.add_download_record(222, "https://tiktok.com/x", "tiktok.com", "t", 10, True)

    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    url = await generate_webapp_url(user, used_downloads=1, bot_username="TestBot")
    params = _params(url)

    assert "Alice" in params["tu"]
    assert "Bob" in params["tu"]
    assert "YouTube" in params["ts"]
    assert "TikTok" in params["ts"]


async def test_generate_webapp_url_merges_domain_variants(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_download_record(111, "https://music.youtube.com/x", "music.youtube.com", "t", 10, True)
    await db.add_download_record(111, "https://www.youtube.com/x", "www.youtube.com", "t", 10, True)

    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    url = await generate_webapp_url(user, used_downloads=2, bot_username="TestBot")
    params = _params(url)

    # music.youtube.com and www.youtube.com should merge under the "YouTube Music" /
    # "YouTube" buckets rather than appearing as separate raw domains.
    assert "music.youtube.com" not in params["ts"]
    assert "www.youtube.com" not in params["ts"]


async def test_generate_webapp_url_admin_gets_all_themes(db, monkeypatch):
    from core import webapp as webapp_module

    monkeypatch.setattr(webapp_module, "ADMIN_IDS", [111])
    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    url = await generate_webapp_url(user, used_downloads=0, bot_username="TestBot")
    params = _params(url)

    assert set(params["ow"].split(",")) == {"standard", "neon", "retro"}


async def test_generate_webapp_url_non_admin_gets_own_themes_only(db):
    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_owned_theme(111, "neon")
    user = await db.get_or_create_user(111, "alice", "Alice", "en")

    url = await generate_webapp_url(user, used_downloads=0, bot_username="TestBot")
    params = _params(url)
    assert set(params["ow"].split(",")) == {"standard", "neon"}


async def test_generate_webapp_url_includes_badges_and_totals(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.add_download_record(111, "https://x.com", "x.com", "t", 100, True)
    await db.add_downloaded_bytes(111, 100)
    await db.award_badge(111, "first_blood")

    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    url = await generate_webapp_url(user, used_downloads=1, bot_username="TestBot")
    params = _params(url)

    assert params["bdg"] == "first_blood"
    assert params["tb"] == "100"
    assert params["td"] == "1"


async def test_generate_webapp_url_no_vip_gives_zero_timestamp(db):
    user = await db.get_or_create_user(111, "alice", "Alice", "en")
    url = await generate_webapp_url(user, used_downloads=0, bot_username="TestBot")
    params = _params(url)
    assert params["vu"] == "0"


async def test_generate_webapp_url_vip_gives_nonzero_timestamp(db):
    await db.get_or_create_user(111, "alice", "Alice", "en")
    await db.grant_vip(111, 7, tier="pro")
    user = await db.get_or_create_user(111, "alice", "Alice", "en")

    url = await generate_webapp_url(user, used_downloads=0, bot_username="TestBot")
    params = _params(url)
    assert int(params["vu"]) > 0
