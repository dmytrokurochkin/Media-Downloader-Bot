import datetime

import pytest

from core.utils import parse_db_date, temporary_download_session


def test_parse_db_date_with_space_separator():
    dt = parse_db_date("2024-01-15 10:30:00")
    assert dt is not None
    assert dt.year == 2024 and dt.month == 1 and dt.day == 15
    assert dt.tzinfo is not None


def test_parse_db_date_adds_utc_when_naive():
    dt = parse_db_date("2024-01-15T10:30:00")
    assert dt.tzinfo == datetime.timezone.utc


def test_parse_db_date_preserves_existing_timezone():
    dt = parse_db_date("2024-01-15T10:30:00+02:00")
    assert dt.utcoffset() == datetime.timedelta(hours=2)


def test_parse_db_date_none_input():
    assert parse_db_date(None) is None


def test_parse_db_date_empty_string():
    assert parse_db_date("") is None


def test_parse_db_date_invalid_string_returns_none():
    assert parse_db_date("not-a-date") is None


async def test_temporary_download_session_creates_and_cleans_up(tmp_path):
    session_dir = tmp_path / "session_123"
    async with temporary_download_session(session_dir) as d:
        assert d == session_dir
        assert session_dir.exists()
        (session_dir / "file.txt").write_text("data")

    assert not session_dir.exists()


async def test_temporary_download_session_cleans_up_on_exception(tmp_path):
    session_dir = tmp_path / "session_456"
    try:
        async with temporary_download_session(session_dir):
            assert session_dir.exists()
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    assert not session_dir.exists()


# --- розбір посилань і хостів ---

from core.utils import detect_language, domain_matches, extract_url, host_matches, is_forbidden_url, url_host  # noqa: E402


def test_host_matches_uses_real_host():
    assert host_matches("https://m.youtube.com/watch?v=1", "youtube.com")
    assert not host_matches("https://notyoutube.com/", "youtube.com")
    assert not host_matches("https://evil.example/?u=youtube.com", "youtube.com")
    assert domain_matches("WWW.YouTube.com.", "youtube.com")


def test_url_host_survives_malformed_urls():
    assert url_host("http://[::1") == ""
    assert not host_matches("http://[::1", "youtube.com")
    assert not is_forbidden_url("http://[::1")


@pytest.mark.parametrize("text, expected", [
    ("дивись https://youtu.be/abc).", "https://youtu.be/abc"),
    ("https://en.wikipedia.org/wiki/Python_(language)", "https://en.wikipedia.org/wiki/Python_(language)"),
    ("«https://example.com/a»", "https://example.com/a"),
    ("без посилання", None),
    (None, None),
])
def test_extract_url(text, expected):
    assert extract_url(text) == expected


@pytest.mark.parametrize("url, forbidden", [
    ("https://www.youtube.com/@somechannel", True),
    ("https://www.youtube.com/watch?v=abc", False),
    ("https://example.com/user/profile", False),
])
def test_is_forbidden_url(url, forbidden):
    assert is_forbidden_url(url) is forbidden


@pytest.mark.parametrize("code, expected", [("uk", "uk"), ("pl-PL", "pl"), ("ru", "en"), (None, "en")])
def test_detect_language(code, expected):
    assert detect_language(code) == expected
