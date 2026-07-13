import os
import re
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
LOCAL_API_SERVER_URL = os.getenv("LOCAL_API_SERVER_URL", "http://127.0.0.1:8081")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "")

# Database path
DB_PATH = Path("database.db")

# Limits
TIER_LIMITS = {
    'free': {'daily': 25, 'playlist': 10, 'size': 50 * 1024 * 1024},
    'pro': {'daily': 100, 'playlist': 30, 'size': 500 * 1024 * 1024},
    'max': {'daily': 999999, 'playlist': 9999, 'size': 2000 * 1024 * 1024}
}

MAX_ACTIVE_REQUESTS = 15

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
