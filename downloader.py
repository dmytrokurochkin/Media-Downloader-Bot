import os
import re
import sys
import json
import asyncio
import logging
import threading
import subprocess
import time
from pathlib import Path
from typing import Union, List, Optional
from urllib.parse import urlsplit
import yt_dlp
from core.config import TIER_LIMITS, TELEGRAM_UPLOAD_LIMIT, YTDLP_COOKIES_FROM_BROWSER
from core.net_guard import FetchError, ResponseTooLargeError, ensure_public_url, safe_download, safe_get
from core.utils import host_matches, run_command

logger = logging.getLogger(__name__)

# Ліміти часу. Раніше зовнішні процеси й yt-dlp могли висіти вічно, займаючи
# один із трьох слотів семафора завантажень, — три такі зависання, і бот більше
# не качав нічого до рестарту.
SUBPROCESS_TIMEOUT = 20 * 60
YTDLP_JOB_TIMEOUT = 60 * 60
YTDLP_SOCKET_TIMEOUT = 30
FFMPEG_TIMEOUT = 30 * 60

# Службові та недокачані файли, які не можна віддавати користувачу як «результат».
_LEFTOVER_SUFFIXES = {'.part', '.ytdl', '.temp', '.tmp', '.json', '.description', '.spotdl', '.lrc', '.m3u', '.m3u8'}
# Проміжні потоки yt-dlp, що лишаються, якщо злиття відео+аудіо не вдалося (`title.f137.mp4`).
_INTERMEDIATE_STREAM_RE = re.compile(r'\.f\d+(-\d+)?$')
_IMAGE_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp'}
_GALLERY_SUFFIXES = {'.jpg', '.jpeg', '.png', '.webp', '.mp4'}


class SizeLimitExceeded(Exception):
    """Файл більший за ліміт тарифу або за ліміт Telegram на завантаження."""

    def __init__(self, message: str = 'SIZE_LIMIT_EXCEEDED'):
        super().__init__(message)


class DownloadTimeoutError(Exception):
    """Завантаження не вклалось у відведений час і було зупинене."""


class DownloadFailedError(Exception):
    """Завантаження не вдалося; текст — справжня причина від бекенду."""


def is_leftover_file(path: Path) -> bool:
    if path.suffix.lower() in _LEFTOVER_SUFFIXES:
        return True
    # `video.f137.mp4`: stem `video.f137` закінчується на `.f137`.
    return bool(_INTERMEDIATE_STREAM_RE.search(path.stem))


def collect_media_files(session_dir: Path, *, recursive: bool = False, keep_images: bool = True) -> List[Path]:
    """Готові файли з теки сесії без службових і недокачаних залишків.

    Раніше бралось «усе, що є в теці»: при збої лишався `.part` або непомерджені
    потоки `.f137.mp4`/`.f140.m4a`, і їх відправляли користувачу як успішне завантаження.
    """
    candidates = session_dir.rglob('*') if recursive else session_dir.iterdir()
    files = []
    for path in candidates:
        if not path.is_file() or is_leftover_file(path):
            continue
        if not keep_images and path.suffix.lower() in _IMAGE_SUFFIXES:
            continue
        files.append(path)
    return files


def enforce_size_limit(files: List[Path], max_bytes: int) -> List[Path]:
    """Перевірка ФАКТИЧНОГО розміру після завантаження.

    match_filter yt-dlp знає розмір не завжди (HLS, TikTok тощо), а gallery-dl,
    spotdl і Threads раніше не обмежувались зовсім. Завеликі файли відкидаються;
    якщо не лишилось нічого — SizeLimitExceeded.
    """
    allowed = [f for f in files if f.stat().st_size <= max_bytes]
    if files and not allowed:
        raise SizeLimitExceeded()
    if len(allowed) != len(files):
        logger.info("Skipped %d file(s) larger than %d bytes", len(files) - len(allowed), max_bytes)
    return allowed


def _natural_key(path: Path):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r'(\d+)', path.name)]


def _short_error(tool: str, stderr: str) -> str:
    # Хвіст stderr інформативніший за початок: там сама помилка, а не банер.
    tail = (stderr or "").strip()[-1000:] or "невідома помилка"
    return f"Помилка {tool}: {tail}"


def _ffmpeg_binary() -> str:
    from core.config import FFMPEG_WIN_PATH
    return FFMPEG_WIN_PATH if Path(FFMPEG_WIN_PATH).exists() else "ffmpeg"


