from keyboards.inline import (
    get_onboarding_keyboard,
    get_youtube_keyboard,
    get_settings_main_keyboard,
    get_lang_keyboard,
    get_guest_quality_keyboard,
)
from keyboards.reply import (
    get_main_keyboard,
    get_admin_keyboard,
    get_admin_ad_keyboard,
    get_admin_cancel_keyboard,
)


def _all_buttons(markup):
    return [btn for row in markup.inline_keyboard for btn in row]


def test_onboarding_keyboard_has_test_download_callback():
    kb = get_onboarding_keyboard("en")
    buttons = _all_buttons(kb)
    assert len(buttons) == 1
    assert buttons[0].callback_data == "onboarding_test_dl"


def test_youtube_keyboard_has_five_quality_options():
    kb = get_youtube_keyboard("https://youtu.be/x", "en")
    buttons = _all_buttons(kb)
    callback_data = {b.callback_data for b in buttons}
    assert callback_data == {"yt_1080", "yt_720", "yt_360", "yt_audio", "yt_best"}


def test_lang_keyboard_has_three_languages():
    kb = get_lang_keyboard()
    buttons = _all_buttons(kb)
    callback_data = {b.callback_data for b in buttons}
    assert callback_data == {"lang_en", "lang_uk", "lang_pl"}


def test_guest_quality_keyboard_free_tier_has_no_premium_options():
    kb = get_guest_quality_keyboard("720p", tier="free")
    buttons = _all_buttons(kb)
    callback_data = [b.callback_data for b in buttons]
    assert callback_data == ["setyt_720p", "setyt_480p", "setyt_360p", "setyt_audio"]


def test_guest_quality_keyboard_pro_tier_adds_premium_options():
    kb = get_guest_quality_keyboard("best", tier="pro")
    buttons = _all_buttons(kb)
    callback_data = [b.callback_data for b in buttons]
    assert callback_data[0] == "setyt_best"
    assert callback_data[1] == "setyt_1080p"
    assert "setyt_720p" in callback_data


def test_guest_quality_keyboard_marks_current_selection():
    kb = get_guest_quality_keyboard("360p", tier="free")
    buttons = _all_buttons(kb)
    marked = [b for b in buttons if b.text.startswith("✅")]
    assert len(marked) == 1
    assert marked[0].callback_data == "setyt_360p"


def test_settings_main_keyboard_has_two_rows():
    kb = get_settings_main_keyboard("en")
    assert len(kb.inline_keyboard) == 2


# --- reply keyboards ---

def test_main_keyboard_without_webapp_url_has_plain_profile_button():
    kb = get_main_keyboard("en", webapp_url=None)
    buttons = [b for row in kb.keyboard for b in row]
    assert all(b.web_app is None for b in buttons)


def test_main_keyboard_with_webapp_url_sets_web_app_on_profile_button():
    kb = get_main_keyboard("en", webapp_url="https://example.com/app")
    buttons = [b for row in kb.keyboard for b in row]
    web_app_buttons = [b for b in buttons if b.web_app is not None]
    assert len(web_app_buttons) == 1
    assert web_app_buttons[0].web_app.url == "https://example.com/app"


def test_admin_keyboard_button_count():
    kb = get_admin_keyboard("en")
    buttons = [b for row in kb.keyboard for b in row]
    assert len(buttons) == 10


def test_admin_ad_keyboard_button_count():
    kb = get_admin_ad_keyboard("en")
    buttons = [b for row in kb.keyboard for b in row]
    assert len(buttons) == 4


def test_admin_cancel_keyboard_single_button():
    kb = get_admin_cancel_keyboard("en")
    buttons = [b for row in kb.keyboard for b in row]
    assert len(buttons) == 1
