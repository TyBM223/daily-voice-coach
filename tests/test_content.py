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
    load_history,
    pick_content,
    pick_quote,
    recent_phrase,
    record_sent,
    sent_keys,
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


def offline(request):
    raise httpx.ConnectError("offline")  # forces the local decks


def send_daily(days, pick):
    """Pick and "send" on each day in turn, recording each pick like the coach does.
    pick(day, history) returns (kind, key). Returns the keys in order."""
    history, keys = {}, []
    for day in days:
        kind, key = pick(day, history)
        history.setdefault(kind, {})[key] = day
        keys.append(key)
    return keys


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
    friday = pick_content(FRIDAY, ROTATION, "Spanish", history={"phrase": {monday.phrase: MONDAY}})
    assert friday.review is True
    assert (friday.phrase, friday.meaning) == (monday.phrase, monday.meaning)


def test_friday_with_no_phrase_heard_this_week_is_a_fun_fact():
    old = {"phrase": {pick_content(MONDAY, ROTATION, "Spanish").phrase: MONDAY - timedelta(days=7)}}
    assert isinstance(pick_content(FRIDAY, ROTATION, "Spanish", history=old), Fact)


def test_each_monday_gets_a_new_phrase_until_the_deck_is_used_up():
    deck_size = len(content._load_deck("phrases_spanish"))
    mondays = [MONDAY + timedelta(weeks=n) for n in range(deck_size + 1)]
    phrases = send_daily(mondays, lambda day, h: ("phrase", pick_content(day, ROTATION, "Spanish", history=h).phrase))
    assert len(set(phrases[:deck_size])) == deck_size
    assert phrases[deck_size] == phrases[0]  # then the oldest comes back first


@pytest.mark.parametrize("age, reviewed", [(0, False), (1, True), (2, False), (3, True), (7, True), (8, False)])
def test_evening_review_days(age, reviewed):
    phrase = pick_content(MONDAY, ROTATION, "Spanish").phrase
    review = recent_phrase(MONDAY + timedelta(days=age), {"phrase": {phrase: MONDAY}}, "Spanish",
                           ages=content.REVIEW_AFTER_DAYS)
    assert (review is not None) is reviewed
    if reviewed:
        assert review.phrase == phrase and review.review is True


def test_latest_phrase_for_slash_phrase():
    deck = content._load_deck("phrases_spanish")
    history = {"phrase": {deck[0]["phrase"]: MONDAY - timedelta(days=7), deck[1]["phrase"]: MONDAY}}
    assert recent_phrase(TUESDAY, history, "Spanish").phrase == deck[1]["phrase"]
    assert recent_phrase(TUESDAY, {}, "Spanish") is None


def test_missing_language_deck_falls_back_to_fact():
    assert isinstance(pick_content(MONDAY, ROTATION, "Klingon"), Fact)


# --- facts ------------------------------------------------------------------

def test_facts_dont_repeat_until_deck_is_used_up():
    deck_size = len(content._load_deck("facts"))
    tuesdays = [TUESDAY + timedelta(weeks=n) for n in range(deck_size)]
    facts = send_daily(tuesdays, lambda day, h: ("fact", pick_content(day, ROTATION, "Spanish", history=h).text))
    assert len(set(facts)) == deck_size


def test_a_fact_added_to_the_deck_later_still_gets_its_turn(tmp_path, monkeypatch):
    (tmp_path / "facts.json").write_text(json.dumps(["Old one.", "New one."]), encoding="utf-8")
    monkeypatch.setattr(content, "DECKS_DIR", tmp_path)
    item = pick_content(TUESDAY, ROTATION, "Spanish", history={"fact": {"Old one.": MONDAY}})
    assert item == Fact("New one.")


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


def test_history_skips_events_already_told():
    events = [{"year": 1965, "text": "The Gateway Arch was completed."}, {"year": 1886, "text": "Lady Liberty arrived."}]
    told = {"history": {"The Gateway Arch was completed.": MONDAY}}
    item = pick_content(WEDNESDAY, ROTATION, "Spanish", client=wikipedia(events), history=told)
    assert item == HistoryMoment("Lady Liberty arrived.", year=1886)


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


