"""
DukaanVoice — Gnani Voice AI Provider Module
Integrates:
- Gnani Prisma v3.0: Multilingual Speech-to-Text (STT)
- Gnani Timbre v3.0: Indic Text-to-Speech (TTS)
Official API Endpoint Base: https://api.vachana.ai
Authentication: Header 'X-API-Key-ID'
"""

import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv
import httpx


class GnaniError(Exception):
    """Base exception for all Gnani Voice AI provider errors."""
    pass


class GnaniNotConfiguredError(GnaniError):
    """Raised when Gnani API credentials are not set in environment."""
    pass


class GnaniAuthenticationError(GnaniError):
    """Raised when Gnani API key is missing, invalid, or expired (HTTP 401)."""
    pass


class GnaniTimeoutError(GnaniError):
    """Raised when Gnani API request times out."""
    pass


class GnaniNetworkError(GnaniError):
    """Raised when network or DNS connection to Gnani API fails."""
    pass


class GnaniAudioError(GnaniError):
    """Raised when audio payload or parameters are invalid or unsupported (HTTP 400/422)."""
    pass


class GnaniRateLimitError(GnaniError):
    """Raised when Gnani API quota or rate limit is exceeded (HTTP 429)."""
    pass


class GnaniProviderError(GnaniError):
    """Raised when Gnani API returns an unexpected server error (HTTP 5xx)."""
    pass


class GnaniConfig:
    """Manages Gnani Voice AI configuration and credentials from environment variables."""

    def __init__(self):
        self.reload()

    def reload(self):
        backend_env = Path(__file__).resolve().parent / ".env"
        if backend_env.exists():
            load_dotenv(backend_env, override=False)
        self.api_key = os.getenv("GNANI_API_KEY") or os.getenv("VACHANA_API_KEY") or os.getenv("API_KEY") or ""
        self.stt_url = os.getenv("GNANI_STT_URL") or "https://api.vachana.ai/stt/v3"
        self.tts_url = os.getenv("GNANI_TTS_URL") or "https://api.vachana.ai/api/v1/tts/inference"
        self.stt_model = os.getenv("GNANI_STT_MODEL") or "prisma-v3.0"
        self.tts_model = os.getenv("GNANI_TTS_MODEL") or "timbre-v3.0"
        self.tts_voice = os.getenv("GNANI_TTS_VOICE") or "Shivani"
        self.timeout_seconds = float(os.getenv("GNANI_TIMEOUT_SECONDS", "10.0"))

    @property
    def is_configured(self) -> bool:
        """Returns True if a valid non-empty API key is present."""
        return bool(self.api_key and self.api_key.strip())

    def get_public_status(self) -> dict[str, Any]:
        """Returns safe status metadata without exposing secrets."""
        return {
            "provider": "Gnani Voice AI (Vachana Platform)",
            "is_configured": self.is_configured,
            "stt_model": self.stt_model,
            "tts_model": self.tts_model,
            "tts_voice": self.tts_voice,
            "stt_endpoint": self.stt_url,
            "tts_endpoint": self.tts_url,
            "fallback_active": not self.is_configured,
            "fallback_provider": "Browser Web Speech API",
            "status_note": (
                "Gnani Prisma v3.0 & Timbre v3.0 active"
                if self.is_configured
                else "Gnani credentials not configured in environment; fallback is active."
            )
        }


class GnaniPrismaSTTProvider:
    """
    Adapter for Gnani Prisma v3.0 Speech-to-Text (STT).
    Official endpoint: POST https://api.vachana.ai/stt/v3
    """

    MAX_AUDIO_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

    def __init__(self, config: GnaniConfig, client: httpx.Client | None = None):
        self.config = config
        self._client = client

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self.config.timeout_seconds)

    def transcribe_audio(
        self,
        audio_bytes: bytes,
        filename: str = "audio.wav",
        content_type: str = "audio/wav",
        language_code: str = "kn-IN"
    ) -> dict[str, Any]:
        """
        Sends audio bytes to Gnani Prisma v3.0 STT endpoint.
        Returns dictionary with transcript, detected_language, and latency.
        """
        if not self.config.is_configured:
            raise GnaniNotConfiguredError(
                "Gnani API key is not configured. Configure GNANI_API_KEY to use Prisma v3.0."
            )

        if not audio_bytes or len(audio_bytes) == 0:
            raise GnaniAudioError("Audio payload is empty.")

        if len(audio_bytes) > self.MAX_AUDIO_SIZE_BYTES:
            raise GnaniAudioError(
                f"Audio payload size ({len(audio_bytes)} bytes) exceeds 10MB limit."
            )

        headers = {
            "X-API-Key-ID": self.config.api_key.strip(),
        }

        files = {
            "audio_file": (filename, audio_bytes, content_type)
        }
        data = {
            "model": self.config.stt_model,
            "language_code": language_code
        }

        try:
            client = self._get_client()
            response = client.post(
                self.config.stt_url,
                headers=headers,
                files=files,
                data=data
            )
        except httpx.TimeoutException as e:
            raise GnaniTimeoutError(f"Prisma STT request timed out: {e}") from e
        except (httpx.ConnectError, httpx.NetworkError) as e:
            raise GnaniNetworkError(f"Prisma STT network connection failed: {e}") from e
        except Exception as e:
            raise GnaniProviderError(f"Unexpected error communicating with Prisma STT: {e}") from e

        # Handle HTTP status codes
        if response.status_code == 200:
            try:
                res_json = response.json()
            except Exception as e:
                raise GnaniProviderError(f"Invalid JSON returned by Prisma STT: {e}") from e

            transcript = res_json.get("transcript", "")
            return {
                "success": True,
                "transcript": transcript,
                "detected_language": res_json.get("detected_language_code") or language_code,
                "model": res_json.get("model", self.config.stt_model),
                "request_id": res_json.get("request_id"),
                "processing_time": res_json.get("processing_time")
            }

        elif response.status_code == 401:
            err_msg = "Invalid or missing Gnani API key."
            try:
                err_detail = response.json().get("detail", {})
                if isinstance(err_detail, dict):
                    err_msg = err_detail.get("message", err_msg)
            except Exception:
                pass
            raise GnaniAuthenticationError(f"Prisma STT authentication failure: {err_msg}")

        elif response.status_code in (400, 422):
            err_msg = "Invalid audio or parameters sent to Prisma STT."
            try:
                err_json = response.json()
                err_msg = err_json.get("message") or str(err_json.get("detail", err_msg))
            except Exception:
                pass
            raise GnaniAudioError(f"Prisma STT validation error: {err_msg}")

        elif response.status_code == 429:
            raise GnaniRateLimitError("Prisma STT rate limit or quota exceeded.")

        else:
            raise GnaniProviderError(
                f"Prisma STT returned HTTP error {response.status_code}: {response.text[:200]}"
            )


