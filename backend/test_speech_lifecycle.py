"""
Phase 1.4 Stage B: Backend Voice Interaction Lifecycle & Speech Safety Test Suite.
Verifies audio validation, silence/whitespace handling, absence of orphan pending transactions,
and database isolation without network calls, loopback sockets, or modifying dukaanvoice.db.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import base64
import pytest
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Customer
from speech_provider import (
    GnaniPrismaSTTProvider,
    GnaniTimbreTTSProvider,
    GnaniAudioError,
    GnaniConfig,
    speech_provider_manager
)
from routes.voice import (
    transcribe_audio_endpoint,
    process_voice_command,
    process_audio_voice_command
)
from schemas import (
    AudioTranscribeRequest,
    VoiceParseRequest,
    AudioVoiceCommandRequest
)
from pending_manager import pending_manager


# 1. Isolated in-memory SQLite database fixture for Stage B testing
@pytest.fixture(name="isolated_session")
def fixture_isolated_session():
    test_engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestingSessionLocal()
    pending_manager._session_factory = TestingSessionLocal

    # Seed isolated customer
    c = Customer(id=1, name="Ramesh", phone="9876543210")
    session.add(c)
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=test_engine)


# =====================================================================
# Tests: Speech Safety, Silence Detection, Lifecycle
# =====================================================================

def test_stt_provider_rejects_empty_audio_bytes():
    """Scenario 1: Prisma STT adapter must reject empty audio payload before network call."""
    config = GnaniConfig()
    config.api_key = "test_key"
    provider = GnaniPrismaSTTProvider(config)

    with pytest.raises(GnaniAudioError, match="Audio payload is empty"):
        provider.transcribe_audio(
            audio_bytes=b"",
            filename="empty.webm",
            content_type="audio/webm"
        )


def test_stt_provider_rejects_oversized_audio():
    """Scenario 2: Prisma STT adapter must reject audio exceeding 10MB limit."""
    config = GnaniConfig()
    config.api_key = "test_key"
    provider = GnaniPrismaSTTProvider(config)
    oversized = b"0" * (10 * 1024 * 1024 + 1)

    with pytest.raises(GnaniAudioError, match="exceeds 10MB limit"):
        provider.transcribe_audio(
            audio_bytes=oversized,
            filename="large.webm",
            content_type="audio/webm"
        )


def test_tts_provider_rejects_empty_or_whitespace_text():
    """Scenario 3: Timbre TTS adapter must reject empty/whitespace synthesis requests."""
    config = GnaniConfig()
    config.api_key = "test_key"
    provider = GnaniTimbreTTSProvider(config)

    with pytest.raises(GnaniAudioError, match="cannot be empty"):
        provider.synthesize_speech(text="", language="kn-IN")

    with pytest.raises(GnaniAudioError, match="cannot be empty"):
        provider.synthesize_speech(text="   \n\t  ", language="kn-IN")


def test_transcribe_endpoint_handles_invalid_base64():
    """Scenario 4: /api/speech/transcribe returns graceful error on malformed base64."""
    req = AudioTranscribeRequest(
        audio_base64="!!!not-valid-base64!!!",
        format="webm",
        language="kn-IN"
    )
    resp = transcribe_audio_endpoint(req)
    assert resp.success is False
    assert "Invalid base64" in resp.error


def test_process_voice_command_whitespace_creates_no_pending_transaction(isolated_session):
    """Scenario 5: Whitespace-only speech input must not create any pending transaction."""
    session_id = "test_silence_session_1"

    req = VoiceParseRequest(transcript="   ", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is False
    assert resp.intent == "UNKNOWN"

    # Verify no pending transaction was created
    pending = pending_manager.get_active_for_session(session_id, db=isolated_session)
    assert pending is None


def test_audio_command_empty_transcript_creates_no_pending_transaction(isolated_session, monkeypatch):
    """Scenario 6: Audio command with empty STT output returns silence notice and creates no pending txn."""
    session_id = "test_silence_session_2"

    # Mock STT provider to return empty transcript (simulating silence in audio)
    mock_stt = MagicMock()
    mock_stt.transcribe_audio.return_value = {
        "success": True,
        "transcript": "",
        "detected_language": "kn-IN"
    }
    monkeypatch.setattr(speech_provider_manager, "stt_provider", mock_stt)

    dummy_audio = base64.b64encode(b"RIFFdummydata").decode("ascii")
    req = AudioVoiceCommandRequest(
        audio_base64=dummy_audio,
        format="webm",
        language="kn-IN",
        session_id=session_id
    )
    data = process_audio_voice_command(req, db=isolated_session)

    assert data["transcript"] == ""
    assert data["action_response"]["intent"] == "UNKNOWN"
    assert "No speech detected" in data["action_response"]["message"]

    # Verify no pending transaction exists in database
    pending = pending_manager.get_active_for_session(session_id, db=isolated_session)
    assert pending is None


def test_repeated_silence_does_not_corrupt_subsequent_commands(isolated_session):
    """Scenario 7: Multiple silence inputs followed by a valid command behaves correctly."""
    session_id = "test_recovery_session"

    # Send 3 silence/empty inputs
    for _ in range(3):
        req = VoiceParseRequest(transcript="   \t  ", session_id=session_id)
        r = process_voice_command(req, db=isolated_session)
        assert r.intent == "UNKNOWN"

    # Send valid command
    req_valid = VoiceParseRequest(transcript="Ramesh ge 430 rupees udhaar haaku", session_id=session_id)
    resp = process_voice_command(req_valid, db=isolated_session)

    assert resp.intent == "PENDING_CONFIRMATION"
    assert resp.pending_transaction.amount == 430
    assert resp.pending_transaction.customer_name == "Ramesh"

    # Verify active pending transaction is properly established
    pending = pending_manager.get_active_for_session(session_id, db=isolated_session)
    assert pending is not None
    assert pending["amount"] == 430
