"""Runs the agents in order and reports progress. One call = one finished video."""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import media, render, script, seo, thumbnail, voice

Progress = Callable[[str, float, str], None]

STAGES = [
    ("script", "Writing the script"),
    ("seo", "Writing title, description and tags"),
    ("voice", "Recording the voiceover"),
    ("footage", "Finding footage"),
    ("render", "Editing the video"),
    ("finish", "Making the thumbnail"),
]


@dataclass
class Options:
    title: str
    length: str = "short"
    tone: str = "curious"
    voice: str = "andrew"
    format: str = "landscape"


def run(opts: Options, workdir: Path, progress: Progress) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    size = render.FORMATS.get(opts.format, render.FORMATS["landscape"])
    portrait = size[1] > size[0]

    progress("script", 0.04, "Writing the script")
    scenes = script.write_script(opts.title, length=opts.length, tone=opts.tone)

    progress("seo", 0.14, "Writing title, description and tags")
    meta = seo.optimize(opts.title, scenes)

    # Each sentence becomes its own caption line with its own voice file, so captions stay short
    # and are on screen exactly while they're spoken. Lines in a scene share one footage clip.
    lines = [{"text": t, "scene": si} for si, sc in enumerate(scenes) for t in script.sentences(sc["narration"])]

    progress("voice", 0.22, f"Recording {len(lines)} lines of voiceover")
    engines: list[str] = []

    def do_voice(i: int) -> float:
        path = workdir / f"voice_{i:03d}.mp3"
        engines.append(voice.speak(lines[i]["text"], opts.voice, path))
        return render.duration(path) + 0.3  # small breath between lines

    with ThreadPoolExecutor(4) as pool:
        durations = list(pool.map(do_voice, range(len(lines))))
    for ln, d in zip(lines, durations):
        ln["seconds"] = round(d, 2)
    for si, sc in enumerate(scenes):
        sc["seconds"] = round(sum(ln["seconds"] for ln in lines if ln["scene"] == si), 2)

    # Footage: a different clip per scene where possible.
    progress("footage", 0.42, "Finding footage for each scene")
    used: set[int] = set()
    credits: list[dict] = []
    clips: list[Path | None] = []
    for i, sc in enumerate(scenes):
        found = media.search_video(sc["visual"], portrait=portrait, min_seconds=sc["seconds"], exclude=used)
        if not found and sc["visual"] != opts.title:
            found = media.search_video(" ".join(opts.title.split()[:3]), portrait=portrait,
                                       min_seconds=sc["seconds"], exclude=used)
        clip = None
        if found:
            used.add(found["id"])
            try:
                clip = media.download(found["url"], workdir / f"clip_{i:03d}.mp4")
                credits.append({"by": found["credit"], "url": found["page"]})
            except Exception:
                clip = None
        clips.append(clip)
        progress("footage", 0.42 + 0.22 * (i + 1) / len(scenes), f"Footage {i + 1} of {len(scenes)}")

    # Edit every line (continuing its scene's clip where the last line stopped), then join.
    clip_len = {i: render.duration(c) for i, c in enumerate(clips) if c}
    parts: list[Path] = []
    offset_in_scene = 0.0
    for i, ln in enumerate(lines):
        si = ln["scene"]
        first = i == 0 or lines[i - 1]["scene"] != si
        last = i == len(lines) - 1 or lines[i + 1]["scene"] != si
        if first:
            offset_in_scene = 0.0
        start = offset_in_scene % clip_len[si] if si in clip_len and clip_len[si] > 0.5 else 0.0
        cap = render.caption_png(ln["text"], size, workdir / f"cap_{i:03d}.png")
        parts.append(render.render_scene(clip=clips[si], caption=cap, audio=workdir / f"voice_{i:03d}.mp3",
                                         seconds=ln["seconds"], size=size, out=workdir / f"part_{i:03d}.mp4",
                                         start=start, fade_in=first, fade_out=last))
        offset_in_scene += ln["seconds"]
        progress("render", 0.66 + 0.26 * (i + 1) / len(lines), f"Edited line {i + 1} of {len(lines)}")

    name = render.safe_name(meta["title"])
    video = render.concat(parts, workdir / f"{name}.mp4")

    progress("finish", 0.94, "Making the thumbnail")
    photo = media.search_photo(scenes[0]["visual"]) or media.search_photo(opts.title)
    thumb = thumbnail.make(meta["title"], workdir / f"{name}-thumbnail.jpg", photo["url"] if photo else None,
                           text=meta.get("thumbnail_text"))
    if photo:
        credits.append({"by": photo["credit"], "url": photo["page"]})

    # Pexels asks for credit where possible: add it to the description automatically.
    names = sorted({c["by"] for c in credits if c.get("by")})
    if names:
        meta["description"] = meta["description"].rstrip() + "\n\nFootage: " + ", ".join(names) + " via Pexels."

    meta_path = workdir / f"{name}-metadata.json"
    payload = json.dumps({k: meta[k] for k in ("title", "description", "tags", "hashtags")}, indent=2, ensure_ascii=False)
    meta_path.write_text(payload, encoding="utf-8")

    # Remove working files; keep only what the user downloads.
    for p in workdir.iterdir():
        if p not in (video, thumb, meta_path):
            p.unlink(missing_ok=True)

    return {
        "video": video.name,
        "thumbnail": thumb.name,
        "metadata": meta_path.name,
        "seconds": round(sum(s["seconds"] for s in scenes), 1),
        "scenes": [{"narration": s["narration"], "visual": s["visual"]} for s in scenes],
        "seo": meta,
        "voice_engine": "neural" if engines and all(e == "edge" for e in engines) else "standard",
        "format": opts.format,
    }