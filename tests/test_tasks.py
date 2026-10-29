import json
from datetime import date
from pathlib import Path

import pytest

from coach.sources.tasks import (
    Task,
    TasksFileError,
    add_task,
    drop_task,
    load_tasks,
    move_to_tomorrow,
    task_key,
    toggle_done,
)

TODAY = date(2026, 10, 29)
TOMORROW = date(2026, 10, 30)
EXAMPLE = Path(__file__).resolve().parent.parent / "coach" / "tasks.example.json"


def write(tmp_path, tasks, encoding="utf-8"):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"tasks": tasks}), encoding=encoding)
    return path


def test_daily_undated_and_dated_rules(tmp_path):
    path = write(tmp_path, [
        {"text": "Gym", "repeat": "daily"},
        {"text": "Finish cover letter"},
        {"text": "Dentist", "date": "2026-10-29"},
        {"text": "Call mom", "date": "2026-10-30"},
        {"text": "Old thing", "date": "2026-10-01"},
    ])
    assert load_tasks(path, TODAY) == [
        Task("Gym", daily=True),
        Task("Finish cover letter"),
        Task("Dentist"),
    ]


def test_missing_file_means_no_tasks(tmp_path):
    assert load_tasks(tmp_path / "tasks.json", TODAY) == []


def test_empty_list(tmp_path):
    assert load_tasks(write(tmp_path, []), TODAY) == []


def test_notepad_byte_order_mark_is_fine(tmp_path):
    assert load_tasks(write(tmp_path, [{"text": "Gym"}], encoding="utf-8-sig"), TODAY) == [Task("Gym")]


def test_example_file_is_valid():
    assert Task("Gym", daily=True) in load_tasks(EXAMPLE, TODAY)


@pytest.mark.parametrize("content", [
    '{"tasks": [{"text": "Gym"} {"text": "Run"}]}',  # missing comma
    '{"todo": []}',  # wrong top-level key
    '{"tasks": [{"name": "Gym"}]}',  # missing text
    '{"tasks": [{"text": "  "}]}',  # empty text
    '{"tasks": [{"text": "Gym", "repeat": "dialy"}]}',  # typo in repeat
    '{"tasks": [{"text": "Call", "date": "10/30/2026"}]}',  # wrong date format
    '{"tasks": ["Gym"]}',  # plain string instead of an entry
    '{"tasks": [{"text": "Gym", "done": "yesterday"}]}',  # bad done date
])
def test_broken_file_raises_clear_error(tmp_path, content):
    path = tmp_path / "tasks.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(TasksFileError, match="tasks.json"):
        load_tasks(path, TODAY)


# --- checking tasks off -----------------------------------------------------

def tap(tmp_path, text, day=TODAY):
    return toggle_done(tmp_path / "tasks.json", tmp_path / "log.json", task_key(text), day)


def done_log(tmp_path):
    return json.loads((tmp_path / "log.json").read_text(encoding="utf-8"))


def test_checking_off_a_daily_task_lasts_only_that_day(tmp_path):
    path = write(tmp_path, [{"text": "Gym", "repeat": "daily"}])
    assert tap(tmp_path, "Gym") == Task("Gym", daily=True, done=True)
    assert load_tasks(path, TODAY) == [Task("Gym", daily=True, done=True)]
    assert load_tasks(path, TOMORROW) == [Task("Gym", daily=True)]  # back again tomorrow


def test_a_finished_one_off_task_disappears_the_next_day(tmp_path):
    path = write(tmp_path, [{"text": "Finish cover letter"}, {"text": "Call mom", "date": "2026-10-29"}])
    tap(tmp_path, "Finish cover letter")
    assert load_tasks(path, TODAY) == [Task("Finish cover letter", done=True), Task("Call mom")]
    assert load_tasks(path, TOMORROW) == []


def test_tapping_again_undoes_it(tmp_path):
    path = write(tmp_path, [{"text": "Finish cover letter"}])
    tap(tmp_path, "Finish cover letter")
    assert tap(tmp_path, "Finish cover letter") == Task("Finish cover letter")
    assert load_tasks(path, TOMORROW) == [Task("Finish cover letter")]
    assert done_log(tmp_path) == {"2026-10-29": {"done": []}}


def test_check_offs_are_logged_by_day(tmp_path):
    write(tmp_path, [{"text": "Gym", "repeat": "daily"}, {"text": "Finish cover letter"}])
    tap(tmp_path, "Gym")
    tap(tmp_path, "Finish cover letter")
    tap(tmp_path, "Gym", day=TOMORROW)
    assert done_log(tmp_path) == {
        "2026-10-29": {"done": ["Gym", "Finish cover letter"]},
        "2026-10-30": {"done": ["Gym"]},
    }


