import os
from pathlib import Path

from openai import AsyncOpenAI

SUPPORTED = {".mp3", ".mp4", ".m4a", ".wav", ".webm"}


async def transcribe(data: bytes, filename: str) -> str:
    if Path(filename).suffix.lower() not in SUPPORTED:
        raise ValueError("Use MP3, MP4, M4A, WAV or WebM audio.")
    if len(data) > 1_000_000:
        raise ValueError("Audio must be under 1 MB.")
    key = os.getenv("OPENAI_API_KEY", "").strip()
    if not key:
        raise ValueError("Audio transcription needs OPENAI_API_KEY. Text input works without it.")
    async with AsyncOpenAI(api_key=key, timeout=15, max_retries=0) as client:
        try:
            result = await client.audio.transcriptions.create(
                file=(Path(filename).name, data),
                model=os.getenv("TRANSCRIBE_MODEL", "gpt-4o-mini-transcribe-2025-12-15"),
            )
        except Exception as exc:
            raise ValueError(
                "Audio could not be transcribed. Send text or try a shorter recording."
            ) from exc
    if not result.text.strip():
        raise ValueError("No speech was transcribed. Send your report as text.")
    return result.text
