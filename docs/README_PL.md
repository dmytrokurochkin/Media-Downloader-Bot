<div align="center">
  <h1>🚀 Media Downloader Bot</h1>
  <p>Wielofunkcyjny bot Telegram do pobierania treści multimedialnych z popularnych platform i sieci społecznościowych.</p>

  <p>
    <b>Język / Language / Мова:</b><br/>
    <a href="../README.md">🇬🇧 English</a> •
    <a href="README_UA.md">🇺🇦 Українська</a> •
    <a href="README_PL.md">🇵🇱 Polski</a>
  </p>
</div>

<p align="center">
  <a href="https://t.me/SaveMDLBot">
    <img src="https://img.shields.io/badge/Wypróbuj_Bota-@SaveMDLBot-0088cc?style=for-the-badge&logo=telegram&logoColor=white" alt="Test Bot" />
  </a>
</p>

## 📖 O projekcie

**Media Downloader Bot** to nowoczesny bot dla platformy Telegram stworzony w języku Python (Aiogram 3), który umożliwia użytkownikom wygodne pobieranie filmów, dźwięków i obrazów z platform takich jak YouTube, YouTube Music, SoundCloud, Spotify, TikTok, Instagram, Threads, Facebook oraz GitHub.

Projekt zawiera zintegrowaną aplikację **Telegram Mini App** (Web App) z nowoczesnym interfejsem użytkownika, gdzie można przeglądać statystyki, limity, tabele wyników oraz kupować dostęp VIP za pomocą wewnętrznej waluty **Telegram Stars**. W celu zapewnienia stabilnej obsługi dużych plików (do 2 GB) wykorzystywany jest lokalny serwer Telegram Bot API.

---

## ✨ Główne funkcje

- 🎬 **YouTube i YouTube Music**: Pobieranie wideo i audio w najwyższej dostępnej jakości (przy użyciu `yt-dlp`).
- 📸 **Instagram, Facebook i TikTok**: Zapisywanie filmów (Reels, TikTok), postów i albumów karuzelowych (przy użyciu `gallery-dl` oraz `yt-dlp`).
- 🧵 **Threads**: Natywna obsługa pobierania treści multimedialnych.
- 🎵 **Spotify**: Pobieranie pojedynczych utworów i playlist z zachowaniem metadanych oraz okładek (przy użyciu `spotdl`).
- 🎧 **SoundCloud**: Szybkie pobieranie ścieżek dźwiękowych i setów muzycznych w wysokiej jakości.
- 💻 **GitHub**: Szybkie pobieranie kodu źródłowego repozytoriów w formacie `.zip`.
- 📱 **Nowoczesna aplikacja Web App**: Zintegrowana Mini App zawierająca profil użytkownika, tabelę liderów oraz sklep VIP.
- 💎 **Monetyzacja**: Wbudowany system poziomów dostępu (Free, Pro, Max, VIP) i obsługa płatności przez Telegram Stars.
- 🚀 **Obsługa dużych plików**: Możliwość pobierania i wysyłania plików o rozmiarze do 2 GB dzięki lokalnemu serwerowi Telegram Bot API.

---

## 🖼️ Wersja demonstracyjna i zrzuty ekranu

| Menu główne i Mini App | Tabela liderów | Sklep VIP |
| :---: | :---: | :---: |
| <img src="assets/demo-webapp.jpg" width="250" /> | <img src="assets/demo-leaderboard.jpg" width="250" /> | <img src="assets/demo-store.jpg" width="250" /> |
| **Pobieranie z YouTube** | **Muzyka ze Spotify** | **Tryb gościa (Guest Mode)** |
| <img src="assets/demo-youtube.jpg" width="250" /> | <img src="assets/demo-spotify.jpg" width="250" /> | <img src="assets/demo-guest.jpg" width="250" /> |

---

## 📋 Wymagania systemowe

