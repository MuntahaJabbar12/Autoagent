"""All settings come from environment variables (or a local .env file).

Nothing secret is ever written in code. Copy .env.example to .env and fill it in.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / "assets"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except ValueError:
        return default


@dataclass
class Settings:
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    groq_model: str = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    groq_base_url: str = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
    pexels_api_key: str = os.getenv("PEXELS_API_KEY", "")
    youtube_api_key: str = os.getenv("YOUTUBE_API_KEY", "")  # optional

    output_dir: Path = Path(os.getenv("OUTPUT_DIR", str(ROOT / "output")))
    max_videos_per_hour: int = _int("MAX_VIDEOS_PER_HOUR", 4)  # per visitor
    max_queue: int = _int("MAX_QUEUE", 6)
    workers: int = _int("WORKERS", 1)
    keep_minutes: int = _int("KEEP_MINUTES", 120)  # finished videos are deleted after this

    def missing(self) -> list[str]:
        """Keys the app cannot run without."""
        return [name for name, value in (("GROQ_API_KEY", self.groq_api_key),
                                         ("PEXELS_API_KEY", self.pexels_api_key)) if not value]


settings = Settings()
