#!/bin/bash
set -e

# Кольори для виводу
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Автоматичне налаштування Telegram Media Downloader Bot (Debian/Ubuntu) ===${NC}"

# 1. Запит даних у користувача
echo -e "\n${BLUE}[1/8] Налаштування змінних оточення...${NC}"
if [ ! -f .env ]; then
    read -r -p "Введіть BOT_TOKEN: " bot_token
    read -r -p "Введіть BOT_USERNAME (без @, наприклад SaveMDLBot): " bot_username
    read -r -p "Введіть ваш API_ID (з my.telegram.org): " api_id
    read -r -p "Введіть ваш API_HASH (з my.telegram.org): " api_hash
    read -r -p "Введіть ваш Telegram ID (для прав адміна): " admin_ids
    read -r -p "Введіть URL вашого Mini App (наприклад, https://dmytrokurochkin.github.io): " cors_origins
    read -r -p "Повний URL сторінки Mini App (…/webapp/index.html), або Enter для стандартного: " webapp_url
    read -r -p "Ngrok authtoken (https://dashboard.ngrok.com/get-started/your-authtoken), або Enter щоб пропустити: " ngrok_authtoken
    ngrok_domain=""
    if [ -n "$ngrok_authtoken" ]; then
        read -r -p "Ваш зарезервований ngrok домен (напр. your-name.ngrok-free.dev), або Enter для випадкового: " ngrok_domain
    fi

    public_api_url="http://127.0.0.1:8080/api"
    if [ -n "$ngrok_domain" ]; then
        public_api_url="https://${ngrok_domain}/api"
    fi

    # umask 077 у підоболонці: .env з токенами одразу створюється з правами 600,
    # без вікна, коли його може прочитати будь-який локальний користувач.
    (
    umask 077
    cat > .env <<EOL
BOT_TOKEN=${bot_token}
BOT_USERNAME=${bot_username}
LOCAL_API_SERVER_URL=http://127.0.0.1:8081
API_ID=${api_id}
API_HASH=${api_hash}
ADMIN_IDS=${admin_ids}
ALLOWED_CORS_ORIGINS=${cors_origins}
PUBLIC_API_URL=${public_api_url}
NGROK_AUTHTOKEN=${ngrok_authtoken}
NGROK_DOMAIN=${ngrok_domain}
EOL
    if [ -n "$webapp_url" ]; then
        echo "WEBAPP_URL=${webapp_url}" >> .env
    fi
    )
    echo -e "${GREEN}Файл .env створено!${NC}"
else
    echo ".env файл вже існує. Використовую його."
    source .env
    api_id=$API_ID
    api_hash=$API_HASH

    # Довстановлюємо ngrok-змінні, якщо .env створений до появи цієї опції
    if [ -z "${NGROK_AUTHTOKEN+x}" ]; then
        read -r -p "Ngrok authtoken (https://dashboard.ngrok.com/get-started/your-authtoken), або Enter щоб пропустити: " ngrok_authtoken
        ngrok_domain=""
        if [ -n "$ngrok_authtoken" ]; then
            read -r -p "Ваш зарезервований ngrok домен (напр. your-name.ngrok-free.dev), або Enter для випадкового: " ngrok_domain
        fi
        {
            echo "NGROK_AUTHTOKEN=${ngrok_authtoken}"
            echo "NGROK_DOMAIN=${ngrok_domain}"
        } >> .env
        if ! grep -q '^PUBLIC_API_URL=' .env && [ -n "$ngrok_domain" ]; then
            echo "PUBLIC_API_URL=https://${ngrok_domain}/api" >> .env
        fi
        source .env
    fi
fi

# 2. Встановлення системних пакетів
echo -e "\n${BLUE}[2/8] Встановлення залежностей Debian/Ubuntu...${NC}"
SUDO=""
if [ "$EUID" -ne 0 ]; then
    SUDO="sudo"
fi
$SUDO apt-get update
$SUDO apt-get install -y build-essential cmake gperf zlib1g-dev libssl-dev git python3 python3-pip python3-venv ffmpeg curl unzip libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libffi-dev shared-mime-info

# The gdk-pixbuf runtime package was renamed (libgdk-pixbuf2.0-0 -> libgdk-pixbuf-2.0-0)
# on newer Debian/Ubuntu releases (e.g. Debian 13 "trixie"). Try both names separately
# so an unknown package name here can't abort the whole apt-get transaction under set -e.
$SUDO apt-get install -y libgdk-pixbuf-2.0-0 || $SUDO apt-get install -y libgdk-pixbuf2.0-0 || \
    echo -e "${BLUE}Warning: could not install a gdk-pixbuf package under either known name. PDF export (weasyprint) may not work.${NC}"

