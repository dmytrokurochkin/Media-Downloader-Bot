import aiosqlite
import datetime
import logging
import time
from pathlib import Path
from typing import Optional, List

DB_PATH = Path("database.db")
_db_connection = None
logger = logging.getLogger(__name__)

# Лідерборди рахуються GROUP BY по всій таблиці downloads, а потрібні при кожному
# /start і зміні мови (вони вшиті в URL Mini App) — тож результат кешуємо на хвилину.
LEADERBOARD_TTL = 60
_leaderboard_cache: dict = {}


def _leaderboard_cached(key):
    entry = _leaderboard_cache.get(key)
    if entry and time.monotonic() - entry[0] < LEADERBOARD_TTL:
        return entry[1]
    return None


def _leaderboard_store(key, rows: list) -> list:
    _leaderboard_cache[key] = (time.monotonic(), rows)
    return rows

async def init_db_connection():
    global _db_connection
    if _db_connection is None:
        _db_connection = await aiosqlite.connect(DB_PATH, timeout=20.0)
        _db_connection.row_factory = aiosqlite.Row
        await _db_connection.execute('PRAGMA journal_mode=WAL;')
        await _db_connection.execute('PRAGMA synchronous=NORMAL;')
        await _db_connection.commit()

async def close_db_connection():
    global _db_connection
    if _db_connection is not None:
        await _db_connection.close()
        _db_connection = None

