"""Thumbnail agent: a 1280×720 cover with a photo background and big, readable words."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps

from .config import ASSETS
from .render import wrap

FONT = ASSETS / "fonts" / "Anton-Regular.ttf"
SIZE = (1280, 720)
RED = (225, 37, 27)
WHITE = (255, 255, 255)


WEAK_END = {"a", "an", "the", "and", "or", "but", "of", "to", "in", "on", "for", "with", "at", "by", "from",
            "that", "which", "who", "their", "your", "our", "its", "his", "her", "is", "are", "was", "make",
            "makes", "how", "why", "what", "you", "we", "they", "it", "this", "these", "than", "so", "very", "more", "as", "be", "into", "about"}


def hook_words(title: str, limit: int = 5) -> str:
    """Thumbnails work best with a few big words. Never end on a dangling word like 'their'."""
    words = title.split(":")[0].split()
    if len(words) < 2:
        words = title.replace(":", " ").split()
    words = words[:limit]
    while len(words) > 2 and words[-1].lower().strip(",.!?") in WEAK_END:
        words.pop()
    return " ".join(words).strip(",.!?").upper()


def _background(photo_url: str | None) -> Image.Image:
    if photo_url:
        try:
            r = httpx.get(photo_url, timeout=20, follow_redirects=True)
            r.raise_for_status()
            img = Image.open(BytesIO(r.content)).convert("RGB")
            img = ImageOps.fit(img, SIZE)
            img = ImageEnhance.Brightness(img).enhance(0.62)
            return ImageEnhance.Contrast(img).enhance(1.12)
        except Exception:
            pass
    # No photo: a deep red field with a soft light from the top right.
    base = Image.new("RGB", SIZE, (120, 14, 10))
    glow = Image.new("L", SIZE, 0)
    ImageDraw.Draw(glow).ellipse([700, -300, 1600, 500], fill=200)
    glow = glow.filter(ImageFilter.GaussianBlur(160))
    return Image.composite(Image.new("RGB", SIZE, RED), base, glow)


def make(title: str, out: Path, photo_url: str | None = None, text: str | None = None) -> Path:
    img = _background(photo_url)
    w, h = SIZE

    # Darken the left side so white text always reads.
    shade = Image.new("L", SIZE, 0)
    sd = ImageDraw.Draw(shade)
    for x in range(w):
        sd.line([(x, 0), (x, h)], fill=int(200 * max(0.0, 1 - x / (w * 0.85))))
    img = Image.composite(Image.new("RGB", SIZE, (15, 8, 8)), img, shade)

    text = (text or "").strip().upper()[:40] or hook_words(title)
    size = 150
    while size > 70:
        font = ImageFont.truetype(str(FONT), size)
        lines = wrap(text, font, int(w * 0.62))
        if len(lines) <= 3:
            break
        size -= 10
    line_h = int(size * 1.05)
    block_h = line_h * len(lines)
    y = (h - block_h) // 2
    x = 70
    d = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        tw = font.getlength(line)
        if i == 0:  # the first line sits on a red label
            d.rectangle([x - 18, y + int(size * 0.08), x + tw + 18, y + line_h - int(size * 0.02)], fill=RED)
        d.text((x + 4, y + 5), line, font=font, fill=(0, 0, 0))
        d.text((x, y), line, font=font, fill=WHITE)
        y += line_h

    d.rectangle([0, h - 14, w, h], fill=RED)
    img.save(out, quality=92)
    return out
