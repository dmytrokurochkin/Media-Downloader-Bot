from aiogram.types import ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import ReplyKeyboardBuilder
from locales import get_text

from aiogram.types import WebAppInfo

def get_main_keyboard(lang: str, webapp_url: str = None) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=get_text(lang, 'menu_download'))
    
    if webapp_url:
        builder.button(text=get_text(lang, 'menu_profile'), web_app=WebAppInfo(url=webapp_url))
    else:
        builder.button(text=get_text(lang, 'menu_profile'))
        
    builder.button(text=get_text(lang, 'menu_vip'))
    builder.button(text=get_text(lang, 'menu_settings'))
    builder.button(text=get_text(lang, 'menu_help'))
    builder.button(text=get_text(lang, 'menu_hide_keyboard'))
    builder.adjust(2, 2, 2)
    return builder.as_markup(resize_keyboard=True)

def get_admin_keyboard(lang: str) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=get_text(lang, 'admin_btn_broadcast'))
    builder.button(text=get_text(lang, 'admin_btn_reply'))
    builder.button(text=get_text(lang, 'admin_btn_give_vip'))
    builder.button(text=get_text(lang, 'admin_btn_revoke_vip'))
    builder.button(text=get_text(lang, 'admin_btn_vip_list'))
    builder.button(text=get_text(lang, 'admin_btn_ban_bot'))
    builder.button(text=get_text(lang, 'admin_btn_ban_support'))
    builder.button(text=get_text(lang, 'admin_btn_unban'))
    builder.button(text=get_text(lang, 'admin_btn_exit'))
    builder.adjust(2, 3, 3, 1)
    return builder.as_markup(resize_keyboard=True)

def get_admin_cancel_keyboard(lang: str) -> ReplyKeyboardMarkup:
    builder = ReplyKeyboardBuilder()
    builder.button(text=get_text(lang, 'admin_btn_cancel'))
    return builder.as_markup(resize_keyboard=True)