# JS-рантайм для yt-dlp. YouTube віддає формати лише після розв'язання JS-челенджу
# (пакет yt-dlp-ejs), і yt-dlp запускає його через Deno >= 2.3. Node з apt для цього
# не годиться: у Debian/Ubuntu він застарий, а yt-dlp без окремого прапорця його й не
# використовує. Без рантайму YouTube віддає лише частину форматів або нічого.
DENO_MIN="2.3"
install_deno() {
    local arch tmp
    case "$(uname -m)" in
        x86_64|amd64) arch="x86_64" ;;
        aarch64|arm64) arch="aarch64" ;;
        *) echo "Warning: немає збірки Deno для $(uname -m) — YouTube може не працювати."; return 1 ;;
    esac
    tmp=$(mktemp -d)
    curl -fsSL -o "$tmp/deno.zip" "https://github.com/denoland/deno/releases/latest/download/deno-${arch}-unknown-linux-gnu.zip" \
        && unzip -q -o "$tmp/deno.zip" -d "$tmp" \
        && $SUDO install -m 0755 "$tmp/deno" /usr/local/bin/deno
    local status=$?
    rm -rf "$tmp"
    return $status
}
current_deno=$(deno --version 2>/dev/null | head -n1 | awk '{print $2}')
if [ -z "$current_deno" ] || [ "$(printf '%s\n%s\n' "$DENO_MIN" "$current_deno" | sort -V | head -n1)" != "$DENO_MIN" ]; then
    echo "Встановлення Deno (JS-рантайм для YouTube у yt-dlp)..."
    install_deno || echo -e "${BLUE}Warning: Deno не встановлено — завантаження з YouTube може не працювати.${NC}"
else
    echo "Deno ${current_deno} вже встановлено."
fi

# 3. Завантаження та збірка Telegram Bot API (якщо не зібрано)
echo -e "\n${BLUE}[3/8] Налаштування Telegram Bot API Server...${NC}"
# Оновлення: UPDATE_BOT_API=1 ./auto_deploy.sh. Сервер, зібраний колись давно, відстає
# від Bot API, і нові методи (як-от гостьовий режим) просто не працюють.
if [ "${UPDATE_BOT_API:-0}" = "1" ] && [ -d "telegram-bot-api/.git" ]; then
    echo "Оновлення вихідного коду Telegram Bot API..."
    git -C telegram-bot-api pull --ff-only
    git -C telegram-bot-api submodule update --init --recursive
    rm -f telegram-bot-api/build/telegram-bot-api
fi
if [ ! -f "telegram-bot-api/build/telegram-bot-api" ]; then
    echo "Компіляція Telegram Bot API. Це може зайняти 5-15 хвилин..."
    if [ ! -d "telegram-bot-api" ]; then
        git clone --recursive https://github.com/tdlib/telegram-bot-api.git
    fi
    cd telegram-bot-api
    rm -rf build && mkdir build && cd build
    cmake -DCMAKE_BUILD_TYPE=Release ..
    make -j"$(nproc)"
    cd ../..
    echo -e "${GREEN}Telegram Bot API скомпільовано!${NC}"
else
    echo "Сервер вже скомпільовано, пропускаємо."
fi
# Бінарник ставимо в /usr/local/bin: сервіс Bot API працює з ProtectHome=yes і
# не бачить домашніх тек, тож запускати його з ${WORK_DIR} він не зміг би.
$SUDO install -m 0755 telegram-bot-api/build/telegram-bot-api /usr/local/bin/telegram-bot-api

# 4. Налаштування Python
echo -e "\n${BLUE}[4/8] Налаштування Python віртуального середовища...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
# Self-heal: install the latest yt-dlp into THIS venv.  On a long-running
# server this is the step that actually repairs a bot whose yt-dlp bit-rotted
# (the weekly timer keeps it fresh afterwards).  The updater exits non-zero
# when pip fails, so the warning below really fires instead of being dead.
./venv/bin/python -m core.yt_dlp_updater || echo "Warning: yt-dlp upgrade failed, keeping the current build (see output above)."
echo -e "${GREEN}Залежності Python встановлено!${NC}"

