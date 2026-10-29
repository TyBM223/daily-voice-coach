"""Today's tasks from data/tasks.json, a file Ty edits by hand.

Each entry is {"text": ...} plus optionally "repeat": "daily" or "date": "YYYY-MM-DD".
  - "repeat": "daily"  -> shows every day
  - no date            -> shows every day until it's deleted
  - "date"             -> shows only on that day
"""
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass
class Task:
    text: str
    daily: bool = False


class TasksFileError(Exception):
    """tasks.json exists but can't be read, so the briefing should say so."""


def load_tasks(path: Path, today: date) -> list[Task]:
    """Return every task that applies today, in file order. A missing file means no tasks."""
    if not path.exists():
        return []
    try:
        # utf-8-sig: Notepad sometimes saves a byte-order mark that plain utf-8 json can't read.
        entries = json.loads(path.read_text(encoding="utf-8-sig"))["tasks"]
        return [
            Task(entry["text"].strip(), daily=entry.get("repeat") == "daily")
            for entry in entries
            if _applies(entry, today)
        ]
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ValueError) as e:
        raise TasksFileError(f"Couldn't read {path.name}: {e}") from e


def _applies(entry: dict, today: date) -> bool:
    if not entry["text"].strip():
        raise ValueError("a task has empty text")
    repeat = entry.get("repeat")
    if repeat is not None and repeat != "daily":
        raise ValueError(f'unknown repeat "{repeat}" (only "daily" is supported)')
    if repeat == "daily":
        return True
    if "date" in entry:
        return date.fromisoformat(entry["date"]) == today
    return True