def _trim_spotdl_save_file(save_file: Path, playlist_limit: int) -> None:
    """Обрізає список треків spotdl до ліміту тарифу (JSON-список або текстовий список)."""
    if not save_file.exists() or playlist_limit >= 9999:
        return
    content = save_file.read_text(encoding="utf-8")
    try:
        data = json.loads(content)
        if isinstance(data, list) and len(data) > playlist_limit:
            save_file.write_text(json.dumps(data[:playlist_limit]), encoding="utf-8")
    except json.JSONDecodeError:
        lines = content.splitlines()
        if len(lines) > playlist_limit:
            save_file.write_text('\n'.join(lines[:playlist_limit]), encoding="utf-8")


async def download_with_spotdl(url: str, session_dir: Path, progress_callback=None, tier: str = 'free') -> List[Path]:
    """
    Завантажує треки, альбоми та плейлисти зі Spotify за допомогою spotdl.
    """
    if progress_callback:
        await progress_callback(10)

    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", NO_COLOR="1", TERM="dumb")
    from core.config import FFMPEG_WIN_PATH
    ffmpeg_args = ["--ffmpeg", FFMPEG_WIN_PATH] if Path(FFMPEG_WIN_PATH).exists() else []

    # Спершу `spotdl save`: отримуємо список треків, щоб застосувати ліміт плейлиста тарифу.
    save_file = session_dir / "tracks.spotdl"
    # `--` перед URL: рядок із Mini App, що починається з `-`, інакше став би опцією spotdl.
    save_cmd = [sys.executable, "-m", "spotdl", "save", "--save-file", str(save_file), *ffmpeg_args, "--", url]
    code, _, stderr = await run_command(save_cmd, timeout=SUBPROCESS_TIMEOUT, name="spotdl", env=env)
    if code != 0:
        raise DownloadFailedError(_short_error("spotdl", stderr))

    _trim_spotdl_save_file(save_file, TIER_LIMITS[tier]['playlist'])

    # spotdl качає треки паралельно, тож час створення файлів не відповідає порядку
    # альбому/плейлиста. Для списків номер позиції йде в назву файлу, і ми сортуємо за ним.
    # Для одиночного треку {list-position} порожній (spotdl підставив би «None»).
    is_list = not urlsplit(url).path.startswith('/track/')
    template = "{list-position} - {title} - {artist}.{output-ext}" if is_list else "{title} - {artist}.{output-ext}"
    cmd = [
        sys.executable, "-m", "spotdl", "download", str(save_file),
        "--output", str(session_dir / template),
        "--audio", "youtube-music", "youtube",
        "--log-level", "ERROR",
        *ffmpeg_args,
    ]
    code, _, stderr = await run_command(cmd, timeout=SUBPROCESS_TIMEOUT, name="spotdl", env=env)

    if progress_callback:
        await progress_callback(100)

    downloaded_files = collect_media_files(session_dir)
    if not downloaded_files:
        if code != 0:
            raise DownloadFailedError(_short_error("spotdl", stderr))
        raise DownloadFailedError("Не вдалося завантажити медіа зі Spotify. Можливо, трек не знайдено.")

    downloaded_files.sort(key=_natural_key)
    return downloaded_files


async def download_github(url: str, session_dir: Path, progress_callback=None, max_bytes: int = TIER_LIMITS['free']['size']) -> Path:
    """
    Парсить посилання на GitHub та завантажує .zip архів репозиторію.
    `archive/HEAD.zip` GitHub віддає з дефолтної гілки репозиторію, тож працюють і
    репозиторії з гілкою `dev`/`trunk`, а не лише main/master. Розмір обмежений
    тарифом: архів стрімиться на диск і обривається, щойно перевищить ліміт.
    """
    match = re.match(r'https?://(?:www\.)?github\.com/([^/]+)/([^/\?#]+)', url)
    if not match:
        raise ValueError("Невірний формат посилання на GitHub.")

    user, repo = match.groups()
    repo = repo.removesuffix('.git')

    archive_url = f"https://github.com/{user}/{repo}/archive/HEAD.zip"
    try:
        return await safe_download(
            archive_url,
            session_dir / f"{repo}.zip",
            max_bytes=max_bytes,
            progress_callback=progress_callback,
        )
    except FetchError as e:
        if e.status == 404:
            raise DownloadFailedError("Репозиторій не знайдено або він приватний.") from e
        raise