# 5. Інформація про cookies
echo -e "\n${BLUE}[5/8] Налаштування cookies для Instagram/Facebook/YouTube 18+...${NC}"
if [ ! -f "cookies.txt" ]; then
    echo -e "Для завантаження приватного контенту, Instagram, Facebook та YouTube 18+ потрібен файл cookies.txt."
    echo -e "Будь ласка, експортуйте cookies з вашого браузера (наприклад, через розширення Get cookies.txt)"
    echo -e "та збережіть їх у файл $(pwd)/cookies.txt після завершення встановлення."
else
    echo -e "${GREEN}Файл cookies.txt знайдено!${NC}"
fi

# 6. Створення systemd сервісів
echo -e "\n${BLUE}[6/8] Створення systemd сервісів для фонової роботи...${NC}"

WORK_DIR=$(pwd)
CURRENT_USER=$(whoami)
TG_API_BIN="/usr/local/bin/telegram-bot-api"

# Секрети бота не мають читатися іншими користувачами системи, зокрема tgbotapi нижче.
chmod 600 .env
for secret in cookies.txt database.db database.db-wal database.db-shm; do
    [ -f "$secret" ] && chmod 600 "$secret"
done

# Bot API — окремим системним користувачем без доступу до файлів бота.
# Чому: у режимі --local він уміє відправити БУДЬ-ЯКИЙ локальний файл (file:/...)
# на запит з будь-яким бот-токеном. Якщо до нього якось дістанеться чужий запит
# (SSRF через посилання або відкритий порт), читати він може лише власну теку,
# а не .env / cookies.txt / database.db.
if ! id -u tgbotapi >/dev/null 2>&1; then
    $SUDO useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin tgbotapi
fi
# API_ID/API_HASH — через EnvironmentFile, а не аргументами: аргументи видно в `ps` усім.
$SUDO install -d -o root -g tgbotapi -m 0750 /etc/telegram-bot-api
printf 'TELEGRAM_API_ID=%s\nTELEGRAM_API_HASH=%s\n' "$api_id" "$api_hash" | $SUDO tee /etc/telegram-bot-api/env >/dev/null
$SUDO chown root:tgbotapi /etc/telegram-bot-api/env
$SUDO chmod 0640 /etc/telegram-bot-api/env

# Сервіс сервера Telegram Bot API
# --http-ip-address=127.0.0.1: за замовчуванням сервер слухає 0.0.0.0, тобто весь інтернет.
# Дані (сесія бота, файли користувачів) — у /var/lib/telegram-bot-api (StateDirectory);
# бот читає звідти файли через групу tgbotapi (SupplementaryGroups у юніті бота).
cat > telegram-bot-api.service <<EOL
[Unit]
Description=Local Telegram Bot API Server
After=network.target

[Service]
Type=simple
User=tgbotapi
Group=tgbotapi
EnvironmentFile=/etc/telegram-bot-api/env
StateDirectory=telegram-bot-api
StateDirectoryMode=0750
UMask=0027
ExecStart=${TG_API_BIN} --local --http-ip-address=127.0.0.1 --http-port=8081 --dir=/var/lib/telegram-bot-api
Restart=always
RestartSec=5
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
LockPersonality=yes

[Install]
WantedBy=multi-user.target
EOL

# Сервіс самого бота
cat > tg-media-bot.service <<EOL
[Unit]
Description=Telegram Media Downloader Bot
After=network.target telegram-bot-api.service
Requires=telegram-bot-api.service

[Service]
Type=simple
User=${CURRENT_USER}
# Читати файли, які Bot API кладе в /var/lib/telegram-bot-api (local-режим віддає шляхи).
SupplementaryGroups=tgbotapi
# database.db, cookies та тимчасові файли створюються лише для власника.
UMask=0077
WorkingDirectory=${WORK_DIR}
ExecStartPre=/bin/bash -c 'for i in \$(seq 1 30); do curl -sf http://127.0.0.1:8081 >/dev/null 2>&1 && break || sleep 2; done'
ExecStart=${WORK_DIR}/venv/bin/python3 main.py
Restart=always
RestartSec=10
Environment="PATH=${WORK_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Бот обробляє чужі посилання і запускає ffmpeg/yt-dlp/gallery-dl над чужими файлами:
# якщо щось із цього зламають, процес не повинен отримати більше прав, ніж має.
# ProtectHome не вмикаємо: venv, кеш spotdl/Deno та сам бот живуть у домашній теці.
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=full
ProtectKernelTunables=yes
ProtectKernelModules=yes
ProtectControlGroups=yes
RestrictSUIDSGID=yes
RestrictRealtime=yes
LockPersonality=yes

