"""The daily content slot: a language phrase, fun fact, history moment or joke.

config.yaml's content_rotation decides which kind runs each weekday. Picks from
the local decks follow the date, so v1 stores nothing: each kind walks through
its deck in order and only repeats once the whole deck has been used.
"""
import json
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import httpx

from coach.sources import new_client

log = logging.getLogger(__name__)

DECKS_DIR = Path(__file__).resolve().parent.parent / "content_data"
JOKE_URL = "https://v2.jokeapi.dev/joke/Any?safe-mode&blacklistFlags=nsfw,religious,political,racist,sexist,explicit"
HISTORY_URL = "https://en.wikipedia.org/api/rest_v1/feed/onthisday/selected/{month:02d}/{day:02d}"

WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MIX_ORDER = ("fact", "history", "joke")
EPOCH = date(2026, 1, 5)  # a Monday; deck positions are counted from here

# "On this day" events that would make a grim start to the morning get skipped.
GRIM = re.compile(
    r"\b(kill\w*|dead|deaths?|died|dies|massacre\w*|bomb\w*|attack\w*|terror\w*|shoot\w*|shot|"
    r"murder\w*|execut(ed|ion|ions)|wars?|battle\w*|invad\w*|invasion|genocide|crash\w*|"
    r"earthquake\w*|hurricane\w*|disaster\w*|riot\w*|assassinat\w*|hijack\w*|casualt\w*)\b",
    re.IGNORECASE,
)


@dataclass
class Phrase:
    language: str
    phrase: str
    meaning: str
    note: str | None = None
    review: bool = False  # True on review days: a repeat of the week's new phrase


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


def content_kind(day: date, rotation: dict) -> str:
    """The content kind scheduled for this day, with "mix" resolved to fact, history or joke."""
    kind = rotation[WEEKDAYS[day.weekday()]]
    if kind == "mix":
        kind = MIX_ORDER[day.toordinal() % len(MIX_ORDER)]
    return kind


def pick_content(day: date, rotation: dict, language: str, client: httpx.Client | None = None) -> ContentItem:
    """Today's content item. Online sources fall back to the local decks."""
    kind = content_kind(day, rotation)

    if kind in ("phrase", "phrase_review"):
        try:
            return _pick_phrase(day, kind, rotation, language)
        except FileNotFoundError:
            log.warning("No phrase deck for %s; using a fun fact instead", language)
            kind = "fact"

    if kind == "fact":
        return Fact(_deck_entry("facts", day, "fact", rotation))
    if kind == "history":
        return _fetch_history(day, client) or HistoryMoment(_deck_entry("history", day, "history", rotation))
    if kind == "joke":
        return _fetch_joke(client) or Joke(**_deck_entry("jokes", day, "joke", rotation))
    raise ValueError(f"Unknown content kind in config.yaml: {kind}")


def _load_deck(name: str) -> list:
    return json.loads((DECKS_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _deck_index(day: date, kind: str, rotation: dict, size: int) -> int:
    """How many days since EPOCH ran this kind before `day`, wrapped to the deck size."""
    earlier = (date.fromordinal(n) for n in range(EPOCH.toordinal(), day.toordinal()))
    uses = sum(1 for d in earlier if content_kind(d, rotation) == kind)
    return uses % size


def _deck_entry(name: str, day: date, kind: str, rotation: dict):
    deck = _load_deck(name)
    return deck[_deck_index(day, kind, rotation, len(deck))]


def _pick_phrase(day: date, kind: str, rotation: dict, language: str) -> Phrase:
    phrase_day = day
    if kind == "phrase_review":
        # Review the most recent new phrase from the past week.
        for back in range(1, 7):
            earlier = day - timedelta(days=back)
            if content_kind(earlier, rotation) == "phrase":
                phrase_day = earlier
                break
    entry = _deck_entry(f"phrases_{language.lower()}", phrase_day, "phrase", rotation)
    return Phrase(language, entry["phrase"], entry["meaning"], entry.get("note"), review=phrase_day != day)


def _fetch_history(day: date, client: httpx.Client | None) -> HistoryMoment | None:
    """A non-grim Wikipedia "on this day" event, or None if Wikipedia is unavailable."""
    try:
        with (client or new_client()) as http:
            response = http.get(HISTORY_URL.format(month=day.month, day=day.day))
            response.raise_for_status()
            events = response.json()["selected"]
        candidates = [event for event in events if not GRIM.search(event["text"])]
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


def _fetch_joke(client: httpx.Client | None) -> Joke | None:
    """A safe-mode joke from JokeAPI, or None if it's unavailable."""
    try:
        with (client or new_client()) as http:
            response = http.get(JOKE_URL)
            response.raise_for_status()
            data = response.json()
        if data.get("error") or not data.get("safe"):
            log.warning("JokeAPI returned no safe joke")
            return None
        if data["type"] == "single":
            return Joke(data["joke"].strip())
        return Joke(data["setup"].strip(), data["delivery"].strip())
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as e:
        log.warning("JokeAPI unavailable: %s", e)
        return None
