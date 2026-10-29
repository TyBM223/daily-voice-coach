import json
from datetime import date

import pytest

from coach.messages import Intent, find_tasks, parse, respond
from coach.sources.tasks import Task, load_tasks

TODAY = date(2026, 10, 30)
TOMORROW = date(2026, 10, 31)
TASKS = [
    {"text": "Gym", "repeat": "daily"},
    {"text": "Send two job applications", "repeat": "daily"},
    {"text": "Finish cover letter"},
    {"text": "go walk/run for 5 minutes"},
    {"text": "Finish resume"},
]


@pytest.fixture
def files(tmp_path):
    tasks = tmp_path / "tasks.json"
    tasks.write_text(json.dumps({"tasks": TASKS}), encoding="utf-8")
    return tasks, tmp_path / "log.json"


def say(files, text):
    intent = parse(text)
    assert intent is not None, f"not understood: {text}"
    return respond(intent, TODAY, *files)


def done_texts(files):
    return [task.text for task in load_tasks(files[0], TODAY) if task.done]


# --- understanding ------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("done gym", Intent("done", "gym")),
    ("Done with the cover letter.", Intent("done", "the cover letter")),
    ("did my applications", Intent("done", "my applications")),
    ("finished resume!", Intent("done", "resume")),
    ("gym done", Intent("done", "gym")),
    ("Gym’s done", Intent("done", "Gym's")),
    ("cover letter is finished", Intent("done", "cover letter")),
    ("undo gym", Intent("undo", "gym")),
    ("not done with gym", Intent("undo", "gym")),
    ("push resume to tomorrow", Intent("move", "resume")),
    ("move the cover letter", Intent("move", "the cover letter")),
    ("push the walk back", Intent("move", "the walk")),
    ("drop the walk", Intent("drop", "the walk")),
    ("forget about the walk", Intent("drop", "the walk")),
    ("add Call recruiter tomorrow", Intent("add", "Call recruiter", tomorrow=True)),
    ("add tomorrow Call mom", Intent("add", "Call mom", tomorrow=True)),
    ("remind me to email Sarah", Intent("add", "email Sarah")),
    ("what's left?", Intent("list")),
    ("Whats next", Intent("list")),
    ("help", Intent("help")),
    ("thanks man", Intent("thanks")),
])
def test_parse(text, expected):
    assert parse(text) == expected


@pytest.mark.parametrize("text", ["did you see the game?", "morning", "I'm up", "done", "how are you", ""])
def test_not_a_request(text):
    assert parse(text) is None


# --- matching ------------------------------------------------------------------

def tasks(*texts):
    return [Task(text) for text in texts]


def test_part_of_the_name_is_enough():
    found = find_tasks("letter", tasks("Gym", "Finish cover letter"))
    assert [task.text for task in found] == ["Finish cover letter"]


def test_prefixes_count():
    assert find_tasks("apps", tasks("Send two job applications")) == []  # "apps" isn't a prefix of "applications"
    assert len(find_tasks("app", tasks("Send two job applications"))) == 1


def test_more_matching_words_win():
    found = find_tasks("finish resume", tasks("Finish resume", "Finish cover letter"))
    assert [task.text for task in found] == ["Finish resume"]


def test_a_whole_name_beats_a_longer_task():
    found = find_tasks("gym", tasks("Pay gym membership", "Gym"))
    assert [task.text for task in found] == ["Gym"]


def test_a_toss_up_returns_both():
    found = find_tasks("finish", tasks("Finish resume", "Finish taxes"))
    assert len(found) == 2


# --- doing it -------------------------------------------------------------------

def test_done_checks_it_off_and_counts_whats_left(files):
    reply = say(files, "done gym")
    assert reply.text == "Nice. Checked off: Gym. 4 to go."
    assert done_texts(files) == ["Gym"]
    assert json.loads(files[1].read_text(encoding="utf-8")) == {"2026-10-30": {"done": ["Gym"]}}


def test_done_twice_doesnt_undo_it(files):
    say(files, "done gym")
    assert say(files, "gym done").text == "Already done: Gym."
    assert done_texts(files) == ["Gym"]


def test_several_at_once(files):
    reply = say(files, "done gym, the cover letter and applications")
    assert reply.text == ("Nice. Checked off: Gym, Finish cover letter, and Send two job applications. 2 to go.")


def test_several_with_one_missing(files):
    reply = say(files, "done gym and taxes")
    assert reply.text == 'Nice. Checked off: Gym. Couldn\'t find: "taxes". 4 to go.'
    assert reply.buttons is not None  # the open tasks, to tap instead


def test_everything_done(files):
    say(files, "done gym, applications, cover letter, walk")
    assert say(files, "finished resume").text == "Nice. Checked off: Finish resume. That's everything for today."


def test_not_found_shows_the_list(files):
    reply = say(files, "done taxes")
    assert reply.text == 'I couldn\'t find "taxes" on today\'s list. Here it is:'
    assert len(reply.buttons.inline_keyboard) == 5


def test_ambiguous_done_offers_buttons(files):
    reply = say(files, "done finish")
    assert reply.text == "Which one: Finish cover letter or Finish resume? Tap it below."
    assert [row[0].text for row in reply.buttons.inline_keyboard] == ["⬜ Finish cover letter", "⬜ Finish resume"]
    assert done_texts(files) == []


def test_undo(files):
    say(files, "done gym")
    assert say(files, "undo gym").text == "Back on the list: Gym"
    assert say(files, "undo gym").text == "Gym isn't checked off."


def test_move_and_drop(files):
    assert say(files, "push resume to tomorrow").text == "Moved to tomorrow: Finish resume"
    assert say(files, "drop the walk").text == "Dropped: go walk/run for 5 minutes"
    assert [task.text for task in load_tasks(files[0], TODAY)] == [
        "Gym", "Send two job applications", "Finish cover letter"]
    assert "Finish resume" in [task.text for task in load_tasks(files[0], TOMORROW)]


def test_a_finished_task_isnt_moved_or_dropped(files):
    say(files, "done the walk")
    assert say(files, "push the walk back").text == "go walk/run for 5 minutes is already checked off today."
    assert "go walk/run for 5 minutes" in done_texts(files)
    assert "go walk/run for 5 minutes" not in [task.text for task in load_tasks(files[0], TOMORROW)]


def test_daily_habits_cant_be_moved_or_dropped(files):
    reply = say(files, "drop gym")
    assert reply.text.startswith("Gym is a daily habit")
    assert "Gym" in [task.text for task in load_tasks(files[0], TODAY)]


def test_add_keeps_capitals_and_dates(files):
    assert say(files, "add Call Recruiter Dana tomorrow").text == "Added for tomorrow: Call Recruiter Dana"
    assert say(files, "remind me to email Sarah").text == "Added: email Sarah"
    assert "Call Recruiter Dana" in [task.text for task in load_tasks(files[0], TOMORROW)]
    assert "Call Recruiter Dana" not in [task.text for task in load_tasks(files[0], TODAY)]


def test_whats_left_lists_with_buttons(files):
    reply = say(files, "what's left")
    assert reply.text == "Today's list. Tap a task when it's done:"
    assert len(reply.buttons.inline_keyboard) == 5
