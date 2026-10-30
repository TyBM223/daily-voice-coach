"""Plain-word messages from Ty: "done gym", "push resume to tomorrow", "drop the walk",
"add call recruiter tomorrow", "what's left". Simple patterns, no AI: instant and predictable.
Tasks are matched loosely, so part of a task's name is enough ("letter" finds "Finish cover letter").
"""
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from telegram import InlineKeyboardMarkup

from coach.delivery.telegram import task_buttons
from coach.sources.tasks import Task, add_task, drop_task, load_tasks, move_to_tomorrow, task_key, toggle_done

MATCH_THRESHOLD = 0.6  # share of the words Ty typed that must appear in the task's name
# Words that don't help pick a task: "did the gym" and "gym" should match the same way.
FILLER = {"a", "an", "the", "my", "to", "for", "of", "on", "at", "with", "i", "im", "go", "went", "some",
          "that", "this", "it", "today", "task", "just", "already", "also"}

_TOMORROW = r"(?:\s+(?:to|for|until|till)?\s*tomorrow)"
PATTERNS = [
    ("list", re.compile(r"^(?:what'?s|whats|what is)\s+(?:left|next|on my list|on the list)|^(?:list|my tasks|tasks)$")),
    ("help", re.compile(r"^(?:help|what can you do|commands)$")),
    ("thanks", re.compile(r"^(?:thanks|thank you|thx|appreciate it)(?: (?:so much|a lot|man|bro|myles))?$")),
    ("undo", re.compile(r"^(?:undo|uncheck|not done(?: with)?|didn'?t (?:do|finish))\s+(?P<target>.+)$")),
    ("move", re.compile(r"^(?:push|move|bump|postpone|delay|punt)\s+(?P<target>.+?)(?:\s+back)?" + _TOMORROW + r"?$")),
    ("drop", re.compile(r"^(?:drop|delete|remove|cancel|scrap|forget(?: about)?)\s+(?P<target>.+)$")),
    ("add", re.compile(r"^(?:add|todo|to do|new task|remind me to)\s*:?\s+(?P<tomorrow1>tomorrow\s+)?(?P<target>.+?)"
                       r"(?P<tomorrow2>" + _TOMORROW + r")?$")),
    ("done", re.compile(r"^(?:done(?: with)?|did|finished|completed|knocked out|checked off|crushed)\s+(?P<target>.+)$")),
    ("done", re.compile(r"^(?P<target>.+?)\s+(?:is |'s )?(?:done|finished|complete|completed|checked off)$")),
]


@dataclass
class Intent:
    kind: str  # "done", "undo", "move", "drop", "add", "list", "help", "thanks"
    target: str = ""  # the task as Ty typed it
    tomorrow: bool = False  # add: for tomorrow only


@dataclass
class Reply:
    text: str
    buttons: InlineKeyboardMarkup | None = None


def parse(text: str) -> Intent | None:
    """What a message asks for, or None if it isn't one of the plain-word patterns."""
    text = text.replace("’", "'")  # phone keyboards type curly apostrophes
    clean = re.sub(r"\s+", " ", text.strip().lower()).rstrip(".!")
    if not clean or clean.endswith("?") and not clean.startswith(("what", "whats")):
        return None  # a question ("did you see the game?") isn't a request
    clean = clean.rstrip("?")
    clean = re.sub(r"^(\w+),", r"\1", clean)  # "Done, gym." (how speech-to-text writes it) reads as "done gym"
    for kind, pattern in PATTERNS:
        found = pattern.match(clean)
        if found:
            groups = found.groupdict()
            target = _original_case(text, groups.get("target") or "")
            return Intent(kind, target, bool(groups.get("tomorrow1") or groups.get("tomorrow2")))
    return None


def respond(intent: Intent, today: date, tasks_path: Path, log_path: Path) -> Reply:
    """Carry out a task intent ("done", "undo", "move", "drop", "add", "list") and say what happened.
    Raises TasksFileError if tasks.json can't be read."""
    if intent.kind == "add":
        day = today + timedelta(days=1) if intent.tomorrow else None
        if not add_task(tasks_path, intent.target, today, day):
            return Reply(f"That's already on your list: {intent.target}")
        return Reply(f"Added for tomorrow: {intent.target}" if day else f"Added: {intent.target}")

    tasks = load_tasks(tasks_path, today)
    if intent.kind == "list":
        if not tasks:
            return Reply("Nothing on your list today. Add one by typing: add Finish resume")
        return Reply("Today's list. Tap a task when it's done:", task_buttons(tasks, today))

    if intent.kind == "done":
        return _done(intent.target, tasks, today, tasks_path, log_path)

    found = find_tasks(intent.target, tasks)
    if not found:
        return _not_found(intent.target, tasks, today)
    if len(found) > 1:
        return Reply(f"Which one: {_or(found)}? Add a bit more of the name.")
    task = found[0]
    key = task_key(task.text)
    if intent.kind == "undo":
        if not task.done:
            return Reply(f"{task.text} isn't checked off.")
        toggle_done(tasks_path, log_path, key, today)
        return Reply(f"Back on the list: {task.text}")
    if task.daily:
        return Reply(f"{task.text} is a daily habit, so it comes back every day on its own. "
                     "To change that, edit tasks.json.")
    if task.done:  # moving it would reopen it tomorrow; dropping it is pointless (it clears off tomorrow)
        return Reply(f"{task.text} is already checked off today.")
    if intent.kind == "move":
        move_to_tomorrow(tasks_path, key, today)
        return Reply(f"Moved to tomorrow: {task.text}")
    drop_task(tasks_path, key, today)
    return Reply(f"Dropped: {task.text}")