class GnaniTimbreTTSProvider:
    """
    Adapter for Gnani Timbre v3.0 Text-to-Speech (TTS).
    Official endpoint: POST https://api.vachana.ai/api/v1/tts/inference
    """

    MAX_TEXT_LENGTH = 1000

    def __init__(self, config: GnaniConfig, client: httpx.Client | None = None):
        self.config = config
        self._client = client

    def _get_client(self) -> httpx.Client:
        if self._client is not None:
            return self._client
        return httpx.Client(timeout=self.config.timeout_seconds)

    def synthesize_speech(
        self,
        text: str,
        language: str = "kn-IN",
        voice: str | None = None,
        speed: float = 1.0,
        container: str = "wav"
    ) -> tuple[bytes, str]:
        """
        Sends text to Gnani Timbre v3.0 TTS endpoint.
        Returns a tuple: (audio_bytes, content_type).
        """
        if not self.config.is_configured:
            raise GnaniNotConfiguredError(
                "Gnani API key is not configured. Configure GNANI_API_KEY to use Timbre v3.0."
            )

        cleaned_text = (text or "").strip()
        if not cleaned_text:
            raise GnaniAudioError("Text for speech synthesis cannot be empty.")

        if len(cleaned_text) > self.MAX_TEXT_LENGTH:
            raise GnaniAudioError(
                f"Text length ({len(cleaned_text)} chars) exceeds maximum limit of {self.MAX_TEXT_LENGTH} chars."
            )

        headers = {
            "X-API-Key-ID": self.config.api_key.strip(),
            "Content-Type": "application/json"
        }

        payload = {
            "text": cleaned_text,
            "model": self.config.tts_model,
            "voice": voice or self.config.tts_voice,
            "language": language,
            "speed": max(0.5, min(speed, 2.0)),
            "audio_config": {
                "container": container,
                "sample_rate": 24000,
                "encoding": "linear_pcm"
            }
        }

        try:
            client = self._get_client()
            response = client.post(
                self.config.tts_url,
                headers=headers,
                json=payload
            )
        except httpx.TimeoutException as e:
            raise GnaniTimeoutError(f"Timbre TTS request timed out: {e}") from e
        except (httpx.ConnectError, httpx.NetworkError) as e:
            raise GnaniNetworkError(f"Timbre TTS network connection failed: {e}") from e
        except Exception as e:
            raise GnaniProviderError(f"Unexpected error communicating with Timbre TTS: {e}") from e

        # Handle HTTP status codes
        if response.status_code == 200:
            content_type = response.headers.get("content-type", f"audio/{container}")
            return response.content, content_type

        elif response.status_code == 401:
            err_msg = "Invalid or missing Gnani API key."
            try:
                err_detail = response.json().get("detail", {})
                if isinstance(err_detail, dict):
                    err_msg = err_detail.get("message", err_msg)
            except Exception:
                pass
            raise GnaniAuthenticationError(f"Timbre TTS authentication failure: {err_msg}")

        elif response.status_code in (400, 422):
            err_msg = "Invalid text or audio configuration sent to Timbre TTS."
            try:
                err_json = response.json()
                err_msg = err_json.get("message") or str(err_json.get("detail", err_msg))
            except Exception:
                pass
            raise GnaniAudioError(f"Timbre TTS validation error: {err_msg}")

        elif response.status_code == 429:
            raise GnaniRateLimitError("Timbre TTS rate limit or quota exceeded.")

        else:
            raise GnaniProviderError(
                f"Timbre TTS returned HTTP error {response.status_code}: {response.text[:200]}"
            )


class SpeechProviderManager:
    """Central registry and coordinator for STT and TTS providers."""

    def __init__(self):
        self.config = GnaniConfig()
        self.stt_provider = GnaniPrismaSTTProvider(self.config)
        self.tts_provider = GnaniTimbreTTSProvider(self.config)

    def reload_config(self):
        self.config.reload()
        self.stt_provider = GnaniPrismaSTTProvider(self.config)
        self.tts_provider = GnaniTimbreTTSProvider(self.config)

    def get_status(self) -> dict[str, Any]:
        return self.config.get_public_status()


# Global singleton instance
speech_provider_manager = SpeechProviderManager()