class _YtdlpLogger:
    """Збирає повідомлення yt-dlp замість того, щоб їх губити.

    З ignoreerrors=True yt-dlp не кидає винятків, а лише пише помилку в лог.
    Раніше будь-який збій перетворювався на «можливо, cookies.txt застарів», а гілка
    про вікові обмеження не спрацьовувала ніколи. Попередження (зокрема про
    відсутній JS-рантайм для YouTube) тепер потрапляють у лог бота.
    """

    def __init__(self):
        self.errors: List[str] = []
        self.size_exceeded = False

    def debug(self, msg):
        if 'max-filesize' in msg:
            self.size_exceeded = True

    def info(self, msg):
        self.debug(msg)

    def warning(self, msg):
        logger.warning("yt-dlp: %s", msg)

    def error(self, msg):
        self.errors.append(msg)
        logger.warning("yt-dlp error: %s", msg)


def describe_ytdlp_failure(messages: List[str]) -> str:
    """Перетворює помилки yt-dlp на зрозуміле пояснення для користувача."""
    text = " ".join(messages)
    lowered = text.lower()
    if "confirm your age" in lowered or "age-restricted" in lowered or "age restricted" in lowered:
        return "Цей контент має вікові обмеження (18+). YouTube блокує його завантаження для ботів. Додайте файл cookies.txt для автентифікації."
    if "private video" in lowered or "this video is private" in lowered:
        return "Це приватне відео — завантажити його неможливо."
    if "sign in to confirm you" in lowered or "not a bot" in lowered:
        return "YouTube вимагає підтвердити, що це не бот. Оновіть cookies.txt на сервері."
    if messages:
        return re.sub(r'^ERROR:\s*', '', messages[-1])[:500]
    return "Не вдалося завантажити медіа. Можливо, відео видалено або воно приватне."


def _cookie_configs() -> List[dict]:
    """Варіанти cookies по черзі: cookies.txt -> браузер (якщо задано в .env) -> без cookies.

    Раніше перебирались ще й шість браузерів підряд: на сервері їх немає, а кожен
    збій завантаження повторювався до восьми разів.
    """
    configs = []
    if Path('cookies.txt').exists():
        configs.append({'cookiefile': 'cookies.txt'})
    if YTDLP_COOKIES_FROM_BROWSER:
        configs.append({'cookiesfrombrowser': (YTDLP_COOKIES_FROM_BROWSER, None, None, None)})
    configs.append({})
    return configs


def _make_progress_hook(progress_callback, loop, cancel_event: Optional[threading.Event]):
    last = {"sent": -1.0, "at": 0.0}

    def hook(d):
        # Виняток із progress hook зупиняє завантаження — так спрацьовує таймаут задачі.
        if cancel_event is not None and cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled("Download timed out")
        if d.get('status') != 'downloading' or not progress_callback or not loop:
            return
        try:
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            if total:
                percent = d.get('downloaded_bytes', 0) / total * 100
            else:
                percent_str = re.sub(r'\x1b\[[0-9;]*m', '', d.get('_percent_str', '0%')).strip()
                percent = float(percent_str.replace('%', ''))
        except (TypeError, ValueError, ZeroDivisionError):
            return
        # Hook викликається десятки разів на секунду; event loop не засипаємо корутинами.
        now = time.monotonic()
        if percent - last["sent"] < 1 and now - last["at"] < 1:
            return
        last["sent"], last["at"] = percent, now
        asyncio.run_coroutine_threadsafe(progress_callback(min(percent, 100.0)), loop)

    return hook


def _embed_square_covers(session_dir: Path) -> None:
    """Обрізає обкладинки до 1:1 і вшиває їх у mp3 (mutagen), бо EmbedThumbnail не кропає."""
    from PIL import Image
    from mutagen.id3 import ID3, APIC, error

    for file_path in session_dir.iterdir():
        if file_path.suffix.lower() != '.mp3':
            continue
        jpg_path = file_path.with_suffix('.jpg')
        if not jpg_path.exists():
            continue
        try:
            with Image.open(jpg_path) as img:
                width, height = img.size
                min_dim = min(width, height)
                left = (width - min_dim) / 2
                top = (height - min_dim) / 2
                img.crop((left, top, left + min_dim, top + min_dim)).save(jpg_path)

            try:
                tags = ID3(str(file_path))
            except error:
                tags = ID3()

            tags.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=jpg_path.read_bytes()))
            tags.save(str(file_path), v2_version=3)
        except Exception as e:
            logger.warning("Не вдалося вшити обкладинку в %s: %s", file_path.name, e)


