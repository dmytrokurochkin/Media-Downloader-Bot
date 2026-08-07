from pathlib import Path

from core import config


def test_base_dir_points_to_project_root():
    assert config.BASE_DIR == Path(__file__).resolve().parent.parent
    assert (config.BASE_DIR / "main.py").exists()


def test_tier_limits_are_monotonically_increasing():
    tiers = ["free", "pro", "max"]
    for key in ("daily", "playlist", "size"):
        values = [config.TIER_LIMITS[t][key] for t in tiers]
        assert values == sorted(values)
        assert len(set(values)) == len(values)


def test_url_pattern_matches_http_and_https():
    assert config.URL_PATTERN.search("check https://youtu.be/abc123 now")
    assert config.URL_PATTERN.search("http://example.com/path")
    assert config.URL_PATTERN.search("no links here") is None


def test_url_pattern_stops_at_whitespace():
    match = config.URL_PATTERN.search("go to https://example.com/x and stop")
    assert match.group(0) == "https://example.com/x"


def test_forbidden_url_pattern_blocks_profile_style_links():
    assert config.FORBIDDEN_URL_PATTERN.search("https://open.spotify.com/artist/123")
    assert config.FORBIDDEN_URL_PATTERN.search("https://www.youtube.com/channel/UC123")
    assert config.FORBIDDEN_URL_PATTERN.search("https://soundcloud.com/user/name")
    assert config.FORBIDDEN_URL_PATTERN.search("https://youtube.com/c/somechannel")


def test_forbidden_url_pattern_allows_direct_content_links():
    assert config.FORBIDDEN_URL_PATTERN.search("https://open.spotify.com/track/123") is None
    assert config.FORBIDDEN_URL_PATTERN.search("https://youtu.be/dQw4w9WgXcQ") is None


def test_vip_tariffs_structure():
    for key, tariff in config.VIP_TARIFFS.items():
        assert tariff["tier"] in ("pro", "max")
        assert tariff["days"] > 0
        assert tariff["stars"] > 0
        assert key == f"{tariff['tier']}_{tariff['days']}d"


def test_ffmpeg_win_path_is_never_the_cwd_sentinel():
    # Path("") resolves to the cwd and always exists, which would make every ffmpeg
    # call site below think a valid binary was configured even when none is set.
    assert config.FFMPEG_WIN_PATH != ""


def test_bot_username_has_no_at_sign():
    assert not config.BOT_USERNAME.startswith("@")
