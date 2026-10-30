import asyncio
import html
from pathlib import Path
from typing import Tuple

from readability import Document
from weasyprint import HTML
from weasyprint.urls import URLFetcher, URLFetcherResponse

from core.net_guard import UnsafeURLError, ensure_public_url, ensure_public_url_sync, safe_get

MAX_HTML_BYTES = 5 * 1024 * 1024
MAX_RESOURCE_BYTES = 10 * 1024 * 1024
MAX_RESOURCES = 40
RESOURCE_TIMEOUT = 10
RENDER_TIMEOUT = 120

BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

# Рендер weasyprint важкий по CPU/RAM, тож паралельно — не більше двох PDF.
_render_slots = asyncio.Semaphore(2)


async def is_safe_url(url: str) -> bool:
    """Сумісна обгортка над net_guard.ensure_public_url (лишилась для старого коду й тестів)."""
    try:
        await ensure_public_url(url)
        return True
    except UnsafeURLError:
        return False


class PublicOnlyURLFetcher(URLFetcher):
    """Fetcher для weasyprint: картинки й стилі статті тягнемо лише з публічних адрес.

    Без нього weasyprint ходить за будь-яким `<img src>` зі сторінки, включно з
    `file://` і `http://127.0.0.1:8081/...` (локальний Bot API) — це той самий
    SSRF, що й у net_guard, тільки через вміст статті.
    """

    def __init__(self):
        super().__init__(
            timeout=RESOURCE_TIMEOUT,
            allowed_protocols={"http", "https", "data"},
            # Редіректи вимкнено: їх перевірити тут нічим, а для картинок у статті це не критично.
            allow_redirects=False,
            # Без стиснення відповідь можна обрізати за розміром, а не розпаковувати «бомбу».
            http_headers={"Accept-Encoding": "identity"},
        )
        self._fetched = 0

    def fetch(self, url, headers=None):
        if url.startswith("data:"):
            return super().fetch(url, headers)

        self._fetched += 1
        if self._fetched > MAX_RESOURCES:
            raise ValueError("Забагато зовнішніх ресурсів у статті.")
        ensure_public_url_sync(url)

        response = super().fetch(url, headers)
        try:
            data = response.read(MAX_RESOURCE_BYTES + 1)
        finally:
            response.close()
        if len(data) > MAX_RESOURCE_BYTES:
            raise ValueError("Ресурс статті завеликий.")
        return URLFetcherResponse(response.url, data, response.headers, response.status)


async def generate_article_pdf(url: str, output_path: Path) -> Tuple[Path, str]:
    """
    Завантажує HTML-сторінку, витягує головний контент статті за допомогою readability-lxml
    і генерує PDF-файл за допомогою weasyprint.
    """
    page = await safe_get(url, max_bytes=MAX_HTML_BYTES, timeout=20, headers=BROWSER_HEADERS)
    html_text = page.body.decode(page.charset or "utf-8", errors="replace")

    # Парсимо статтю
    doc = Document(html_text)
    title = doc.title() or "Article"
    content_html = doc.summary() # Основний контент (тільки текст, заголовки, картинки)
    # Заголовок — це текст зі сторінки, а не HTML: без екранування `<title>` статті
    # міг би підсунути в наш шаблон власні теги.
    safe_title = html.escape(title)

    # HTML-шаблон для PDF
    full_html = f"""
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="utf-8">
        <title>{safe_title}</title>
        <style>
            @page {{
                size: A4;
                margin: 2cm;
            }}
            body {{
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif, Arial;
                line-height: 1.6;
                color: #222;
                font-size: 14pt;
            }}
            h1 {{
                font-size: 24pt;
                color: #111;
                border-bottom: 2px solid #eaeaea;
                padding-bottom: 10px;
                margin-bottom: 20px;
            }}
            h2, h3, h4 {{
                color: #333;
                margin-top: 1.5em;
            }}
            img {{
                max-width: 100%;
                height: auto;
                border-radius: 8px;
                margin: 20px 0;
            }}
            p {{
                margin-bottom: 1em;
                text-align: justify;
            }}
            a {{
                color: #0056b3;
                text-decoration: none;
            }}
            blockquote {{
                border-left: 4px solid #ccc;
                margin-left: 0;
                padding-left: 20px;
                color: #555;
                font-style: italic;
            }}
            figure {{
                margin: 0;
                padding: 0;
            }}
            figcaption {{
                font-size: 10pt;
                color: #777;
                text-align: center;
                margin-top: 5px;
            }}
        </style>
    </head>
    <body>
        <h1>{safe_title}</h1>
        {content_html}
    </body>
    </html>
    """

    # Weasyprint generation has to be synchronous, so we run it in a thread
    def render_pdf():
        # base_url — адреса ПІСЛЯ редіректів, щоб відносні посилання на картинки резолвились правильно
        HTML(string=full_html, base_url=page.url, url_fetcher=PublicOnlyURLFetcher()).write_pdf(target=str(output_path))

    async with _render_slots:
        # Потік не вбити, але кожен ресурс має власний таймаут і ліміт кількості,
        # тож рендер у фоні все одно завершиться; користувач отримає помилку вчасно.
        await asyncio.wait_for(asyncio.to_thread(render_pdf), RENDER_TIMEOUT)

    return output_path, title