def download_media_sync(url: str, format_spec: str, progress_callback, loop, session_dir: Path, tier: str,
                        meta: Optional[dict] = None, cancel_event: Optional[threading.Event] = None) -> Union[Path, List[Path]]:
    """
    Синхронна функція для роботи з yt-dlp. Буде запущена в окремому потоці.
    """
    is_audio = 'bestaudio' in format_spec and 'bestvideo' not in format_spec
    playlist_limit = TIER_LIMITS[tier]['playlist']
    size_limit = min(TIER_LIMITS[tier]['size'], TELEGRAM_UPLOAD_LIMIT)
    size_limit_hit = False

    def check_size(info, *, incomplete):
        nonlocal size_limit_hit
        size = info.get('filesize') or info.get('filesize_approx') or 0
        if size > size_limit:
            size_limit_hit = True
            return 'SIZE_LIMIT_EXCEEDED'
        return None

    opts = {
        'format': format_spec,
        'outtmpl': str(session_dir / '%(title).100s_%(id).40s.%(ext)s'),
        'windowsfilenames': True,
        # Для плейлистів: один недоступний трек не валить решту. Помилки збирає _YtdlpLogger.
        'ignoreerrors': True,
        'quiet': True,
        'noprogress': True,
        'merge_output_format': 'mp4',
        'progress_hooks': [_make_progress_hook(progress_callback, loop, cancel_event)],
        'socket_timeout': YTDLP_SOCKET_TIMEOUT,
        # Обриває HTTP-завантаження, щойно сервер оголосив завеликий розмір.
        'max_filesize': size_limit,
        'match_filter': check_size,
        # YouTube вимагає JS-рантайм для челенджів: Deno (дефолт yt-dlp) або Node >= 22.
        # Буде використано той, що встановлений і підтримується.
        'js_runtimes': {'deno': {}, 'node': {}},
        'writethumbnail': True,
        'postprocessors': [],
    }
    if playlist_limit < 9999:
        opts['playlistend'] = playlist_limit

    from core.config import FFMPEG_WIN_PATH
    if Path(FFMPEG_WIN_PATH).exists():
        opts['ffmpeg_location'] = FFMPEG_WIN_PATH

    if is_audio:
        opts['postprocessors'] = [
            {'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3', 'preferredquality': '192'},
            {'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg'},
            # Вшиваємо метадані, але EmbedThumbnail зробимо власноруч через mutagen для кропу
            {'key': 'FFmpegMetadata'},
        ]
    else:
        # `-movflags +faststart` yt-dlp додає до виходу ffmpeg сам (FFmpegPostProcessor).
        opts['postprocessors'] = [
            {'key': 'FFmpegMetadata'},
            {'key': 'EmbedThumbnail', 'already_have_thumbnail': False},
        ]

    last_errors: List[str] = []
    for config in _cookie_configs():
        ytdlp_logger = _YtdlpLogger()
        current_opts = {**opts, **config, 'logger': ytdlp_logger}
        info = None
        try:
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadCancelled:
            raise DownloadTimeoutError("Завантаження перевищило ліміт часу.") from None
        except Exception as e:
            # CookieLoadError, DownloadError тощо — пробуємо наступний варіант cookies.
            ytdlp_logger.errors.append(str(e))

        if meta is not None and isinstance(info, dict) and info.get('title'):
            meta['title'] = str(info['title'])[:200]

        if cancel_event is not None and cancel_event.is_set():
            raise DownloadTimeoutError("Завантаження перевищило ліміт часу.")
        if size_limit_hit or ytdlp_logger.size_exceeded:
            raise SizeLimitExceeded()

        if is_audio:
            _embed_square_covers(session_dir)

        # Обкладинки вже вшиті у відео/аудіо, тож картинки в результат не йдуть.
        downloaded_files = collect_media_files(session_dir, keep_images=False)
        if downloaded_files:
            # Якщо обрано аудіо, але конвертація в mp3 не відбулась (ffmpeg недоступний
            # або постпроцесор впав), не надсилаємо сирий файл (напр. .webm) мовчки.
            if is_audio and not any(f.suffix.lower() == '.mp3' for f in downloaded_files):
                raise DownloadFailedError("Не вдалося конвертувати аудіо в mp3. Перевірте, що ffmpeg встановлений і FFMPEG_PATH у .env вказує на існуючий файл.")

            # Сортуємо файли за часом створення, щоб зберігався порядок плейлиста
            downloaded_files.sort(key=lambda x: x.stat().st_mtime)
            return downloaded_files[0] if len(downloaded_files) == 1 else downloaded_files

        last_errors = ytdlp_logger.errors or last_errors
        logger.info("yt-dlp attempt (%s) produced no files: %s", ", ".join(config) or "no cookies", last_errors[-1:])

    raise DownloadFailedError(describe_ytdlp_failure(last_errors))


