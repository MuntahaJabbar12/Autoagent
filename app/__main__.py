"""Run locally with:  python -m app"""
import os
import threading
import webbrowser

import uvicorn

from .config import settings

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    if settings.missing():
        print("\n  Missing keys:", ", ".join(settings.missing()))
        print("  Copy .env.example to .env and add them, then run again.\n")
    threading.Timer(1.5, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    uvicorn.run("app.main:app", host="127.0.0.1", port=port)