| Wymaganie | Wartość minimalna | Zalecane |
| :--- | :--- | :--- |
| **System operacyjny** | Ubuntu 20.04 / Debian 11 | Ubuntu 22.04+ / Debian 12 |
| **RAM** | 1 GB | 2 GB+ |
| **Miejsce na dysku** | 5 GB wolnej przestrzeni | 20 GB+ wolnej przestrzeni |
| **Python** | 3.10+ | 3.10+ |
| **Zależności systemowe** | Git, FFmpeg, Narzędzia kompilacji C++ | Git, FFmpeg, Narzędzia kompilacji C++ |

---

## 🛠 Stos technologiczny

- **Backend**: Python 3.10+, [Aiogram 3](https://docs.aiogram.dev/en/latest/)
- **Baza danych**: SQLite (przy użyciu `aiosqlite`)
- **Silniki pobierania**: `yt-dlp`, `gallery-dl`, `spotdl`
- **Przetwarzanie mediów**: `FFmpeg`, `mutagen`, `Pillow`
- **Frontend (Web App)**: HTML5, CSS3, Vanilla JS
- **Infrastruktura**: Lokalny [Telegram Bot API Server](https://github.com/tdlib/telegram-bot-api)

---

## ⚙️ Wdrożenie lokalne (Development)

### 1. Klonowanie repozytorium
```bash
git clone https://github.com/your-username/Media-Downloader-Bot.git
cd Media-Downloader-Bot
```

### 2. Konfiguracja środowiska
Utwórz plik `.env` w głównym katalogu projektu i uzupełnij go danymi:
```env
BOT_TOKEN=twój_token_bota
LOCAL_API_SERVER_URL=http://127.0.0.1:8081
API_ID=twój_api_id
API_HASH=twój_api_hash
ADMIN_IDS=twój_telegram_id
```

### 3. Instalacja zależności
Upewnij się, że w systemie zainstalowany jest program `ffmpeg`.
```bash
python -m venv venv
source venv/bin/activate  # W systemie Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Uruchomienie bota
```bash
python main.py
```

---

## 🚀 Wdrażanie na serwerze (Ubuntu/Debian)

1. Uzyskaj token bota w [@BotFather](https://t.me/BotFather) oraz swój ID w [@userinfobot](https://t.me/userinfobot) (dla `ADMIN_IDS`).
2. Uzyskaj `API_ID` oraz `API_HASH` na stronie [my.telegram.org](https://my.telegram.org).
3. Sklonuj repozytorium i uruchom skrypt automatycznej instalacji:
   ```bash
   git clone https://github.com/your-username/Media-Downloader-Bot.git
   cd Media-Downloader-Bot
   chmod +x auto_deploy.sh
   ./auto_deploy.sh
   ```
4. Umieść plik `cookies.txt` w głównym katalogu projektu do obsługi YouTube 18+, Instagrama oraz Facebooka.

📖 **Szczegółowa instrukcja instalacji:** Aby zapoznać się ze szczegółowym przewodnikiem dotyczącym pozyskiwania kluczy, konfiguracji usług systemd oraz rozwiązywania problemów, zobacz [Instrukcję instalacji po polsku (install_guide_pl.md)](install_guide_pl.md).

---

## ⚠️ Zastrzeżenie prawne (Disclaimer)

Ten projekt został stworzony **wyłącznie w celach edukacyjnych i badawczych**, jako demonstracja tworzenia botów, integracji API oraz przetwarzania plików multimedialnych.  
Autorzy i współtwórcy nie ponoszą żadnej odpowiedzialności za sposób wykorzystania tego oprogramowania przez użytkowników końcowych ani za jakiekolwiek naruszenia praw autorskich, przepisów prawa lub regulaminów (Terms of Service) serwisów zewnętrznych. Pobierając treści, masz obowiązek przestrzegać obowiązującego prawa i szanować prawa autorskie twórców.

---

## 🤝 Wkład w projekt
Wszelki wkład w rozwój projektu jest mile widziany. W przypadku wprowadzania dużych zmian prosimy o wcześniejsze utworzenie zgłoszenia (Issue) w celu przedyskutowania proponowanych poprawek.
