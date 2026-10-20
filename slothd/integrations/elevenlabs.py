"""ElevenLabs integration for slothd voice summaries.

Generates sloth-themed voice briefings describing what was organized while
the user was resting or away from their computer.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"  # George / Warm conversational narrator


def generate_briefing_script(
    total_files: int,
    categories: dict[str, int],
    batch_count: int = 1,
) -> str:
    """Compose a witty, warm sloth-themed audio briefing script."""
    if total_files == 0:
        return (
            "Good day! Your faithful sloth daemon checked your workspace. "
            "Everything was already immaculate, so I took a well-deserved nap."
        )

    cat_breakdown = ", ".join(f"{count} into {cat}" for cat, count in list(categories.items())[:4])

    return (
        f"Greetings. While you were taking it easy, I moved slowly but steadily. "
        f"I have organized {total_files} files across your workspace, filing {cat_breakdown}. "
        f"All original timestamps have been preserved, and you can undo anytime. "
        f"Now, back to resting."
    )


class ElevenLabsClient:
    """Client for ElevenLabs Text-to-Speech API."""

    def __init__(
        self,
        api_key: str | None = None,
        voice_id: str = DEFAULT_VOICE_ID,
    ) -> None:
        self.api_key = api_key
        self.voice_id = voice_id

    def is_available(self) -> bool:
        return bool(self.api_key)

    def text_to_speech(self, text: str) -> bytes:
        """Convert text to speech MP3 bytes.

        If ElevenLabs API key is missing, returns synthetic WAV audio so the
        dashboard player still has functional audio to demonstrate.
        """
        if not self.api_key:
            logger.debug("ElevenLabs API key not provided; returning synthetic demo audio.")
            return _generate_demo_audio_wav(text)

        try:
            import httpx

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}"
            headers = {
                "xi-api-key": self.api_key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            }
            payload = {
                "text": text,
                "model_id": "eleven_multilingual_v2",
                "voice_settings": {
                    "stability": 0.65,
                    "similarity_boost": 0.8,
                    "style": 0.2,
                },
            }

            resp = httpx.post(url, json=payload, headers=headers, timeout=20.0)
            if resp.status_code == 200:
                return resp.content
            else:
                logger.warning("ElevenLabs API error %d: %s", resp.status_code, resp.text)
                return _generate_demo_audio_wav(text)
        except Exception as e:
            logger.error("ElevenLabs request failed: %s", e)
            return _generate_demo_audio_wav(text)


def _generate_demo_audio_wav(text: str) -> bytes:
    """Generate a valid, gentle ambient chime WAV byte stream as fallback."""
    import io
    import math
    import struct
    import wave

    sample_rate = 22050
    duration_s = 2.5
    num_samples = int(sample_rate * duration_s)

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16-bit
        wav_file.setframerate(sample_rate)

        # Gentle relaxing harmonic chords (Sloth wake sound: E minor chord 330Hz, 392Hz, 493Hz)
        frames = bytearray()
        for i in range(num_samples):
            t = float(i) / sample_rate
            # Fade envelope
            envelope = math.exp(-2.5 * t) if t < 2.0 else 0.0
            val = (
                0.4 * math.sin(2.0 * math.pi * 329.63 * t)
                + 0.3 * math.sin(2.0 * math.pi * 392.00 * t)
                + 0.3 * math.sin(2.0 * math.pi * 493.88 * t)
            ) * envelope
            sample = int(val * 16000.0)
            sample = max(-32768, min(32767, sample))
            frames.extend(struct.pack("<h", sample))

        wav_file.writeframes(frames)

    return buf.getvalue()
