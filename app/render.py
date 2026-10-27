"""Video agent: builds each scene with ffmpeg (footage + caption + voice), then joins them.

Uses the ffmpeg binary bundled with imageio-ffmpeg, so nothing extra (like ImageMagick) needs installing.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import ASSETS

CAPTION_FONT = ASSETS / "fonts" / "Inter-ExtraBold.ttf"
RED = (225, 37, 27)
FORMATS = {"landscape": (1280, 720), "shorts": (1080, 1920)}


class RenderError(RuntimeError):
    pass


def ffmpeg() -> str:
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args],
                          capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RenderError(proc.stderr.strip()[-600:] or "ffmpeg failed")
    return proc


def duration(path: Path) -> float:
    proc = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", proc.stderr)
    if not m:
        raise RenderError(f"Couldn't read the length of {path.name}")
    h, mnt, s = m.groups()
    return int(h) * 3600 + int(mnt) * 60 + float(s)


def wrap(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words, lines, line = text.split(), [], ""
    for w in words:
        trial = f"{line} {w}".strip()
        if font.getlength(trial) <= max_width or not line:
            line = trial
        else:
            lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def caption_png(text: str, size: tuple[int, int], path: Path) -> Path:
    """Transparent overlay: white text on a dark band with a red edge, in the lower third."""
    w, h = size
    portrait = h > w
    font_size = 64 if portrait else 40
    font = ImageFont.truetype(str(CAPTION_FONT), font_size)
    max_w = int(w * (0.84 if portrait else 0.78))
    lines = wrap(text, font, max_w)
    if len(lines) > 4:  # very long line: shrink to fit
        font = ImageFont.truetype(str(CAPTION_FONT), int(font_size * 0.8))
        lines = wrap(text, font, max_w)
    line_h = int(font.size * 1.28)
    pad_x, pad_y = int(font.size * 0.7), int(font.size * 0.5)
    block_w = int(max(font.getlength(l) for l in lines)) + pad_x * 2
    block_h = line_h * len(lines) + pad_y * 2
    x0 = (w - block_w) // 2
    y0 = int(h * (0.62 if portrait else 0.74)) - block_h // 2
    y0 = min(y0, h - block_h - int(h * 0.05))

    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([x0, y0, x0 + block_w, y0 + block_h], radius=int(font.size * 0.35), fill=(20, 12, 12, 190))
    d.rectangle([x0, y0 + 8, x0 + 6, y0 + block_h - 8], fill=RED + (255,))
    for i, line in enumerate(lines):
        lx = (w - font.getlength(line)) / 2
        d.text((lx, y0 + pad_y + i * line_h), line, font=font, fill=(255, 255, 255, 255))
    img.save(path)
    return path


def render_scene(*, clip: Path | None, caption: Path, audio: Path, seconds: float,
                 size: tuple[int, int], out: Path, start: float = 0.0,
                 fade_in: bool = True, fade_out: bool = True) -> Path:
    """One caption line. `start` continues a clip where the previous line left off."""
    w, h = size
    fade = min(0.25, seconds / 4)
    inputs = (["-stream_loop", "-1", "-ss", f"{max(start, 0):.3f}", "-i", str(clip)] if clip
              else ["-f", "lavfi", "-i", f"color=c=0x2a1414:s={w}x{h}:r=30"])
    fades = ""
    if fade_in:
        fades += f",fade=t=in:st=0:d={fade:.2f}"
    if fade_out:
        fades += f",fade=t=out:st={seconds - fade:.2f}:d={fade:.2f}"
    vf = (f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1,fps=30{fades}[bg];"
          f"[bg][1:v]overlay=0:0,format=yuv420p[v]")
    run([*inputs, "-loop", "1", "-i", str(caption), "-i", str(audio),
         "-filter_complex", vf, "-map", "[v]", "-map", "2:a",
         "-af", "apad", "-t", f"{seconds:.3f}",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-r", "30",
         "-c:a", "aac", "-b:a", "160k", "-ar", "44100", "-ac", "2", str(out)])
    return out


def concat(parts: list[Path], out: Path) -> Path:
    listing = out.with_suffix(".txt")
    listing.write_text("".join(f"file '{p.resolve().as_posix()}'\n" for p in parts), encoding="utf-8")
    run(["-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(out)])
    listing.unlink(missing_ok=True)
    return out


def safe_name(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "video"


__all__ = ["FORMATS", "caption_png", "concat", "duration", "render_scene", "RenderError", "safe_name"]