async def init_db():
    global _db_connection
    db = _db_connection
    # Таблиця користувачів
    await db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            telegram_id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            is_vip BOOLEAN DEFAULT 0,
            vip_until DATETIME DEFAULT NULL,
            language_code TEXT DEFAULT 'en',
            guest_yt_quality TEXT DEFAULT 'best'
        )
    ''')
    
    # Міграція: перевіряємо чи існує колонка vip_until, якщо ні - додаємо
    async with db.execute('PRAGMA table_info(users)') as cursor:
        columns = [row[1] for row in await cursor.fetchall()]
        if 'vip_until' not in columns:
            await db.execute('ALTER TABLE users ADD COLUMN vip_until DATETIME DEFAULT NULL')
        if 'guest_yt_quality' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN guest_yt_quality TEXT DEFAULT 'best'")
        if 'tier' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN tier TEXT DEFAULT 'free'")
            await db.execute("UPDATE users SET tier = 'max' WHERE is_vip = 1")
        if 'banned_bot_until' not in columns:
            await db.execute('ALTER TABLE users ADD COLUMN banned_bot_until DATETIME DEFAULT NULL')
        if 'banned_support_until' not in columns:
            await db.execute('ALTER TABLE users ADD COLUMN banned_support_until DATETIME DEFAULT NULL')
        
        # Налаштування
        if 'is_anonymous' not in columns:
            await db.execute('ALTER TABLE users ADD COLUMN is_anonymous BOOLEAN DEFAULT 0')
        if 'theme' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN theme TEXT DEFAULT 'standard'")
        if 'watermark_file_id' not in columns:
            await db.execute('ALTER TABLE users ADD COLUMN watermark_file_id TEXT DEFAULT NULL')
        if 'watermark_position' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN watermark_position TEXT DEFAULT 'bottom_right'")
        if 'total_bytes_downloaded' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN total_bytes_downloaded INTEGER DEFAULT 0")
        if 'last_active_at' not in columns:
            await db.execute('ALTER TABLE users ADD COLUMN last_active_at DATETIME DEFAULT NULL')
        if 'retention_promo_received' not in columns:
            await db.execute('ALTER TABLE users ADD COLUMN retention_promo_received BOOLEAN DEFAULT 0')
        if 'owned_themes' not in columns:
            await db.execute("ALTER TABLE users ADD COLUMN owned_themes TEXT DEFAULT 'standard'")
            
        # Initialize existing users as active now to avoid spamming recent users
        await db.execute('UPDATE users SET last_active_at = CURRENT_TIMESTAMP WHERE last_active_at IS NULL')
    
    # Таблиця історії завантажень (аналітика)
    await db.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            url TEXT,
            domain TEXT,
            page_title TEXT,
            file_size INTEGER,
            success BOOLEAN,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (telegram_id) REFERENCES users (telegram_id)
        )
    ''')
    
    # Таблиця бейджів користувачів
    await db.execute('''
        CREATE TABLE IF NOT EXISTS user_badges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER,
            badge_code VARCHAR(50),
            awarded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (telegram_id) REFERENCES users (telegram_id),
            UNIQUE(telegram_id, badge_code)
        )
    ''')
    
    # Таблиця рекламних кампаній
    await db.execute('''
        CREATE TABLE IF NOT EXISTS ad_campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad_text TEXT,
            is_active BOOLEAN DEFAULT 0
        )
    ''')
    
    # Індекси для оптимізації швидкодії
    await db.execute('CREATE INDEX IF NOT EXISTS idx_downloads_daily ON downloads(telegram_id, timestamp);')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_downloads_domain ON downloads(success, domain);')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_downloads_timestamp ON downloads(timestamp);')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_user_badges ON user_badges(telegram_id);')

    # Журнал платежів Telegram Stars. charge_id UNIQUE — захист від подвійного
    # зарахування, якщо Telegram доставить successful_payment повторно. Без цього
    # журналу неможливо зробити refund (refundStarPayment вимагає charge_id) чи звірку.
    await db.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            charge_id TEXT NOT NULL UNIQUE,
            payer_id INTEGER NOT NULL,
            beneficiary_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            item TEXT NOT NULL,
            days INTEGER,
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL,
            payload TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'paid',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            refunded_at DATETIME DEFAULT NULL
        )
    ''')
    await db.execute('CREATE INDEX IF NOT EXISTS idx_payments_payer ON payments(payer_id, created_at);')

    # Стан кук сервісів (самі куки — у cookies.txt, тут лише коли оновлено й чи працюють):
    # без цього про мертві куки адмін дізнавався від користувачів.
    await db.execute('''
        CREATE TABLE IF NOT EXISTS cookie_status (
            service TEXT PRIMARY KEY,
            updated_at DATETIME DEFAULT NULL,
            last_ok_at DATETIME DEFAULT NULL,
            last_error_at DATETIME DEFAULT NULL,
            last_error TEXT DEFAULT NULL
        )
    ''')
    
    await db.commit()

async def get_or_create_user(telegram_id: int, username: str, full_name: str, language_code: str = 'en') -> dict:
    global _db_connection
    db = _db_connection
    async with db.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)) as cursor:
        user = await cursor.fetchone()
        
    if not user:
        # ON CONFLICT: перші апдейти нового користувача (повідомлення + callback, гостьовий
        # виклик) обробляються паралельно, і другий INSERT падав на UNIQUE посеред хендлера.
        # last_active_at одразу, щоб retention-розсилка не вважала новачка «неактивним».
        await db.execute('''
            INSERT INTO users (telegram_id, username, full_name, language_code, tier, last_active_at)
            VALUES (?, ?, ?, ?, 'free', ?)
            ON CONFLICT(telegram_id) DO NOTHING
        ''', (telegram_id, username, full_name, language_code, datetime.datetime.now(datetime.timezone.utc).isoformat()))
        await db.commit()
        async with db.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)) as cursor:
            user = await cursor.fetchone()
        return dict(user)
    
    user_dict = dict(user)

    # Оновлюємо ім'я та юзернейм, якщо вони змінились
    if user_dict['username'] != username or user_dict['full_name'] != full_name:
        await db.execute('''
            UPDATE users SET username = ?, full_name = ? WHERE telegram_id = ?
        ''', (username, full_name, telegram_id))
        await db.commit()
        user_dict['username'] = username
        user_dict['full_name'] = full_name
    
    # Перевірка на закінчення VIP
    if user_dict.get('vip_until'):
        try:
            from core.utils import parse_db_date
            vip_until_dt = parse_db_date(user_dict['vip_until'])
            now_dt = datetime.datetime.now(datetime.timezone.utc)
            
            # Якщо час вийшов
            if vip_until_dt and now_dt > vip_until_dt:
                await db.execute("UPDATE users SET is_vip = 0, vip_until = NULL, tier = 'free' WHERE telegram_id = ?", (telegram_id,))
                await db.commit()
                user_dict['is_vip'] = 0
                user_dict['vip_until'] = None
                user_dict['tier'] = 'free'
            else:
                user_dict['is_vip'] = 1
        except (TypeError, ValueError) as e:
            logger.warning("Bad vip_until for %s: %s", telegram_id, e)
        
    return user_dict

async def set_user_language(telegram_id: int, language_code: str):
    global _db_connection
    await _db_connection.execute('UPDATE users SET language_code = ? WHERE telegram_id = ?', (language_code, telegram_id))
    await _db_connection.commit()

def compute_vip_until(current_until: Optional[str], current_tier: Optional[str], tier: str, days: int, now: datetime.datetime) -> str:
    """Нова дата завершення VIP: продовження того ж тарифу або відлік від «зараз» для іншого."""
    vip_until = now
    if current_until:
        from core.utils import parse_db_date
        current_vip_until = parse_db_date(current_until)
        if current_vip_until and current_vip_until > now and current_tier == tier:
            vip_until = current_vip_until
    return (vip_until + datetime.timedelta(days=days)).isoformat()


async def grant_vip(telegram_id: int, days: int, tier: str = 'max') -> str:
    """Видає VIP доступ на задану кількість днів. Повертає нову дату закінчення."""
    global _db_connection
    db = _db_connection
    now = datetime.datetime.now(datetime.timezone.utc)
    
    async with db.execute('SELECT vip_until, tier FROM users WHERE telegram_id = ?', (telegram_id,)) as cursor:
        user = await cursor.fetchone()
        
    if not user:
        raise ValueError("User not found")

    new_vip_until_iso = compute_vip_until(user['vip_until'], user['tier'], tier, days, now)
    
    await db.execute('UPDATE users SET is_vip = 1, vip_until = ?, tier = ? WHERE telegram_id = ?', (new_vip_until_iso, tier, telegram_id))
    await db.commit()
    return new_vip_until_iso

async def revoke_vip(telegram_id: int):
    """Забирає VIP доступ"""
    global _db_connection
    db = _db_connection
    async with db.execute('SELECT telegram_id FROM users WHERE telegram_id = ?', (telegram_id,)) as cursor:
        if not await cursor.fetchone():
            raise ValueError("User not found")
            
    await db.execute("UPDATE users SET is_vip = 0, vip_until = NULL, tier = 'free' WHERE telegram_id = ?", (telegram_id,))
    await db.commit()

async def get_daily_download_count(telegram_id: int) -> int:
    """Отримує кількість успішних завантажень за поточну добу"""
    global _db_connection
    db = _db_connection
    async with db.execute('''
        SELECT COUNT(*) FROM downloads 
        WHERE telegram_id = ? AND success = 1 AND timestamp >= DATE('now')
    ''', (telegram_id,)) as cursor:
        row = await cursor.fetchone()
        return row[0] if row else 0

async def add_download_record(telegram_id: int, url: str, domain: str, page_title: str, file_size: int, success: bool):
    global _db_connection
    db = _db_connection
    await db.execute('''
        INSERT INTO downloads (telegram_id, url, domain, page_title, file_size, success)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (telegram_id, url, domain, page_title, file_size, success))
    await db.commit()

