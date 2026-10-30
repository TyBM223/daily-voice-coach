"""Speech-to-text for Ty's voice notes, run on this laptop with faster-whisper (free, MIT license).

The model (Whisper base.en, ~150 MB) is downloaded once into coach/data/models, and Hugging
Face's own cache is pointed there too, so nothing is written outside the project. After that
it works offline. A short voice note takes a second or two on the CPU.
"""
import logging
import os
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).resolve().parent.parent / "data" / "models"


class STT(Protocol):
    def transcribe(self, path: Path, hint: str = "") -> str:
        """The words in the audio file. hint lists words likely to come up (task names), to help spelling."""


class WhisperSTT:
    """Loads the model on the first voice note (a few seconds) and keeps it in memory after that."""

    def __init__(self, model: str = "base.en", models_dir: Path = MODELS_DIR):
        self.model_name = model
        self.models_dir = models_dir
        self._model = None

    def transcribe(self, path: Path, hint: str = "") -> str:
        segments, _ = self._load().transcribe(str(path), beam_size=5, vad_filter=True, initial_prompt=hint or None)
        return " ".join(segment.text.strip() for segment in segments).strip()

    def _load(self):
        if self._model is None:
            # Must be set before huggingface_hub is first imported (faster_whisper imports it).
            os.environ.setdefault("HF_HOME", str(self.models_dir / "hf-home"))
            os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            from faster_whisper import WhisperModel  # heavy; only imported once a voice note arrives

            options = {"device": "cpu", "compute_type": "int8", "download_root": str(self.models_dir)}
            try:
                self._model = WhisperModel(self.model_name, local_files_only=True, **options)
            except Exception:  # not downloaded yet: fetch it once
                log.info("Downloading the %s speech model (one time)", self.model_name)
                self._model = WhisperModel(self.model_name, **options)
        return self._model
