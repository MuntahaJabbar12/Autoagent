"""Idea agent: what's popular for a topic, and fresh video ideas built from it."""
from __future__ import annotations

import html
import re
from datetime import datetime, timedelta, timezone

import httpx

from . import llm
from .config import settings


def clean_title(title: str) -> str:
    title = html.unescape(title)
    title = re.sub(r"#\w+", "", title)               # hashtags
    title = re.sub(r"[|•]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -–—:")
    return title


def trending_on_youtube(topic: str, limit: int = 5) -> list[dict]:
    """Most-viewed recent videos for a topic. Needs YOUTUBE_API_KEY; returns [] without it."""
    if not settings.youtube_api_key:
        return []
    since = (datetime.now(timezone.utc) - timedelta(days=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        r = httpx.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part": "snippet", "q": topic, "type": "video", "order": "viewCount",
                    "maxResults": limit, "publishedAfter": since, "relevanceLanguage": "en",
                    "safeSearch": "strict", "key": settings.youtube_api_key},
            timeout=15,
        )
        r.raise_for_status()
    except httpx.HTTPError:
        return []
    out = []
    for item in r.json().get("items", []):
        sn = item.get("snippet", {})
        title = clean_title(sn.get("title", ""))
        if title:
            out.append({"title": title, "channel": sn.get("channelTitle", ""), "source": "youtube"})
    return out


def generate_ideas(topic: str, inspiration: list[str] | None = None, count: int = 6) -> list[dict]:
    inspo = ""
    if inspiration:
        inspo = "Titles currently doing well on YouTube for this topic:\n" + "\n".join(
            f"- {t}" for t in inspiration) + "\nUse them as signals, never copy them.\n"
    prompt = f"""You plan videos for a faceless YouTube channel.
Topic: "{topic}"
{inspo}
Suggest {count} original video ideas that would work as a 1–2 minute narrated video over stock footage.
Each title: under 65 characters, specific, curiosity-driven, no clickbait lies, no emojis.
Each angle: one sentence on what the viewer learns.

Reply with JSON only: {{"ideas": [{{"title": "...", "angle": "..."}}]}}"""
    data = llm.chat_json(prompt, temperature=0.9)
    ideas = data.get("ideas", []) if isinstance(data, dict) else data
    out = []
    for idea in ideas:
        if isinstance(idea, dict) and idea.get("title"):
            out.append({"title": clean_title(str(idea["title"]))[:90],
                        "angle": str(idea.get("angle", ""))[:200], "source": "ai"})
    if not out:
        raise llm.LLMError("No ideas came back. Try a different topic.")
    return out[:count]


def ideas_for(topic: str) -> dict:
    trending = trending_on_youtube(topic)
    ideas = generate_ideas(topic, [t["title"] for t in trending])
    return {"topic": topic, "trending": trending, "ideas": ideas}
