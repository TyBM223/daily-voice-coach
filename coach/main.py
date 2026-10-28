"""Coach entrypoint.

Usage (from the repo root):
    python -m coach.main          # run on schedule (long-running)
    python -m coach.main --now    # send the morning briefing once, right away
"""
import argparse
from pathlib import Path

import yaml
from dotenv import load_dotenv

PACKAGE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = PACKAGE_DIR / "config.yaml"
DATA_DIR = PACKAGE_DIR / "data"


def load_config(path: Path = CONFIG_PATH) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="Coach: daily voice check-ins.")
    parser.add_argument("--now", action="store_true", help="send the morning briefing once, right away")
    parser.parse_args()

    load_dotenv(PACKAGE_DIR.parent / ".env")
    load_config()

    raise SystemExit("The briefing isn't built yet (v1 groups 2-4).")


if __name__ == "__main__":
    main()