async def get_all_users() -> List[int]:
    """Повертає список всіх telegram_id для розсилки"""
    global _db_connection
    async with _db_connection.execute('SELECT telegram_id FROM users') as cursor:
        rows = await cursor.fetchall()
        return [row[0] for row in rows]

async def get_users_stats_by_tier() -> dict:
    """Повертає загальну кількість та розбивку по рівнях"""
    global _db_connection
    async with _db_connection.execute('SELECT tier, COUNT(*) as count FROM users GROUP BY tier') as cursor:
        rows = await cursor.fetchall()
        
    stats = {'total': 0, 'free': 0, 'pro': 0, 'max': 0}
    for r in rows:
        t = r['tier']
        c = r['count']
        if t in stats:
            stats[t] = c
        stats['total'] += c
        
    return stats

async def get_top_domains(limit: int = 50) -> List[dict]:
    """Повертає лідерборд найпопулярніших ресурсів.

    Сирих доменів береться більше, ніж показується: youtube.com, m.youtube.com і youtu.be
    потім зливаються в один сервіс (core/webapp.merge_top_domains), і з LIMIT 10
    до злиття менші сервіси випадали з топу.
    """
    global _db_connection
    cached = _leaderboard_cached(('domains', limit))
    if cached is not None:
        return cached
    async with _db_connection.execute('''
        SELECT domain, COUNT(*) as count 
        FROM downloads 
        WHERE success = 1 
        GROUP BY domain 
        ORDER BY count DESC 
        LIMIT ?
    ''', (limit,)) as cursor:
        rows = await cursor.fetchall()
        return _leaderboard_store(('domains', limit), [dict(r) for r in rows])

