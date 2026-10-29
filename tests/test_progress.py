import json
from datetime import date, timedelta

from coach.progress import Week, load_days, record_list, streak, week

SUNDAY = date(2026, 11, 1)


def days_ago(n):
    return SUNDAY - timedelta(days=n)


def log(entries):
    """{days_ago: {"done": [...], "list": [...]}} -> what load_days returns."""
    return {days_ago(n): entry for n, entry in entries.items()}


# --- streaks ------------------------------------------------------------------

def test_streak_counts_days_in_a_row_through_today():
    days = log({0: {"done": ["Gym"]}, 1: {"done": ["Gym"]}, 2: {"done": ["Gym"]}, 4: {"done": ["Gym"]}})
    assert streak(days, "Gym", SUNDAY) == 3


def test_not_done_yet_today_keeps_yesterdays_run_on_the_line():
    days = log({1: {"done": ["Gym"]}, 2: {"done": ["Gym"]}})
    assert streak(days, "Gym", SUNDAY) == 2


def test_a_missed_day_breaks_it():
    days = log({2: {"done": ["Gym"]}, 3: {"done": ["Gym"]}})
    assert streak(days, "Gym", SUNDAY) == 0


# --- the week -----------------------------------------------------------------

def test_week_report():
    habits = ["Gym", "Send two job applications"]
    days = log({
        6: {"done": ["Gym"], "list": habits + ["Finish cover letter"]},
        5: {"done": ["Gym", "Finish cover letter"], "list": habits + ["Finish cover letter"]},
        4: {"done": ["Gym", "Send two job applications"], "list": habits},
        3: {"done": ["Send two job applications"]},  # evening missed: no list, so not in the rate
        2: {"done": ["Gym"], "list": habits + ["Call mom"]},
        1: {"done": ["Gym", "Call mom"], "list": habits + ["Call mom"]},
        0: {"done": ["Gym", "Late add"], "list": habits},  # "Late add" was added and done after the evening
    })
    report = week(days, habits, SUNDAY)
    assert (report.start, report.end, report.days_tracked) == (days_ago(6), SUNDAY, 7)
    assert (report.done, report.planned, report.rate) == (10, 17, 59)
    assert report.habits == {"Gym": 6, "Send two job applications": 2}
    assert report.wins == ["Finish cover letter", "Call mom", "Late add"]
    assert report.best_streak == ("Gym", 3)


def test_first_week_counts_only_days_since_logging_began():
    days = log({3: {"done": ["Gym"], "list": ["Gym"]}, 0: {"done": [], "list": ["Gym"]}})
    report = week(days, ["Gym"], SUNDAY)
    assert report.days_tracked == 4
    assert report.rate == 50
    assert report.best_streak is None  # a 1-day run isn't a streak


def test_week_without_any_saved_list_has_no_rate():
    report = week(log({0: {"done": ["Gym"]}}), ["Gym"], SUNDAY)
    assert report.rate is None
    assert report.habits == {"Gym": 1}


def test_record_list_keeps_whats_there(tmp_path):
    path = tmp_path / "log.json"
    path.write_text(json.dumps({"2026-11-01": {"done": ["Gym"], "sent": {"quote": "Q"}}}), encoding="utf-8")
    record_list(path, SUNDAY, ["Gym", "Call mom"])
    assert load_days(path) == {SUNDAY: {"done": ["Gym"], "sent": {"quote": "Q"}, "list": ["Gym", "Call mom"]}}


def test_damaged_log_is_left_alone(tmp_path):
    path = tmp_path / "log.json"
    path.write_text("{oops", encoding="utf-8")
    assert load_days(path) == {}
    record_list(path, SUNDAY, ["Gym"])
    assert path.read_text(encoding="utf-8") == "{oops"


def test_rate_rounds():
    assert Week(SUNDAY, SUNDAY, 1, done=2, planned=3).rate == 67
