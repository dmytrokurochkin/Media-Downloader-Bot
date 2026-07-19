import os
import re
import asyncio
import aiohttp
import subprocess
import time
from pathlib import Path
from typing import Union, List
import yt_dlp
from core.config import TIER_LIMITS

async def download_with_spotdl(url: str, session_dir: Path, progress_callback=None, tier: str = 'free') -> List[Path]:
    """
    Завантажує треки, альбоми та плейлисти зі Spotify за допомогою spotdl.
    """
    import sys
    
    if progress_callback:
        await progress_callback(10)
        
    def run_spotdl():
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1", NO_COLOR="1", TERM="dumb")
        
        # Використовуємо spotdl save для отримання списку треків, щоб застосувати ліміт 30
        save_file = session_dir / "tracks.spotdl"
        try:
            subprocess.run([
                sys.executable, "-m", "spotdl", "save", url, "--save-file", str(save_file)
            ], check=True, capture_output=True, text=True, env=env, encoding='utf-8', errors='replace')
            
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
            from core.config import FFMPEG_WIN_PATH
            import os
            from pathlib import Path
            ffmpeg_winget = Path(FFMPEG_WIN_PATH)
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

async def download_github(url: str, session_dir: Path, progress_callback=None) -> Path:
    """
    Парсить посилання на GitHub та завантажує .zip архів репозиторію.
    Спочатку перевіряє гілку main, потім (якщо 404) перевіряє гілку master.
    """
    match = re.match(r'https?://github\.com/([^/]+)/([^/\?#]+)', url)
    if not match:
        raise ValueError("Невірний формат посилання на GitHub.")
    
    user, repo = match.groups()
    repo = repo.removesuffix('.git')
    
    main_url = f"https://github.com/{user}/{repo}/archive/refs/heads/main.zip"
    master_url = f"https://github.com/{user}/{repo}/archive/refs/heads/master.zip"
    
    async with aiohttp.ClientSession() as session:
        # Спочатку пробуємо гілку main
        async with session.get(main_url) as resp:
            if resp.status == 200:
                return await _download_file(resp, session_dir / f"{repo}_main.zip", progress_callback)
            
        # Якщо main не знайдено, пробуємо master
        async with session.get(master_url) as resp:
            if resp.status == 200:
                return await _download_file(resp, session_dir / f"{repo}_master.zip", progress_callback)
                
    raise Exception("Не вдалося знайти гілку main або master (отримано 404).")

async def _download_file(response, filepath: Path, progress_callback) -> Path:
    """
    Внутрішня функція для асинхронного завантаження файлу по шматках з трекінгом прогресу.
    """
    total_size = int(response.headers.get('content-length', 0))
    
    with open(filepath, 'wb') as f:
        downloaded = 0
        async for chunk in response.content.iter_chunked(8192):
            f.write(chunk)
            downloaded += len(chunk)
            if total_size > 0 and progress_callback:
                percent = downloaded / total_size * 100
                await progress_callback(percent)
                
    return filepath

def download_media_sync(url: str, format_spec: str, progress_callback, loop, session_dir: Path, tier: str) -> Path:
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
    import os
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
    else:
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
                ydl.extract_info(url, download=True)
                
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
                
                # Сортуємо файли за часом створення, щоб зберігався порядок плейлиста
                downloaded_files.sort(key=lambda x: x.stat().st_mtime)
                
                if len(downloaded_files) == 1:
                    return downloaded_files[0]
                return downloaded_files
                
        except Exception as e:
            if str(e) == 'SIZE_LIMIT_EXCEEDED':
                raise e
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
            url
        ]
        
        playlist_limit = TIER_LIMITS[tier]['playlist']
        if playlist_limit < 9999:
            cmd.extend(["--range", f"1-{playlist_limit}"])
        
        if Path('cookies.txt').exists():
            cmd.extend(["--cookies", "cookies.txt"])
            
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

