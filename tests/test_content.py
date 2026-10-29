import json
from datetime import date, timedelta

import httpx
import pytest

from coach.sources import content
from coach.sources.content import (
    MIX_ORDER,
    Fact,
    HistoryMoment,
    Joke,
    Phrase,
    Quote,
    content_kind,
    pick_content,
    pick_quote,
)

ROTATION = {
    "monday": "phrase",
    "tuesday": "fact",
    "wednesday": "history",
    "thursday": "joke",
    "friday": "phrase_review",
    "saturday": "mix",
    "sunday": "mix",
}
MONDAY = date(2026, 10, 26)
TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = (MONDAY + timedelta(days=n) for n in range(1, 7))


def fake_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def no_network(request):
    raise AssertionError(f"unexpected network call to {request.url}")


# --- rotation ---------------------------------------------------------------

def test_weekday_rotation():
    assert content_kind(MONDAY, ROTATION) == "phrase"
    assert content_kind(TUESDAY, ROTATION) == "fact"
    assert content_kind(WEDNESDAY, ROTATION) == "history"
    assert content_kind(THURSDAY, ROTATION) == "joke"
    assert content_kind(FRIDAY, ROTATION) == "phrase_review"


def test_weekend_mix_varies():
    saturday, sunday = content_kind(SATURDAY, ROTATION), content_kind(SUNDAY, ROTATION)
    assert {saturday, sunday} <= set(MIX_ORDER)
    assert saturday != sunday


# --- phrases ----------------------------------------------------------------

def test_monday_phrase():
    item = pick_content(MONDAY, ROTATION, "Spanish", client=fake_client(no_network))
    assert isinstance(item, Phrase)
    assert item.language == "Spanish" and item.phrase and item.meaning
    assert item.review is False


def test_friday_reviews_mondays_phrase():
    monday = pick_content(MONDAY, ROTATION, "Spanish")
    friday = pick_content(FRIDAY, ROTATION, "Spanish")
    assert friday.review is True
    assert (friday.phrase, friday.meaning) == (monday.phrase, monday.meaning)


def test_each_monday_gets_a_new_phrase():
    deck_size = len(content._load_deck("phrases_spanish"))
    mondays = [content.EPOCH + timedelta(weeks=n) for n in range(deck_size)]
    phrases = [pick_content(day, ROTATION, "Spanish").phrase for day in mondays]
    assert len(set(phrases)) == deck_size


def test_missing_language_deck_falls_back_to_fact():
    assert isinstance(pick_content(MONDAY, ROTATION, "Klingon"), Fact)


# --- facts ------------------------------------------------------------------

def test_facts_dont_repeat_until_deck_is_used_up():
    deck_size = len(content._load_deck("facts"))
    fact_days = [d for d in (content.EPOCH + timedelta(days=n) for n in range(800))
                 if content_kind(d, ROTATION) == "fact"][:deck_size]
    facts = [pick_content(day, ROTATION, "Spanish").text for day in fact_days]
    assert len(set(facts)) == deck_size


# --- history ----------------------------------------------------------------

def wikipedia(events):
    return fake_client(lambda request: httpx.Response(200, json={"selected": events}))


def test_history_skips_grim_events_and_tidies_text():
    events = [
        {"year": 2013, "text": "Attackers drove a vehicle into a crowd, killing five people."},
        {"year": 1940, "text": "World War II: Italy invaded Greece."},
        {"year": 1965, "text": "In St. Louis, the 630-foot (190 m)-tall Gateway Arch was completed."},
    ]
    item = pick_content(WEDNESDAY, ROTATION, "Spanish", client=wikipedia(events))
    assert item == HistoryMoment("In St. Louis, the 630-foot-tall Gateway Arch was completed.", year=1965)


def test_history_requests_todays_date():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(200, json={"selected": [{"year": 1965, "text": "The Gateway Arch was completed."}]})

    pick_content(WEDNESDAY, ROTATION, "Spanish", client=fake_client(handler))
    assert seen == ["/api/rest_v1/feed/onthisday/selected/10/28"]


