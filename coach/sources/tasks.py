"""Today's tasks from data/tasks.json. Ty can edit it by hand, and the bot edits it too
(/add, and tapping a task to check it off).

Each entry is {"text": ...} plus optionally "repeat": "daily" or "date": "YYYY-MM-DD".
  - "repeat": "daily"  -> shows every day
  - no date            -> shows every day until it's done (or deleted)
  - "date"             -> shows only on that day
The bot adds "done": "YYYY-MM-DD" when a task is checked off. A daily task counts as
done only on that date; any other task is hidden from the next day on. Moving a task to
tomorrow (from the evening check-in) sets "from": "YYYY-MM-DD": hidden until that day,
then shown every day until it's done.

Every check-off is also recorded in data/log.json ({"YYYY-MM-DD": {"done": [...]}}),
which keeps the history after finished tasks are cleared out of tasks.json.
"""
import hashlib
import json
import logging
import os
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Task:
    text: str
    daily: bool = False
    done: bool = False  # checked off today


class TasksFileError(Exception):
    """tasks.json exists but can't be read, so the briefing should say so."""


def load_tasks(path: Path, today: date) -> list[Task]:
    """Return every task that shows today, in file order. A missing file means no tasks."""
    return [_task(entry, today) for entry in _read(path) if _shows(entry, today)]


def task_key(text: str) -> str:
    """A short, stable ID for a task, small enough for a Telegram button."""
    return hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


def add_task(path: Path, text: str, today: date, day: date | None = None) -> bool:
    """Add a one-off task (only on `day`, if given). False if it's already on the list."""
    text = text.strip()
    entries = _read(path)
    if any(entry["text"].strip() == text and _shows(entry, day or today) and not _done_on(entry, today)
           for entry in entries):
        return False
    entries.append({"text": text, "date": day.isoformat()} if day else {"text": text})
    _write(path, entries, today)
    return True


def toggle_done(path: Path, log_path: Path, key: str, today: date) -> Task | None:
    """Check off today's task with this key, or un-check it if it was already done.
    Returns the task as it is now, or None if no task showing today has that key."""
    entries = _read(path)
    entry = _find(entries, key, today)
    if entry is None:
        return None
    if _done_on(entry, today):
        del entry["done"]
    else:
        entry["done"] = today.isoformat()
    _write(path, entries, today)
    task = _task(entry, today)
    _log_done(log_path, today, task.text, task.done)
    return task


def move_to_tomorrow(path: Path, key: str, today: date) -> Task | None:
    """Push a one-off task to tomorrow; it then shows every day until it's done.
    None if no one-off task showing today has that key (daily tasks come back anyway)."""
    entries = _read(path)
    entry = _find(entries, key, today)
    if entry is None or entry.get("repeat") == "daily":
        return None
    for field in ("date", "done"):
        entry.pop(field, None)
    entry["from"] = (today + timedelta(days=1)).isoformat()
    _write(path, entries, today)
    return _task(entry, today)


def drop_task(path: Path, key: str, today: date) -> Task | None:
    """Delete a one-off task. None if no one-off task showing today has that key
    (daily tasks are only removed by editing tasks.json, so a stray tap can't delete a habit)."""
    entries = _read(path)
    entry = _find(entries, key, today)
    if entry is None or entry.get("repeat") == "daily":
        return None
    entries.remove(entry)
    _write(path, entries, today)
    return _task(entry, today)


def _find(entries: list[dict], key: str, today: date) -> dict | None:
    return next((entry for entry in entries if task_key(entry["text"]) == key and _shows(entry, today)), None)


def _read(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        # utf-8-sig: Notepad sometimes saves a byte-order mark that plain utf-8 json can't read.
        entries = json.loads(path.read_text(encoding="utf-8-sig"))["tasks"]
        for entry in entries:
            _check(entry)
        return entries
    except (json.JSONDecodeError, KeyError, TypeError, AttributeError, ValueError) as e:
        raise TasksFileError(f"Couldn't read {path.name}: {e}") from e


def _check(entry: dict) -> None:
    if not entry["text"].strip():
        raise ValueError("a task has empty text")
    repeat = entry.get("repeat")
    if repeat is not None and repeat != "daily":
        raise ValueError(f'unknown repeat "{repeat}" (only "daily" is supported)')
    for field in ("date", "done", "from"):
        if field in entry:
            date.fromisoformat(entry[field])


def _shows(entry: dict, today: date) -> bool:
    if entry.get("repeat") == "daily":
        return True
    if _finished_before(entry, today):
        return False
    if "from" in entry and date.fromisoformat(entry["from"]) > today:
        return False  # moved to a later day
    if "date" in entry:
        return date.fromisoformat(entry["date"]) == today
    return True


def _finished_before(entry: dict, today: date) -> bool:
    """A one-off task checked off on an earlier day."""
    return entry.get("repeat") != "daily" and "done" in entry and date.fromisoformat(entry["done"]) < today


def _done_on(entry: dict, day: date) -> bool:
    return entry.get("done") == day.isoformat()


def _task(entry: dict, today: date) -> Task:
    return Task(entry["text"].strip(), daily=entry.get("repeat") == "daily", done=_done_on(entry, today))


def _write(path: Path, entries: list[dict], today: date) -> None:
    """One task per line, like the example file, so it stays easy to edit by hand.
    One-off tasks finished before today are cleared out (log.json keeps the record)."""
    kept = [entry for entry in entries if not _finished_before(entry, today)]
    lines = ",\n".join("    " + json.dumps(entry, ensure_ascii=False) for entry in kept)
    _replace(path, '{\n  "tasks": [\n' + lines + "\n  ]\n}\n" if kept else '{\n  "tasks": []\n}\n')


def _log_done(log_path: Path, day: date, text: str, done: bool) -> None:
    try:
        history = json.loads(log_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        history = {}
    except json.JSONDecodeError as e:
        # Leave a damaged log alone rather than overwrite its history; the check-off itself still counts.
        log.warning("Couldn't update %s: %s", log_path.name, e)
        return
    finished = history.setdefault(day.isoformat(), {}).setdefault("done", [])
    if done and text not in finished:
        finished.append(text)
    elif not done and text in finished:
        finished.remove(text)
    _replace(log_path, json.dumps(history, indent=2, ensure_ascii=False) + "\n")


def _replace(path: Path, text: str) -> None:
    """Write to a temporary file first, so a crash mid-write can't leave a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)
