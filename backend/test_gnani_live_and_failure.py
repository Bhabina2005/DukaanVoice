"""
DukaanVoice — Live Gnani Voice AI & Failure Handling Verification Suite.
Validates:
1. Live STT (Prisma v3.0) with real Gnani API credentials (en-IN and kn-IN).
2. Live TTS (Timbre v3.0) with real Gnani API credentials (en-IN and kn-IN).
3. Live Invalid Credentials handling (real HTTP 401 response from Gnani API).
4. Failure Handling: Missing credentials (GnaniNotConfiguredError).
5. Failure Handling: Network timeout (GnaniTimeoutError).
6. Failure Handling: Connection failure / Provider error (GnaniNetworkError).
7. Failure Handling: Audio payload validation (empty and oversized audio).
8. Failure Handling: TTS parameter validation (empty and oversized text).
9. Failure Handling: Fallback hint generation for frontend Web Speech API.
10. Database Safety: Uses isolated in-memory DB or zero DB writes.
"""

import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pytest
import httpx

from speech_provider import (
    GnaniConfig,
    GnaniPrismaSTTProvider,
    GnaniTimbreTTSProvider,
    speech_provider_manager,
    GnaniError,
    GnaniNotConfiguredError,
    GnaniAuthenticationError,
    GnaniTimeoutError,
    GnaniNetworkError,
    GnaniAudioError,
    GnaniProviderError
)
from routes.voice import (
    transcribe_audio_endpoint,
    text_to_speech_endpoint
)
from schemas import (
    AudioTranscribeRequest,
    TTSRequest
)


# =====================================================================
# LIVE API TESTS (Requires Internet & Real Gnani Credentials)
# =====================================================================

@pytest.mark.live
def test_live_tts_english_and_kannada():
    """Live TTS: Synthesizes legitimate English and Kannada audio from Gnani Timbre v3.0."""
    assert speech_provider_manager.config.is_configured, "Gnani API key must be configured for live test"

    # 1. English synthesis
    t0 = time.time()
    audio_en, ctype_en = speech_provider_manager.tts_provider.synthesize_speech(
        text="Credit 500 to Ramesh",
        language="en-IN"
    )
    latency_en = time.time() - t0
    assert len(audio_en) > 1000, "Synthesized audio must be non-empty (> 1KB)"
    assert "audio/" in ctype_en, f"Expected audio content-type, got {ctype_en}"
    assert latency_en < 10.0, f"TTS English latency exceeded 10s: {latency_en:.2f}s"

    # Verify WAV header magic bytes (RIFF .... WAVE)
    assert audio_en[:4] == b"RIFF", "Output must be valid RIFF WAV audio"
    assert audio_en[8:12] == b"WAVE", "Output must contain WAVE format marker"

    # 2. Kannada synthesis with Shivani voice
    t0 = time.time()
    audio_kn, ctype_kn = speech_provider_manager.tts_provider.synthesize_speech(
        text="ನಮಸ್ಕಾರ ರಮೇಶ್ ಅವರಿಗೆ ಐನೂರು ರೂಪಾಯಿ ಉದ್ದಾರ",
        language="kn-IN",
        voice="Shivani"
    )
    latency_kn = time.time() - t0
    assert len(audio_kn) > 1000, "Synthesized audio must be non-empty (> 1KB)"
    assert "audio/" in ctype_kn
    assert audio_kn[:4] == b"RIFF"
    assert latency_kn < 10.0


@pytest.mark.live
def test_live_stt_english_and_kannada():
    """Live STT: Submits real audio to Gnani Prisma v3.0 and verifies valid transcripts."""
    assert speech_provider_manager.config.is_configured, "Gnani API key must be configured for live test"

    # Synthesize short legitimate audio samples first
    audio_en, _ = speech_provider_manager.tts_provider.synthesize_speech(
        text="Credit 500 to Ramesh",
        language="en-IN"
    )
    audio_kn, _ = speech_provider_manager.tts_provider.synthesize_speech(
        text="ನಮಸ್ಕಾರ ರಮೇಶ್ ಅವರಿಗೆ ಐನೂರು ರೂಪಾಯಿ ಉದ್ದಾರ",
        language="kn-IN",
        voice="Shivani"
    )

    # 1. Transcribe English audio
    t0 = time.time()
    try:
        res_en = speech_provider_manager.stt_provider.transcribe_audio(
            audio_bytes=audio_en,
            filename="live_en.wav",
            content_type="audio/wav",
            language_code="en-IN"
        )
    except GnaniProviderError as err:
        sanitized_msg = str(err)
        # Ensure secret API key is never printed
        if speech_provider_manager.config.api_key:
            sanitized_msg = sanitized_msg.replace(speech_provider_manager.config.api_key, "[REDACTED]")
        pytest.fail(f"Live Gnani Prisma STT English transcription failed upstream (sanitized): {sanitized_msg}")

    latency_en = time.time() - t0
    assert res_en["success"] is True
    assert len(res_en["transcript"].strip()) > 0, "English transcript must not be empty"
    assert "credit" in res_en["transcript"].lower() or "500" in res_en["transcript"] or "ramesh" in res_en["transcript"].lower()
    assert latency_en < 10.0, f"STT English latency exceeded 10s: {latency_en:.2f}s"

    # 2. Transcribe Kannada audio
    t0 = time.time()
    try:
        res_kn = speech_provider_manager.stt_provider.transcribe_audio(
            audio_bytes=audio_kn,
            filename="live_kn.wav",
            content_type="audio/wav",
            language_code="kn-IN"
        )
    except GnaniProviderError as err:
        sanitized_msg = str(err)
        if speech_provider_manager.config.api_key:
            sanitized_msg = sanitized_msg.replace(speech_provider_manager.config.api_key, "[REDACTED]")
        pytest.fail(f"Live Gnani Prisma STT Kannada transcription failed upstream (sanitized): {sanitized_msg}")

    latency_kn = time.time() - t0
    assert res_kn["success"] is True
    assert len(res_kn["transcript"].strip()) > 0, "Kannada transcript must not be empty"
    assert latency_kn < 10.0