async def download_with_gallery_dl(url: str, session_dir: Path, progress_callback=None, tier: str = 'free') -> List[Path]:
    if progress_callback:
        await progress_callback(10)

    limits = TIER_LIMITS[tier]
    cmd = [
        sys.executable, "-m", "gallery_dl",
        "--directory", str(session_dir),
        # Без --no-mtime gallery-dl ставить файлам час із Last-Modified сервера, і
        # сортування за mtime перемішувало порядок каруселі.
        "--no-mtime",
        "--filesize-max", str(min(limits['size'], TELEGRAM_UPLOAD_LIMIT)),
    ]

    playlist_limit = limits['playlist']
    if playlist_limit < 9999:
        cmd.extend(["--range", f"1-{playlist_limit}"])

    if Path('cookies.txt').exists():
        cmd.extend(["--cookies", "cookies.txt"])

    # `--` перед URL: рядок із Mini App, що починається з `-`, інакше став би опцією gallery-dl.
    cmd.extend(["--", url])

    code, _, stderr = await run_command(cmd, timeout=SUBPROCESS_TIMEOUT, name="gallery-dl")

    if progress_callback:
        await progress_callback(100)

    files = [p for p in collect_media_files(session_dir, recursive=True) if p.suffix.lower() in _GALLERY_SUFFIXES]
    if not files:
        if code != 0:
            raise DownloadFailedError(_short_error("gallery-dl", stderr))
        raise DownloadFailedError("Не вдалося завантажити медіа. Можливо, пост порожній, приватний, або посилання недійсне.")
    if code != 0:
        # Частковий успіх (напр. один елемент каруселі недоступний) — віддаємо те, що є.
        logger.warning("gallery-dl finished with code %s: %s", code, (stderr or "")[-300:])

    files.sort(key=lambda x: x.stat().st_mtime)
    return files


THREADS_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Sec-Fetch-Mode": "navigate",
}
THREADS_PAGE_MAX_BYTES = 10 * 1024 * 1024
THREADS_MAX_ITEMS = 10


def _decode_json_string(raw: str) -> str:
    """Розкодовує вміст JSON-рядка (`\\/`, `\\u0026`), вирізаний регекспом зі сторінки.

    Раніше тут був `.decode('unicode_escape')`, який ламав не-ASCII символи
    (UTF-8 байти перечитувались як latin-1).
    """
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw.replace('\\/', '/')


def extract_threads_media(page_text: str, shortcode: str) -> List[tuple]:
    """Повертає [(url, ext), ...] для медіа посту в порядку каруселі."""
    media = []
    for chunk in page_text.split('"code":"')[1:]:
        if not chunk.startswith(shortcode + '"'):
            continue
        for block in re.findall(r'"video_versions":\[(.*?)\]', chunk):
            urls = re.findall(r'"url":"([^"]+)"', block)
            if urls:
                media.append((_decode_json_string(urls[0]), ".mp4"))
        for block in re.findall(r'"image_versions2":\{"candidates":\[(.*?)\]\}', chunk):
            urls = re.findall(r'"url":"([^"]+)"', block)
            if urls:
                image_url = _decode_json_string(urls[0])
                media.append((image_url, ".webp" if ".webp" in image_url else ".jpg"))
        break

    unique, seen = [], set()
    for media_url, ext in media:
        if media_url not in seen:
            seen.add(media_url)
            unique.append((media_url, ext))
    return unique


