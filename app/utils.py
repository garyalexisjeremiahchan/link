import hashlib
import html
import re
from urllib.parse import urljoin, urlparse
from typing import Dict, Any, Optional
import httpx
from bs4 import BeautifulSoup

def anonymize_ip(ip: Optional[str]) -> str:
    if not ip:
        return "anonymous"
    # Anonymize IP address via SHA-256 hash prefix
    salt = "fcc-link-salt"
    return hashlib.sha256(f"{salt}-{ip}".encode("utf-8")).hexdigest()[:16]

def detect_device_type(user_agent: Optional[str]) -> str:
    if not user_agent:
        return "desktop"
    ua = user_agent.lower()
    if "tablet" in ua or "ipad" in ua:
        return "tablet"
    if "mobile" in ua or "android" in ua or "iphone" in ua or "ipod" in ua:
        return "mobile"
    return "desktop"

async def fetch_url_metadata(url: str) -> Dict[str, Any]:
    """Fetch <title>, favicon, and OpenGraph description from target destination."""
    metadata = {
        "title": "",
        "description": "",
        "favicon_url": ""
    }
    
    if not url:
        return metadata

    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    parsed = urlparse(url)
    if not parsed.netloc:
        return metadata

    base_url = f"{parsed.scheme}://{parsed.netloc}"
    default_favicon = f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=64"
    metadata["favicon_url"] = default_favicon

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 FCCLink/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        async with httpx.AsyncClient(timeout=6.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers=headers)
            content_type = resp.headers.get("content-type", "").lower()
            if resp.status_code == 200 and ("text/html" in content_type or "xml" in content_type or not content_type):
                # Modern SSR/SPA applications (Next.js, Vite, React) can embed large preloads or hydration chunks
                # in the HTML before or after the title. Scan up to 2.5MB.
                html_text = resp.text[:2500000]
                soup = BeautifulSoup(html_text, "html.parser")
                
                # Title extraction order:
                # 1. OpenGraph title
                og_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "og:title"})
                # 2. Twitter title
                twitter_title = soup.find("meta", property="twitter:title") or soup.find("meta", attrs={"name": "twitter:title"})
                # 3. HTML <title> tag
                title_tag = soup.find("title")

                extracted_title = ""
                if og_title and og_title.get("content"):
                    extracted_title = og_title.get("content").strip()
                elif twitter_title and twitter_title.get("content"):
                    extracted_title = twitter_title.get("content").strip()
                elif title_tag and title_tag.get_text():
                    extracted_title = title_tag.get_text().strip()

                # Fallback: regex search on raw HTML text in case BeautifulSoup missed malformed tag
                if not extracted_title:
                    m = re.search(r"<title[^>]*>(.*?)</title>", html_text, re.IGNORECASE | re.DOTALL)
                    if m:
                        extracted_title = html.unescape(m.group(1)).strip()

                if extracted_title:
                    metadata["title"] = re.sub(r"\s+", " ", extracted_title).strip()
                else:
                    metadata["title"] = parsed.netloc

                # Description
                og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
                if og_desc and og_desc.get("content"):
                    metadata["description"] = re.sub(r"\s+", " ", og_desc.get("content")).strip()

                # Favicon
                icon_tag = soup.find("link", rel=lambda x: x and ("icon" in x.lower()))
                if icon_tag and icon_tag.get("href"):
                    metadata["favicon_url"] = urljoin(base_url, icon_tag.get("href"))
            else:
                metadata["title"] = parsed.netloc
    except Exception:
        # Fallback to domain hostname if request failed or timed out
        if not metadata["title"]:
            metadata["title"] = parsed.netloc

    return metadata
