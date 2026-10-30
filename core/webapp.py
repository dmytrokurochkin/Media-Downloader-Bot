import urllib.parse
from database import get_top_users, get_top_domains, get_user_stats
from core.config import TIER_LIMITS, ADMIN_IDS, PUBLIC_API_URL, WEBAPP_URL
from core.utils import domain_matches

# Імена в лідерборді обрізаються: топ-10 повних імен (кирилиця/емодзі × percent-encoding)
# роздували URL кнопки Mini App до кількох КБ.
LEADERBOARD_NAME_LIMIT = 24
OWN_NAME_LIMIT = 64
DOMAIN_LIMIT = 40


# Домени → назва сервісу в лідербордах. Порядок важливий: music.youtube.com має
# перевірятися раніше за youtube.com. Порівняння — за хостом, а не підрядком:
# раніше `'youtube' in domain` зараховував до YouTube і notyoutube.example.
SERVICE_NAMES = (
    ('YouTube Music', ('music.youtube.com',)),
    ('YouTube', ('youtube.com', 'youtu.be')),
    ('Instagram', ('instagram.com',)),
    ('TikTok', ('tiktok.com',)),
    ('Spotify', ('spotify.com',)),
    ('SoundCloud', ('soundcloud.com',)),
    ('Threads', ('threads.net', 'threads.com')),
    ('Facebook', ('facebook.com', 'fb.watch')),
    ('GitHub', ('github.com',)),
)


def service_name(domain: str) -> str:
    # Старі записи зберігали netloc цілком, разом з `user@` і `:порт`.
    host = (domain or '').lower().rsplit('@', 1)[-1].split(':', 1)[0]
    for name, domains in SERVICE_NAMES:
        if domain_matches(host, *domains):
            return name
    return host.removeprefix('www.') or 'unknown'


def merge_top_domains(rows, limit: int = 10) -> list:
    """Зводить сирі домени (youtube.com, m.youtube.com, youtu.be…) до сервісів і повертає топ."""
    merged = {}
    for row in rows:
        name = service_name(row['domain'])
        merged[name] = merged.get(name, 0) + row['count']
    return sorted(merged.items(), key=lambda item: item[1], reverse=True)[:limit]


def clean_display_text(value, limit: int, fallback: str = "User") -> str:
    """Готує ім'я/домен для URL Mini App.

    Прибирає керівні символи й переноси, схлопує пробіли, вирізає `,` та `:`
    (це роздільники формату `id:name:count,...`) і обрізає довжину. Від HTML
    це НЕ захищає — Mini App вставляє ці значення лише як textContent.
    """
    text = "".join(ch for ch in str(value or "") if ch.isprintable())
    text = " ".join(text.split()).replace(",", "").replace(":", "")
    return text[:limit].strip() or fallback


async def generate_webapp_url(user: dict, used_downloads: int, bot_username: str) -> str:
    """
    Generates a compressed URL containing all user stats and leaderboards.
    This allows the static GitHub Pages Mini App to display dynamic data without a backend API.
    """
    base_url = WEBAPP_URL

    tier = user.get('tier', 'free')
    limit_daily = TIER_LIMITS.get(tier, {}).get('daily', 25)
    limit_playlist = TIER_LIMITS.get(tier, {}).get('playlist', 10)
    limit_size = TIER_LIMITS.get(tier, {}).get('size', 50*1024*1024)
    lang = user.get('language_code', 'uk')
    user_name = clean_display_text(user.get('full_name'), OWN_NAME_LIMIT)
    guest_yt_quality = user.get('guest_yt_quality', 'best')
    is_anonymous = user.get('is_anonymous', 0)
    theme = user.get('theme', 'standard')
    watermark_position = user.get('watermark_position', 'bottom_right')
    
    # Fetch Leaderboards
    top_users_data = await get_top_users(limit=10)
    # Format: ID:Name:Count,ID:Name:Count
    tu_str = ",".join([f"{u.get('telegram_id')}:{clean_display_text(u.get('full_name'), LEADERBOARD_NAME_LIMIT)}:{u['count']}" for u in top_users_data])
    
    sorted_domains = merge_top_domains(await get_top_domains())
    ts_str = ",".join([f"{clean_display_text(domain, DOMAIN_LIMIT, 'site')}:{count}" for domain, count in sorted_domains])
    
    vip_until = user.get('vip_until')
    vu_ts = 0
    if vip_until:
        from core.utils import parse_db_date
        try:
            dt = parse_db_date(vip_until)
            vu_ts = int(dt.timestamp())
        except Exception:
            pass

    owned_themes = user.get('owned_themes', 'standard')
    if user.get('telegram_id') in ADMIN_IDS:
        owned_themes = "standard,neon,retro"

    stats = await get_user_stats(user.get('telegram_id'))
    total_bytes = stats.get('total_bytes_downloaded', 0) if stats else 0
    total_downloads = stats.get('downloads_count', 0) if stats else 0
    badges_str = ",".join(stats.get('badges', [])) if stats else ""

    # Build query parameters
    params = {
        'v': 43, # Cache buster for the HTML file itself
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
        'ow': owned_themes,
        'wp': watermark_position,
        'api': PUBLIC_API_URL,
        'tb': total_bytes,
        'td': total_downloads,
        'bdg': badges_str
    }
    
    # URL Encode the parameters safely
    query_string = urllib.parse.urlencode(params)
    return f"{base_url}?{query_string}"
