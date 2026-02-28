"""
Voice command recognition service using OpenAI Whisper (local inference).

Requirements:
    pip install openai-whisper  (or faster-whisper for lower VRAM)
    pacman -S ffmpeg

Whisper model is loaded once and reused.  The model name is controlled by
the WHISPER_MODEL env-var (default: "base" — fast, ~74 MB).
For better accuracy on Russian/English set WHISPER_MODEL=small or medium.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Optional

from loguru import logger

# ---------------------------------------------------------------------------
# Whisper loader — graceful fallback when package is absent
# ---------------------------------------------------------------------------
try:
    import whisper as _whisper  # openai-whisper

    _MODEL_NAME = os.getenv("WHISPER_MODEL", "base")
    _model: Optional[_whisper.Whisper] = None  # lazy-loaded

    def _get_model() -> _whisper.Whisper:
        global _model
        if _model is None:
            logger.info(f"Loading Whisper model '{_MODEL_NAME}'…")
            _model = _whisper.load_model(_MODEL_NAME)
            logger.info("Whisper model loaded.")
        return _model

    WHISPER_AVAILABLE = True
except ImportError:
    WHISPER_AVAILABLE = False
    logger.warning(
        "openai-whisper not installed. Voice commands disabled. "
        "Install with: pip install openai-whisper"
    )


# ---------------------------------------------------------------------------
# Command vocabulary — keyword → normalized command token
# ---------------------------------------------------------------------------
COMMAND_MAP: dict[str, str] = {
    # Power
    "перезагрузи": "reboot",
    "перезагрузка": "reboot",
    "reboot": "reboot",
    "restart": "reboot",
    "выключи": "shutdown",
    "выключение": "shutdown",
    "shutdown": "shutdown",
    "poweroff": "shutdown",
    "отмени выключение": "cancel",
    "отмена выключения": "cancel",
    "cancel shutdown": "cancel",
    # Screenshot
    "скриншот": "screenshot",
    "сделай скриншот": "screenshot",
    "screenshot": "screenshot",
    "снимок экрана": "screenshot",
    # Status / processes
    "статус": "status",
    "status": "status",
    "процессы": "processes",
    "processes": "processes",
    "список процессов": "processes",
    # Dota
    "дота": "dota",
    "dota": "dota",
    "статус доты": "dota",
    "dota status": "dota",
    # WoL
    "включи компьютер": "wake",
    "wake": "wake",
    "разбуди компьютер": "wake",
}


class VoiceCommandService:
    """Transcribes a Telegram voice/audio file and maps it to a bot command."""

    def __init__(self) -> None:
        self._available = WHISPER_AVAILABLE

    @property
    def available(self) -> bool:
        return self._available

    async def transcribe(self, ogg_bytes: bytes) -> Optional[str]:
        """
        Transcribe raw OGG/Opus audio bytes (from Telegram voice message).

        Returns the transcribed text or None on failure.
        Runs Whisper inference in a thread-pool to avoid blocking the event loop.
        """
        if not self._available:
            return None

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as f:
            f.write(ogg_bytes)
            tmp_path = f.name

        try:
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, self._run_whisper, tmp_path)
            logger.info(f"Whisper transcription: {text!r}")
            return text
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    @staticmethod
    def _run_whisper(audio_path: str) -> str:
        """Blocking Whisper call — executed in thread pool."""
        model = _get_model()
        result = model.transcribe(audio_path, language=None, task="transcribe")
        return result.get("text", "").strip()

    def parse_command(self, text: str) -> Optional[str]:
        """
        Map transcribed text to a bot command token.

        Returns one of: reboot, shutdown, cancel, screenshot, status,
        processes, dota, wake — or None if not recognised.
        """
        text_lower = text.lower().strip()

        # Exact match first
        if text_lower in COMMAND_MAP:
            return COMMAND_MAP[text_lower]

        # Substring match (first hit wins, sorted by key length descending
        # so longer phrases match before shorter ones)
        for phrase in sorted(COMMAND_MAP, key=len, reverse=True):
            if phrase in text_lower:
                return COMMAND_MAP[phrase]

        return None

    # ------------------------------------------------------------------
    # Convenience: transcribe + parse in one call
    # ------------------------------------------------------------------
    async def process_voice(self, ogg_bytes: bytes) -> tuple[Optional[str], Optional[str]]:
        """
        Transcribe and parse a voice message.

        Returns:
            (transcribed_text, command_token)
            Both may be None on failure / unrecognised command.
        """
        text = await self.transcribe(ogg_bytes)
        if text is None:
            return None, None
        command = self.parse_command(text)
        return text, command