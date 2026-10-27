"""SEO agent: title, description and tags, plus a transparent checklist score."""
from __future__ import annotations

import re

from . import llm

STOP = set("""a an the and or but if of to in on for with at by from as is are was were be been it its this that
these those you your we our they their how why what when who will can not no do does did just into about over
more most very than then so such""".split())


def keywords(text: str, n: int = 8) -> list[str]:
    words = [w for w in re.findall(r"[a-zA-Z][a-zA-Z0-9']{2,}", text.lower()) if w not in STOP]
    seen, out = set(), []
    for w in words:
        if w not in seen:
            seen.add(w)
            out.append(w)
    return out[:n]


def checklist(title: str, description: str, tags: list[str]) -> list[dict]:
    """Each check is something a creator can see and fix. Score = share of checks passed."""
    first_line = description.strip().split("\n", 1)[0].lower()
    title_kw = keywords(title, 3)
    tags_len = sum(len(t) for t in tags) + max(len(tags) - 1, 0)
    return [
        {"label": "Title is 30–70 characters", "ok": 30 <= len(title) <= 70},
        {"label": "Title has no all-caps shouting", "ok": not re.search(r"\b[A-Z]{5,}\b", title)},
        {"label": "Description opens with the title's main keyword",
         "ok": bool(title_kw) and any(k in first_line for k in title_kw)},
        {"label": "Description is 200+ characters", "ok": len(description) >= 200},
        {"label": "Description asks viewers to subscribe", "ok": "subscribe" in description.lower()},
        {"label": "8–15 tags", "ok": 8 <= len(tags) <= 15},
        {"label": "Tags fit YouTube's 500-character limit", "ok": tags_len <= 500},
    ]


def score(checks: list[dict]) -> int:
    return round(100 * sum(c["ok"] for c in checks) / len(checks)) if checks else 0


def _clean_tags(tags: object) -> list[str]:
    out, seen = [], set()
    for t in tags if isinstance(tags, list) else []:
        t = re.sub(r"[<>#,]", "", str(t)).strip().lower()
        if 1 < len(t) <= 40 and t not in seen:
            seen.add(t)
            out.append(t)
    while out and sum(len(t) for t in out) + len(out) - 1 > 500:
        out.pop()
    return out[:15]


def fallback(title: str, script_text: str) -> dict:
    kws = keywords(title + " " + script_text, 12)
    desc = (f"{title}.\n\n{script_text[:600]}\n\n"
            "If you enjoyed this, subscribe for more videos like it.")
    return {"title": title[:70], "description": desc, "tags": kws, "hashtags": ["#" + k for k in kws[:3]],
            "thumbnail_text": ""}


def optimize(title: str, scenes: list[dict]) -> dict:
    script_text = " ".join(s["narration"] for s in scenes)
    prompt = f"""You are a YouTube SEO editor. Video title idea: "{title}"
Script: {script_text[:2500]}

Return metadata that is honest to the script (no clickbait lies):
- "title": 40–65 characters, main keyword near the start, no all-caps words, no emojis.
- "description": 3 short paragraphs (250–600 characters total). First sentence contains the main keyword. End with a line inviting viewers to subscribe.
- "tags": 10–14 search phrases, lowercase.
- "hashtags": 3 hashtags.
- "thumbnail_text": 2–4 punchy words for the thumbnail (a complete phrase, not a cut-off title).

Reply with JSON only: {{"title": "...", "description": "...", "tags": ["..."], "hashtags": ["#..."], "thumbnail_text": "..."}}"""
    try:
        data = llm.chat_json(prompt, temperature=0.5)
        meta = {
            "title": re.sub(r"\s+", " ", str(data.get("title") or title)).strip()[:100],
            "description": str(data.get("description") or "").strip()[:4900],
            "tags": _clean_tags(data.get("tags")),
            "hashtags": [h if str(h).startswith("#") else f"#{h}" for h in data.get("hashtags", [])][:3],
            "thumbnail_text": " ".join(str(data.get("thumbnail_text") or "").split()[:5]),
        }
        if not meta["description"]:
            raise llm.LLMError("empty description")
    except (llm.LLMError, AttributeError):
        meta = fallback(title, script_text)
    checks = checklist(meta["title"], meta["description"], meta["tags"])
    meta["checks"] = checks
    meta["score"] = score(checks)
    return meta
