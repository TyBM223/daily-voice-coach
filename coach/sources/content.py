"""The daily content slot (a language phrase, fun fact, history moment or joke) and the closing quote.

config.yaml's content_rotation decides which kind runs each weekday. Every briefing that
goes out is recorded in data/log.json ("sent"), and picks come from that history: each
kind walks through its deck in order, skips anything already sent, and only repeats once
the whole deck has been used (then the one heard longest ago comes back first). Jokes and
history from the internet are checked against the same history. Entries added to a deck
later simply get their turn.

Phrase reviews also come from the history, so they only ever review a phrase Ty heard.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

from coach.sources import new_client, write_atomic

log = logging.getLogger(__name__)

DECKS_DIR = Path(__file__).resolve().parent.parent / "content_data"
JOKE_URL = "https://v2.jokeapi.dev/joke/Any?safe-mode&blacklistFlags=nsfw,religious,political,racist,sexist,explicit"
HISTORY_URL = "https://en.wikipedia.org/api/rest_v1/feed/onthisday/selected/{month:02d}/{day:02d}"
JOKE_TRIES = 3  # JokeAPI picks at random; ask again if it returns one already told

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MIX_ORDER = ("fact", "history", "joke")
REVIEW_AFTER_DAYS = (1, 3, 7)  # the evening check-in reviews a new phrase this many days after it's taught

# "On this day" events that would make a grim start to the morning get skipped.
GRIM = re.compile(
    r"\b(kill\w*|dead|deaths?|died|dies|massacre\w*|bomb\w*|attack\w*|terror\w*|shoot\w*|shot|"
    r"murder\w*|execut(ed|ion|ions)|wars?|battle\w*|invad\w*|invasion|genocide|crash\w*|"
    r"earthquake\w*|hurricane\w*|disaster\w*|riot\w*|assassinat\w*|hijack\w*|casualt\w*)\b",
    re.IGNORECASE,
)

# What's been sent, by kind ("phrase", "fact", "history", "joke", "quote"): {entry: last day sent}.
# Entries are keyed by their text (a phrase by the phrase itself, a joke by its setup).
History = dict[str, dict[str, date]]


@dataclass
class Phrase:
    language: str
    phrase: str
    meaning: str
    note: str | None = None
    review: bool = False  # True when it's a repeat of a phrase taught earlier


@dataclass
class Fact:
    text: str


@dataclass
class HistoryMoment:
    text: str
    year: int | None = None  # set for Wikipedia "on this day" events


@dataclass
class Joke:
    setup: str
    punchline: str | None = None  # None for one-liners


ContentItem = Phrase | Fact | HistoryMoment | Joke


@dataclass
class Quote:
    """Closes every briefing; separate from the content slot."""
    text: str
    author: str


def content_kind(day: date, rotation: dict) -> str:
    """The content kind scheduled for this day, with "mix" resolved to fact, history or joke."""
    kind = rotation[WEEKDAYS[day.weekday()]]
    if kind == "mix":
        kind = MIX_ORDER[day.toordinal() % len(MIX_ORDER)]
    return kind


def pick_content(day: date, rotation: dict, language: str, client: httpx.Client | None = None,
                 history: History | None = None) -> ContentItem:
    """Today's content item. Online sources fall back to the local decks."""
    history = history or {}
    kind = content_kind(day, rotation)

    if kind == "phrase":
        try:
            entry = _next_entry(_load_deck(_phrase_deck(language)), "phrase", history)
            return Phrase(language, entry["phrase"], entry["meaning"], entry.get("note"))
        except FileNotFoundError:
            log.warning("No phrase deck for %s; using a fun fact instead", language)
            kind = "fact"
    if kind == "phrase_review":
        # Review the most recent new phrase from the past week. Nothing to review yet: a fun fact.
        review = recent_phrase(day, history, language, ages=range(1, 7))
        if review:
            return review
        kind = "fact"

    if kind == "fact":
        return Fact(_next_entry(_load_deck("facts"), "fact", history))
    if kind == "history":
        return (_fetch_history(day, client, history.get("history", {}))
                or HistoryMoment(_next_entry(_load_deck("history"), "history", history)))
    if kind == "joke":
        return _fetch_joke(client, history.get("joke", {})) or Joke(**_next_entry(_load_deck("jokes"), "joke", history))
    raise ValueError(f"Unknown content kind in config.yaml: {kind}")


def pick_quote(history: History | None = None) -> Quote | None:
    """Today's closing quote, or None if quotes.json can't be read (it's meant to be hand-edited)."""
    try:
        entry = _next_entry(_load_deck("quotes"), "quote", history or {})
        return Quote(entry["text"].strip(), entry["author"].strip())
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as e:
        log.warning("Couldn't read quotes.json: %s", e)
        return None


