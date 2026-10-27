"""Script agent: turns a title into narrated scenes, each with a stock-footage search."""
from __future__ import annotations

import re

from . import llm

# length id: (scenes, total duration, sentences per scene)
LENGTHS = {
    "short": (6, "about 45 seconds", "1–2"),
    "standard": (10, "about 90 seconds", "1–2"),
    "long": (20, "about 5 minutes (roughly 750 words)", "2–3"),
}
TONES = {
    "curious": "curious and intriguing, like a good documentary",
    "dramatic": "dramatic and suspenseful, with tension and payoff",
    "calm": "calm, warm and reassuring",
    "energetic": "upbeat, fast and energetic",
}

_DIRECTIONS = re.compile(r"^\s*(narrator|narration|visuals?|footage|scene|audio|music|sfx|cut to|transition)\s*[:\-]\s*",
                         re.IGNORECASE)


def clean_narration(text: str) -> str:
    """Keep only words meant to be spoken."""
    text = re.sub(r"\[[^\]]*\]|\([^)]*\)|\*+", "", text)
    text = _DIRECTIONS.sub("", text)
    text = re.sub(r"[#_`>]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([.,!?;:])", r"\1", text)


def _query(text: str, fallback: str) -> str:
    q = re.sub(r"[^\w\s-]", " ", text or "").strip()
    q = " ".join(q.split()[:5])
    return q or fallback


def validate_scenes(raw: object, topic_hint: str) -> list[dict]:
    items = raw.get("scenes", []) if isinstance(raw, dict) else raw
    scenes = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        narration = clean_narration(str(item.get("narration", "")))
        if len(narration) < 3:
            continue
        scenes.append({"narration": narration[:400],
                       "visual": _query(str(item.get("visual", "")), topic_hint)})
    if len(scenes) < 2:
        raise llm.LLMError("The script came back too short. Try again.")
    return scenes


def write_script(title: str, *, length: str = "short", tone: str = "curious") -> list[dict]:
    n, duration, sentences = LENGTHS.get(length, LENGTHS["short"])
    voice = TONES.get(tone, TONES["curious"])
    prompt = f"""Write a voiceover script for a faceless YouTube video titled "{title}".
Length: {n} scenes, {duration} in total when read aloud.
Tone: {voice}.
Rules:
- Scene 1 is a hook that makes people keep watching.
- Build a clear story from start to finish; each scene adds something new.
- Each narration is {sentences} short spoken sentences. Only words to be read aloud: no stage directions, labels, emojis or brackets.
- Share real, checkable facts. If unsure of a number, don't state one.
- Last scene invites viewers to subscribe for more.
- "visual" is a 2–4 word search for stock footage that matches the scene (concrete things you can film, e.g. "city traffic night").

Reply with JSON only: {{"scenes": [{{"narration": "...", "visual": "..."}}]}}"""
    data = llm.chat_json(prompt, temperature=0.7, timeout=150)
    hint = " ".join(title.split()[:3])
    return validate_scenes(data, hint)


def sentences(text: str) -> list[str]:
    """Split narration into caption-sized lines. Tiny fragments ("Wow.", "Dr.") join a neighbour."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])", text) if p.strip()]
    out: list[str] = []
    for part in parts:
        if out and (len(part) < 15 or len(out[-1]) < 12):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out or [text]