def find_tasks(query: str, tasks: list[Task]) -> list[Task]:
    """The task(s) a few typed words refer to: one if it's clear, several if it's a toss-up, none if nothing fits."""
    scored = [(_score(query, task.text), task) for task in tasks]
    scored = [(score, task) for score, task in scored if score[0] >= MATCH_THRESHOLD]
    if not scored:
        return []
    best = max(hits for (hits, _), _ in scored)
    top = [(covered, task) for (hits, covered), task in scored if hits == best]
    # A tie goes to a task whose whole name was typed ("gym" -> "Gym", not "Pay gym membership").
    # Otherwise it's a real toss-up ("finish" -> resume or cover letter?), so ask.
    whole = [task for covered, task in top if covered == 1.0]
    return whole if len(whole) == 1 else [task for _, task in top]


def _done(target: str, tasks: list[Task], today: date, tasks_path: Path, log_path: Path) -> Reply:
    """Check off one task, or several: "done gym and applications"."""
    whole = find_tasks(target, tasks)
    parts = [target] if len(whole) == 1 else [part for part in re.split(r",|&|\band\b", target) if part.strip()]
    checked, already, missing, unclear = [], [], [], []
    for part in parts:
        found = find_tasks(part, tasks)
        if not found:
            missing.append(part.strip())
        elif len(found) > 1:
            unclear.append(found)
        elif found[0].done:
            already.append(found[0])
        elif found[0] not in checked:
            toggle_done(tasks_path, log_path, task_key(found[0].text), today)
            checked.append(found[0])
    if len(parts) == 1 and missing:
        return _not_found(target, tasks, today)
    if len(parts) == 1 and unclear:
        return Reply(f"Which one: {_or(unclear[0])}? Tap it below.", task_buttons(unclear[0], today))

    lines = []
    if checked:
        lines.append("Nice. Checked off: " + _and([task.text for task in checked]) + ".")
    if already:
        lines.append("Already done: " + _and([task.text for task in already]) + ".")
    if missing:
        lines.append("Couldn't find: " + _and([f'"{part}"' for part in missing]) + ".")
    for options in unclear:
        lines.append(f"Not sure which you meant: {_or(options)}.")
    left = [task for task in load_tasks(tasks_path, today) if not task.done]
    if checked:
        lines.append("That's everything for today." if not left else f"{len(left)} to go.")
    return Reply(" ".join(lines), task_buttons(left, today) if (missing or unclear) and left else None)


def _not_found(target: str, tasks: list[Task], today: date) -> Reply:
    if not tasks:
        return Reply(f'Nothing on today\'s list matches "{target}". The list is empty.')
    return Reply(f'I couldn\'t find "{target}" on today\'s list. Here it is:', task_buttons(tasks, today))


def _score(query: str, task: str) -> tuple[float, float]:
    """(share of the typed words found in the task, share of the task's words that were typed)."""
    typed, words = _words(query), _words(task)
    if not typed or not words:
        return (0.0, 0.0)
    hits = sum(any(_similar(word, other) for other in words) for word in typed)
    covered = sum(any(_similar(word, other) for other in typed) for word in words)
    return (hits / len(typed), covered / len(words))


def _words(text: str) -> list[str]:
    text = re.sub(r"'s\b", "", text.lower().replace("’", "'"))  # "gym's done" -> "gym done"
    return [word for word in re.findall(r"[a-z0-9]+", text) if word not in FILLER]


def _similar(a: str, b: str) -> bool:
    """Same word, or one starts the other ("app" / "applications", "letter" / "letters")."""
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


def _original_case(text: str, lowered: str) -> str:
    """The matched part of the message as Ty typed it, so an added task keeps his capitals."""
    if not lowered:
        return ""
    found = re.search(re.escape(lowered).replace(r"\ ", r"\s+"), text, re.IGNORECASE)
    return found.group(0).strip() if found else lowered


def _and(items: list[str]) -> str:
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + f", and {items[-1]}"


def _or(tasks: list[Task]) -> str:
    names = [task.text for task in tasks]
    return " or ".join(names) if len(names) <= 2 else ", ".join(names[:-1]) + f", or {names[-1]}"
