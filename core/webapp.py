import urllib.parse
from database import get_top_users, get_top_domains
from core.config import TIER_LIMITS

async def generate_webapp_url(user: dict, used_downloads: int, bot_username: str) -> str:
    """
    Generates a compressed URL containing all user stats and leaderboards.
    This allows the static GitHub Pages Mini App to display dynamic data without a backend API.
    """
    # Replace this with the actual GitHub Pages URL later
    base_url = "https://your-username.github.io/Media-Downloader-Bot/webapp/index.html"
    
    tier = user.get('tier', 'free')
    limit = TIER_LIMITS.get(tier, {}).get('playlist', 30)
    lang = user.get('language_code', 'uk')
    user_name = user.get('full_name', 'User')
    
    # Fetch Leaderboards
    top_users_data = await get_top_users(limit=10)
    # Format: Name:Count,Name:Count
    tu_str = ",".join([f"{u.get('full_name', 'User').replace(',', '').replace(':', '')}:{u['count']}" for u in top_users_data])
    
    top_sites_data = await get_top_domains()
    ts_str = ",".join([f"{s['domain'].replace(',', '').replace(':', '')}:{s['count']}" for s in top_sites_data])
    
    # Build query parameters
    params = {
        'l': lang,
        't': tier,
        'u': used_downloads,
        'lm': limit,
        'tu': tu_str,
        'ts': ts_str,
        'b': bot_username,
        'nm': user_name
    }
    
    # URL Encode the parameters safely
    query_string = urllib.parse.urlencode(params)
    return f"{base_url}?{query_string}"
