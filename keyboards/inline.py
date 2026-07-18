from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from locales import get_text

def get_onboarding_keyboard(lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text=get_text(lang, 'btn_test_download'), callback_data="onboarding_test_dl")
    return builder.as_markup()

def get_youtube_keyboard(url: str, lang: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="1080p", callback_data="yt_1080")
    builder.button(text="720p", callback_data="yt_720")
    builder.button(text="360p", callback_data="yt_360")
    builder.button(text=get_text(lang, 'btn_audio'), callback_data="yt_audio")
    builder.button(text=get_text(lang, 'btn_best'), callback_data="yt_best")
    builder.adjust(3, 1, 1)
    return builder.as_markup()

def get_settings_main_keyboard(lang: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=get_text(lang, 'btn_change_lang'), callback_data="set_lang"))
    kb.row(InlineKeyboardButton(text=get_text(lang, 'btn_guest_quality'), callback_data="set_guest_quality"))
    return kb.as_markup()

def get_lang_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="English 🇺🇸", callback_data="lang_en"), InlineKeyboardButton(text="Українська 🇺🇦", callback_data="lang_uk"))
    kb.row(InlineKeyboardButton(text="Polski 🇵🇱", callback_data="lang_pl"))
    return kb.as_markup()

def get_guest_quality_keyboard(current_quality: str, tier: str = 'free') -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    qualities = [
        ("720p", "720p 📱"),
        ("480p", "480p 📻"),
        ("360p", "360p 📉"),
        ("audio", "Лише аудіо 🎵")
    ]
    if tier in ['pro', 'max']:
        qualities.insert(0, ("1080p", "1080p 📺"))
        qualities.insert(0, ("best", "Максимум 🚀"))
    for q_key, q_name in qualities:
        text = f"✅ {q_name}" if current_quality == q_key else q_name
        kb.row(InlineKeyboardButton(text=text, callback_data=f"setyt_{q_key}"))
    return kb.as_markup()
