import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from coach.main import (
    CANT_READ_YET,
    RedactingFormatter,
    load_last_sent,
    morning_time,
    parse_add,
    save_last_sent,
    slot_due,
    wake_reply,
)

TZ = ZoneInfo("America/New_York")
EIGHT = time(8, 0)


def at(hour, minute=0, day=29):
    return datetime(2026, 10, day, hour, minute, tzinfo=TZ)


@pytest.mark.parametrize("now, last_sent, due", [
    (at(7, 59), None, False),  # too early
    (at(8, 0), None, True),  # on time
    (at(9, 30), None, True),  # laptop woke up late, still within the grace window
    (at(10, 59), None, True),
    (at(11, 0), None, False),  # too late for a "morning" briefing
    (at(8, 0), date(2026, 10, 29), False),  # already sent today
    (at(8, 0), date(2026, 10, 28), True),  # sent yesterday
])
def test_slot_due(now, last_sent, due):
    assert slot_due(now, EIGHT, last_sent) is due


SCHEDULE = {"morning_weekdays": "09:00", "morning_weekends": "wake", "wake_earliest": "06:00", "wake_latest": "12:00"}


@pytest.mark.parametrize("day, expected", [
    (date(2026, 10, 30), time(9, 0)),  # Friday: the set time
    (date(2026, 10, 31), time(12, 0)),  # Saturday: wake day, so noon is the no-tap fallback
    (date(2026, 11, 1), time(12, 0)),  # Sunday
    (date(2026, 11, 2), time(9, 0)),  # Monday
])
def test_weekdays_and_weekends_have_their_own_time(day, expected):
    assert morning_time(SCHEDULE, day) == expected


@pytest.mark.parametrize("sent_at, last_sent, text, expected", [
    (at(10, 14, day=31), None, "I'm up", None),  # Saturday, up at 10:14: send it now
    (at(10, 14, day=31), None, "morning", None),  # any message counts
    (at(6, 0, day=31), None, "I'm up", None),
    (at(2, 30, day=31), None, "I'm up", "after 6:00 AM"),  # still Friday night, really
    (at(10, 14, day=31), date(2026, 10, 31), "I'm up", "already went out"),
    (at(10, 14, day=31), date(2026, 10, 31), "done gym", CANT_READ_YET),  # not the button: say what works
    (at(7, 0, day=30), None, "I'm up", "comes at 9:00 AM"),  # Friday: weekdays keep their set time
    (at(10, 30, day=30), None, "I'm up", None),  # Friday, past 9:00 and nothing sent (laptop was asleep)
    (at(10, 30, day=30), date(2026, 10, 30), "I'm up", "already went out"),
])
def test_wake_reply(sent_at, last_sent, text, expected):
    reply = wake_reply(sent_at, SCHEDULE, last_sent, text)
    assert reply == expected if expected is None else expected in reply


@pytest.mark.parametrize("args, expected", [
    ("Finish resume", ("Finish resume", None)),
    ("  Finish resume  ", ("Finish resume", None)),
    ("tomorrow Call mom", ("Call mom", date(2026, 10, 30))),
    ("Tomorrow  Call mom", ("Call mom", date(2026, 10, 30))),
    ("tomorrow", ("", date(2026, 10, 30))),
    ("", ("", None)),
])
def test_parse_add(args, expected):
    assert parse_add(args, date(2026, 10, 29)) == expected


def test_last_sent_round_trip(tmp_path):
    path = tmp_path / "state.json"
    assert load_last_sent(path) is None  # no file yet
    save_last_sent(date(2026, 10, 29), path)
    assert load_last_sent(path) == date(2026, 10, 29)
    save_last_sent(None, path)
    assert load_last_sent(path) is None


def test_each_slot_keeps_its_own_date(tmp_path):
    path = tmp_path / "state.json"
    save_last_sent(date(2026, 10, 29), path)
    save_last_sent(date(2026, 10, 28), path, slot="evening")
    assert load_last_sent(path) == date(2026, 10, 29)
    assert load_last_sent(path, slot="evening") == date(2026, 10, 28)
    assert load_last_sent(path, slot="midday") is None


def test_corrupt_state_file_is_treated_as_not_sent(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{oops", encoding="utf-8")
    assert load_last_sent(path) is None


def test_token_is_masked_in_messages_and_tracebacks():
    token = "123456:SECRET-token"
    formatter = RedactingFormatter("%(message)s", token)
    try:
        raise ValueError(f"The token `{token}` was rejected by the server.")
    except ValueError as e:
        record = logging.LogRecord("coach", logging.ERROR, __file__, 1, "failed: %s", (e,), exc_info=True)
        record.exc_info = __import__("sys").exc_info()
    text = formatter.format(record)
    assert token not in text
    assert "[BOT TOKEN]" in text
