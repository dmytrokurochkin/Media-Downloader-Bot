# CLAUDE.md — гід по проєкту Media Downloader Bot

Довідник по репозиторію: **що це за проєкт**, **як він влаштований** і **які тут пастки**.
Читати перед будь-якими змінами; оновлювати разом із кодом.

Мова проєкту — **українська**: нові коментарі в коді, тексти комітів (тіло), цей файл.
Тексти для користувачів — лише через `locales.py` (uk/en/pl) і `webapp/locales.js`, ніколи не
хардкодом у хендлерах. Старі англомовні коментарі не переписуємо, але нові пишемо українською.

---

## 1. Що це за проєкт

**Media Downloader Bot** — Telegram-бот, що завантажує відео, аудіо й фото з YouTube, YouTube
Music, Spotify, SoundCloud, TikTok, Instagram, Threads, Facebook і GitHub. Працює в особистих
чатах, у групах і в гостьовому режимі (Bot API 10.0: бота кличуть у чаті, де його немає).
Є Mini App (статичні файли з `webapp/` на GitHub Pages) з профілем, лідербордами, налаштуваннями,
Smart Trim, редактором тегів і магазином тем. Тарифи Free / Pro / Max оплачуються Telegram Stars.

**Статус:** production (живий бот [@SaveMDLBot](https://t.me/SaveMDLBot)).

**Автор:** dmytrokurochkin · **Репозиторій:** https://github.com/dmytrokurochkin/Media-Downloader-Bot

### Стек

| Компонент | Що використовується |
|---|---|
| Мова | Python 3.11+ (spotdl 4.6 нижче не ставиться) |
| Telegram-фреймворк | `aiogram` 3.29.1 (Bot API 10.0), long polling |
| Bot API | локальний `telegram-bot-api --local` (файли до 2000 МБ) |
| Завантаження | `yt-dlp[default]` + Deno (JS-челенджі YouTube), `gallery-dl`, `spotdl` |
| Медіа | `ffmpeg`, `mutagen`, `Pillow`, `weasyprint` (PDF статей), `readability-lxml` |
| БД | SQLite через `aiosqlite`, WAL; один файл `database.db` |
| Внутрішній API | `aiohttp` + `aiohttp_cors` (пошук і профілі для Mini App) |
| Mini App | HTML/CSS/vanilla JS, GitHub Pages |
| Тести | `pytest` + `pytest-asyncio`, `ruff` |

---

## 2. Структура репозиторію

```
main.py                  # точка входу: БД, роутери, middleware, API-сервер, фонові задачі, polling
database.py              # усі SQL-запити (aiosqlite), міграції колонок, кеші реклами й лідербордів
downloader.py            # бекенди завантаження: yt-dlp, gallery-dl, spotdl, Threads, GitHub
locales.py               # LOCALES[uk|en|pl] + get_text(lang, key, **kwargs)
core/
  config.py              # .env → константи, тарифи (TIER_LIMITS, VIP_TARIFFS, THEME_PRICES)
  loader.py              # bot (локальний Bot API, parse_mode=HTML) і dp
  net_guard.py           # захист від SSRF: ensure_public_url, safe_get, safe_download
  utils.py               # spawn, schedule_delete, extract_url, host_matches, run_command, …
  error_handler.py       # єдина обробка помилок завантаження + звіт у канал помилок
  webapp.py              # URL Mini App з усіма даними в query-параметрах, merge_top_domains
  webapp_data.py         # pydantic-схеми для web_app_data (sendData з Mini App)
  api.py                 # /api/search_users, /api/get_profile (авторизація initData)
  telegram_auth.py       # перевірка підпису initData (HMAC)
  pdf_generator.py       # стаття → PDF (weasyprint з фетчером лише публічних адрес)
  media_processor.py     # вотермарка для Max (одноразово «озброюється» кнопкою)
  watermark.py           # ffmpeg/Pillow-накладання логотипу
  audio_tags.py          # ID3-теги й обкладинка (редактор тегів)
  badges.py              # бейджі за кількість/обсяг завантажень
  scheduler.py           # щоденно: retention-подарунок Pro, стирання старих URL
  backup.py              # python -m core.backup — копія БД (systemd-таймер)
  yt_dlp_updater.py      # python -m core.yt_dlp_updater — оновлення yt-dlp (тижневий таймер)
handlers/
  user.py                # /start, онбординг, профіль, налаштування, підтримка, /top, web_app_data
  admin.py               # адмін-панель: розсилка, VIP, бани, реклама, /refund
  payment.py             # VIP і теми за Stars, pre_checkout, successful_payment, /paysupport
  media.py               # посилання → завантаження → відправка; гостьовий режим; PDF; Smart Trim
keyboards/               # inline.py, reply.py — фабрики get_*_keyboard()
middlewares/             # throttling.py (1 апдейт/с), ban.py (бан + створення користувача)
webapp/                  # Mini App: index.html, app.js, locales.js, style.css
tests/                   # pytest; conftest.py дає кожному тесту окрему тимчасову БД
auto_deploy.sh           # розгортання на Debian/Ubuntu: збірка Bot API, systemd-юніти, таймери
```

---

## 3. Конфігурація (`.env`)

Повний перелік із коментарями — `.env.example`.

| Змінна | Обов'язкова? | Призначення |
|---|---|---|
| `BOT_TOKEN` | так | токен від @BotFather; без нього падає навіть імпорт хендлерів |
| `BOT_USERNAME` | так | юзернейм без `@` (підписи, посилання «запустіть бота») |
| `LOCAL_API_SERVER_URL` | так | локальний Bot API, `http://127.0.0.1:8081` |
| `API_ID`, `API_HASH` | так (сервер) | для запуску `telegram-bot-api`, з my.telegram.org |
| `ADMIN_IDS` | так | Telegram ID адмінів через кому |
| `ERROR_LOG_CHANNEL_ID` | ні | канал для звітів про критичні помилки завантаження |
| `ALLOWED_CORS_ORIGINS` | ні | origin-и Mini App для CORS внутрішнього API |
| `WEBAPP_URL` | ні | повна адреса `webapp/index.html` (форк — свою) |
| `API_HOST`, `API_PORT` | ні | де слухає внутрішній API (за замовч. `127.0.0.1:8080`) |
| `PUBLIC_API_URL` | ні | публічна HTTPS-адреса API для Mini App (ngrok) |
| `NGROK_AUTHTOKEN`, `NGROK_DOMAIN` | ні | тунель для `PUBLIC_API_URL` (налаштовує auto_deploy.sh) |
| `STORAGE_CHAT_ID` | ні | канал-сховище для `file_id` у гостьовому режимі |
| `YTDLP_COOKIES_FROM_BROWSER` | ні | cookies з браузера для локальної розробки (на сервері — `cookies.txt`) |
| `FFMPEG_PATH` | ні | шлях до ffmpeg, якщо його немає в PATH (Windows) |

---

## 4. Архітектура — карта модулів

| Модуль | Відповідальність | Ключове |
|---|---|---|
| `handlers/media.py` | вхід посилань і весь цикл завантаження | `get_download_block_reason`, `process_url`, `start_download`, `dispatch_telegram_media`, `process_smart_trim`, `guest_text_handler` |
| `downloader.py` | вибір бекенда за хостом і саме завантаження | `download_media`, `download_media_sync` (yt-dlp у потоці), `enforce_size_limit`, `collect_media_files` |
| `core/net_guard.py` | будь-який HTTP-запит до адреси від користувача | `ensure_public_url`, `safe_get`, `safe_download`, `PublicOnlyResolver` |
| `core/error_handler.py` | що показати користувачу і чи слати звіт | `classify_media_error`, `handle_media_error` |
| `handlers/payment.py` + `database.py` | гроші | `validate_purchase`, `apply_vip_purchase`, `apply_theme_purchase`, `refund_payment` |
| `handlers/user.py` | меню, профіль, підтримка, дані з Mini App | `web_app_data_handler`, `process_support_message`, `support_ban_text` |
| `handlers/admin.py` | адмін-панель | `run_broadcast`, `parse_id_and_days`, `NOT_ADMIN_BUTTON` |
| `middlewares/ban.py` | створює користувача (мова з клієнта), оновлює активність, блокує забанених | `BanCheckMiddleware` |
| `core/webapp.py` | URL Mini App (дані вшиті в query, бекенд не потрібен) | `generate_webapp_url`, `merge_top_domains` |
| `core/utils.py` | спільні дрібниці | `spawn`, `schedule_delete`, `extract_url`, `host_matches`, `run_command`, `get_event_user` |

---

## 5. Як це працює — потік обробки

### Порядок роутерів і middleware — критично

`main.py` підключає роутери так: `user` → `admin` → `payment` → `media`. Причина:
`media_router` закінчується «всеїдним» `@media_router.message(F.text)` (`text_handler`), який
ловить будь-який текст із посиланням. Якщо поставити його раніше, кнопки меню, адмінки й оплати
перестануть працювати. Нові хендлери тексту — лише в роутери перед `media`, а всередині
`media.py` — вище за `text_handler`.

Outer-middleware: спершу `ThrottlingMiddleware` (1 апдейт/с на користувача), потім
`BanCheckMiddleware` — для `message`, `callback_query`, `inline_query` **і окремо
`guest_message`** (це окремий тип апдейту; без явної реєстрації бан і троттлінг на гостьовий
режим не діють). `guest_message` додається в `allowed_updates` вручну.

### Посилання → файл

1. `text_handler` / `guest_text_handler` / `youtube_callback` / Smart Trim з Mini App дістають URL
   (`extract_url`) і йдуть у `process_url` → `start_download`.
2. `start_download` — **єдиний допуск**: `get_download_block_reason` (заборонені посилання,
   DRM-сервіси, денний ліміт), cooldown «одне завантаження на користувача», семафор
   `MAX_CONCURRENT_DOWNLOADS` з чергою. Відмова гостьовому запиту закривається відповіддю.
3. `download_media` спершу викликає `ensure_public_url`, потім бекенд за хостом
   (`host_matches`, не підрядок): spotdl, gallery-dl, Threads, GitHub (HEAD.zip) або yt-dlp.
   Розмір перевіряється по реальних файлах (`enforce_size_limit`), є таймаути й скасування.
4. Обробка: теги (`audio_tags`), вотермарка (`media_processor`).
5. `dispatch_telegram_media`: один файл — `send_media_file`, кілька — альбоми по 10; у гостьовому
   режимі — `_deliver_guest` (файл у канал-сховище або в ЛС → `answer_guest_query` з `file_id`).
6. Успіх рахується **лише після** реальної відправки (`_record_download_stats`, бейджі).
   Тимчасова тека сесії видаляється завжди (`temporary_download_session`).

### Оплата

`send_invoice` (Stars, `XTR`) → `pre_checkout_handler` (`validate_purchase`: payload, ціна,
валюта, бан, тема вже куплена) → `successful_payment_handler` (`apply_*_purchase` — запис у
`payments` і видача в одній транзакції). `/refund <charge_id>` (адмін): спершу
`refundStarPayment`, потім відкат у БД. `/paysupport` — обов'язкова за правилами Stars.

### Фонові задачі

`core/scheduler.py` (раз на добу): стирає URL завантажень старших за 30 днів і дарує 3 дні Pro
неактивним Free-користувачам. systemd-таймери з `auto_deploy.sh`: оновлення yt-dlp (щотижня,
з рестартом бота) і копія БД у `backups/` (щодня, 14 копій).

---

## 6. Пастки, про які треба знати наперед

**`guest_message.from_user` — це САМ БОТ.** Справжній відправник — `guest_bot_caller_user`.
Скрізь бери користувача через `core.utils.get_event_user`. Відповісти можна лише
`answer_guest_query` і рівно один раз; альбом у гостьовому режимі неможливий.

**Локальний Bot API у режимі `--local` віддає БУДЬ-ЯКИЙ локальний файл** (`file:/…`) на запит із
будь-яким токеном і за замовчуванням слухає `0.0.0.0`. Тому в `auto_deploy.sh` він працює від
користувача `tgbotapi`, слухає лише `127.0.0.1`, а дані тримає в `/var/lib/telegram-bot-api`.
Бот читає звідти файли через групу `tgbotapi`. Не відкривай порт 8081 і не запускай Bot API від
користувача бота.

**SSRF.** Кожен URL від користувача — через `core/net_guard.py`: `ensure_public_url` до
завантаження, `safe_get`/`safe_download` для власних запитів (перевірка кожного редиректу,
`PublicOnlyResolver` проти DNS rebinding; aiohttp не викликає резолвер для IP-літералів, тому
URL перевіряється окремо). Залишковий ризик: yt-dlp, gallery-dl і spotdl ходять за редиректами
самі, а фетчер weasyprint має вікно між перевіркою DNS і з'єднанням — від цього рятує лише
ізоляція Bot API вище.

**Усе, що прийшло від користувача, — в `html.escape`.** `parse_mode=HTML` стоїть за
замовчуванням (`core/loader.py`). Ім'я, назва відео, URL, текст помилки чи реклама з `<` або
`&` ламали відправку цілого повідомлення («can't parse entities»). Рекламу перевіряємо тестовою
відправкою, а підпис до медіа — `send_with_caption_fallback` (повтор без реклами).

**`successful_payment` може прийти двічі.** Захист — `payments.charge_id UNIQUE` і запис разом
із видачею в одній транзакції `BEGIN IMMEDIATE` на окремому з'єднанні (`_open_write_transaction`).
Не виноси перевірку в окремий `SELECT` перед вставкою — між ними `await`, і race повернеться.
Троттлінг і бан пропускають `successful_payment`: гроші вже списані, покупку треба видати.

**`sendData` з Mini App працює лише з reply-клавіатури.** Mini App, відкрита з inline-кнопки
чи menu button, `tg.sendData()` не має — тому `/start` скидає menu button на дефолтну, а
онбординг дає reply-клавіатуру. Дані з `web_app_data` можна підробити (інспектор WebView), тож
вони проходять строгу схему `core/webapp_data.py`, а тариф/ліміти перевіряються на сервері.

**Mini App отримує дані в URL — вони під контролем користувача.** Лише `textContent`, ніколи
`innerHTML`; є CSP в `index.html`. `initData` для API йде заголовком `Authorization: tma …`,
а не в query (query потрапляє в логи).

**yt-dlp з `ignoreerrors` ковтає помилки** — справжню причину збирає `_YtdlpLogger`.
YouTube без JS-рантайму (Deno ≥ 2.3) і `yt-dlp-ejs` (екстра `[default]`) віддає не всі формати.
spotdl 4.6 пінить `yt-dlp<2027`; апдейтер свідомо ставить найновіший yt-dlp (для YouTube свіжість
важливіша), тож після року-переходу перевір, чи працює Spotify.

**Зовнішні процеси — лише через `run_command`** (власна група процесів, `killpg` за таймаутом)
або з `cancel_event` для yt-dlp у потоці. Голий `subprocess` без таймауту колись вішав слот
завантаження назавжди.

**Дати в БД у двох форматах:** `YYYY-MM-DD HH:MM:SS` (`CURRENT_TIMESTAMP`) і ISO з `T` та зсувом
(Python). У SQL порівнюй через `datetime(...)`, у Python — `parse_db_date` (повертає `None` на
сміття, перевіряй). Денна квота скидається о 00:00 **UTC**.

**Фонові задачі — через `core.utils.spawn`, не `asyncio.create_task`:** event loop тримає лише
слабке посилання, і задачу без власника може прибрати збирач сміття.

**Адмін-хендлери станів стоять раніше за хендлери кнопок**, тому мають фільтр
`NOT_ADMIN_BUTTON`: інакше натискання іншої кнопки посеред введення ставало, наприклад, текстом
розсилки для всіх.

**FSM у `MemoryStorage`** — незавершені діалоги (підтримка, обкладинка, PDF) губляться при
рестарті. Це прийнятно; не покладайся на стан між рестартами.

**Callback до повідомлення, старшого за 48 год, приходить з `InaccessibleMessage`** без `text` —
перевіряй перед `callback.message.text`.

**`bot.me()` замість `bot.get_me()`:** перший кешується, другий — мережевий запит на кожне
повідомлення.

---

## 7. Правила для агента

- **Мова:** відповідай користувачу українською, стисло. Нові коментарі — українською і про
  «чому», а не «що».
- **Тексти для користувача** — новий ключ у `locales.py` **в усіх трьох мовах** (і в
  `webapp/locales.js`, якщо це Mini App). Паритет Python-локалей перевіряє `tests/test_locales.py`.
- **Модульність:** нова логіка — у відповідний модуль (див. §2/§4), не в `main.py`. Будь-який
  HTTP-запит до адреси від користувача — лише через `core/net_guard.py`.
- **Перевірка aiogram API:** дивись вихідний код встановленого `aiogram` 3.29.1 у venv
  (`grep` по `site-packages/aiogram`), а не пам'ять — гостьовий режим і Stars змінювались.
- **Тести разом зі змінами.** Запуск: `python -m pytest -q` і `ruff check .`
  (`requirements-dev.txt`). Токен-заглушку `tests/conftest.py` ставить сам: `core/loader.py`
  створює `Bot` уже при імпорті, а справжній токен з `.env` тестам не потрібен.
  Логіку оплат, лімітів, банів і маршрутизації посилань міняй лише разом із тестом.
- **Не запускай `python main.py` з реальним токеном** і нічого не роби на сервері без прямого
  прохання: це живий бот із платежами.
- **Секрети:** `.env`, `cookies.txt`, `database.db`, `backups/` — ніколи не виводь і не коміть.
- **Коміти:** Conventional Commits (`fix:`, `feat:`, `docs:`…), заголовок англійською в наказовому
  способі, тіло можна українською. Без трейлерів `Co-authored-by` і згадок інструментів, якими
  писався код. Після зміни поведінки — онови цей файл (особливо §6).