async def download_threads_native(url: str, session_dir: Path, progress_callback=None) -> List[Path]:
    import requests
    import re
    import aiohttp
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Sec-Fetch-Mode": "navigate",
    }
    
    match = re.search(r'post/([^/?#]+)', url)
    if not match:
        raise ValueError("Не вдалося знайти ID посту в посиланні Threads.")
    shortcode = match.group(1)
    
    def fetch():
        r = requests.get(url.replace('threads.com', 'threads.net'), headers=headers)
        if r.status_code != 200:
            raise Exception("Threads сторінка не завантажилась.")
        return r.text
        
    if progress_callback:
        await progress_callback(10)
        
    text = await asyncio.to_thread(fetch)
    
    chunks = text.split('"code":"')
    media_urls = []
    
    for chunk in chunks[1:]:
        if chunk.startswith(shortcode + '"'):
            v_blocks = re.findall(r'"video_versions":\[(.*?)\]', chunk)
            for v in v_blocks:
                urls = re.findall(r'"url":"([^"]+)"', v)
                if urls:
                    media_urls.append(urls[0].replace('\\/', '/'))
                    
            i_blocks = re.findall(r'"image_versions2":\{"candidates":\[(.*?)\]\}', chunk)
            for i in i_blocks:
                urls = re.findall(r'"url":"([^"]+)"', i)
                if urls:
                    media_urls.append(urls[0].replace('\\/', '/'))
            break
            
    unique_urls = list(dict.fromkeys(media_urls))
    
    if not unique_urls:
        raise Exception("Не вдалося знайти медіа. Threads міг змінити формат сайту або пост не містить фото/відео.")
        
    if progress_callback:
        await progress_callback(30)
        
    downloaded = []
    
    async def download_file(m_url, index):
        m_url = m_url.encode('utf-8').decode('unicode_escape')
        ext = ".mp4" if "video" in m_url or ".mp4" in m_url else ".jpg"
        if ".webp" in m_url: ext = ".webp"
        
        filepath = session_dir / f"threads_{shortcode}_{index}{ext}"
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(m_url, headers={"User-Agent": headers["User-Agent"]}) as resp:
                    if resp.status == 200:
                        content = await resp.read()
                        with open(filepath, "wb") as f:
                            f.write(content)
                        downloaded.append(filepath)
        except Exception as e:
            print(f"Помилка завантаження файлу Threads: {e}")

    tasks = []
    for i, m_url in enumerate(unique_urls[:10]):
        tasks.append(download_file(m_url, i))
        
    await asyncio.gather(*tasks)
    
    if progress_callback:
        await progress_callback(100)
        
    if not downloaded:
        raise Exception("Не вдалося завантажити медіа з Threads.")
        
    downloaded.sort()
    return downloaded

async def download_media(url: str, format_spec: str = 'bestvideo+bestaudio/best', progress_callback=None, tier: str = 'free', session_dir: Path = None) -> Union[Path, List[Path]]:
    """
    Головна асинхронна функція для завантаження медіа.
    """
    loop = asyncio.get_running_loop()
    if session_dir is None:
        session_dir = Path(f"downloads/{time.time_ns()}")
        session_dir.mkdir(parents=True, exist_ok=True)
    
    # Перенаправляємо Instagram на gallery-dl
    if 'instagram.com' in url:
        return await download_with_gallery_dl(url, session_dir, progress_callback, tier)
        
    # Перенаправляємо Threads на кастомний парсер
    if 'threads.net' in url or 'threads.com' in url:
        return await download_threads_native(url, session_dir, progress_callback)
        
    # Перенаправляємо фотографії Facebook на gallery-dl (yt-dlp краще працює з відео)
    if 'facebook.com/photo' in url or 'facebook.com/media' in url:
        return await download_with_gallery_dl(url, session_dir, progress_callback, tier)

    if 'spotify.com' in url:
        return await download_with_spotdl(url, session_dir, progress_callback, tier)
        
    if 'github.com' in url:
        if tier == 'free':
            # We can't easily check github zip size before download, so we just allow it or reject big ones later.
            pass
        return await download_github(url, session_dir, progress_callback)

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
            tier
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
    import os
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
