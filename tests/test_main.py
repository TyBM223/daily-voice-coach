import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from coach.main import RedactingFormatter, load_last_sent, morning_due, morning_time, save_last_sent

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
def test_morning_due(now, last_sent, due):
    assert morning_due(now, EIGHT, last_sent) is due


@pytest.mark.parametrize("day, expected", [
    (date(2026, 10, 30), time(9, 0)),  # Friday
    (date(2026, 10, 31), time(8, 0)),  # Saturday
    (date(2026, 11, 1), time(8, 0)),  # Sunday
    (date(2026, 11, 2), time(9, 0)),  # Monday
])
def test_weekdays_and_weekends_have_their_own_time(day, expected):
    schedule = {"morning_weekdays": "09:00", "morning_weekends": "08:00"}
    assert morning_time(schedule, day) == expected


def test_last_sent_round_trip(tmp_path):
    path = tmp_path / "state.json"
    assert load_last_sent(path) is None  # no file yet
    save_last_sent(date(2026, 10, 29), path)
    assert load_last_sent(path) == date(2026, 10, 29)
    save_last_sent(None, path)
    assert load_last_sent(path) is None


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