def test_history_all_grim_falls_back_to_local_deck():
    item = pick_content(WEDNESDAY, ROTATION, "Spanish", client=wikipedia([{"year": 1940, "text": "A war began."}]))
    assert isinstance(item, HistoryMoment) and item.year is None
    assert item.text in content._load_deck("history")


def test_history_outage_falls_back_to_local_deck():
    item = pick_content(WEDNESDAY, ROTATION, "Spanish", client=fake_client(lambda request: httpx.Response(503)))
    assert item.text in content._load_deck("history")


# --- jokes ------------------------------------------------------------------

def jokeapi(payload, status=200):
    return fake_client(lambda request: httpx.Response(status, json=payload))


def test_two_part_joke():
    payload = {"error": False, "safe": True, "type": "twopart", "setup": "Why?", "delivery": "Because!\n"}
    assert pick_content(THURSDAY, ROTATION, "Spanish", client=jokeapi(payload)) == Joke("Why?", "Because!")


def test_one_liner_joke():
    payload = {"error": False, "safe": True, "type": "single", "joke": "A one-liner."}
    assert pick_content(THURSDAY, ROTATION, "Spanish", client=jokeapi(payload)) == Joke("A one-liner.")


@pytest.mark.parametrize("payload, status", [
    ({"error": True, "message": "No matching joke found"}, 200),
    ({"error": False, "safe": False, "type": "single", "joke": "Not safe."}, 200),
    ({}, 500),
])
def test_joke_problems_fall_back_to_local_deck(payload, status):
    item = pick_content(THURSDAY, ROTATION, "Spanish", client=jokeapi(payload, status))
    local = [Joke(**entry) for entry in content._load_deck("jokes")]
    assert item in local


# --- quotes -----------------------------------------------------------------

def test_a_new_quote_every_day_until_the_deck_is_used_up():
    deck_size = len(content._load_deck("quotes"))
    days = [MONDAY + timedelta(days=n) for n in range(deck_size)]
    quotes = [pick_quote(day) for day in days]
    assert all(isinstance(quote, Quote) for quote in quotes)
    assert len({quote.text for quote in quotes}) == deck_size
    assert pick_quote(MONDAY + timedelta(days=deck_size)) == quotes[0]


@pytest.mark.parametrize("contents", [None, "{oops", "[]", '[{"text": "No author."}]'])
def test_unreadable_quotes_give_none(tmp_path, monkeypatch, contents):
    if contents is not None:
        (tmp_path / "quotes.json").write_text(contents, encoding="utf-8")
    monkeypatch.setattr(content, "DECKS_DIR", tmp_path)
    assert pick_quote(MONDAY) is None


# --- decks ------------------------------------------------------------------

@pytest.mark.parametrize("name", ["facts", "history"])
def test_text_decks_are_clean(name):
    deck = content._load_deck(name)
    assert deck and all(isinstance(entry, str) and entry.strip() for entry in deck)
    assert len(set(deck)) == len(deck), "duplicate entries"


def test_phrase_deck_is_clean():
    deck = content._load_deck("phrases_spanish")
    assert len(deck) >= 52, "at least a year of Mondays"
    assert all(entry["phrase"].strip() and entry["meaning"].strip() for entry in deck)
    assert len({entry["phrase"] for entry in deck}) == len(deck), "duplicate phrases"


def test_joke_deck_is_clean():
    deck = content._load_deck("jokes")
    assert all(set(entry) <= {"setup", "punchline"} and entry["setup"].strip() for entry in deck)
    assert len({json.dumps(entry) for entry in deck}) == len(deck), "duplicate jokes"


def test_quote_deck_is_clean():
    deck = content._load_deck("quotes")
    assert len(deck) >= 60, "about two months before a repeat"
    for entry in deck:
        assert set(entry) == {"text", "author"} and entry["author"].strip()
        assert entry["text"].rstrip()[-1] in ".!?", entry["text"]
        assert '"' not in entry["text"], "the written copy adds its own quotation marks"
        # Longer quotes would push the busiest briefing past 75 seconds (see test_briefing).
        assert len(entry["text"].split()) <= 22, entry["text"]
    assert len({entry["text"] for entry in deck}) == len(deck), "duplicate quotes"