async def get_top_users(limit: int = 10) -> List[dict]:
    """Повертає лідерборд користувачів за кількістю завантажень"""
    global _db_connection
    cached = _leaderboard_cached(('users', limit))
    if cached is not None:
        return cached
    async with _db_connection.execute('''
        SELECT u.telegram_id, u.full_name, u.username, COUNT(d.id) as count
        FROM users u
        JOIN downloads d ON u.telegram_id = d.telegram_id
        WHERE d.success = 1 AND u.is_anonymous = 0
        GROUP BY u.telegram_id
        ORDER BY count DESC
        LIMIT ?
    ''', (limit,)) as cursor:
        rows = await cursor.fetchall()
        return _leaderboard_store(('users', limit), [dict(r) for r in rows])

async def set_guest_yt_quality(telegram_id: int, quality: str):
    global _db_connection
    await _db_connection.execute('UPDATE users SET guest_yt_quality = ? WHERE telegram_id = ?', (quality, telegram_id))
    await _db_connection.commit()

async def update_user_settings(telegram_id: int, language_code: str, guest_yt_quality: str, is_anonymous: bool, theme: str, watermark_position: str):
    global _db_connection
    await _db_connection.execute('''
        UPDATE users
        SET language_code = ?, guest_yt_quality = ?, is_anonymous = ?, theme = ?, watermark_position = ?
        WHERE telegram_id = ?
    ''', (language_code, guest_yt_quality, is_anonymous, theme, watermark_position, telegram_id))
    await _db_connection.commit()
    # Хто щойно увімкнув анонімність, має зникнути з лідерборду одразу, а не через хвилину.
    _leaderboard_cache.clear()

async def set_watermark_file_id(telegram_id: int, file_id: str):
    global _db_connection
    await _db_connection.execute('UPDATE users SET watermark_file_id = ? WHERE telegram_id = ?', (file_id, telegram_id))
    await _db_connection.commit()

async def add_owned_theme(telegram_id: int, theme: str):
    global _db_connection
    async with _db_connection.execute('SELECT owned_themes FROM users WHERE telegram_id = ?', (telegram_id,)) as cursor:
        row = await cursor.fetchone()
        if not row: return
        owned = row['owned_themes'] or 'standard'
        if theme not in owned.split(','):
            owned += f",{theme}"
            await _db_connection.execute('UPDATE users SET owned_themes = ? WHERE telegram_id = ?', (owned, telegram_id))
            await _db_connection.commit()

async def ban_user_bot(telegram_id: int, days: Optional[int] = None) -> str:
    global _db_connection
    if days is None:
        ban_until = "9999-12-31T23:59:59"
    else:
        now = datetime.datetime.now(datetime.timezone.utc)
        ban_until = (now + datetime.timedelta(days=days)).isoformat()
        
    await _db_connection.execute('UPDATE users SET banned_bot_until = ? WHERE telegram_id = ?', (ban_until, telegram_id))
    await _db_connection.commit()
    return ban_until

async def ban_user_support(telegram_id: int, days: Optional[int] = None) -> str:
    global _db_connection
    if days is None:
        ban_until = "9999-12-31T23:59:59"
    else:
        now = datetime.datetime.now(datetime.timezone.utc)
        ban_until = (now + datetime.timedelta(days=days)).isoformat()
        
    await _db_connection.execute('UPDATE users SET banned_support_until = ? WHERE telegram_id = ?', (ban_until, telegram_id))
    await _db_connection.commit()
    return ban_until

