import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
LOCAL_API_SERVER_URL = os.getenv("LOCAL_API_SERVER_URL", "http://127.0.0.1:8081")
PUBLIC_API_URL = os.getenv("PUBLIC_API_URL", "http://127.0.0.1:8080/api")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")
ERROR_LOG_CHANNEL_ID = os.getenv("ERROR_LOG_CHANNEL_ID", "")
if ERROR_LOG_CHANNEL_ID:
    try:
        ERROR_LOG_CHANNEL_ID = int(ERROR_LOG_CHANNEL_ID)
    except ValueError:
        ERROR_LOG_CHANNEL_ID = None

BOT_USERNAME = os.getenv("BOT_USERNAME", "MediaDownloaderForGroups_bot").replace('@', '')

# Database path
DB_PATH = Path("database.db")

# Limits
TIER_LIMITS = {
    'free': {'daily': 25, 'playlist': 10, 'size': 50 * 1024 * 1024},
    'pro': {'daily': 100, 'playlist': 30, 'size': 500 * 1024 * 1024},
    'max': {'daily': 1000, 'playlist': 100, 'size': 2000 * 1024 * 1024}
}

MAX_ACTIVE_REQUESTS = 15
MAX_CONCURRENT_DOWNLOADS = 3

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

# Paths
FFMPEG_WIN_PATH = "C:\\Users\\MrMozozavr\\AppData\\Local\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg.Shared_Microsoft.Winget.Source_m18.22.422\\ffmpeg-7.1-full_build-shared\\bin\\ffmpeg.exe"
