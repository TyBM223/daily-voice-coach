import json
from datetime import date
from pathlib import Path

import pytest

from coach.sources.tasks import TasksFileError, load_tasks

TODAY = date(2026, 10, 29)
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
    assert load_tasks(path, TODAY) == ["Gym", "Finish cover letter", "Dentist"]


def test_missing_file_means_no_tasks(tmp_path):
    assert load_tasks(tmp_path / "tasks.json", TODAY) == []


def test_empty_list(tmp_path):
    assert load_tasks(write(tmp_path, []), TODAY) == []


def test_notepad_byte_order_mark_is_fine(tmp_path):
    assert load_tasks(write(tmp_path, [{"text": "Gym"}], encoding="utf-8-sig"), TODAY) == ["Gym"]


def test_example_file_is_valid():
    assert "Gym" in load_tasks(EXAMPLE, TODAY)


@pytest.mark.parametrize("content", [
    '{"tasks": [{"text": "Gym"} {"text": "Run"}]}',  # missing comma
    '{"todo": []}',  # wrong top-level key
    '{"tasks": [{"name": "Gym"}]}',  # missing text
    '{"tasks": [{"text": "  "}]}',  # empty text
    '{"tasks": [{"text": "Gym", "repeat": "dialy"}]}',  # typo in repeat
    '{"tasks": [{"text": "Call", "date": "10/30/2026"}]}',  # wrong date format
    '{"tasks": ["Gym"]}',  # plain string instead of an entry
])
def test_broken_file_raises_clear_error(tmp_path, content):
    path = tmp_path / "tasks.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(TasksFileError, match="tasks.json"):
        load_tasks(path, TODAY)