async def download_threads_native(url: str, session_dir: Path, progress_callback=None, max_bytes: int = TIER_LIMITS['free']['size']) -> List[Path]:
    match = re.search(r'/post/([^/?#]+)', url)
    if not match:
        raise ValueError("Не вдалося знайти ID посту в посиланні Threads.")
    shortcode = match.group(1)

    if progress_callback:
        await progress_callback(10)

    # Без переписування threads.com -> threads.net: канонічний домен тепер threads.com,
    # а редіректи safe_get і так пройде (з перевіркою кожного хопу).
    page = await safe_get(url, max_bytes=THREADS_PAGE_MAX_BYTES, timeout=20, headers=THREADS_HEADERS)
    media = extract_threads_media(page.body.decode(page.charset or 'utf-8', errors='replace'), shortcode)

    if not media:
        raise DownloadFailedError("Не вдалося знайти медіа. Threads міг змінити формат сайту або пост не містить фото/відео.")

    if progress_callback:
        await progress_callback(30)

    async def fetch_item(index: int, media_url: str, ext: str):
        filepath = session_dir / f"threads_{shortcode}_{index:02d}{ext}"
        try:
            return await safe_download(
                media_url, filepath, max_bytes=max_bytes,
                headers={"User-Agent": THREADS_HEADERS["User-Agent"]},
            )
        except ResponseTooLargeError:
            raise
        except Exception as e:
            logger.warning("Threads: не вдалося завантажити %s: %s", media_url, e)
            return None

    # gather зберігає порядок аргументів, тож порядок каруселі не губиться.
    results = await asyncio.gather(
        *(fetch_item(i, media_url, ext) for i, (media_url, ext) in enumerate(media[:THREADS_MAX_ITEMS]))
    )
    downloaded = [path for path in results if path is not None]

    if progress_callback:
        await progress_callback(100)

    if not downloaded:
        raise DownloadFailedError("Не вдалося завантажити медіа з Threads.")

    return downloaded


def _apply_size_limit(result: Union[Path, List[Path]], max_bytes: int) -> Union[Path, List[Path]]:
    if isinstance(result, list):
        return enforce_size_limit(result, max_bytes)
    enforce_size_limit([result], max_bytes)
    return result


async def download_media(url: str, format_spec: str = 'bestvideo+bestaudio/best', progress_callback=None, tier: str = 'free', session_dir: Path = None, meta: Optional[dict] = None) -> Union[Path, List[Path]]:
    """
    Головна асинхронна функція для завантаження медіа.

    `meta` (необов'язковий dict) заповнюється метаданими, які вдалося дізнатись
    під час завантаження (зараз — `title` від yt-dlp).
    """
    # Перевірка на SSRF ДО будь-якого бекенду: всі вони ходять у мережу з нашого сервера.
    await ensure_public_url(url)

    loop = asyncio.get_running_loop()
    if session_dir is None:
        session_dir = Path(f"downloads/{time.time_ns()}")
        session_dir.mkdir(parents=True, exist_ok=True)

    # Ліміт розміру одного файлу: тариф, але не більше, ніж Telegram дозволяє завантажити.
    max_bytes = min(TIER_LIMITS[tier]['size'], TELEGRAM_UPLOAD_LIMIT)

    # Перенаправляємо Instagram на gallery-dl
    if host_matches(url, 'instagram.com'):
        return _apply_size_limit(await download_with_gallery_dl(url, session_dir, progress_callback, tier), max_bytes)

    # Перенаправляємо Threads на кастомний парсер
    if host_matches(url, 'threads.net', 'threads.com'):
        return _apply_size_limit(await download_threads_native(url, session_dir, progress_callback, max_bytes), max_bytes)

    # Перенаправляємо фотографії Facebook на gallery-dl (yt-dlp краще працює з відео)
    if host_matches(url, 'facebook.com') and urlsplit(url).path.startswith(('/photo', '/media')):
        return _apply_size_limit(await download_with_gallery_dl(url, session_dir, progress_callback, tier), max_bytes)

    if host_matches(url, 'spotify.com'):
        return _apply_size_limit(await download_with_spotdl(url, session_dir, progress_callback, tier), max_bytes)

    if host_matches(url, 'github.com'):
        return _apply_size_limit(await download_github(url, session_dir, progress_callback, max_bytes), max_bytes)

    cancel_event = threading.Event()
    try:
        # yt-dlp синхронний — запускаємо в окремому потоці. Потік не вбити, тому
        # таймаут працює через cancel_event: progress hook кидає DownloadCancelled.
        filepath = await asyncio.wait_for(
            asyncio.to_thread(
                download_media_sync,
                url,
                format_spec,
                progress_callback,
                loop,
                session_dir,
                tier,
                meta,
                cancel_event,
            ),
            timeout=YTDLP_JOB_TIMEOUT,
        )
        return _apply_size_limit(filepath, max_bytes)
    except BaseException as e:
        cancel_event.set()
        # Видаляємо тимчасову папку при помилці
        import shutil
        shutil.rmtree(session_dir, ignore_errors=True)
        if isinstance(e, asyncio.TimeoutError):
            raise DownloadTimeoutError("Завантаження перевищило ліміт часу.") from None
        raise


