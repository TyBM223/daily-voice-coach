"""Streaks and the weekly report, from data/log.json.

Each day in the log can hold "done" (tasks checked off, written by tasks.py) and "list"
(the day's whole task list, saved at the evening check-in). Streaks count daily habits;
the week report adds a completion rate (only over days that have a saved list, so a day
the laptop was off doesn't count as perfect), wins (one-off tasks finished) and the best streak.
"""
import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from coach.sources import write_atomic

log = logging.getLogger(__name__)

WEEK = 7


@dataclass
class Week:
    start: date
    end: date
    days_tracked: int  # days in the week since the coach started logging
    done: int = 0  # tasks checked off, on days with a saved list
    planned: int = 0  # tasks on the list, on those same days
    habits: dict[str, int] = field(default_factory=dict)  # daily task -> days done this week
    wins: list[str] = field(default_factory=list)  # one-off tasks finished this week
    best_streak: tuple[str, int] | None = None

    @property
    def rate(self) -> int | None:
        """Percent of planned tasks done, or None if no day this week has a saved list."""
        return round(100 * self.done / self.planned) if self.planned else None


def load_days(log_path: Path) -> dict[date, dict]:
    """The log by day. A missing or damaged log reads as empty (nothing to report yet)."""
    try:
        raw = json.loads(log_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.warning("Couldn't read %s: %s", log_path.name, e)
        return {}
    return {date.fromisoformat(day): entry for day, entry in raw.items()}


def streak(days: dict[date, dict], task: str, today: date) -> int:
    """Days in a row a habit was done, up to today. If it isn't done yet today, the run through
    yesterday still counts: that's the streak on the line."""
    def done_on(day: date) -> bool:
        return task in days.get(day, {}).get("done", [])

    day = today if done_on(today) else today - timedelta(days=1)
    count = 0
    while done_on(day):
        count += 1
        day -= timedelta(days=1)
    return count


def week(days: dict[date, dict], habits: list[str], today: date) -> Week:
    """The 7 days ending today. habits are the daily tasks, as they're named now."""
    start = today - timedelta(days=WEEK - 1)
    logged = [day for day in days if day <= today]
    first = max(start, min(logged)) if logged else today
    report = Week(start, today, days_tracked=(today - first).days + 1)
    habit_set = set(habits)
    for offset in range(WEEK):
        day = start + timedelta(days=offset)
        entry = days.get(day, {})
        done = set(entry.get("done", []))
        if "list" in entry:
            on_list = set(entry["list"]) | done  # something added and finished after the evening counts too
            report.planned += len(on_list)
            report.done += len(done & on_list)
        for task in entry.get("done", []):  # in the order they were checked off
            if task in habit_set:
                report.habits[task] = report.habits.get(task, 0) + 1
            elif task not in report.wins:
                report.wins.append(task)
    for habit in habits:
        report.habits.setdefault(habit, 0)
    streaks = [(habit, streak(days, habit, today)) for habit in habits]
    best = max(streaks, key=lambda pair: pair[1], default=None)
    report.best_streak = best if best and best[1] >= 2 else None
    return report


def record_list(log_path: Path, day: date, tasks: list[str]) -> None:
    """Save the day's whole task list (done and open) for the week's completion rate.
    A damaged log is left alone, not overwritten."""
    try:
        raw = json.loads(log_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raw = {}
    except json.JSONDecodeError as e:
        log.warning("Couldn't update %s: %s", log_path.name, e)
        return
    raw.setdefault(day.isoformat(), {})["list"] = tasks
    write_atomic(log_path, json.dumps(raw, indent=2, ensure_ascii=False) + "\n")
