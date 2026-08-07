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
    read -p "Введіть BOT_TOKEN: " bot_token
    read -p "Введіть BOT_USERNAME (без @, наприклад SaveMDLBot): " bot_username
    read -p "Введіть ваш API_ID (з my.telegram.org): " api_id
    read -p "Введіть ваш API_HASH (з my.telegram.org): " api_hash
    read -p "Введіть ваш Telegram ID (для прав адміна): " admin_ids
    read -p "Введіть URL вашого Mini App (наприклад, https://dmytrokurochkin.github.io): " cors_origins
    read -p "Ngrok authtoken (https://dashboard.ngrok.com/get-started/your-authtoken), або Enter щоб пропустити: " ngrok_authtoken
    ngrok_domain=""
    if [ -n "$ngrok_authtoken" ]; then
        read -p "Ваш зарезервований ngrok домен (напр. your-name.ngrok-free.dev), або Enter для випадкового: " ngrok_domain
    fi

    public_api_url="http://127.0.0.1:8080/api"
    if [ -n "$ngrok_domain" ]; then
        public_api_url="https://${ngrok_domain}/api"
    fi

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
    echo -e "${GREEN}Файл .env створено!${NC}"
else
    echo ".env файл вже існує. Використовую його."
    source .env
    api_id=$API_ID
    api_hash=$API_HASH

    # Довстановлюємо ngrok-змінні, якщо .env створений до появи цієї опції
    if [ -z "${NGROK_AUTHTOKEN+x}" ]; then
        read -p "Ngrok authtoken (https://dashboard.ngrok.com/get-started/your-authtoken), або Enter щоб пропустити: " ngrok_authtoken
        ngrok_domain=""
        if [ -n "$ngrok_authtoken" ]; then
            read -p "Ваш зарезервований ngrok домен (напр. your-name.ngrok-free.dev), або Enter для випадкового: " ngrok_domain
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
$SUDO apt-get install -y build-essential cmake gperf zlib1g-dev libssl-dev git python3 python3-pip python3-venv ffmpeg nodejs curl libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libffi-dev shared-mime-info

# The gdk-pixbuf runtime package was renamed (libgdk-pixbuf2.0-0 -> libgdk-pixbuf-2.0-0)
# on newer Debian/Ubuntu releases (e.g. Debian 13 "trixie"). Try both names separately
# so an unknown package name here can't abort the whole apt-get transaction under set -e.
$SUDO apt-get install -y libgdk-pixbuf-2.0-0 || $SUDO apt-get install -y libgdk-pixbuf2.0-0 || \
    echo -e "${BLUE}Warning: could not install a gdk-pixbuf package under either known name. PDF export (weasyprint) may not work.${NC}"

# 3. Завантаження та збірка Telegram Bot API (якщо не зібрано)
echo -e "\n${BLUE}[3/8] Налаштування Telegram Bot API Server...${NC}"
if [ ! -f "telegram-bot-api/build/telegram-bot-api" ]; then
    echo "Компіляція Telegram Bot API. Це може зайняти 5-15 хвилин..."
    if [ ! -d "telegram-bot-api" ]; then
        git clone --recursive https://github.com/tdlib/telegram-bot-api.git
    fi
    cd telegram-bot-api
    rm -rf build && mkdir build && cd build
    cmake -DCMAKE_BUILD_TYPE=Release ..
    make -j$(nproc)
    cd ../..
    echo -e "${GREEN}Telegram Bot API скомпільовано!${NC}"
else
    echo "Сервер вже скомпільовано, пропускаємо."
fi

# 4. Налаштування Python
echo -e "\n${BLUE}[4/8] Налаштування Python віртуального середовища...${NC}"
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
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
TG_API_BIN="${WORK_DIR}/telegram-bot-api/build/telegram-bot-api"

# Створення робочої папки для API сервера, якщо її немає
mkdir -p "${WORK_DIR}/tg-api-workdir"

# Сервіс сервера Telegram Bot API
cat > telegram-bot-api.service <<EOL
[Unit]
Description=Local Telegram Bot API Server
After=network.target

[Service]
Type=simple
User=${CURRENT_USER}
ExecStart=${TG_API_BIN} --local --api-id=${api_id} --api-hash=${api_hash} --dir=${WORK_DIR}/tg-api-workdir
Restart=always
RestartSec=5

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
WorkingDirectory=${WORK_DIR}
ExecStartPre=/bin/bash -c 'for i in \$(seq 1 30); do curl -sf http://127.0.0.1:8081 >/dev/null 2>&1 && break || sleep 2; done'
ExecStart=${WORK_DIR}/venv/bin/python3 main.py
Restart=always
RestartSec=10
Environment="PATH=${WORK_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

[Install]
WantedBy=multi-user.target
EOL

$SUDO mv telegram-bot-api.service /etc/systemd/system/
$SUDO mv tg-media-bot.service /etc/systemd/system/

# 7. Ngrok-тунель для публічного API (пошук/профілі в Mini App)
echo -e "\n${BLUE}[7/8] Налаштування ngrok...${NC}"
NGROK_ENABLED=0
if [ -n "$NGROK_AUTHTOKEN" ]; then
    if ! command -v ngrok >/dev/null 2>&1; then
        curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
            | $SUDO tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
        echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
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
    $SUDO mv ngrok.service /etc/systemd/system/
    NGROK_ENABLED=1
    echo -e "${GREEN}Ngrok налаштовано!${NC}"
else
    echo "Ngrok authtoken не вказано, пропускаю (публічний API для пошуку/профілів у Mini App буде недоступний ззовні)."
fi

$SUDO systemctl daemon-reload

# 8. Запуск і додавання в автозавантаження
echo -e "\n${BLUE}[8/8] Запуск сервісів та додавання в автозавантаження...${NC}"
$SUDO systemctl enable --now telegram-bot-api.service
$SUDO systemctl enable --now tg-media-bot.service
if [ "$NGROK_ENABLED" -eq 1 ]; then
    $SUDO systemctl enable --now ngrok.service
fi

echo -e "\n${GREEN}======================================================================${NC}"
echo -e "${GREEN}ГОТОВО! Ваш бот та локальний сервер успішно встановлені та запущені.${NC}"
echo -e "======================================================================"
echo -e "🔗 Локальний Telegram API сервер працює за адресою: http://127.0.0.1:8081"
echo -e "🔄 Бот підключено до локального сервера (через LOCAL_API_SERVER_URL у .env)."
echo -e "📦 Тепер ви можете надсилати та приймати файли розміром до 2 ГБ!"
echo -e ""
echo -e "📋 Перевірити статус API сервера: ${BLUE}sudo systemctl status telegram-bot-api${NC}"
echo -e "📋 Перевірити статус бота:        ${BLUE}sudo systemctl status tg-media-bot${NC}"
echo -e "📋 Подивитись логи бота:          ${BLUE}sudo journalctl -u tg-media-bot -f${NC}"
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
