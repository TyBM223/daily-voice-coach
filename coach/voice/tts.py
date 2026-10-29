"""Text-to-speech behind a small interface, so edge-tts can be swapped for Piper if it breaks."""
from typing import Protocol

import edge_tts

from coach.briefing import Segment


class TTS(Protocol):
    async def synthesize(self, text: str, voice: str) -> bytes:
        """Return MP3 audio of `text` spoken in `voice`."""


class EdgeTTS:
    """Microsoft Edge's free online voices (no key). Every voice returns the same MP3 format."""

    async def synthesize(self, text: str, voice: str) -> bytes:
        audio = bytearray()
        async for chunk in edge_tts.Communicate(text, voice).stream():
            if chunk["type"] == "audio":
                audio += chunk["data"]
        if not audio:
            raise RuntimeError(f"edge-tts returned no audio for voice {voice}")
        return bytes(audio)


async def render(segments: list[Segment], tts: TTS, voice: str, phrase_voice: str) -> bytes:
    """Speak each segment in the right voice and join them into one MP3.

    edge-tts output is plain MP3 frames with no header, so clips can be joined
    back to back without re-encoding (no ffmpeg needed).
    """
    clips = [await tts.synthesize(s.text, phrase_voice if s.foreign else voice) for s in segments]
    return b"".join(clips)
