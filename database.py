import aiosqlite
import datetime
from pathlib import Path
from typing import Optional, Dict, Any, List

DB_PATH = Path("database.db")
_db_connection = None

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
    await db.execute('CREATE INDEX IF NOT EXISTS idx_user_badges ON user_badges(telegram_id);')
    
    await db.commit()

async def get_or_create_user(telegram_id: int, username: str, full_name: str, language_code: str = 'en') -> dict:
    global _db_connection
    db = _db_connection
    async with db.execute('SELECT * FROM users WHERE telegram_id = ?', (telegram_id,)) as cursor:
        user = await cursor.fetchone()
        
    if not user:
        await db.execute('''
            INSERT INTO users (telegram_id, username, full_name, language_code, tier)
            VALUES (?, ?, ?, ?, 'free')
        ''', (telegram_id, username, full_name, language_code))
        await db.commit()
        return {
            "telegram_id": telegram_id,
            "username": username,
            "full_name": full_name,
            "is_vip": False,
            "vip_until": None,
            "language_code": language_code,
            "guest_yt_quality": "best",
            "tier": "free",
            "banned_bot_until": None,
            "banned_support_until": None,
            "is_anonymous": 0,
            "theme": "standard",
            "watermark_file_id": None,
            "watermark_position": "bottom_right"
        }
    
    # Оновлюємо ім'я та юзернейм, якщо вони змінились
    if user['username'] != username or user['full_name'] != full_name:
        await db.execute('''
            UPDATE users SET username = ?, full_name = ? WHERE telegram_id = ?
        ''', (username, full_name, telegram_id))
        await db.commit()
        
    user_dict = dict(user)
    
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
        except Exception as e:
            print(f"Помилка парсингу vip_until для {telegram_id}: {e}")
        
    return user_dict

async def set_user_language(telegram_id: int, language_code: str):
    global _db_connection
    await _db_connection.execute('UPDATE users SET language_code = ? WHERE telegram_id = ?', (language_code, telegram_id))
    await _db_connection.commit()

async def set_user_vip(telegram_id: int, is_vip: bool):
    global _db_connection
    await _db_connection.execute('UPDATE users SET is_vip = ? WHERE telegram_id = ?', (is_vip, telegram_id))
    await _db_connection.commit()

async def grant_vip(telegram_id: int, days: int, tier: str = 'max') -> str:
    """Видає VIP доступ на задану кількість днів. Повертає нову дату закінчення."""
    global _db_connection
    db = _db_connection
    now = datetime.datetime.now(datetime.timezone.utc)
    
    async with db.execute('SELECT vip_until, tier FROM users WHERE telegram_id = ?', (telegram_id,)) as cursor:
        user = await cursor.fetchone()
        
    if not user:
        raise ValueError("User not found")
        
    vip_until = now
    if user['vip_until']:
        from core.utils import parse_db_date
        current_vip_until = parse_db_date(user['vip_until'])
        if current_vip_until and current_vip_until > now:
            if user['tier'] == tier:
                vip_until = current_vip_until
            
    new_vip_until = vip_until + datetime.timedelta(days=days)
    new_vip_until_iso = new_vip_until.isoformat()
    
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
        WHERE telegram_id = ? AND success = 1 AND DATE(timestamp) = DATE('now')
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

async def get_top_domains() -> List[dict]:
    """Повертає лідерборд найпопулярніших ресурсів"""
    global _db_connection
    async with _db_connection.execute('''
        SELECT domain, COUNT(*) as count 
        FROM downloads 
        WHERE success = 1 
        GROUP BY domain 
        ORDER BY count DESC 
        LIMIT 10
    ''') as cursor:
        rows = await cursor.fetchall()
        return [dict(r) for r in rows]

async def get_top_users(limit: int = 10) -> List[dict]:
    """Повертає лідерборд користувачів за кількістю завантажень"""
    global _db_connection
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
        return [dict(r) for r in rows]

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
    search_term = f"%{query_string}%"
    async with _db_connection.execute('''
        SELECT telegram_id, username, full_name, tier, total_bytes_downloaded 
        FROM users 
        WHERE is_anonymous = 0 
        AND (full_name LIKE ? OR username LIKE ? OR CAST(telegram_id AS TEXT) = ?)
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

async def get_active_ad() -> Optional[str]:
    """Повертає текст активної рекламної кампанії, або None."""
    global _db_connection
    async with _db_connection.execute('SELECT ad_text FROM ad_campaigns WHERE is_active = 1 LIMIT 1') as cursor:
        row = await cursor.fetchone()
        if row:
            return row['ad_text']
    return None

async def set_active_ad(ad_text: str):
    """Робить всі існуючі кампанії неактивними і додає нову активну."""
    global _db_connection
    await _db_connection.execute('UPDATE ad_campaigns SET is_active = 0')
    await _db_connection.execute('INSERT INTO ad_campaigns (ad_text, is_active) VALUES (?, 1)', (ad_text,))
    await _db_connection.commit()

async def clear_active_ads():
    """Вимкнути всі рекламні кампанії."""
    global _db_connection
    await _db_connection.execute('UPDATE ad_campaigns SET is_active = 0')
    await _db_connection.commit()