[Install]
WantedBy=multi-user.target
EOL

# install, а не mv: mv зберіг би власника — звичайного користувача, — і той міг би
# переписати юніт (скажімо, User=root) і отримати root при наступному рестарті.
$SUDO install -o root -g root -m 0644 telegram-bot-api.service tg-media-bot.service /etc/systemd/system/
rm -f telegram-bot-api.service tg-media-bot.service

# 7. Ngrok-тунель для публічного API (пошук/профілі в Mini App)
echo -e "\n${BLUE}[7/8] Налаштування ngrok...${NC}"
NGROK_ENABLED=0
if [ -n "$NGROK_AUTHTOKEN" ]; then
    if ! command -v ngrok >/dev/null 2>&1; then
        curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
            | $SUDO tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
        echo "deb https://ngrok-agent.s3.amazonaws.com bookworm main" \
            | $SUDO tee /etc/apt/sources.list.d/ngrok.list >/dev/null
        $SUDO apt-get update
        $SUDO apt-get install -y ngrok
    fi

    ngrok config add-authtoken "$NGROK_AUTHTOKEN"

    NGROK_DOMAIN_FLAG=""
    if [ -n "$NGROK_DOMAIN" ]; then
        NGROK_DOMAIN_FLAG="--domain=${NGROK_DOMAIN}"
    else
        echo -e "${BLUE}Увага: без зарезервованого домену ngrok видаватиме новий випадковий URL при кожному перезапуску.${NC}"
        echo -e "${BLUE}Тоді PUBLIC_API_URL у .env доведеться оновлювати вручну після кожного рестарту ngrok.service.${NC}"
    fi

    cat > ngrok.service <<EOL
[Unit]
Description=Ngrok tunnel for Media Downloader Bot API
After=network.target tg-media-bot.service

[Service]
Type=simple
User=${CURRENT_USER}
ExecStart=$(command -v ngrok) http 8080 ${NGROK_DOMAIN_FLAG} --log=stdout
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOL
    $SUDO install -o root -g root -m 0644 ngrok.service /etc/systemd/system/
    rm -f ngrok.service
    NGROK_ENABLED=1
    echo -e "${GREEN}Ngrok налаштовано!${NC}"
else
    echo "Ngrok authtoken не вказано, пропускаю (публічний API для пошуку/профілів у Mini App буде недоступний ззовні)."
fi

$SUDO systemctl daemon-reload

# Тижневий апдейтер yt-dlp
# Keeps YouTube/YouTubeMusic working while the bot stays up for months between
# restarts.  Upgrading the venv on disk does nothing for an already-running
# process, so the unit restarts the bot whenever the version actually changes.
cat > yt-dlp-updater.service <<EOL
[Unit]
Description=Upgrade yt-dlp to the latest release
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=${CURRENT_USER}
WorkingDirectory=${WORK_DIR}
ExecStart=${WORK_DIR}/venv/bin/python -m core.yt_dlp_updater --restart
TimeoutStartSec=600
EOL

cat > yt-dlp-updater.timer <<EOL
[Unit]
Description=Weekly yt-dlp upgrade for Media Downloader Bot

[Timer]
OnCalendar=Mon *-*-* 03:00
RandomizedDelaySec=1h
Persistent=true
Unit=yt-dlp-updater.service

[Install]
WantedBy=timers.target
EOL

# Щоденна резервна копія бази (журнал платежів, VIP-статуси). Копії — у ${WORK_DIR}/backups,
# лишаються 14 найновіших. Від втрати диска це не рятує: їх варто копіювати й за межі сервера.
cat > tg-media-bot-backup.service <<EOL
[Unit]
Description=Back up the Media Downloader Bot database

[Service]
Type=oneshot
User=${CURRENT_USER}
UMask=0077
WorkingDirectory=${WORK_DIR}
ExecStart=${WORK_DIR}/venv/bin/python -m core.backup --keep 14
EOL

cat > tg-media-bot-backup.timer <<EOL
[Unit]
Description=Daily database backup for Media Downloader Bot

[Timer]
OnCalendar=*-*-* 04:30
RandomizedDelaySec=30m
Persistent=true
Unit=tg-media-bot-backup.service

[Install]
WantedBy=timers.target
EOL

# install, not mv: mv would preserve the deploying user's ownership, leaving a
# root-run unit file writable by a non-root account.
$SUDO install -o root -g root -m 0644 yt-dlp-updater.service yt-dlp-updater.timer tg-media-bot-backup.service tg-media-bot-backup.timer /etc/systemd/system/
rm -f yt-dlp-updater.service yt-dlp-updater.timer tg-media-bot-backup.service tg-media-bot-backup.timer

