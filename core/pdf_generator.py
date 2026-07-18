import asyncio
import aiohttp
from pathlib import Path
from bs4 import BeautifulSoup
from readability import Document
from weasyprint import HTML, CSS

async def is_safe_url(url: str) -> bool:
    import socket
    import ipaddress
    from urllib.parse import urlparse
    
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ('http', 'https'):
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        
        loop = asyncio.get_running_loop()
        addr_info = await loop.getaddrinfo(hostname, None)
        for result in addr_info:
            ip_str = result[4][0]
            ip = ipaddress.ip_address(ip_str)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
                return False
        return True
    except Exception:
        return False

async def generate_article_pdf(url: str, output_path: Path) -> Path:
    """
    Завантажує HTML-сторінку, витягує головний контент статті за допомогою readability-lxml
    і генерує PDF-файл за допомогою weasyprint.
    """
    if not await is_safe_url(url):
        raise Exception("Недопустима або небезпечна URL-адреса.")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    }
    
    MAX_SIZE = 5 * 1024 * 1024 # 5 MB
    html_bytes = bytearray()
    
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=15) as resp:
            if resp.status != 200:
                raise Exception(f"Не вдалося завантажити сторінку (статус {resp.status})")
            
            async for chunk in resp.content.iter_chunked(8192):
                html_bytes.extend(chunk)
                if len(html_bytes) > MAX_SIZE:
                    raise Exception("Файл занадто великий (ліміт 5 МБ)")
                    
            html = html_bytes.decode('utf-8', errors='replace')

    # Парсимо статтю
    doc = Document(html)
    title = doc.title()
    content_html = doc.summary() # Основний контент (тільки текст, заголовки, картинки)

    # HTML-шаблон для PDF
    full_html = f"""
    <!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
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
        <h1>{title}</h1>
        {content_html}
    </body>
    </html>
    """

    # Weasyprint generation has to be synchronous, so we run it in a thread
    def render_pdf():
        # HTML object, passing base_url to resolve relative image links correctly
        HTML(string=full_html, base_url=url).write_pdf(target=str(output_path))

    await asyncio.to_thread(render_pdf)
    
    return output_path, title