async def unban_user(telegram_id: int):
    global _db_connection
    await _db_connection.execute('UPDATE users SET banned_bot_until = NULL, banned_support_until = NULL WHERE telegram_id = ?', (telegram_id,))
    await _db_connection.commit()

async def get_vip_users() -> List[dict]:
    """Повертає список всіх VIP користувачів з деталями"""
    global _db_connection
    async with _db_connection.execute('''
        SELECT telegram_id, username, full_name, tier, vip_until 
        FROM users 
        WHERE is_vip = 1
        ORDER BY vip_until ASC
    ''') as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

# --- Gamification Methods ---

async def add_downloaded_bytes(telegram_id: int, bytes_downloaded: int):
    global _db_connection
    await _db_connection.execute('''
        UPDATE users 
        SET total_bytes_downloaded = total_bytes_downloaded + ? 
        WHERE telegram_id = ?
    ''', (bytes_downloaded, telegram_id))
    await _db_connection.commit()

async def get_user_badges(telegram_id: int) -> List[str]:
    global _db_connection
    async with _db_connection.execute('''
        SELECT badge_code FROM user_badges WHERE telegram_id = ?
    ''', (telegram_id,)) as cursor:
        rows = await cursor.fetchall()
        return [r['badge_code'] for r in rows]

async def award_badge(telegram_id: int, badge_code: str) -> bool:
    """Awards a badge. Returns True if awarded (was new), False if already had it."""
    global _db_connection
    try:
        await _db_connection.execute('''
            INSERT INTO user_badges (telegram_id, badge_code)
            VALUES (?, ?)
        ''', (telegram_id, badge_code))
        await _db_connection.commit()
        return True
    except aiosqlite.IntegrityError:
        # User already has this badge (UNIQUE constraint failed)
        return False

async def search_users_query(query_string: str) -> List[dict]:
    """Searches public users by name, username, or ID."""
    global _db_connection
    # % і _ у запиті — це шаблони LIKE: без екранування пошук «%» віддавав би
    # випадкових користувачів, а «_» — будь-який символ.
    escaped = query_string.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    search_term = f"%{escaped}%"
    async with _db_connection.execute('''
        SELECT telegram_id, username, full_name, tier, total_bytes_downloaded 
        FROM users 
        WHERE is_anonymous = 0 
        AND (full_name LIKE ? ESCAPE '\\' OR username LIKE ? ESCAPE '\\' OR CAST(telegram_id AS TEXT) = ?)
        LIMIT 20
    ''', (search_term, search_term, query_string)) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_public_profile(telegram_id: int) -> Optional[dict]:
    """Gets a public profile. Returns None if hidden or not found."""
    profile = await get_user_stats(telegram_id)
    if not profile or profile.get('is_anonymous'):
        return None
    return profile

async def get_user_stats(telegram_id: int) -> Optional[dict]:
    """Gets all user stats regardless of anonymity."""
    global _db_connection
    async with _db_connection.execute('''
        SELECT telegram_id, username, full_name, tier, total_bytes_downloaded, is_anonymous
        FROM users 
        WHERE telegram_id = ?
    ''', (telegram_id,)) as cursor:
        user_row = await cursor.fetchone()
        
    if not user_row:
        return None
        
    # Get total download count
    async with _db_connection.execute('''
        SELECT COUNT(*) FROM downloads WHERE telegram_id = ? AND success = 1
    ''', (telegram_id,)) as cursor:
        count_row = await cursor.fetchone()
        downloads_count = count_row[0] if count_row else 0
        
    badges = await get_user_badges(telegram_id)
    
    profile = dict(user_row)
    profile['downloads_count'] = downloads_count
    profile['badges'] = badges
    
    return profile

_ad_cache = {"text": None, "timestamp": 0}
CACHE_TTL = 300 # 5 хвилин кешу для реклами