def test_a_joke_already_told_is_skipped():
    told = {"joke": {"Why?": MONDAY}}
    answers = iter([
        {"error": False, "safe": True, "type": "twopart", "setup": "Why?", "delivery": "Because!"},
        {"error": False, "safe": True, "type": "single", "joke": "A new one."},
    ])
    client = fake_client(lambda request: httpx.Response(200, json=next(answers)))
    assert pick_content(THURSDAY, ROTATION, "Spanish", client=client, history=told) == Joke("A new one.")


def test_jokeapi_stuck_on_old_jokes_falls_back_to_the_deck():
    told = {"joke": {"Why?": MONDAY}}
    payload = {"error": False, "safe": True, "type": "twopart", "setup": "Why?", "delivery": "Because!"}
    item = pick_content(THURSDAY, ROTATION, "Spanish", client=jokeapi(payload), history=told)
    assert item in [Joke(**entry) for entry in content._load_deck("jokes")]


# --- quotes -----------------------------------------------------------------

def test_a_new_quote_every_day_until_the_deck_is_used_up():
    deck_size = len(content._load_deck("quotes"))
    days = [MONDAY + timedelta(days=n) for n in range(deck_size + 1)]
    quotes = send_daily(days, lambda day, h: ("quote", pick_quote(h).text))
    assert len(set(quotes[:deck_size])) == deck_size
    assert quotes[deck_size] == quotes[0]
    assert isinstance(pick_quote(), Quote)


@pytest.mark.parametrize("contents", [None, "{oops", "[]", '[{"text": "No author."}]'])
def test_unreadable_quotes_give_none(tmp_path, monkeypatch, contents):
    if contents is not None:
        (tmp_path / "quotes.json").write_text(contents, encoding="utf-8")
    monkeypatch.setattr(content, "DECKS_DIR", tmp_path)
    assert pick_quote() is None


# --- the sent history (data/log.json) ---------------------------------------

def test_sent_keys():
    quote = Quote("Do your job.", "Bill Belichick")
    assert sent_keys(Phrase("Spanish", "¿Qué tal?", "How's it going?"), quote) == {
        "phrase": "¿Qué tal?", "quote": "Do your job."}
    assert sent_keys(Phrase("Spanish", "¿Qué tal?", "How's it going?", review=True), None) == {}
    assert sent_keys(Fact("A fact."), None) == {"fact": "A fact."}
    assert sent_keys(HistoryMoment("An event.", 1965), None) == {"history": "An event."}
    assert sent_keys(Joke("Why?", "Because!"), None) == {"joke": "Why?"}


def test_history_round_trip_keeps_task_check_offs(tmp_path):
    log_path = tmp_path / "log.json"
    log_path.write_text(json.dumps({"2026-10-26": {"done": ["Gym"]}}), encoding="utf-8")
    record_sent(log_path, MONDAY, {"phrase": "¿Qué tal?", "quote": "Do your job."})
    record_sent(log_path, TUESDAY, {"fact": "A fact.", "quote": "Be quick, but don't hurry."})
    assert json.loads(log_path.read_text(encoding="utf-8"))["2026-10-26"]["done"] == ["Gym"]
    assert load_history(log_path) == {
        "phrase": {"¿Qué tal?": MONDAY},
        "quote": {"Do your job.": MONDAY, "Be quick, but don't hurry.": TUESDAY},
        "fact": {"A fact.": TUESDAY},
    }


def test_missing_or_damaged_log_means_a_fresh_start(tmp_path):
    log_path = tmp_path / "log.json"
    assert load_history(log_path) == {}
    log_path.write_text("{oops", encoding="utf-8")
    assert load_history(log_path) == {}
    record_sent(log_path, MONDAY, {"fact": "A fact."})
    assert log_path.read_text(encoding="utf-8") == "{oops"  # left alone, not overwritten


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
