import asyncio
from datetime import date
from types import SimpleNamespace

from coach.delivery.telegram import (
    KEYBOARD,
    NO_VOICE_NOTE,
    WAKE_BUTTON,
    evening_buttons,
    recent_chats,
    send_briefing,
    task_buttons,
)
from coach.sources.tasks import Task, task_key

DAY = date(2026, 10, 30)


class FakeBot:
    def __init__(self, updates=()):
        self.sent = []
        self.keyboards = []
        self.updates = list(updates)

    async def send_voice(self, chat_id, voice, caption=None, reply_markup=None):
        self.sent.append(("voice", chat_id, voice.read(), caption))
        self.keyboards.append(reply_markup)

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(("message", chat_id, text))
        self.keyboards.append(reply_markup)

    async def get_updates(self):
        return self.updates


def mp3(tmp_path):
    path = tmp_path / "morning.mp3"
    path.write_bytes(b"audio")
    return path


def test_short_text_rides_along_as_the_caption(tmp_path):
    bot = FakeBot()
    asyncio.run(send_briefing(bot, 42, "Morning, Ty.", mp3(tmp_path)))
    assert bot.sent == [("voice", 42, b"audio", "Morning, Ty.")]


def test_long_text_goes_in_its_own_message(tmp_path):
    bot = FakeBot()
    text = "x" * 1500
    asyncio.run(send_briefing(bot, 42, text, mp3(tmp_path)))
    assert bot.sent == [("voice", 42, b"audio", None), ("message", 42, text)]


def test_no_audio_sends_text_with_a_note():
    bot = FakeBot()
    asyncio.run(send_briefing(bot, 42, "Morning, Ty.", None))
    assert bot.sent == [("message", 42, f"{NO_VOICE_NOTE}\n\nMorning, Ty.")]


def test_without_task_buttons_every_message_carries_the_wake_button(tmp_path):
    for audio in (mp3(tmp_path), None):
        for text in ("Morning, Ty.", "x" * 1500):
            bot = FakeBot()
            asyncio.run(send_briefing(bot, 42, text, audio))
            assert bot.keyboards and all(keyboard is KEYBOARD for keyboard in bot.keyboards)
    assert KEYBOARD.keyboard[0][0].text == WAKE_BUTTON


def test_task_buttons_go_on_the_message_with_the_text(tmp_path):
    buttons = task_buttons([Task("Gym")], DAY)
    bot = FakeBot()
    asyncio.run(send_briefing(bot, 42, "Morning, Ty.", mp3(tmp_path), buttons))
    assert bot.keyboards == [buttons]
    bot = FakeBot()
    asyncio.run(send_briefing(bot, 42, "x" * 1500, mp3(tmp_path), buttons))
    assert bot.keyboards == [KEYBOARD, buttons]  # voice note, then the text


def test_task_buttons_show_whats_done():
    buttons = task_buttons([Task("Gym", daily=True, done=True), Task("Finish cover letter")], DAY)
    rows = [row[0] for row in buttons.inline_keyboard]
    assert [button.text for button in rows] == ["✅ Gym", "⬜ Finish cover letter"]
    assert rows[1].callback_data == f"t:2026-10-30:{task_key('Finish cover letter')}"
    assert all(len(button.callback_data.encode()) <= 64 for button in rows)  # Telegram's limit


def test_no_tasks_no_buttons():
    assert task_buttons([], DAY) is None


def test_evening_buttons_cover_only_open_tasks():
    tasks = [Task("Gym", daily=True, done=True), Task("Send applications", daily=True), Task("Call mom")]
    rows = evening_buttons(tasks, DAY).inline_keyboard
    assert [[button.text for button in row] for row in rows] == [
        ["⬜ Send applications"],  # daily: check off only
        ["⬜ Call mom"],
        ["↪ Tomorrow", "✕ Drop"],  # one-off: can also move or drop
    ]
    key = task_key("Call mom")
    assert [button.callback_data for button in rows[2]] == [f"m:2026-10-30:{key}", f"x:2026-10-30:{key}"]
    assert rows[1][0].callback_data == f"e:2026-10-30:{key}"


def test_no_evening_buttons_once_everything_is_done():
    assert evening_buttons([Task("Gym", daily=True, done=True)], DAY) is None


def test_recent_chats_lists_who_messaged_the_bot():
    def update(chat_id, name):
        return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id, first_name=name, title=None, username=None))

    bot = FakeBot([update(111, "Ty"), update(111, "Ty"), SimpleNamespace(effective_chat=None)])
    assert asyncio.run(recent_chats(bot)) == {111: "Ty"}