def recent_phrase(day: date, history: History, language: str, ages=None) -> Phrase | None:
    """The newest phrase taught `ages` days before `day` (any time, if ages is None), as a review.
    None if there isn't one, or it's no longer in the deck."""
    taught = {text: sent for text, sent in history.get("phrase", {}).items()
              if ages is None or (day - sent).days in ages}
    if not taught:
        return None
    text = max(taught, key=taught.get)
    try:
        entry = next((e for e in _load_deck(_phrase_deck(language)) if e["phrase"] == text), None)
    except FileNotFoundError:
        return None
    if entry is None:
        return None
    return Phrase(language, entry["phrase"], entry["meaning"], entry.get("note"), review=True)


def sent_keys(item: ContentItem, quote: Quote | None) -> dict[str, str]:
    """What to record in the history once a briefing with this item and quote has gone out.
    Reviews aren't recorded, so a review never pushes back a phrase's review schedule."""
    sent = {}
    match item:
        case Phrase(review=False):
            sent["phrase"] = item.phrase
        case Fact():
            sent["fact"] = item.text
        case HistoryMoment():
            sent["history"] = item.text
        case Joke():
            sent["joke"] = item.setup
    if quote:
        sent["quote"] = quote.text
    return sent


def load_history(log_path: Path) -> History:
    """Everything sent so far, from data/log.json. A missing or damaged log means a fresh start."""
    try:
        days = json.loads(log_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.warning("Couldn't read %s, so picks may repeat: %s", log_path.name, e)
        return {}
    history: History = {}
    for day in sorted(days):
        for kind, text in days[day].get("sent", {}).items():
            history.setdefault(kind, {})[text] = date.fromisoformat(day)
    return history


def record_sent(log_path: Path, day: date, sent: dict[str, str]) -> None:
    """Add what went out today to data/log.json. A damaged log is left alone, not overwritten."""
    try:
        days = json.loads(log_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        days = {}
    except json.JSONDecodeError as e:
        log.warning("Couldn't update %s: %s", log_path.name, e)
        return
    days.setdefault(day.isoformat(), {}).setdefault("sent", {}).update(sent)
    write_atomic(log_path, json.dumps(days, indent=2, ensure_ascii=False) + "\n")


def _phrase_deck(language: str) -> str:
    return f"phrases_{language.lower()}"


def _load_deck(name: str) -> list:
    return json.loads((DECKS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _key(entry, kind: str) -> str:
    """How an entry is named in the history."""
    if isinstance(entry, str):
        return entry
    return entry[{"phrase": "phrase", "joke": "setup"}.get(kind, "text")]


def _next_entry(deck: list, kind: str, history: History):
    """The first entry never sent; once all have been, the one sent longest ago."""
    used = history.get(kind, {})
    fresh = [entry for entry in deck if _key(entry, kind) not in used]
    if fresh:
        return fresh[0]
    return min(deck, key=lambda entry: used[_key(entry, kind)])


def _fetch_history(day: date, client: httpx.Client | None, used: dict[str, date]) -> HistoryMoment | None:
    """A non-grim Wikipedia "on this day" event not sent before, or None if Wikipedia is unavailable."""
    try:
        with (client or new_client()) as http:
            response = http.get(HISTORY_URL.format(month=day.month, day=day.day))
            response.raise_for_status()
            events = response.json()["selected"]
        candidates = [event for event in events
                      if not GRIM.search(event["text"]) and _tidy(event["text"]) not in used]
        if not candidates:
            return None
        event = candidates[day.year % len(candidates)]
        return HistoryMoment(_tidy(event["text"]), year=int(event["year"]))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
        log.warning("Wikipedia On This Day unavailable: %s", e)
        return None


def _tidy(text: str) -> str:
    """Drop asides like "(pictured)" or "(190 m)" that sound odd read aloud."""
    return re.sub(r"\s+", " ", re.sub(r"\s*\([^)]*\)", "", text)).strip()


def _fetch_joke(client: httpx.Client | None, used: dict[str, date]) -> Joke | None:
    """A safe-mode joke from JokeAPI that hasn't been told before, or None if there isn't one."""
    try:
        with (client or new_client()) as http:
            for _ in range(JOKE_TRIES):
                response = http.get(JOKE_URL)
                response.raise_for_status()
                data = response.json()
                if data.get("error") or not data.get("safe"):
                    log.warning("JokeAPI returned no safe joke")
                    return None
                if data["type"] == "single":
                    joke = Joke(data["joke"].strip())
                else:
                    joke = Joke(data["setup"].strip(), data["delivery"].strip())
                if joke.setup not in used:
                    return joke
        log.info("JokeAPI kept repeating old jokes; using the local deck")
        return None
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as e:
        log.warning("JokeAPI unavailable: %s", e)
        return None
