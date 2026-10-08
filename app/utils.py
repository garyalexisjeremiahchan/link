import hashlib
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
    
    # Basic URL validation
    if not url.startswith(("http://", "https://")):
        return metadata

    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    default_favicon = f"https://www.google.com/s2/favicons?domain={parsed.netloc}&sz=64"
    metadata["favicon_url"] = default_favicon

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 FCCLink/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        }
        async with httpx.AsyncClient(timeout=4.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", ""):
                soup = BeautifulSoup(resp.text[:100000], "html.parser")
                
                # Title
                og_title = soup.find("meta", property="og:title")
                if og_title and og_title.get("content"):
                    metadata["title"] = og_title.get("content").strip()
                elif soup.title and soup.title.string:
                    metadata["title"] = soup.title.string.strip()

                # Description
                og_desc = soup.find("meta", property="og:description") or soup.find("meta", attrs={"name": "description"})
                if og_desc and og_desc.get("content"):
                    metadata["description"] = og_desc.get("content").strip()

                # Favicon
                icon_tag = soup.find("link", rel=lambda x: x and ("icon" in x.lower()))
                if icon_tag and icon_tag.get("href"):
                    metadata["favicon_url"] = urljoin(base_url, icon_tag.get("href"))
    except Exception:
        # Fallback to domain-based default favicon and hostname title
        if not metadata["title"]:
            metadata["title"] = parsed.netloc

    return metadata
