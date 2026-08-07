import re

import pytest

from locales import LOCALES, get_text


LANGS = ["uk", "en", "pl"]


def test_all_languages_present():
    assert set(LOCALES.keys()) == set(LANGS)


@pytest.mark.parametrize("lang", LANGS)
def test_get_text_returns_known_key(lang):
    text = get_text(lang, "start")
    assert text == LOCALES[lang]["start"]


def test_get_text_unknown_language_falls_back_to_english():
    assert get_text("fr", "too_fast") == LOCALES["en"]["too_fast"]


def test_get_text_unknown_key_returns_key_itself():
    assert get_text("en", "this_key_does_not_exist") == "this_key_does_not_exist"


def test_get_text_formats_placeholders():
    text = get_text("en", "in_queue", pos=5)
    assert "5" in text
    assert "{pos}" not in text


def test_get_text_without_kwargs_returns_raw_template():
    # No kwargs at all -> get_text skips .format() entirely and returns the raw
    # template, placeholders included. This is current, intentional behavior.
    text = get_text("en", "in_queue")
    assert "{pos}" in text


def test_get_text_with_wrong_kwargs_raises_keyerror():
    # Once *any* kwargs are passed, .format() runs for real and a missing
    # placeholder key raises like a normal str.format() call would.
    with pytest.raises(KeyError):
        get_text("en", "in_queue", wrong_key=5)


@pytest.mark.parametrize("lang", LANGS)
def test_every_locale_has_the_same_keys_as_english(lang):
    missing = set(LOCALES["en"].keys()) - set(LOCALES[lang].keys())
    extra = set(LOCALES[lang].keys()) - set(LOCALES["en"].keys())
    assert not missing, f"{lang} is missing keys: {missing}"
    assert not extra, f"{lang} has extra keys not in en: {extra}"


PLACEHOLDER_RE = re.compile(r"\{(\w+)\}")


@pytest.mark.parametrize("lang", LANGS)
def test_every_locale_has_matching_placeholders_to_english(lang):
    mismatches = []
    for key, en_text in LOCALES["en"].items():
        if key not in LOCALES[lang]:
            continue
        en_placeholders = set(PLACEHOLDER_RE.findall(en_text))
        other_placeholders = set(PLACEHOLDER_RE.findall(LOCALES[lang][key]))
        if en_placeholders != other_placeholders:
            mismatches.append((key, en_placeholders, other_placeholders))
    assert not mismatches, f"Placeholder mismatches in {lang}: {mismatches}"


def test_too_many_requests_key_exists_in_all_locales():
    for lang in LANGS:
        assert "too_many_requests" in LOCALES[lang]
        assert LOCALES[lang]["too_many_requests"]
