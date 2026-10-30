import os
import re
import json
import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import Union, List, Optional
from urllib.parse import urlsplit
import yt_dlp
from core.config import TIER_LIMITS
from core.net_guard import FetchError, ResponseTooLargeError, ensure_public_url, safe_download, safe_get

logger = logging.getLogger(__name__)


def host_matches(url: str, *domains: str) -> bool:
    """True, якщо хост URL — це один із доменів або його піддомен.

    Перевірка підрядком (`'instagram.com' in url`) ловила й `https://evil.com/?x=instagram.com`,
    тож маршрутизація йде лише за справжнім хостом.
    """
    host = (urlsplit(url).hostname or "").lower()
    return any(host == domain or host.endswith("." + domain) for domain in domains)

async def download_with_spotdl(url: str, session_dir: Path, progress_callback=None, tier: str = 'free') -> List[Path]:
    """
    Завантажує треки, альбоми та плейлисти зі Spotify за допомогою spotdl.
    """
    import sys
    
    if progress_callback:
        await progress_callback(10)
        
    def run_spotdl():
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", NO_COLOR="1", TERM="dumb")
        
        from core.config import FFMPEG_WIN_PATH
        from pathlib import Path
        ffmpeg_winget = Path(FFMPEG_WIN_PATH)

        # Використовуємо spotdl save для отримання списку треків, щоб застосувати ліміт 30
        save_file = session_dir / "tracks.spotdl"
        try:
            save_cmd = [
                sys.executable, "-m", "spotdl", "save", "--save-file", str(save_file)
            ]
            if ffmpeg_winget.exists():
                save_cmd.extend(["--ffmpeg", str(ffmpeg_winget)])
            # `--` перед URL: рядок із Mini App, що починається з `-`, інакше став би опцією spotdl.
            save_cmd.extend(["--", url])

            subprocess.run(save_cmd, check=True, capture_output=True, text=True, env=env, encoding='utf-8', errors='replace')
            
            playlist_limit = TIER_LIMITS[tier]['playlist']
            if save_file.exists() and playlist_limit < 9999:
                with open(save_file, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # spotdl save може зберігати у json або текстовому форматі.
                # Якщо це просто список url, рахуємо рядки. Якщо JSON - спробуємо розпарсити.
                # Для надійності, якщо це JSON list:
                import json
                try:
                    data = json.loads(content)
                    if isinstance(data, list) and len(data) > playlist_limit:
                        with open(save_file, "w", encoding="utf-8") as f:
                            json.dump(data[:playlist_limit], f)
                except json.JSONDecodeError:
                    # Це звичайний текстовий список
                    lines = content.splitlines()
                    if len(lines) > playlist_limit:
                        with open(save_file, "w", encoding="utf-8") as f:
                            f.write('\n'.join(lines[:playlist_limit]))

            cmd = [
                sys.executable, "-m", "spotdl",
                str(save_file),
                "--output", str(session_dir / "{title} - {artist}.{output-ext}"),
                "--audio", "youtube-music", "youtube",
                "--log-level", "ERROR"
            ]
            if ffmpeg_winget.exists():
                cmd.extend(["--ffmpeg", str(ffmpeg_winget)])

            subprocess.run(cmd, check=True, capture_output=True, text=True, env=env, encoding='utf-8', errors='replace')
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr if e.stderr else "Невідома помилка"
            if len(err_msg) > 1000:
                err_msg = err_msg[:1000] + "..."
            raise Exception(f"Помилка spotdl: {err_msg}")
            
    await asyncio.to_thread(run_spotdl)
    
    if progress_callback:
        await progress_callback(100)
        
    downloaded_files = []
    for file_path in session_dir.iterdir():
        if file_path.is_file() and file_path.suffix.lower() != '.spotdl':
            downloaded_files.append(file_path)
            
    if not downloaded_files:
        raise Exception("Не вдалося завантажити медіа зі Spotify. Можливо, трек не знайдено.")
        
    # Сортуємо за часом створення, щоб зберегти порядок
    downloaded_files.sort(key=lambda x: x.stat().st_mtime)
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
            raise Exception("Репозиторій не знайдено або він приватний.") from e
        raise

def download_media_sync(url: str, format_spec: str, progress_callback, loop, session_dir: Path, tier: str, meta: Optional[dict] = None) -> Path:
    """
    Синхронна функція для роботи з yt-dlp. Буде запущена в окремому потоці.
    """
    def hook(d):
        if d['status'] == 'downloading':
            try:
                # Отримуємо відсоток і видаляємо можливі ANSI escape коди кольорів
                percent_str = d.get('_percent_str', '0%').strip()
                percent_str = re.sub(r'\x1b\[[0-9;]*m', '', percent_str)
                percent = float(percent_str.replace('%', ''))
                
                # Надсилаємо оновлення в головний event loop (asyncio)
                if progress_callback and loop:
                    asyncio.run_coroutine_threadsafe(progress_callback(percent), loop)
            except Exception:
                pass

    opts = {
        'format': format_spec,
        'outtmpl': str(session_dir / '%(title).100s_%(id).40s.%(ext)s'),
        'windowsfilenames': True,
        'ignoreerrors': True,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'progress_hooks': [hook] if progress_callback else [],
        'js_runtimes': {'node': {}},
    }
    
    size_limit_hit = False
    
    playlist_limit = TIER_LIMITS[tier]['playlist']
    size_limit = TIER_LIMITS[tier]['size']
    
    if playlist_limit < 9999:
        opts['playlistend'] = playlist_limit
        
    def check_size(info, *, incomplete):
        nonlocal size_limit_hit
        size = info.get('filesize') or info.get('filesize_approx') or 0
        if size > size_limit:
            size_limit_hit = True
            return 'SIZE_LIMIT_EXCEEDED'
        return None
        
    opts['match_filter'] = check_size

    from core.config import FFMPEG_WIN_PATH
    ffmpeg_winget = Path(FFMPEG_WIN_PATH)
    if ffmpeg_winget.exists():
        opts['ffmpeg_location'] = str(ffmpeg_winget)
    
    # Додаємо метадані та обкладинки
    opts['writethumbnail'] = True
    opts['postprocessors'] = []
    
    # Якщо вибрано аудіо, робимо конвертацію в mp3
    if 'bestaudio' in format_spec and 'bestvideo' not in format_spec:
        opts['postprocessors'].append({
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        })
        opts['postprocessors'].append({
            'key': 'FFmpegThumbnailsConvertor',
            'format': 'jpg',
        })
        # Вшиваємо метадані, але EmbedThumbnail зробимо власноруч через mutagen для кропу
        opts['postprocessors'].append({'key': 'FFmpegMetadata'})
    else:
        # Додаємо faststart для правильного відображення відео в Telegram
        opts['postprocessor_args'] = {'FFmpegVideoConvertor': ['-movflags', '+faststart']}
        opts['postprocessors'].extend([
            {'key': 'FFmpegMetadata'},
            {'key': 'EmbedThumbnail', 'already_have_thumbnail': False}
        ])

    # Формуємо список конфігів для перебору cookies
    browsers = ['brave', 'firefox', 'chrome', 'edge', 'opera', 'safari']
    configs = []

    if Path('cookies.txt').exists():
        configs.append({'cookiefile': 'cookies.txt'})
    for b in browsers:
        configs.append({'cookiesfrombrowser': (b, None, None, None)})

    # Запасний варіант без cookies
    configs.append({})
    
    last_error = None
    for config in configs:
        current_opts = opts.copy()
        current_opts.update(config)
        try:
            with yt_dlp.YoutubeDL(current_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if meta is not None and isinstance(info, dict) and info.get('title'):
                    meta['title'] = str(info['title'])[:200]

                if size_limit_hit:
                    raise Exception('SIZE_LIMIT_EXCEEDED')
                
                # Для аудіо обрізаємо та вшиваємо обкладинку 1:1
                if 'bestaudio' in format_spec and 'bestvideo' not in format_spec:
                    from PIL import Image
                    from mutagen.id3 import ID3, APIC, error
                    
                    for file_path in session_dir.iterdir():
                        if file_path.suffix.lower() == '.mp3':
                            jpg_path = file_path.with_suffix('.jpg')
                            if jpg_path.exists():
                                try:
                                    img = Image.open(jpg_path)
                                    width, height = img.size
                                    min_dim = min(width, height)
                                    left = (width - min_dim) / 2
                                    top = (height - min_dim) / 2
                                    right = (width + min_dim) / 2
                                    bottom = (height + min_dim) / 2
                                    img = img.crop((left, top, right, bottom))
                                    img.save(jpg_path)
                                    
                                    try:
                                        tags = ID3(str(file_path))
                                    except error:
                                        tags = ID3()
                                        
                                    with open(jpg_path, 'rb') as f:
                                        img_data = f.read()
                                        
                                    tags.add(APIC(
                                        encoding=3,
                                        mime='image/jpeg',
                                        type=3, 
                                        desc=u'Cover',
                                        data=img_data
                                    ))
                                    tags.save(str(file_path), v2_version=3)
                                except Exception as e:
                                    print("Помилка вшивання обкладинки:", e)

                # Після завантаження просто беремо всі файли з директорії
                downloaded_files = []
                for file_path in session_dir.iterdir():
                    if file_path.is_file():
                        # Видаляємо обкладинки, бо вони вже вшиті у відео/аудіо
                        if file_path.suffix.lower() in ['.jpg', '.jpeg', '.png', '.webp']:
                            try:
                                file_path.unlink()
                            except:
                                pass
                            continue
                        downloaded_files.append(file_path)
                        
                if not downloaded_files:
                    raise Exception("Не вдалося завантажити медіа. Можливо, відео видалено, приватне, або має вікові обмеження (18+), а ваш файл cookies.txt застарів. Спробуйте оновити cookies.txt.")

                # Якщо обрано аудіо, але конвертація в mp3 не відбулась (ffmpeg недоступний
                # або постпроцесор впав), не надсилаємо сирий файл (напр. .webm) мовчки.
                if 'bestaudio' in format_spec and 'bestvideo' not in format_spec:
                    if not any(f.suffix.lower() == '.mp3' for f in downloaded_files):
                        raise Exception('FFMPEG_CONVERSION_FAILED')

                # Сортуємо файли за часом створення, щоб зберігався порядок плейлиста
                downloaded_files.sort(key=lambda x: x.stat().st_mtime)
                
                if len(downloaded_files) == 1:
                    return downloaded_files[0]
                return downloaded_files
                
        except Exception as e:
            if str(e) == 'SIZE_LIMIT_EXCEEDED':
                raise e
            if str(e) == 'FFMPEG_CONVERSION_FAILED':
                raise Exception("Не вдалося конвертувати аудіо в mp3. Перевірте, що ffmpeg встановлений і FFMPEG_PATH у .env вказує на існуючий файл.")
            last_error = e
            print(f"Помилка yt-dlp з конфігом {config}: {e}")

    # Якщо всі спроби провалились
    if last_error:
        err_msg = str(last_error)
        if "Sign in to confirm your age" in err_msg:
            raise Exception("Цей контент має вікові обмеження (18+). YouTube блокує його завантаження для ботів. Додайте файл cookies.txt для автентифікації.")
        raise last_error

async def download_with_gallery_dl(url: str, session_dir: Path, progress_callback=None, tier: str = 'free') -> List[Path]:
    import sys
    
    if progress_callback:
        await progress_callback(10)
        
    def run_gallery_dl():
        cmd = [
            sys.executable, "-m", "gallery_dl",
            "--directory", str(session_dir),
        ]

        playlist_limit = TIER_LIMITS[tier]['playlist']
        if playlist_limit < 9999:
            cmd.extend(["--range", f"1-{playlist_limit}"])

        if Path('cookies.txt').exists():
            cmd.extend(["--cookies", "cookies.txt"])

        # `--` перед URL: рядок із Mini App, що починається з `-`, інакше став би опцією gallery-dl.
        cmd.extend(["--", url])

        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True, encoding='utf-8', errors='replace')
            print("gallery-dl output:", result.stdout)
        except subprocess.CalledProcessError as e:
            print("gallery-dl error:", e.stderr)
            raise Exception(f"Помилка gallery-dl: {e.stderr}")
            
    try:
        await asyncio.to_thread(run_gallery_dl)
    except Exception as e:
        raise Exception(str(e))
        
    if progress_callback:
        await progress_callback(100)
        
    files = []
    allowed_exts = ['.jpg', '.jpeg', '.png', '.webp', '.mp4']
    for root, _, filenames in os.walk(session_dir):
        for f in filenames:
            if any(f.lower().endswith(ext) for ext in allowed_exts):
                files.append(Path(root) / f)
            
    if not files:
        raise Exception("Не вдалося завантажити медіа. Можливо, пост порожній, приватний, або посилання недійсне.")
        
    # Сортуємо за часом створення, щоб зберегти порядок каруселі
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
        raise Exception("Не вдалося знайти медіа. Threads міг змінити формат сайту або пост не містить фото/відео.")

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
        raise Exception("Не вдалося завантажити медіа з Threads.")

    return downloaded

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

    max_bytes = TIER_LIMITS[tier]['size']

    # Перенаправляємо Instagram на gallery-dl
    if host_matches(url, 'instagram.com'):
        return await download_with_gallery_dl(url, session_dir, progress_callback, tier)

    # Перенаправляємо Threads на кастомний парсер
    if host_matches(url, 'threads.net', 'threads.com'):
        return await download_threads_native(url, session_dir, progress_callback, max_bytes)

    # Перенаправляємо фотографії Facebook на gallery-dl (yt-dlp краще працює з відео)
    if host_matches(url, 'facebook.com') and urlsplit(url).path.startswith(('/photo', '/media')):
        return await download_with_gallery_dl(url, session_dir, progress_callback, tier)

    if host_matches(url, 'spotify.com'):
        return await download_with_spotdl(url, session_dir, progress_callback, tier)

    if host_matches(url, 'github.com'):
        return await download_github(url, session_dir, progress_callback, max_bytes)

    try:
        # Запускаємо синхронну yt-dlp функцію в ThreadPool,
        # щоб не блокувати головний цикл asyncio
        filepath = await asyncio.to_thread(
            download_media_sync,
            url,
            format_spec,
            progress_callback,
            loop,
            session_dir,
            tier,
            meta,
        )
        return filepath
    except Exception as e:
        # Видаляємо тимчасову папку при помилці
        try:
            if session_dir.exists():
                for f in session_dir.iterdir():
                    f.unlink()
                session_dir.rmdir()
        except:
            pass
        raise e

def download_trim_sync(url: str, start_sec: int, end_sec: int, session_dir: Path, progress_callback, loop) -> Path:
    """
    Завантажує фрагмент відео використовуючи yt-dlp (download_ranges) 
    або як fallback завантажує все і ріже FFmpeg-ом.
    """
    def hook(d):
        if d['status'] == 'downloading':
            try:
                percent_str = d.get('_percent_str', '0%').strip()
                percent_str = re.sub(r'\x1b\[[0-9;]*m', '', percent_str)
                percent = float(percent_str.replace('%', ''))
                if progress_callback and loop:
                    asyncio.run_coroutine_threadsafe(progress_callback(percent), loop)
            except Exception:
                pass

    from core.config import FFMPEG_WIN_PATH
    import subprocess
    ffmpeg_winget = Path(FFMPEG_WIN_PATH)
    
    opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best',
        'outtmpl': str(session_dir / '%(title).100s_%(id).40s.%(ext)s'),
        'windowsfilenames': True,
        'ignoreerrors': False,
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'progress_hooks': [hook] if progress_callback else [],
        'download_ranges': yt_dlp.utils.download_range_func(None, [(start_sec, end_sec)]),
    }
    
    if ffmpeg_winget.exists():
        opts['ffmpeg_location'] = str(ffmpeg_winget)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])
            
        downloaded_files = [f for f in session_dir.iterdir() if f.is_file() and f.suffix.lower() not in ['.tmp', '.part', '.ytdl']]
        if downloaded_files:
            if progress_callback and loop:
                asyncio.run_coroutine_threadsafe(progress_callback(100), loop)
            return downloaded_files[0]
            
    except Exception as e:
        print(f"Native range download failed: {e}. Falling back to full download + trim.")

    # Fallback
    opts.pop('download_ranges', None)
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
        
    downloaded_files = [f for f in session_dir.iterdir() if f.is_file() and f.suffix.lower() not in ['.tmp', '.part', '.ytdl']]
    if not downloaded_files:
        raise Exception("Не вдалося завантажити медіа для нарізки.")
        
    input_file = downloaded_files[0]
    output_file = session_dir / f"trimmed_{input_file.name}"
    
    cmd = [
        str(ffmpeg_winget) if ffmpeg_winget.exists() else "ffmpeg",
        "-y", "-ss", str(start_sec), "-to", str(end_sec),
        "-i", str(input_file),
        "-c", "copy",
        str(output_file)
    ]
    
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    
    if input_file.exists():
        input_file.unlink()
        
    if progress_callback and loop:
        asyncio.run_coroutine_threadsafe(progress_callback(100), loop)
        
    return output_file
