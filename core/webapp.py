import urllib.parse
import datetime
from database import get_top_users, get_top_domains
from database import get_top_users, get_top_domains
from core.config import TIER_LIMITS

async def generate_webapp_url(user: dict, used_downloads: int, bot_username: str) -> str:
    """
    Generates a compressed URL containing all user stats and leaderboards.
    This allows the static GitHub Pages Mini App to display dynamic data without a backend API.
    """
    # Replace this with the actual GitHub Pages URL later
    base_url = "https://dmytrokurochkin.github.io/Media-Downloader-Bot/webapp/index.html"
    
    tier = user.get('tier', 'free')
    limit_daily = TIER_LIMITS.get(tier, {}).get('daily', 25)
    limit_playlist = TIER_LIMITS.get(tier, {}).get('playlist', 10)
    limit_size = TIER_LIMITS.get(tier, {}).get('size', 50*1024*1024)
    lang = user.get('language_code', 'uk')
    user_name = user.get('full_name', 'User')
    guest_yt_quality = user.get('guest_yt_quality', 'best')
    is_anonymous = user.get('is_anonymous', 0)
    theme = user.get('theme', 'standard')
    watermark_position = user.get('watermark_position', 'bottom_right')
    
    # Fetch Leaderboards
    top_users_data = await get_top_users(limit=10)
    # Format: ID:Name:Count,ID:Name:Count
    tu_str = ",".join([f"{u.get('telegram_id')}:{u.get('full_name', 'User').replace(',', '').replace(':', '')}:{u['count']}" for u in top_users_data])
    
    top_sites_data = await get_top_domains()
    domain_mapping = {
        'YouTube Music': ['music.youtube.com'],
        'YouTube': ['youtube.com', 'youtu.be', 'www.youtube.com', 'm.youtube.com', 'youtube'],
        'Instagram': ['instagram.com', 'www.instagram.com', 'm.instagram.com'],
        'TikTok': ['tiktok.com', 'www.tiktok.com', 'vm.tiktok.com', 'm.tiktok.com'],
        'Spotify': ['spotify.com', 'open.spotify.com'],
        'SoundCloud': ['soundcloud.com', 'on.soundcloud.com', 'm.soundcloud.com'],
        'Threads': ['threads.net', 'www.threads.net', 'threads.com'],
        'Facebook': ['facebook.com', 'www.facebook.com', 'fb.watch', 'm.facebook.com'],
        'GitHub': ['github.com', 'www.github.com']
    }
    merged_counts = {}
    for d in top_sites_data:
        raw_domain = d['domain'].lower()
        mapped = False
        for nice_name, variants in domain_mapping.items():
            if raw_domain in variants or any(v in raw_domain for v in variants):
                merged_counts[nice_name] = merged_counts.get(nice_name, 0) + d['count']
                mapped = True
                break
        if not mapped:
            merged_counts[raw_domain] = merged_counts.get(raw_domain, 0) + d['count']
            
    sorted_domains = sorted(merged_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    ts_str = ",".join([f"{domain.replace(',', '').replace(':', '')}:{count}" for domain, count in sorted_domains])
    
    vip_until = user.get('vip_until')
    vu_ts = 0
    if vip_until:
        from core.utils import parse_db_date
        try:
            dt = parse_db_date(vip_until)
            vu_ts = int(dt.timestamp())
        except Exception:
            pass

    # Build query parameters
    params = {
        'v': 23, # Cache buster for the HTML file itself
        'l': lang,
        't': tier,
        'u': used_downloads,
        'lmd': limit_daily,
        'lmp': limit_playlist,
        'lms': limit_size,
        'tu': tu_str,
        'ts': ts_str,
        'b': bot_username,
        'nm': user_name,
        'vu': vu_ts,
        'gq': guest_yt_quality,
        'anon': is_anonymous,
        'th': theme,
        'wp': watermark_position,
        'api': 'http://127.0.0.1:8080/api'
    }
    
    # URL Encode the parameters safely
    query_string = urllib.parse.urlencode(params)
    return f"{base_url}?{query_string}"