async def get_active_ad() -> Optional[str]:
    """Повертає текст активної рекламної кампанії з використанням In-Memory кешу."""
    global _ad_cache
    now = time.time()
    
    # Повертаємо з кешу, якщо TTL ще не вийшов
    if now - _ad_cache["timestamp"] < CACHE_TTL:
        return _ad_cache["text"]
        
    global _db_connection
    async with _db_connection.execute('SELECT ad_text FROM ad_campaigns WHERE is_active = 1 LIMIT 1') as cursor:
        row = await cursor.fetchone()
        
    _ad_cache["text"] = row['ad_text'] if row else None
    _ad_cache["timestamp"] = now
    return _ad_cache["text"]

async def set_active_ad(ad_text: str):
    """Робить всі існуючі кампанії неактивними і додає нову активну."""
    global _db_connection, _ad_cache
    await _db_connection.execute('UPDATE ad_campaigns SET is_active = 0')
    await _db_connection.execute('INSERT INTO ad_campaigns (ad_text, is_active) VALUES (?, 1)', (ad_text,))
    await _db_connection.commit()
    # Інвалідація кешу
    _ad_cache["timestamp"] = 0

async def clear_active_ads():
    """Вимкнути всі рекламні кампанії."""
    global _db_connection, _ad_cache
    await _db_connection.execute('UPDATE ad_campaigns SET is_active = 0')
    await _db_connection.commit()
    # Інвалідація кешу
    _ad_cache["timestamp"] = 0

async def update_last_active(telegram_id: int):
    """Оновлює час останньої активності користувача"""
    global _db_connection
    if _db_connection:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        await _db_connection.execute('UPDATE users SET last_active_at = ? WHERE telegram_id = ?', (now, telegram_id))
        await _db_connection.commit()

async def get_inactive_users(days_inactive: int = 14) -> List[dict]:
    """Повертає користувачів, які були неактивні більше days_inactive днів"""
    global _db_connection
    if not _db_connection:
        return []
    
    threshold_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days_inactive)).isoformat()
    
    # datetime() з обох боків: last_active_at буває і 'YYYY-MM-DD HH:MM:SS' (CURRENT_TIMESTAMP
    # з міграції), і ISO з 'T' та зсувом — рядкове порівняння цих форматів хибило в межах доби.
    # Забанених не чіпаємо: подарунок і повідомлення їм ні до чого.
    async with _db_connection.execute('''
        SELECT telegram_id, tier, language_code, retention_promo_received
        FROM users
        WHERE (last_active_at IS NULL OR datetime(last_active_at) < datetime(?))
        AND retention_promo_received = 0
        AND tier = 'free'
        AND (banned_bot_until IS NULL OR datetime(banned_bot_until) < datetime('now'))
    ''', (threshold_date,)) as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def purge_old_download_urls(days: int = 30) -> int:
    """Стирає URL і назви старих завантажень, лишаючи агрегати (домен, розмір, дату).

    Повні посилання — це історія переглядів користувача; для лімітів і лідербордів
    вони не потрібні, тож довше ніж `days` днів їх не зберігаємо.
    """
    global _db_connection
    cursor = await _db_connection.execute('''
        UPDATE downloads SET url = NULL, page_title = NULL
        WHERE url IS NOT NULL AND timestamp < datetime('now', ?)
    ''', (f'-{int(days)} days',))
    await _db_connection.commit()
    return cursor.rowcount


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def record_cookie_import(services: List[str]) -> None:
    """Куки сервісів щойно оновлено: стара помилка більше не актуальна."""
    now = _utc_now_iso()
    for service in services:
        await _db_connection.execute('''
            INSERT INTO cookie_status (service, updated_at) VALUES (?, ?)
            ON CONFLICT(service) DO UPDATE SET updated_at = excluded.updated_at, last_error = NULL, last_error_at = NULL
        ''', (service, now))
    await _db_connection.commit()


async def record_cookie_ok(service: str) -> None:
    await _db_connection.execute('''
        INSERT INTO cookie_status (service, last_ok_at) VALUES (?, ?)
        ON CONFLICT(service) DO UPDATE SET last_ok_at = excluded.last_ok_at
    ''', (service, _utc_now_iso()))
    await _db_connection.commit()


