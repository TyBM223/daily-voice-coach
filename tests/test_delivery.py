import asyncio
from types import SimpleNamespace

from coach.delivery.telegram import KEYBOARD, NO_VOICE_NOTE, WAKE_BUTTON, recent_chats, send_briefing


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


def test_every_message_carries_the_wake_button(tmp_path):
    for audio in (mp3(tmp_path), None):
        for text in ("Morning, Ty.", "x" * 1500):
            bot = FakeBot()
            asyncio.run(send_briefing(bot, 42, text, audio))
            assert bot.keyboards and all(keyboard is KEYBOARD for keyboard in bot.keyboards)
    assert KEYBOARD.keyboard[0][0].text == WAKE_BUTTON


def test_recent_chats_lists_who_messaged_the_bot():
    def update(chat_id, name):
        return SimpleNamespace(effective_chat=SimpleNamespace(id=chat_id, first_name=name, title=None, username=None))

    bot = FakeBot([update(111, "Ty"), update(111, "Ty"), SimpleNamespace(effective_chat=None)])
    assert asyncio.run(recent_chats(bot)) == {111: "Ty"}