# The updater runs as ${CURRENT_USER}, which cannot restart a system unit on
# its own -- a bare systemctl restart there hangs on polkit or is denied, so
# the upgraded build would never be loaded.  Validate with visudo before
# installing: a malformed drop-in breaks sudo entirely.
SYSTEMCTL_BIN=$(command -v systemctl)
cat > yt-dlp-updater.sudoers <<EOL
${CURRENT_USER} ALL=(root) NOPASSWD: ${SYSTEMCTL_BIN} restart tg-media-bot.service
EOL
if $SUDO visudo -cqf yt-dlp-updater.sudoers; then
    $SUDO install -o root -g root -m 0440 yt-dlp-updater.sudoers /etc/sudoers.d/yt-dlp-updater
else
    echo "Warning: sudoers drop-in rejected by visudo; the weekly job will upgrade yt-dlp but cannot restart the bot."
fi
rm -f yt-dlp-updater.sudoers

$SUDO systemctl daemon-reload

# 8. Запуск і додавання в автозавантаження
echo -e "\n${BLUE}[8/8] Запуск сервісів та додавання в автозавантаження...${NC}"
$SUDO systemctl enable telegram-bot-api.service tg-media-bot.service
# restart, а не enable --now: повторний запуск скрипта (новий код, новий бінарник
# Bot API чи змінені юніти) інакше не застосувався б до вже запущених сервісів.
$SUDO systemctl restart telegram-bot-api.service
$SUDO systemctl restart tg-media-bot.service
# --now: without it the timer stays inactive until the next reboot.
$SUDO systemctl enable --now yt-dlp-updater.timer
$SUDO systemctl enable --now tg-media-bot-backup.timer
if [ "$NGROK_ENABLED" -eq 1 ]; then
    $SUDO systemctl enable ngrok.service
    $SUDO systemctl restart ngrok.service
fi

echo -e "\n${GREEN}======================================================================${NC}"
echo -e "${GREEN}ГОТОВО! Ваш бот та локальний сервер успішно встановлені та запущені.${NC}"
echo -e "======================================================================"
echo -e "🔗 Локальний Telegram API сервер працює за адресою: http://127.0.0.1:8081 (лише localhost, користувач tgbotapi)"
if [ -d "${WORK_DIR}/tg-api-workdir" ]; then
    echo -e "🧹 Стара тека ${WORK_DIR}/tg-api-workdir більше не використовується (дані тепер у /var/lib/telegram-bot-api) — її можна видалити."
fi
echo -e "🔄 Бот підключено до локального сервера (через LOCAL_API_SERVER_URL у .env)."
echo -e "📦 Тепер ви можете надсилати та приймати файли розміром до 2 ГБ!"
echo -e ""
echo -e "📋 Перевірити статус API сервера: ${BLUE}sudo systemctl status telegram-bot-api${NC}"
echo -e "📋 Перевірити статус бота:        ${BLUE}sudo systemctl status tg-media-bot${NC}"
echo -e "📋 Подивитись логи бота:          ${BLUE}sudo journalctl -u tg-media-bot -f${NC}"
echo -e "💾 Резервні копії бази:           ${WORK_DIR}/backups (щодня, 14 останніх; вручну: ${BLUE}./venv/bin/python -m core.backup${NC})"
echo -e "🔄 Оновити Telegram Bot API:      ${BLUE}UPDATE_BOT_API=1 ./auto_deploy.sh${NC}"
if [ "$NGROK_ENABLED" -eq 1 ]; then
    echo -e "🌐 Ngrok тунель запущено (публічний API для Mini App): PUBLIC_API_URL=${PUBLIC_API_URL}"
    echo -e "📋 Перевірити статус ngrok:       ${BLUE}sudo systemctl status ngrok${NC}"
    if [ -z "$NGROK_DOMAIN" ]; then
        echo -e "⚠️  У вас немає зарезервованого домену - перевірте актуальний URL: ${BLUE}curl -s http://127.0.0.1:4040/api/tunnels${NC}"
        echo -e "   і за потреби оновіть PUBLIC_API_URL у .env, після чого перезапустіть бота: ${BLUE}sudo systemctl restart tg-media-bot${NC}"
    fi
else
    echo -e "ℹ️  Ngrok не налаштовано - пошук користувачів і публічні профілі в Mini App працювати не будуть."
fi