async def record_cookie_error(service: str, error: str) -> None:
    await _db_connection.execute('''
        INSERT INTO cookie_status (service, last_error_at, last_error) VALUES (?, ?, ?)
        ON CONFLICT(service) DO UPDATE SET last_error_at = excluded.last_error_at, last_error = excluded.last_error
    ''', (service, _utc_now_iso(), error[:300]))
    await _db_connection.commit()


async def clear_cookie_status(service: str) -> None:
    await _db_connection.execute('DELETE FROM cookie_status WHERE service = ?', (service,))
    await _db_connection.commit()


async def get_cookie_status() -> dict:
    async with _db_connection.execute('SELECT * FROM cookie_status') as cursor:
        return {row['service']: dict(row) for row in await cursor.fetchall()}


async def mark_retention_promo_received(telegram_id: int):
    """Позначає, що користувач отримав промо після неактивності"""
    global _db_connection
    if _db_connection:
        await _db_connection.execute('UPDATE users SET retention_promo_received = 1 WHERE telegram_id = ?', (telegram_id,))
        await _db_connection.commit()


async def get_user(telegram_id: int) -> Optional[dict]:
    """Читає користувача БЕЗ створення та без зміни імені.

    get_or_create_user(id, "", "") для «чужого» користувача (після оплати, у
    відповіді адміна) затирав у БД його username і ім'я порожніми рядками —
    до наступної активності він зникав з лідерборду й пошуку.
    """
    global _db_connection
    async with _db_connection.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


# --- Платежі ---

async def _open_write_transaction() -> aiosqlite.Connection:
    """Окреме з'єднання з BEGIN IMMEDIATE для багатокрокових транзакцій.

    Основне з'єднання спільне для всіх корутин: commit() будь-якої з них зафіксував
    би половину нашої транзакції. Окреме з'єднання в режимі WAL захоплює блокування
    запису, тож запис платежу й видача покупки відбуваються атомарно.
    """
    conn = await aiosqlite.connect(DB_PATH, timeout=20.0)
    conn.row_factory = aiosqlite.Row
    await conn.execute('BEGIN IMMEDIATE')
    return conn


async def _payment_exists(conn: aiosqlite.Connection, charge_id: str) -> bool:
    async with conn.execute('SELECT 1 FROM payments WHERE charge_id = ?', (charge_id,)) as cursor:
        return await cursor.fetchone() is not None


async def apply_vip_purchase(charge_id: str, payer_id: int, beneficiary_id: int, item: str, tier: str, days: int,
                             amount: int, currency: str, payload: str) -> Optional[str]:
    """Атомарно записує платіж і продовжує VIP. Повертає нову дату або None для повтору того ж charge_id."""
    conn = await _open_write_transaction()
    try:
        if await _payment_exists(conn, charge_id):
            await conn.rollback()
            return None
        async with conn.execute('SELECT vip_until, tier FROM users WHERE telegram_id = ?', (beneficiary_id,)) as cursor:
            user = await cursor.fetchone()
        if not user:
            raise ValueError("User not found")

        now = datetime.datetime.now(datetime.timezone.utc)
        new_until = compute_vip_until(user['vip_until'], user['tier'], tier, days, now)
        await conn.execute('UPDATE users SET is_vip = 1, vip_until = ?, tier = ? WHERE telegram_id = ?', (new_until, tier, beneficiary_id))
        await conn.execute('''
            INSERT INTO payments (charge_id, payer_id, beneficiary_id, kind, item, days, amount, currency, payload)
            VALUES (?, ?, ?, 'vip', ?, ?, ?, ?, ?)
        ''', (charge_id, payer_id, beneficiary_id, item, days, amount, currency, payload))
        await conn.commit()
        return new_until
    except BaseException:
        await conn.rollback()
        raise
    finally:
        await conn.close()


