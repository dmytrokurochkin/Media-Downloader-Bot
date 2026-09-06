<p align="center">
  <b>🇬🇧 English</b> | <a href="README.uk.md">🇺🇦 Українська</a> | <a href="README.pl.md">🇵🇱 Polski</a>
</p>

<div align="center">
  <h1>🚀 Media Downloader Bot</h1>
  <p>A full-featured Telegram bot for downloading media content from popular platforms and social networks.</p>
</div>

<p align="center">
  <a href="https://github.com/dmytrokurochkin/Media-Downloader-Bot/actions/workflows/tests.yml">
    <img src="https://github.com/dmytrokurochkin/Media-Downloader-Bot/actions/workflows/tests.yml/badge.svg" alt="Tests" />
  </a>
</p>

<p align="center">
  <a href="https://t.me/SaveMDLBot">
    <img src="https://img.shields.io/badge/Try_the_Bot-@SaveMDLBot-0088cc?style=for-the-badge&logo=telegram&logoColor=white" alt="Test Bot" />
  </a>
</p>

## 📖 About the project

**Media Downloader Bot** is a modern Telegram bot built on Python (Aiogram 3) that lets users conveniently download video, audio, and images from platforms such as YouTube, YouTube Music, SoundCloud, Spotify, TikTok, Instagram, Threads, Facebook, and GitHub.

The project includes an integrated **Telegram Mini App** (Web App) with a modern interface, where users can view their own stats, limits, leaderboards, and purchase VIP access using **Telegram Stars**. A local Telegram Bot API server is used to reliably handle large files (up to 2 GB).

---

## ✨ Key features

- 🎬 **YouTube and YouTube Music**: Download videos and audio files in the highest available quality (using `yt-dlp`).
- 📸 **Instagram, Facebook, and TikTok**: Save videos (Reels, TikTok), posts, and carousels (using `gallery-dl` and `yt-dlp`).
- 🧵 **Threads**: Native support for downloading media content.
- 🎵 **Spotify**: Download individual tracks and playlists with metadata and cover art preserved (using `spotdl`).
- 🎧 **SoundCloud**: Fast downloading of audio tracks and music sets in high quality.
- 💻 **GitHub**: Quick download of repository source code as a `.zip` file.
- 📱 **Modern Web App**: An integrated mini app featuring a user profile, leaderboard, and subscription section.
- 💎 **Monetization**: Built-in tier system (Free, Pro, Max, VIP) with payment support via Telegram Stars.
- 🚀 **Large file handling**: Download and send files up to 2 GB in size thanks to a local Telegram Bot API server.

---

## 🖼️ Demo

| Main menu & Mini App | Leaderboard | VIP Store |
| :---: | :---: | :---: |
| <img src="assets/demo-webapp.jpg" width="250" /> | <img src="assets/demo-leaderboard.jpg" width="250" /> | <img src="assets/demo-store.jpg" width="250" /> |
| **Downloading from YouTube** | **Music from Spotify** | **Guest Mode** |
| <img src="assets/demo-youtube.jpg" width="250" /> | <img src="assets/demo-spotify.jpg" width="250" /> | <img src="assets/demo-guest.jpg" width="250" /> |

---

## 🛠 Tech stack

- **Backend**: Python 3.10+, [Aiogram 3](https://docs.aiogram.dev/en/latest/)
- **Database**: SQLite (using `aiosqlite`)
- **Download components**: `yt-dlp`, `gallery-dl`, `spotdl`
- **Media processing**: `FFmpeg`, `mutagen`, `Pillow`
- **Frontend (Web App)**: HTML5, CSS3, Vanilla JS
- **Infrastructure**: Local [Telegram Bot API Server](https://github.com/tdlib/telegram-bot-api)

---

## ⚙️ Local deployment

### 1. Clone the repository
```bash
git clone https://github.com/dmytrokurochkin/Media-Downloader-Bot.git
cd Media-Downloader-Bot
```

### 2. Configure the environment
Create a `.env` file in the project root and fill it in with the following data:
```env
BOT_TOKEN=your_bot_token
LOCAL_API_SERVER_URL=http://127.0.0.1:8081
API_ID=your_api_id
API_HASH=your_api_hash
```

### 3. Install dependencies
Make sure `ffmpeg` is installed on your system.
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Run the bot
```bash
python main.py
```

---

## 🚀 Server deployment (Ubuntu/Debian)

The repository includes a script for automatically deploying the bot together with the local Telegram API server. The script installs the required dependencies, builds the server, creates a Python virtual environment, and configures the corresponding `systemd` services.

```bash
git clone https://github.com/dmytrokurochkin/Media-Downloader-Bot.git
cd Media-Downloader-Bot
chmod +x auto_deploy.sh
./auto_deploy.sh
```

Once the script completes successfully, the bot will run continuously in the background.
To check the system logs, use:
```bash
sudo journalctl -u tg-media-bot -f
```

## ⚠️ Legal information (Disclaimer)

This project was developed **strictly for educational and research purposes**, as a demonstration of building bots, working with APIs, and processing media files.
The authors and contributors bear no responsibility for any use of this software by end users in a manner that may infringe copyright, violate the laws of any country, or breach the Terms of Service of third-party platforms. When downloading content, you are responsible for complying with applicable law and respecting the rights of content creators.

---

## 🤝 Contributing
We welcome any contribution to the project's development. For significant changes, please open an issue first to discuss what you would like to change.
