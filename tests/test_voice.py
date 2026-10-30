import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

import coach.main as main


class FakeSTT:
    def __init__(self, words="", fail=False):
        self.words, self.fail, self.hints = words, fail, []

    def transcribe(self, path, hint=""):
        self.hints.append(hint)
        if self.fail:
            raise RuntimeError("model missing")
        return self.words


class VoiceMessage:
    def __init__(self):
        self.date = datetime.now(timezone.utc)
        self.text = None
        self.replies = []
        self.voice = SimpleNamespace(get_file=self._get_file)

    async def _get_file(self):
        async def download_to_drive(path):
            path.write_bytes(b"ogg")
        return SimpleNamespace(download_to_drive=download_to_drive)

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(text)


@pytest.fixture
def coach(tmp_path, monkeypatch):
    tasks = tmp_path / "tasks.json"
    tasks.write_text('{"tasks": [{"text": "Gym", "repeat": "daily"}, {"text": "Finish resume"}]}', encoding="utf-8")
    monkeypatch.setattr(main, "TASKS_PATH", tasks)
    monkeypatch.setattr(main, "DAY_LOG_PATH", tmp_path / "log.json")
    monkeypatch.setattr(main, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(main, "INCOMING_AUDIO_PATH", tmp_path / "incoming.ogg")
    main.save_last_sent(datetime.now(main.ZoneInfo("America/New_York")).date(), tmp_path / "state.json")
    return tmp_path


def run_voice(stt):
    message = VoiceMessage()
    async def chat_action(chat_id, action):
        pass
    context = SimpleNamespace(bot=SimpleNamespace(send_chat_action=chat_action),
                              bot_data={"config": main.load_config(), "chat_id": "42", "stt": stt})
    asyncio.run(main.on_voice(SimpleNamespace(effective_message=message), context))
    return message.replies


def test_a_voice_note_is_handled_like_text_and_echoed(coach):
    stt = FakeSTT("Done, gym.")
    assert run_voice(stt) == ['🎙 "Done, gym."\nNice. Checked off: Gym. 1 to go.']
    assert stt.hints == ["Gym, Finish resume"]  # today's task names help it spell


def test_a_voice_note_it_doesnt_understand_still_shows_what_it_heard(coach):
    replies = run_voice(FakeSTT("How's the weather looking?"))
    assert replies == ['🎙 "How\'s the weather looking?"\n' + main.DIDNT_CATCH]


def test_transcription_failure_is_said_plainly(coach):
    assert run_voice(FakeSTT(fail=True)) == ["I couldn't make out that voice note. Try again, or type it."]


def test_silence(coach):
    assert run_voice(FakeSTT("")) == ["I didn't hear anything in that one. Try again, or type it."]
