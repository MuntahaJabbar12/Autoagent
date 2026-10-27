"""Footage agent: finds and downloads stock clips and photos from Pexels (free, licensed for reuse)."""
from __future__ import annotations

from pathlib import Path

import httpx

from .config import settings

API = "https://api.pexels.com"
MAX_BYTES = 60 * 1024 * 1024


class MediaError(RuntimeError):
    pass


def _headers() -> dict:
    if not settings.pexels_api_key:
        raise MediaError("PEXELS_API_KEY is not set.")
    return {"Authorization": settings.pexels_api_key}


def pick_file(files: list[dict], portrait: bool, target: int) -> dict | None:
    """Choose the rendition whose long edge is closest to `target`, in the right orientation."""
    good = [f for f in files if f.get("link") and f.get("width") and f.get("height")
            and ((f["height"] > f["width"]) if portrait else (f["width"] > f["height"]))]
    if not good:
        return None
    return min(good, key=lambda f: abs(max(f["width"], f["height"]) - target))


def search_video(query: str, *, portrait: bool, min_seconds: float, exclude: set[int]) -> dict | None:
    params = {"query": query, "per_page": 15, "orientation": "portrait" if portrait else "landscape",
              "size": "medium"}
    try:
        r = httpx.get(f"{API}/videos/search", headers=_headers(), params=params, timeout=20)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    videos = [v for v in r.json().get("videos", []) if v.get("id") not in exclude]
    # Prefer clips long enough for the scene; otherwise the longest one (it gets looped).
    videos.sort(key=lambda v: (v.get("duration", 0) < min_seconds, -v.get("duration", 0)))
    for v in videos:
        f = pick_file(v.get("video_files", []), portrait, 1920 if portrait else 1280)
        if f:
            return {"id": v["id"], "url": f["link"], "duration": v.get("duration", 0),
                    "credit": v.get("user", {}).get("name", "Pexels"), "page": v.get("url", "")}
    return None


def search_photo(query: str, *, portrait: bool = False) -> dict | None:
    try:
        r = httpx.get(f"{API}/v1/search", headers=_headers(),
                      params={"query": query, "per_page": 5,
                              "orientation": "portrait" if portrait else "landscape"}, timeout=20)
        r.raise_for_status()
    except httpx.HTTPError:
        return None
    photos = r.json().get("photos", [])
    if not photos:
        return None
    p = photos[0]
    return {"url": p["src"].get("large2x") or p["src"].get("original"),
            "credit": p.get("photographer", "Pexels"), "page": p.get("url", "")}


def download(url: str, path: Path) -> Path:
    with httpx.stream("GET", url, timeout=60, follow_redirects=True) as r:
        r.raise_for_status()
        size = 0
        with open(path, "wb") as fh:
            for chunk in r.iter_bytes(1 << 16):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise MediaError("Clip too large")
                fh.write(chunk)
    return path