async def apply_theme_purchase(charge_id: str, payer_id: int, beneficiary_id: int, theme: str,
                               amount: int, currency: str, payload: str) -> bool:
    """Атомарно записує платіж, додає тему у власність і вмикає її. False — повтор того ж charge_id."""
    conn = await _open_write_transaction()
    try:
        if await _payment_exists(conn, charge_id):
            await conn.rollback()
            return False
        async with conn.execute('SELECT owned_themes FROM users WHERE telegram_id = ?', (beneficiary_id,)) as cursor:
            user = await cursor.fetchone()
        if not user:
            raise ValueError("User not found")

        owned = [t for t in (user['owned_themes'] or 'standard').split(',') if t]
        if theme not in owned:
            owned.append(theme)
        await conn.execute('UPDATE users SET owned_themes = ?, theme = ? WHERE telegram_id = ?', (",".join(owned), theme, beneficiary_id))
        await conn.execute('''
            INSERT INTO payments (charge_id, payer_id, beneficiary_id, kind, item, amount, currency, payload)
            VALUES (?, ?, ?, 'theme', ?, ?, ?, ?)
        ''', (charge_id, payer_id, beneficiary_id, theme, amount, currency, payload))
        await conn.commit()
        return True
    except BaseException:
        await conn.rollback()
        raise
    finally:
        await conn.close()


async def get_payment(charge_id: str) -> Optional[dict]:
    global _db_connection
    async with _db_connection.execute('SELECT * FROM payments WHERE charge_id = ?', (charge_id,)) as cursor:
        row = await cursor.fetchone()
    return dict(row) if row else None


async def get_user_payments(telegram_id: int, limit: int = 5) -> List[dict]:
    global _db_connection
    async with _db_connection.execute('''
        SELECT charge_id, kind, item, amount, currency, status, created_at
        FROM payments WHERE payer_id = ? ORDER BY id DESC LIMIT ?
    ''', (telegram_id, limit)) as cursor:
        return [dict(r) for r in await cursor.fetchall()]


async def refund_payment(charge_id: str) -> Optional[dict]:
    """Позначає платіж повернутим і відкочує покупку. None — платежу немає або він уже повернений.

    VIP: дата завершення зсувається назад на куплені дні (якщо минула — тариф free).
    Тема: прибирається з куплених, а якщо була активна — повертається standard.
    Гроші повертає виклик Telegram refundStarPayment — його робить хендлер ДО цього.
    """
    conn = await _open_write_transaction()
    try:
        async with conn.execute("SELECT * FROM payments WHERE charge_id = ? AND status = 'paid'", (charge_id,)) as cursor:
            payment = await cursor.fetchone()
        if not payment:
            await conn.rollback()
            return None
        payment = dict(payment)

        async with conn.execute('SELECT vip_until, tier, owned_themes, theme FROM users WHERE telegram_id = ?', (payment['beneficiary_id'],)) as cursor:
            user = await cursor.fetchone()

        if user and payment['kind'] == 'vip' and user['vip_until']:
            from core.utils import parse_db_date
            current_until = parse_db_date(user['vip_until'])
            now = datetime.datetime.now(datetime.timezone.utc)
            if current_until:
                rolled_back = current_until - datetime.timedelta(days=payment['days'] or 0)
                if rolled_back <= now:
                    await conn.execute("UPDATE users SET is_vip = 0, vip_until = NULL, tier = 'free' WHERE telegram_id = ?", (payment['beneficiary_id'],))
                else:
                    await conn.execute('UPDATE users SET vip_until = ? WHERE telegram_id = ?', (rolled_back.isoformat(), payment['beneficiary_id']))
        elif user and payment['kind'] == 'theme':
            owned = [t for t in (user['owned_themes'] or 'standard').split(',') if t and t != payment['item']] or ['standard']
            active = user['theme'] if user['theme'] != payment['item'] else 'standard'
            await conn.execute('UPDATE users SET owned_themes = ?, theme = ? WHERE telegram_id = ?', (",".join(owned), active, payment['beneficiary_id']))

        await conn.execute("UPDATE payments SET status = 'refunded', refunded_at = CURRENT_TIMESTAMP WHERE charge_id = ?", (charge_id,))
        await conn.commit()
        return payment
    except BaseException:
        await conn.rollback()
        raise
    finally:
        await conn.close()
