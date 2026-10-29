import asyncio

from coach.briefing import Segment
from coach.voice.tts import render


class FakeTTS:
    def __init__(self):
        self.calls = []

    async def synthesize(self, text, voice, slow=False):
        self.calls.append((text, voice, slow))
        return f"[{voice}:{text}]".encode()


def test_render_uses_phrase_voice_for_foreign_segments_and_joins_in_order():
    tts = FakeTTS()
    segments = [
        Segment("Your phrase:"),
        Segment("¿Qué tal?", foreign=True),
        Segment("Slowly:"),
        Segment("¿Qué tal?", foreign=True, slow=True),
    ]

    audio = asyncio.run(render(segments, tts, voice="en-voice", phrase_voice="es-voice"))

    assert tts.calls == [
        ("Your phrase:", "en-voice", False),
        ("¿Qué tal?", "es-voice", False),
        ("Slowly:", "en-voice", False),
        ("¿Qué tal?", "es-voice", True),
    ]
    assert audio == "[en-voice:Your phrase:][es-voice:¿Qué tal?][en-voice:Slowly:][es-voice:¿Qué tal?]".encode()