def test_a_damaged_log_is_left_alone(tmp_path):
    write(tmp_path, [{"text": "Gym", "repeat": "daily"}])
    (tmp_path / "log.json").write_text("{oops", encoding="utf-8")
    assert tap(tmp_path, "Gym").done  # the check-off still counts
    assert (tmp_path / "log.json").read_text(encoding="utf-8") == "{oops"


def test_unknown_or_other_day_task_is_not_found(tmp_path):
    write(tmp_path, [{"text": "Call mom", "date": "2026-10-30"}])
    assert tap(tmp_path, "Nope") is None
    assert tap(tmp_path, "Call mom") is None  # it's for tomorrow


def test_old_finished_tasks_are_cleared_out_but_future_ones_stay(tmp_path):
    path = write(tmp_path, [
        {"text": "Old win", "done": "2026-10-27"},
        {"text": "Call mom", "date": "2026-10-30"},
        {"text": "Gym", "repeat": "daily", "done": "2026-10-27"},
        {"text": "Finish cover letter"},
    ])
    tap(tmp_path, "Finish cover letter")
    texts = [entry["text"] for entry in json.loads(path.read_text(encoding="utf-8"))["tasks"]]
    assert texts == ["Call mom", "Gym", "Finish cover letter"]


def test_written_file_stays_one_task_per_line(tmp_path):
    path = write(tmp_path, [{"text": "Gym", "repeat": "daily"}, {"text": "Café run"}])
    tap(tmp_path, "Gym")
    assert path.read_text(encoding="utf-8") == (
        '{\n  "tasks": [\n'
        '    {"text": "Gym", "repeat": "daily", "done": "2026-10-29"},\n'
        '    {"text": "Café run"}\n'
        '  ]\n}\n'
    )


def test_a_broken_file_is_never_overwritten(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text('{"tasks": [{"text": "Gym"} {"text": "Run"}]}', encoding="utf-8")
    with pytest.raises(TasksFileError):
        tap(tmp_path, "Gym")
    with pytest.raises(TasksFileError):
        add_task(path, "Run", TODAY)
    assert path.read_text(encoding="utf-8") == '{"tasks": [{"text": "Gym"} {"text": "Run"}]}'


# --- moving and dropping (evening check-in) ---------------------------------

def test_moved_task_skips_today_then_stays_until_done(tmp_path):
    path = write(tmp_path, [{"text": "Call mom", "date": "2026-10-29"}, {"text": "Finish cover letter"}])
    assert move_to_tomorrow(path, task_key("Call mom"), TODAY) == Task("Call mom")
    assert load_tasks(path, TODAY) == [Task("Finish cover letter")]
    assert Task("Call mom") in load_tasks(path, TOMORROW)
    assert Task("Call mom") in load_tasks(path, date(2026, 11, 5))  # no longer tied to one date


def test_a_moved_task_that_was_checked_off_comes_back_open(tmp_path):
    path = write(tmp_path, [{"text": "Finish cover letter", "done": "2026-10-29"}])
    move_to_tomorrow(path, task_key("Finish cover letter"), TODAY)
    assert load_tasks(path, TOMORROW) == [Task("Finish cover letter")]


def test_drop_deletes_a_one_off_task(tmp_path):
    path = write(tmp_path, [{"text": "Gym", "repeat": "daily"}, {"text": "Finish cover letter"}])
    assert drop_task(path, task_key("Finish cover letter"), TODAY) == Task("Finish cover letter")
    assert load_tasks(path, TODAY) == [Task("Gym", daily=True)]


def test_daily_tasks_cant_be_moved_or_dropped(tmp_path):
    path = write(tmp_path, [{"text": "Gym", "repeat": "daily"}])
    assert move_to_tomorrow(path, task_key("Gym"), TODAY) is None
    assert drop_task(path, task_key("Gym"), TODAY) is None
    assert load_tasks(path, TODAY) == [Task("Gym", daily=True)]


def test_bad_from_date_is_a_clear_error(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text('{"tasks": [{"text": "Call", "from": "soon"}]}', encoding="utf-8")
    with pytest.raises(TasksFileError):
        load_tasks(path, TODAY)


# --- adding tasks -----------------------------------------------------------

def test_add_task_stays_until_done(tmp_path):
    path = tmp_path / "tasks.json"  # no file yet
    assert add_task(path, " Finish resume ", TODAY)
    assert load_tasks(path, TODAY) == [Task("Finish resume")]
    assert load_tasks(path, TOMORROW) == [Task("Finish resume")]


def test_add_task_for_tomorrow(tmp_path):
    path = write(tmp_path, [])
    assert add_task(path, "Call mom", TODAY, TOMORROW)
    assert load_tasks(path, TODAY) == []
    assert load_tasks(path, TOMORROW) == [Task("Call mom")]


def test_add_task_skips_duplicates(tmp_path):
    path = write(tmp_path, [{"text": "Finish resume"}])
    assert not add_task(path, "Finish resume", TODAY)
    assert len(load_tasks(path, TODAY)) == 1
