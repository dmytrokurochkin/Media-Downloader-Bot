import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
LOCAL_API_SERVER_URL = os.getenv("LOCAL_API_SERVER_URL", "http://127.0.0.1:8081")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://127.0.0.1:8080/api")
# Внутрішній API бота (пошук/профілі для Mini App). Слухає лише localhost:
# назовні його виставляє ngrok/reverse-proxy з TLS. Голий HTTP на 0.0.0.0 Mini App
# і так не використовував би (сторінка на HTTPS блокує mixed content).
API_HOST = os.getenv("API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("API_PORT", "8080"))
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
ERROR_LOG_CHANNEL_ID = os.getenv("ERROR_LOG_CHANNEL_ID", "")
if ERROR_LOG_CHANNEL_ID:
    try:
        ERROR_LOG_CHANNEL_ID = int(ERROR_LOG_CHANNEL_ID)
    except ValueError:
        ERROR_LOG_CHANNEL_ID = None

BOT_USERNAME = os.getenv("BOT_USERNAME", "MediaDownloaderForGroups_bot").replace('@', '')

# Адреса Mini App (статичні файли з webapp/, напр. на GitHub Pages). Форк має вказати
# власну: інакше його користувачі відкривали б фронтенд з чужого репозиторію.
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://dmytrokurochkin.github.io/Media-Downloader-Bot/webapp/index.html")

# Project root directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Database path
DB_PATH = Path("database.db")

# Limits
TIER_LIMITS = {
    'free': {'daily': 25, 'playlist': 10, 'size': 50 * 1024 * 1024},
    'pro': {'daily': 100, 'playlist': 30, 'size': 500 * 1024 * 1024},
    'max': {'daily': 1000, 'playlist': 100, 'size': 2000 * 1024 * 1024}
}

MAX_CONCURRENT_DOWNLOADS = 3

# Локальний Bot API приймає файли до 2000 МБ — більший файл Telegram не прийме за жодного тарифу.
TELEGRAM_UPLOAD_LIMIT = 2000 * 1024 * 1024

# Видимий текст реклами (після розбору HTML) — щоб разом із підписом вміщатися
# в ліміт підпису до медіа (1024 символи) з запасом.
AD_MAX_LENGTH = 300

# Необов'язково: браузер, з якого yt-dlp братиме cookies (firefox, chrome...). Для
# локальної розробки; на сервері використовується cookies.txt.
YTDLP_COOKIES_FROM_BROWSER = os.getenv("YTDLP_COOKIES_FROM_BROWSER", "").strip()

# Необов'язково: ID приватного каналу, куди бот вантажить файли для гостьового режиму,
# щоб отримати file_id. Без нього файл іде в особисті тому, хто покликав бота, —
# а це не працює для людей, які ще не запускали бота.
STORAGE_CHAT_ID = os.getenv("STORAGE_CHAT_ID", "").strip()
STORAGE_CHAT_ID = int(STORAGE_CHAT_ID) if STORAGE_CHAT_ID.lstrip("-").isdigit() else None

# Smart Trim: максимальна тривалість фрагмента для Free (секунди).
FREE_TRIM_MAX_SECONDS = 30

# Regular Expressions
URL_PATTERN = re.compile(r'https?://[^\s]+')
FORBIDDEN_URL_PATTERN = re.compile(r'(/artist/|/channel/|/user/|/c/)')

# VIP settings
VIP_TARIFFS = {
    'pro_7d': {'tier': 'pro', 'days': 7, 'stars': 100},
    'pro_30d': {'tier': 'pro', 'days': 30, 'stars': 300},
    'pro_365d': {'tier': 'pro', 'days': 365, 'stars': 2000},
    'max_7d': {'tier': 'max', 'days': 7, 'stars': 200},
    'max_30d': {'tier': 'max', 'days': 30, 'stars': 600},
    'max_365d': {'tier': 'max', 'days': 365, 'stars': 5000}
}

# Ціни преміум-тем Mini App у Telegram Stars (одне джерело для інвойсу й перевірки оплати).
THEME_PRICES = {'neon': 50, 'retro': 50}

# Paths
# Optional explicit path to a local ffmpeg binary (useful on Windows dev machines
# where ffmpeg isn't on PATH). Falls back to "ffmpeg" (resolved via PATH) everywhere
# it's used when this path doesn't exist, so it's safe to leave unset on Linux/servers.
# NOTE: must never be "" here - Path("").exists() resolves to the cwd and is always
# True, which would make every call site below think a real ffmpeg binary was found.
FFMPEG_WIN_PATH = os.getenv("FFMPEG_PATH", "").strip() or "ffmpeg"
