"""Popular meme templates from Imgflip's free public API (no key needed).

Only image URLs that came from the API list are ever downloaded, so the
server can't be pointed at arbitrary URLs.
"""
from __future__ import annotations

import io
import json
import ssl
import time
import urllib.request
from urllib.parse import urlparse

API_URL = "https://api.imgflip.com/get_memes"
CACHE_SECONDS = 3600
MAX_DOWNLOAD = 10 * 1024 * 1024
USER_AGENT = "StreamFaceMemes/0.2"

_cache: dict = {"at": 0.0, "memes": []}

# Certificates are still fully verified. Python 3.13+ also enables the extra
# VERIFY_X509_STRICT checks by default, which Imgflip's image CDN chain fails
# ("Basic Constraints of CA cert not marked critical"), so turn just that off.
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)


def _get(url: str, limit: int) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx) as resp:
        data = resp.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Response too large.")
    return data


def popular() -> list[dict]:
    if _cache["memes"] and time.time() - _cache["at"] < CACHE_SECONDS:
        return _cache["memes"]
    payload = json.loads(_get(API_URL, 2 * 1024 * 1024))
    if not payload.get("success"):
        raise ValueError("Imgflip API returned an error.")
    memes = [
        {"id": m["id"], "name": m["name"], "url": m["url"],
         "width": m["width"], "height": m["height"], "box_count": m.get("box_count", 2)}
        for m in payload["data"]["memes"]
    ]
    _cache.update(at=time.time(), memes=memes)
    return memes


def download(meme_id: str) -> tuple[dict, io.BytesIO]:
    meme = next((m for m in popular() if m["id"] == meme_id), None)
    if meme is None:
        raise ValueError("Unknown Imgflip template.")
    return meme, download_url(meme["url"])


def download_url(url: str) -> io.BytesIO:
    """Download an Imgflip image. Only imgflip.com hosts are allowed."""
    host = urlparse(url).hostname or ""
    if not (host == "imgflip.com" or host.endswith(".imgflip.com")):
        raise ValueError("Unexpected image host.")
    return io.BytesIO(_get(url, MAX_DOWNLOAD))
