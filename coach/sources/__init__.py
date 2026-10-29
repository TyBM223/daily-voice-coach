"""Data sources for the briefing: weather, tasks, daily content."""
import os
from pathlib import Path

import httpx

USER_AGENT = "CoachBot/0.1 (https://github.com/TyBM223/daily-voice-coach)"


def new_client() -> httpx.Client:
    """HTTP client for the free APIs: short timeout, and a User-Agent (Wikipedia requires one)."""
    return httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT})


def write_atomic(path: Path, text: str) -> None:
    """Write to a temporary file first, so a crash mid-write can't leave a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)