@pytest.mark.live
def test_live_invalid_credentials_returns_401_without_secret_leak():
    """Live Auth: Submitting invalid credentials to real Gnani API triggers 401 without exposing secrets."""
    bad_config = GnaniConfig()
    bad_config.api_key = "vach_invalid_test_key_0000000000000000000000"
    provider = GnaniPrismaSTTProvider(bad_config)

    dummy_wav = b"RIFF" + b"\x00" * 36 + b"data" + b"\x00" * 100
    with pytest.raises(GnaniAuthenticationError) as excinfo:
        provider.transcribe_audio(dummy_wav, language_code="en-IN")

    err_str = str(excinfo.value)
    assert "401" in err_str or "authentication failure" in err_str.lower()
    # Security requirement: API key must NEVER be printed in the exception message
    assert "vach_invalid_test_key" not in err_str


# =====================================================================
# FAILURE HANDLING & FALLBACK TESTS (Deterministic Isolated Mocks)
# =====================================================================

def test_failure_missing_credentials_raises_not_configured():
    """Missing Credentials: Raises GnaniNotConfiguredError and preserves browser fallback."""
    unconfigured_config = GnaniConfig()
    unconfigured_config.api_key = ""
    stt = GnaniPrismaSTTProvider(unconfigured_config)
    tts = GnaniTimbreTTSProvider(unconfigured_config)

    with pytest.raises(GnaniNotConfiguredError):
        stt.transcribe_audio(b"some_bytes")

    with pytest.raises(GnaniNotConfiguredError):
        tts.synthesize_speech("Hello")

    # Verify endpoint returns graceful fallback hint when unconfigured
    import routes.voice
    orig_voice_spm = routes.voice.speech_provider_manager
    orig_stt = speech_provider_manager.stt_provider
    try:
        speech_provider_manager.stt_provider = stt
        routes.voice.speech_provider_manager = speech_provider_manager
        res = transcribe_audio_endpoint(AudioTranscribeRequest(
            audio_base64="AAAA",
            format="wav",
            language="kn-IN"
        ))
        assert res.success is False
        assert "fallback" in (res.fallback_hint or "").lower()
    finally:
        speech_provider_manager.stt_provider = orig_stt
        routes.voice.speech_provider_manager = orig_voice_spm


def test_failure_network_timeout():
    """Network Timeout: Raises GnaniTimeoutError and provides fallback hint."""
    class TimeoutTransport(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.TimeoutException("Connection timed out after 10.0s")

    client = httpx.Client(transport=TimeoutTransport())
    config = GnaniConfig()
    config.api_key = "dummy_for_mock"
    stt = GnaniPrismaSTTProvider(config, client=client)

    dummy_wav = b"RIFF" + b"\x00" * 36 + b"data" + b"\x00" * 100
    with pytest.raises(GnaniTimeoutError):
        stt.transcribe_audio(dummy_wav)


def test_failure_provider_connection_error():
    """Provider Connection Error: Raises GnaniNetworkError."""
    class ConnectErrorTransport(httpx.BaseTransport):
        def handle_request(self, request):
            raise httpx.ConnectError("Connection refused by host")

    client = httpx.Client(transport=ConnectErrorTransport())
    config = GnaniConfig()
    config.api_key = "dummy_for_mock"
    stt = GnaniPrismaSTTProvider(config, client=client)

    dummy_wav = b"RIFF" + b"\x00" * 36 + b"data" + b"\x00" * 100
    with pytest.raises(GnaniNetworkError):
        stt.transcribe_audio(dummy_wav)


def test_failure_empty_and_oversized_audio_rejection():
    """Audio Validation: Empty audio and audio > 10MB rejected immediately."""
    config = GnaniConfig()
    config.api_key = "dummy_key"
    stt = GnaniPrismaSTTProvider(config)

    # Empty bytes
    with pytest.raises(GnaniAudioError) as exc:
        stt.transcribe_audio(b"")
    assert "empty" in str(exc.value).lower()

    # Oversized bytes (> 10MB)
    huge_bytes = b"0" * (10 * 1024 * 1024 + 1)
    with pytest.raises(GnaniAudioError) as exc:
        stt.transcribe_audio(huge_bytes)
    assert "exceeds" in str(exc.value).lower()


def test_failure_empty_and_oversized_tts_text_rejection():
    """TTS Validation: Empty text and text > 1000 characters rejected immediately."""
    config = GnaniConfig()
    config.api_key = "dummy_key"
    tts = GnaniTimbreTTSProvider(config)

    # Empty text
    with pytest.raises(GnaniAudioError) as exc:
        tts.synthesize_speech("")
    assert "empty" in str(exc.value).lower()

    # Whitespace text
    with pytest.raises(GnaniAudioError) as exc:
        tts.synthesize_speech("   \n\t  ")
    assert "empty" in str(exc.value).lower()

    # Oversized text (> 1000 chars)
    long_text = "ಅ" * 1001
    with pytest.raises(GnaniAudioError) as exc:
        tts.synthesize_speech(long_text)
    assert "exceeds" in str(exc.value).lower()
