# 🚀 Media Downloader Telegram Bot

Потужний асинхронний Telegram-бот на базі `aiogram 3.x`, створений для швидкого та зручного завантаження медіаконтенту з популярних платформ. Бот здатний завантажувати файли великого розміру (до 2 ГБ) завдяки інтеграції з власним локальним сервером Telegram Bot API.

## ✨ Основні можливості

- **YouTube**: Завантаження відео з вибором бажаної якості (1080p, 720p, 360p, максимальна) або конвертація у аудіоформат.
- **YouTube Music, SoundCloud, Spotify**: Пряме завантаження музичних треків, альбомів та плейлистів у найкращій доступній якості.
- **Instagram, Threads, Facebook**: Завантаження фото, відео та мультимедійних постів (каруселей/альбомів).
- **GitHub**: Швидке завантаження `.zip` архіву репозиторію за прямим посиланням.

### 🛠 Технологічний стек
- **Python 3** (`aiogram` 3.x, `aiohttp`)
- **yt-dlp** (YouTube, SoundCloud, загальне медіа)
- **gallery-dl** (Instagram, Facebook, Threads)
- **spotdl** (Spotify)
- **FFmpeg** (Злиття відео та аудіо, конвертація форматів)

---

## ⚙️ Вимоги до сервера (Деплой)

Бот розроблений з акцентом на розгортання на headless Debian/Ubuntu серверах.

Для завантаження великих файлів (понад 50 МБ) обов'язковим є використання **Local Telegram Bot API Server**.

## 🚀 Швидке розгортання (Debian/Ubuntu)

У проєкті передбачений зручний скрипт для автоматичного налаштування сервера, компіляції локального API-сервера та створення systemd-сервісів.

1. Склонуйте репозиторій:
   ```bash
   git clone https://github.com/dmytrokurochkin/Media-Downloader-Bot.git
   cd Media-Downloader-Bot
   ```

2. Запустіть скрипт автоматичного розгортання:
   ```bash
   sudo bash auto_deploy.sh
   ```

3. Під час встановлення скрипт попросить вас ввести:
   - `BOT_TOKEN` (отримати у [@BotFather](https://t.me/BotFather))
   - `API_ID` та `API_HASH` (отримати на [my.telegram.org](https://my.telegram.org))

### 🍪 Налаштування cookies.txt (Для 18+ контенту та приватних профілів)

Для того, щоб бот міг завантажувати контент з Instagram, Facebook та відео з віковими обмеженнями на YouTube, необхідний файл `cookies.txt`.
1. Встановіть у своєму браузері розширення (наприклад, [Get cookies.txt LOCALLY](https://chromewebstore.google.com/detail/get-cookiestxt-locally/cclelndahbckbenkjhflpdbgdldlbecc)).
2. Авторизуйтесь в Instagram, YouTube та Facebook у вашому браузері.
3. Експортуйте cookies у форматі **Netscape** і збережіть файл як `cookies.txt` у кореневій папці бота.
4. Перезапустіть бота:
   ```bash
   sudo systemctl restart tg-media-bot
   ```

---

## 💻 Локальний запуск (Без скрипта розгортання)

1. Переконайтесь, що у вас встановлено **Python 3.10+** та **FFmpeg**.
2. Встановіть залежності:
   ```bash
   pip install -r requirements.txt
   ```
3. Створіть файл `.env` на основі `.env.example`:
   ```env
   BOT_TOKEN=your_bot_token_here
   LOCAL_API_SERVER_URL=http://127.0.0.1:8081
   API_ID=your_api_id_here
   API_HASH=your_api_hash_here
   ```
4. [Запустіть локальний API сервер Telegram](https://github.com/tdlib/telegram-bot-api) (якщо потрібно зняти ліміт у 50 МБ).
5. Запустіть бота:
   ```bash
   python main.py
   ```