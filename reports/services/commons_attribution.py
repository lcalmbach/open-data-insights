import json
import re
from html import unescape
from typing import Any
from urllib.parse import urlparse, unquote
from urllib.request import Request, urlopen

from django.utils.html import strip_tags


COMMONS_API_URL = "https://commons.wikimedia.org/w/api.php"


def _extract_commons_file_title(file_url: str) -> str | None:
    """
    Extract a MediaWiki title like 'File:Example.jpg' from a Wikimedia Commons URL.
    """
    if not file_url:
        return None
    parsed = urlparse(file_url)
    if "commons.wikimedia.org" not in (parsed.netloc or ""):
        return None

    path = parsed.path or ""
    if path.startswith("/wiki/"):
        title = unquote(path[len("/wiki/") :])
        if title.startswith("File:"):
            return title
    return None


def _first_href(html: str) -> str | None:
    if not html:
        return None
    match = re.search(r'href=[\'"]([^\'"]+)[\'"]', html, flags=re.IGNORECASE)
    return match.group(1) if match else None


def fetch_commons_attribution(file_url: str, *, timeout_seconds: int = 5) -> dict[str, Any] | None:
    """
    Fetch attribution metadata for a Wikimedia Commons file page URL.

    Returns keys:
      - title
      - author_text
      - author_url
      - description_text
      - license_name
      - license_url
      - source_url
      - image_url
    """
    title = _extract_commons_file_title(file_url)
    if not title:
        return None

    query = (
        f"{COMMONS_API_URL}"
        f"?action=query&format=json"
        f"&prop=imageinfo"
        f"&titles={title}"
        f"&iiprop=extmetadata|url"
    )
    req = Request(query, headers={"User-Agent": "open-data-insights/commons-attribution"})
    with urlopen(req, timeout=timeout_seconds) as resp:  # nosec - external URL expected
        data = json.loads(resp.read().decode("utf-8"))

    pages = (data.get("query") or {}).get("pages") or {}
    page = next(iter(pages.values()), {}) if isinstance(pages, dict) else {}
    imageinfo = (page.get("imageinfo") or [])
    if not imageinfo:
        return None

    info0 = imageinfo[0]
    ext = (info0.get("extmetadata") or {})

    object_name_html = ((ext.get("ObjectName") or {}).get("value") or "").strip()
    image_description_html = ((ext.get("ImageDescription") or {}).get("value") or "").strip()
    artist_html = ((ext.get("Artist") or {}).get("value") or "").strip()
    credit_html = ((ext.get("Credit") or {}).get("value") or "").strip()
    license_short = ((ext.get("LicenseShortName") or {}).get("value") or "").strip()
    license_url = ((ext.get("LicenseUrl") or {}).get("value") or "").strip()

    title_text = strip_tags(unescape(object_name_html)).strip() or title
    description_text = strip_tags(unescape(image_description_html)).strip() or None
    author_url = _first_href(artist_html) or _first_href(credit_html)
    author_text = strip_tags(unescape(artist_html)).strip() or strip_tags(
        unescape(credit_html)
    ).strip()

    if author_url and author_url.startswith("/"):
        author_url = f"https://commons.wikimedia.org{author_url}"

    # Normalize the license URL (Commons sometimes returns protocol-relative or relative URLs)
    if license_url and license_url.startswith("//"):
        license_url = f"https:{license_url}"
    if license_url and license_url.startswith("/"):
        license_url = f"https://commons.wikimedia.org{license_url}"

    result = {
        "title": title_text,
        "author_text": author_text or None,
        "author_url": author_url or None,
        "description_text": description_text,
        "license_name": license_short or None,
        "license_url": license_url or None,
        "source_url": file_url,
        "image_url": (info0.get("url") or "").strip() or None,
    }
    return result
