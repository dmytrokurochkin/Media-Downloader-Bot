FROM python:3.11-slim-bookworm

# Pinned to bookworm explicitly: the unqualified "slim" tag now tracks Debian
# trixie, where libgdk-pixbuf2.0-0 (needed by weasyprint below) was renamed
# and breaks apt-get install. bookworm keeps the package name auto_deploy.sh
# already relies on.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8080/webapp/index.html || exit 1

CMD ["python", "main.py"]
