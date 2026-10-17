"""Bounded, transient audio preprocessing. Raw clips never enter learner storage."""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

from openai import AsyncOpenAI

SUPPORTED = {
    ".mp3": {"mp3"},
    ".mp4": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    ".m4a": {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"},
    ".wav": {"wav"},
    ".webm": {"matroska", "webm"},
}


async def validate_audio(data: bytes, filename: str) -> None:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise ValueError("Use MP3, MP4, M4A, WAV or WebM audio.")
    if not data or len(data) > 1_000_000:
        raise ValueError("Provide nonempty audio under 1 MB.")
    probe = shutil.which("ffprobe")
    decoder = shutil.which("ffmpeg")
    if not probe or not decoder:
        raise ValueError(
            "Audio validation needs ffprobe and ffmpeg. Install FFmpeg or use text input."
        )
    # A private temporary file is removed on success, cancellation and validation failure.
    process = None
    with tempfile.TemporaryDirectory(prefix="loke-audio-") as folder:
        path = Path(folder) / ("clip" + suffix)
        path.write_bytes(data)
        try:
            process = await asyncio.create_subprocess_exec(
                probe,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-show_entries",
                "format=duration,format_name:stream=codec_type,duration",
                "-of",
                "json",
                str(path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            output, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode:
                raise ValueError(
                    "Audio could not be decoded. Upload a valid recording or use text."
                )
            info = json.loads(output)
            streams = info.get("streams", [])
            if not any(s.get("codec_type") == "audio" for s in streams) or any(
                s.get("codec_type") != "audio" for s in streams
            ):
                raise ValueError("Provide an audio-only recording.")
            formats = set(info.get("format", {}).get("format_name", "").split(","))
            if not formats & SUPPORTED[suffix]:
                raise ValueError("The audio format does not match its filename.")
            # Browser WebM often omits duration metadata. Measure decoded PCM locally,
            # stopping after 31 seconds and bounding output to less than 1 MB.
            process = await asyncio.create_subprocess_exec(
                decoder,
                "-v",
                "error",
                "-protocol_whitelist",
                "file,pipe",
                "-i",
                str(path),
                "-map",
                "0:a:0",
                "-t",
                "31",
                "-f",
                "s16le",
                "-ac",
                "1",
                "-ar",
                "16000",
                "pipe:1",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            pcm, _ = await asyncio.wait_for(process.communicate(), timeout=5)
            if process.returncode or not pcm:
                raise ValueError(
                    "Audio could not be decoded. Upload a valid recording or use text."
                )
            if len(pcm) / 32000 > 30.5:
                raise ValueError("Audio must be at most 30 seconds long.")
        except (TimeoutError, json.JSONDecodeError, TypeError, KeyError) as exc:
            raise ValueError("Audio validation failed. Upload a shorter clip or use text.") from exc
        finally:
            if process and process.returncode is None:
                process.kill()
                await process.wait()


async def transcribe(data: bytes, filename: str) -> str:
    await validate_audio(data, filename)
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
    if len(result.text) > 15000:
        raise ValueError("Transcript exceeds 15,000 characters. Try a shorter clip.")
    return result.text
