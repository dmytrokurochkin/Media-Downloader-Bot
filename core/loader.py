import os
from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from core.config import BOT_TOKEN, LOCAL_API_SERVER_URL

session = AiohttpSession(
    api=TelegramAPIServer.from_base(LOCAL_API_SERVER_URL, is_local=True)
)
bot = Bot(token=BOT_TOKEN, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()