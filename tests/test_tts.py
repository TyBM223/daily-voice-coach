import asyncio

from coach.briefing import Segment
from coach.voice.tts import render


class FakeTTS:
    def __init__(self):
        self.calls = []

    async def synthesize(self, text, voice):
        self.calls.append((text, voice))
        return f"[{voice}:{text}]".encode()


def test_render_uses_phrase_voice_for_foreign_segments_and_joins_in_order():
    tts = FakeTTS()
    segments = [Segment("Your phrase:"), Segment("¿Qué tal?", foreign=True), Segment("It means how's it going.")]

    audio = asyncio.run(render(segments, tts, voice="en-voice", phrase_voice="es-voice"))

    assert tts.calls == [("Your phrase:", "en-voice"), ("¿Qué tal?", "es-voice"), ("It means how's it going.", "en-voice")]
    assert audio == "[en-voice:Your phrase:][es-voice:¿Qué tal?][en-voice:It means how's it going.]".encode()
