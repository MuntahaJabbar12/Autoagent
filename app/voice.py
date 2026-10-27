"""Voice agent: one audio file per scene, so captions line up exactly with speech."""
from __future__ import annotations

import asyncio
from pathlib import Path

VOICES = {
    "andrew": {"label": "Andrew · warm, US", "edge": "en-US-AndrewNeural", "gtts": ("en", "com")},
    "ava": {"label": "Ava · bright, US", "edge": "en-US-AvaNeural", "gtts": ("en", "com")},
    "ryan": {"label": "Ryan · calm, UK", "edge": "en-GB-RyanNeural", "gtts": ("en", "co.uk")},
    "sonia": {"label": "Sonia · clear, UK", "edge": "en-GB-SoniaNeural", "gtts": ("en", "co.uk")},
}


class VoiceError(RuntimeError):
    pass


def _edge(text: str, voice: str, path: Path) -> None:
    import edge_tts

    async def run() -> None:
        await edge_tts.Communicate(text, voice, rate="+4%").save(str(path))

    asyncio.run(run())


def _gtts(text: str, lang: str, tld: str, path: Path) -> None:
    from gtts import gTTS

    gTTS(text=text, lang=lang, tld=tld).save(str(path))


def speak(text: str, voice_id: str, path: Path) -> str:
    """Write speech to `path`. Returns the engine used: 'edge' (neural) or 'gtts' (fallback)."""
    voice = VOICES.get(voice_id, VOICES["andrew"])
    try:
        _edge(text, voice["edge"], path)
        if path.exists() and path.stat().st_size > 0:
            return "edge"
    except Exception:  # network hiccup or service change: fall back rather than fail the video
        pass
    try:
        _gtts(text, *voice["gtts"], path)
        return "gtts"
    except Exception as exc:
        raise VoiceError(f"Couldn't create the voiceover: {exc}") from exc
