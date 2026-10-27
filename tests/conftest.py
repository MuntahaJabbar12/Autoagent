"""Shared fixtures. No test calls a real API: every network service is replaced with a fake."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app import render
from app.config import settings


def ffmpeg_make(args: list[str]) -> None:
    subprocess.run([render.ffmpeg(), "-hide_banner", "-loglevel", "error", "-y", *args], check=True)


def make_audio(path: Path, seconds: float = 1.0) -> Path:
    ffmpeg_make(["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "libmp3lame", str(path)])
    return path


def make_clip(path: Path, size=(640, 360), seconds: float = 1.0) -> Path:
    w, h = size
    ffmpeg_make(["-f", "lavfi", "-i", f"testsrc=size={w}x{h}:rate=30:duration={seconds}",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])
    return path


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "test-groq")
    monkeypatch.setattr(settings, "pexels_api_key", "test-pexels")
    monkeypatch.setattr(settings, "youtube_api_key", "")


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.setattr(settings, "groq_api_key", "")
    monkeypatch.setattr(settings, "pexels_api_key", "")


@pytest.fixture
def sample_clip(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("media")
    return make_clip(d / "sample.mp4", seconds=2.0)


@pytest.fixture
def fake_services(monkeypatch, sample_clip):
    """Replace the AI, voice and Pexels calls with deterministic fakes."""
    from app import llm, media, voice

    def fake_chat_json(prompt, **kw):
        if '"scenes"' in prompt:
            return {"scenes": [
                {"narration": "Narrator: The deep sea is darker than you think.", "visual": "deep ocean"},
                {"narration": "[dramatic music] Some fish make their own light.", "visual": "glowing fish"},
                {"narration": "Subscribe for more ocean mysteries.", "visual": "ocean waves"},
            ]}
        if '"ideas"' in prompt:
            return {"ideas": [{"title": "Creatures that live with no sunlight", "angle": "How they survive."}]}
        return {"title": "Deep sea creatures that make their own light",
                "description": "Deep sea creatures live in total darkness. " * 8 + "\nSubscribe for more.",
                "tags": ["deep sea", "bioluminescence", "ocean", "marine life", "anglerfish",
                         "sea creatures", "ocean facts", "science", "nature", "documentary"],
                "hashtags": ["#ocean", "deepsea", "#science"]}

    monkeypatch.setattr(llm, "chat_json", fake_chat_json)

    def fake_speak(text, voice_id, path):
        make_audio(path, 0.8)
        return "edge"

    monkeypatch.setattr(voice, "speak", fake_speak)
    counter = {"n": 0}

    def fake_search_video(query, *, portrait, min_seconds, exclude):
        counter["n"] += 1
        return {"id": counter["n"], "url": "https://example.test/clip.mp4", "duration": 2,
                "credit": "Jane Doe", "page": "https://www.pexels.com/video/1"}

    monkeypatch.setattr(media, "search_video", fake_search_video)
    monkeypatch.setattr(media, "search_photo", lambda q, portrait=False: None)
    monkeypatch.setattr(media, "download", lambda url, path: Path(shutil.copy(sample_clip, path)))
    return counter
