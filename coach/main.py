"""Coach entrypoint.

Usage (from the repo root):
    python -m coach.main          # run on schedule (long-running)
    python -m coach.main --now    # make the morning briefing once, right away
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml
from dotenv import load_dotenv

from coach.briefing import Briefing, build_briefing
from coach.sources.content import pick_content
from coach.sources.tasks import TasksFileError, load_tasks
from coach.sources.weather import fetch_weather
from coach.voice.tts import EdgeTTS, render

log = logging.getLogger("coach")

PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PACKAGE_DIR / "config.yaml"
DATA_DIR = PACKAGE_DIR / "data"
AUDIO_PATH = DATA_DIR / "audio" / "morning.mp3"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


async def prepare_morning(config: dict, now: datetime) -> tuple[Briefing, Path]:
    """Gather today's info, build the briefing, and save it as an MP3."""
    today = now.date()
    location = config["location"]
    weather = await asyncio.to_thread(
        fetch_weather, location["lat"], location["lon"], config["timezone"], config["temperature_unit"]
    )
    try:
        tasks = load_tasks(DATA_DIR / "tasks.json", today)
    except TasksFileError as e:
        log.warning("%s", e)
        tasks = None
    item = await asyncio.to_thread(pick_content, today, config["content_rotation"], config["language_to_learn"])
    briefing = build_briefing(config["owner_name"], location["name"], now, weather, tasks, item)

    audio = await render(briefing.segments, EdgeTTS(), config["voice"], config["phrase_voice"])
    AUDIO_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIO_PATH.write_bytes(audio)
    return briefing, AUDIO_PATH


def main() -> None:
    parser = argparse.ArgumentParser(description="Coach: daily voice check-ins.")
    parser.add_argument("--now", action="store_true", help="make the morning briefing once, right away")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    # httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sys.stdout.reconfigure(errors="replace")  # older Windows consoles can't print every accent

    load_dotenv(PACKAGE_DIR.parent / ".env")
    config = load_config()

    if not args.now:
        raise SystemExit("Scheduled mode isn't built yet (v1 group 4). Use --now.")

    now = datetime.now(ZoneInfo(config["timezone"]))
    briefing, audio_path = asyncio.run(prepare_morning(config, now))
    print(briefing.text)
    print(f"\nAudio saved to {audio_path}")


if __name__ == "__main__":
    main()