def download_trim_sync(url: str, start_sec: int, end_sec: int, session_dir: Path, progress_callback, loop,
                       tier: str = 'free', cancel_event: Optional[threading.Event] = None) -> Path:
    """
    Завантажує фрагмент відео використовуючи yt-dlp (download_ranges)
    або як fallback завантажує все і ріже FFmpeg-ом.
    """
    max_bytes = min(TIER_LIMITS[tier]['size'], TELEGRAM_UPLOAD_LIMIT)
    # Та сама стеля якості, що й для звичайних завантажень: раніше Free через обрізку
    # отримував максимальну якість.
    height = {'free': 720, 'pro': 1080}.get(tier)
    if height:
        fmt = f'bestvideo[ext=mp4][height<={height}]+bestaudio[ext=m4a]/best[ext=mp4][height<={height}]/best[height<={height}]'
    else:
        fmt = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best'

    opts = {
        'format': fmt,
        'outtmpl': str(session_dir / '%(title).100s_%(id).40s.%(ext)s'),
        'windowsfilenames': True,
        'ignoreerrors': False,
        'noplaylist': True,
        'quiet': True,
        'noprogress': True,
        'logger': _YtdlpLogger(),
        'merge_output_format': 'mp4',
        'progress_hooks': [_make_progress_hook(progress_callback, loop, cancel_event)],
        'socket_timeout': YTDLP_SOCKET_TIMEOUT,
        'download_ranges': yt_dlp.utils.download_range_func(None, [(start_sec, end_sec)]),
        'js_runtimes': {'deno': {}, 'node': {}},
    }

    from core.config import FFMPEG_WIN_PATH
    if Path(FFMPEG_WIN_PATH).exists():
        opts['ffmpeg_location'] = FFMPEG_WIN_PATH

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

        downloaded_files = collect_media_files(session_dir, keep_images=False)
        if downloaded_files:
            if progress_callback and loop:
                asyncio.run_coroutine_threadsafe(progress_callback(100), loop)
            return downloaded_files[0]
    except yt_dlp.utils.DownloadCancelled:
        raise DownloadTimeoutError("Обрізка перевищила ліміт часу.") from None
    except Exception as e:
        logger.info("Native range download failed: %s. Falling back to full download + trim.", e)

    # Fallback: качаємо відео повністю, але не більше за ліміт тарифу — інакше заради
    # 30-секундного фрагмента сервер міг тягнути багатогігабайтне джерело.
    opts.pop('download_ranges', None)
    opts['max_filesize'] = max_bytes
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
    except yt_dlp.utils.DownloadCancelled:
        raise DownloadTimeoutError("Обрізка перевищила ліміт часу.") from None

    downloaded_files = collect_media_files(session_dir, keep_images=False)
    if not downloaded_files:
        if opts['logger'].size_exceeded:
            raise SizeLimitExceeded()
        raise DownloadFailedError("Не вдалося завантажити медіа для нарізки.")

    input_file = downloaded_files[0]
    output_file = session_dir / f"trimmed_{input_file.name}"

    cmd = [
        _ffmpeg_binary(),
        "-y", "-ss", str(start_sec), "-to", str(end_sec),
        "-i", str(input_file),
        "-c", "copy",
        str(output_file)
    ]

    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT)
    except subprocess.TimeoutExpired:
        raise DownloadTimeoutError("ffmpeg не встиг обрізати відео.") from None
    except subprocess.CalledProcessError as e:
        raise DownloadFailedError(_short_error("ffmpeg", e.stderr)) from None

    input_file.unlink(missing_ok=True)

    if progress_callback and loop:
        asyncio.run_coroutine_threadsafe(progress_callback(100), loop)

    return output_file
