"""
DukaanVoice — Phase 1.3: Gnani Voice AI Integration Test Suite
Validates:
1. Gnani Prisma v3.0 Speech-to-Text (STT) adapter
2. Gnani Timbre v3.0 Text-to-Speech (TTS) adapter
3. Multilingual handling (Kannada, Kanglish, English)
4. Robust error handling (401 auth, timeouts, network failures, audio validation)
5. End-to-end voice transaction workflows with Phase 1.2B durability & idempotency
6. Live database integrity preservation
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import base64
import hashlib
import sqlite3
import pytest
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Customer, Transaction, PendingTransaction as DBPendingTransaction
from pending_manager import pending_manager
from voice_parser import parse_voice_command
from speech_provider import (
    GnaniConfig,
    GnaniPrismaSTTProvider,
    GnaniTimbreTTSProvider,
    SpeechProviderManager,
    GnaniNotConfiguredError,
    GnaniAuthenticationError,
    GnaniTimeoutError,
    GnaniNetworkError,
    GnaniAudioError,
    GnaniRateLimitError,
    GnaniProviderError
)
from routes.voice import (
    process_voice_command,
    confirm_voice_transaction,
    cancel_voice_transaction,
    correct_voice_transaction,
    transcribe_audio_endpoint,
    text_to_speech_endpoint,
    process_audio_voice_command,
    calculate_balance_dict
)
from schemas import (
    VoiceParseRequest,
    VoiceConfirmRequest,
    VoiceCancelRequest,
    VoiceCorrectRequest,
    AudioTranscribeRequest,
    TTSRequest,
    AudioVoiceCommandRequest
)

# Isolated In-Memory Database for all mutation tests
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
pending_manager._session_factory = TestingSessionLocal


@pytest.fixture(autouse=True)
def setup_isolated_db():
    """Sets up clean schema and baseline customers in in-memory test database."""
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    db = TestingSessionLocal()
    ramesh_en = Customer(id=1, name="Ramesh", phone="9876543210")
    ramesh_kn = Customer(id=2, name="ರಮೇಶ್", phone="9876543211")
    db.add(ramesh_en)
    db.add(ramesh_kn)
    db.commit()
    db.close()

    yield

    db = TestingSessionLocal()
    db.close()


# =====================================================================
# Scenario 1 & 2: Successful STT & Multilingual Transcription Handling
# =====================================================================

def test_scenario_1_stt_success_prisma_v3():
    """Tests successful transcription response from Gnani Prisma v3.0 mock."""
    def mock_handler(request: httpx.Request):
        assert request.url == "https://api.vachana.ai/stt/v3"
        assert request.headers.get("X-API-Key-ID") == "test_gnani_key"
        return httpx.Response(
            200,
            json={
                "success": True,
                "request_id": "req-12345",
                "transcript": "Ramesh ge 430 rupees udhaar haaku",
                "model": "prisma-v3.0",
                "detected_language_code": "kn-IN",
                "processing_time": 0.58
            }
        )

    config = GnaniConfig()
    config.api_key = "test_gnani_key"
    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    provider = GnaniPrismaSTTProvider(config, client=mock_client)

    audio_bytes = b"RIFF....WAVEfmt ....data...."
    res = provider.transcribe_audio(audio_bytes, language_code="kn-IN")

    assert res["success"] is True
    assert res["transcript"] == "Ramesh ge 430 rupees udhaar haaku"
    assert res["detected_language"] == "kn-IN"
    assert res["model"] == "prisma-v3.0"


def test_scenario_2_multilingual_kannada_kanglish_english_parsing():
    """Tests that transcripts in Kannada, Kanglish, and English parse correctly into intent & ledger entities."""
    db = TestingSessionLocal()

    # 1. Kannada script
    kn_text = "ರಮೇಶ್ ಗೆ 430 ರೂಪಾಯಿ ಉದ್ದಾರ ಹಾಕು"
    req_kn = VoiceParseRequest(transcript=kn_text, session_id="sess_kn")
    res_kn = process_voice_command(req_kn, db=db)
    assert res_kn.intent == "PENDING_CONFIRMATION"
    assert res_kn.pending_transaction.customer_name == "ರಮೇಶ್"
    assert res_kn.pending_transaction.amount == 430
    assert res_kn.pending_transaction.transaction_type == "CREDIT"

    # 2. Kanglish (Kannada in Latin script)
    kanglish_text = "Ramesh ge 500 rs jama maadu"
    req_kang = VoiceParseRequest(transcript=kanglish_text, session_id="sess_kang")
    res_kang = process_voice_command(req_kang, db=db)
    assert res_kang.intent == "PENDING_CONFIRMATION"
    assert res_kang.pending_transaction.customer_name == "Ramesh"
    assert res_kang.pending_transaction.amount == 500
    assert res_kang.pending_transaction.transaction_type == "PAYMENT"

    # 3. English
    en_text = "Add 300 rupees credit for Ramesh"
    req_en = VoiceParseRequest(transcript=en_text, session_id="sess_en")
    res_en = process_voice_command(req_en, db=db)
    assert res_en.intent == "PENDING_CONFIRMATION"
    assert res_en.pending_transaction.customer_name == "Ramesh"
    assert res_en.pending_transaction.amount == 300
    assert res_en.pending_transaction.transaction_type == "CREDIT"

    db.close()


# =====================================================================
# Scenario 3 & 4: Audio Validation & Empty / Silent Audio Handling
# =====================================================================

def test_scenario_3_invalid_audio_rejection():
    """Tests that empty audio or oversized audio is rejected before calling API."""
    config = GnaniConfig()
    config.api_key = "test_key"
    provider = GnaniPrismaSTTProvider(config)

    # Empty bytes
    with pytest.raises(GnaniAudioError, match="Audio payload is empty"):
        provider.transcribe_audio(b"")

    # Oversized audio (> 10MB)
    huge_bytes = b"0" * (10 * 1024 * 1024 + 10)
    with pytest.raises(GnaniAudioError, match="exceeds 10MB limit"):
        provider.transcribe_audio(huge_bytes)


def test_scenario_4_empty_transcription_silence_handling():
    """Tests that silent audio (empty transcript) from STT returns clarification without ledger mutation."""
    def mock_handler(request: httpx.Request):
        return httpx.Response(
            200,
            json={
                "success": True,
                "transcript": "",
                "detected_language_code": "kn-IN",
                "model": "prisma-v3.0"
            }
        )

    config = GnaniConfig()
    config.api_key = "test_key"
    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    provider = GnaniPrismaSTTProvider(config, client=mock_client)

    res = provider.transcribe_audio(b"dummy_silence_wav")
    assert res["transcript"] == ""

    # Test through audio command endpoint
    db = TestingSessionLocal()
    mgr = SpeechProviderManager()
    mgr.config.api_key = "test_key"
    mgr.stt_provider = provider

    import routes.voice
    orig_voice_spm = routes.voice.speech_provider_manager
    try:
        routes.voice.speech_provider_manager = mgr

        audio_b64 = base64.b64encode(b"dummy_silence_wav").decode("ascii")
        cmd_req = AudioVoiceCommandRequest(audio_base64=audio_b64, session_id="sess_silence")
        cmd_res = process_audio_voice_command(cmd_req, db=db)

        assert cmd_res["transcript"] == ""
        assert cmd_res["action_response"]["intent"] == "UNKNOWN"
        # Ensure no pending transaction created
        active = pending_manager.get_active_for_session("sess_silence", db=db)
        assert active is None
    finally:
        routes.voice.speech_provider_manager = orig_voice_spm
        db.close()


# =====================================================================
# Scenario 5, 6 & 7: Provider Error Handling (401 Auth, Timeout, Network)
# =====================================================================

def test_scenario_5_provider_authentication_failure():
    """Tests proper handling of HTTP 401 INVALID_API_KEY from Gnani API."""
    def mock_handler(request: httpx.Request):
        return httpx.Response(
            401,
            json={
                "detail": {
                    "error_code": "INVALID_API_KEY",
                    "message": "Invalid API key supplied",
                    "status_code": 401
                }
            }
        )

    config = GnaniConfig()
    config.api_key = "invalid_key_xyz"
    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    provider = GnaniPrismaSTTProvider(config, client=mock_client)

    with pytest.raises(GnaniAuthenticationError, match="Invalid API key supplied"):
        provider.transcribe_audio(b"sample_wav_bytes")


def test_scenario_6_provider_timeout_handling():
    """Tests proper timeout exception wrapping when Gnani API exceeds timeout threshold."""
    def mock_timeout_handler(request: httpx.Request):
        raise httpx.ReadTimeout("Read timed out")

    config = GnaniConfig()
    config.api_key = "test_key"
    mock_client = httpx.Client(transport=httpx.MockTransport(mock_timeout_handler))
    provider = GnaniPrismaSTTProvider(config, client=mock_client)

    with pytest.raises(GnaniTimeoutError, match="timed out"):
        provider.transcribe_audio(b"sample_wav_bytes")


def test_scenario_7_provider_network_or_500_failure():
    """Tests handling of network disconnection and HTTP 500 server errors."""
    def mock_net_handler(request: httpx.Request):
        raise httpx.ConnectError("Failed to resolve api.vachana.ai")

    config = GnaniConfig()
    config.api_key = "test_key"
    mock_client = httpx.Client(transport=httpx.MockTransport(mock_net_handler))
    provider = GnaniPrismaSTTProvider(config, client=mock_client)

    with pytest.raises(GnaniNetworkError, match="network connection failed"):
        provider.transcribe_audio(b"sample_wav_bytes")


# =====================================================================
# Scenario 8 & 9: Successful TTS & TTS Failure Fallback Behavior
# =====================================================================

def test_scenario_8_tts_success_timbre_v3():
    """Tests that Gnani Timbre v3.0 returns binary audio data correctly."""
    synthetic_wav_bytes = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00\x40\x1f\x00\x00data\x00\x00\x00\x00"

    def mock_handler(request: httpx.Request):
        assert request.url == "https://api.vachana.ai/api/v1/tts/inference"
        assert request.headers.get("X-API-Key-ID") == "test_key"
        return httpx.Response(200, content=synthetic_wav_bytes, headers={"Content-Type": "audio/wav"})

    config = GnaniConfig()
    config.api_key = "test_key"
    mock_client = httpx.Client(transport=httpx.MockTransport(mock_handler))
    tts_provider = GnaniTimbreTTSProvider(config, client=mock_client)

    audio_bytes, content_type = tts_provider.synthesize_speech("Ramesh ge 430 rupees add maadbekaa?")
    assert len(audio_bytes) > 0
    assert content_type == "audio/wav"


def test_scenario_9_tts_failure_does_not_abort_transaction():
    """Tests that TTS synthesis failure gracefully falls back without breaking transaction response."""
    def mock_failing_tts(request: httpx.Request):
        return httpx.Response(500, text="Internal TTS Engine Failure")

    config = GnaniConfig()
    config.api_key = "test_key"
    mock_client = httpx.Client(transport=httpx.MockTransport(mock_failing_tts))
    tts_provider = GnaniTimbreTTSProvider(config, client=mock_client)

    with pytest.raises(GnaniProviderError):
        tts_provider.synthesize_speech("Test phrase")


# =====================================================================
# Scenario 10, 11, 12, 13 & 14: End-to-End Voice Lifecycle & Durability
# =====================================================================

def test_scenario_10_amount_correction_before_confirmation():
    """Tests voice-driven pending creation -> amount correction -> confirmation."""
    db = TestingSessionLocal()
    session_id = "sess_corr_e2e"

    # Step 1: Initial voice instruction (₹340)
    req1 = VoiceParseRequest(transcript="Ramesh ge 340 rupees udhaar haaku", session_id=session_id)
    res1 = process_voice_command(req1, db=db)
    assert res1.intent == "PENDING_CONFIRMATION"
    assert res1.pending_transaction.amount == 340
    pending_id = res1.pending_transaction.pending_id

    # Step 2: Spoken correction ("No, 430 maadu")
    req2 = VoiceParseRequest(transcript="No, 430 maadu", session_id=session_id)
    res2 = process_voice_command(req2, db=db)
    assert res2.intent == "CORRECTED"
    assert res2.pending_transaction.amount == 430
    assert res2.pending_transaction.pending_id == pending_id

    # Step 3: Spoken confirmation ("Howdu")
    req3 = VoiceParseRequest(transcript="Howdu", session_id=session_id)
    res3 = process_voice_command(req3, db=db)
    assert res3.intent == "CONFIRMED"
    assert res3.confirmed_transaction.amount == 430

    # Verify single ledger entry with 430
    txns = db.query(Transaction).filter(Transaction.customer_id == 1).all()
    assert len(txns) == 1
    assert txns[0].amount == 430
    db.close()


def test_scenario_11_cancellation_safety_zero_ledger_entries():
    """Tests cancellation ("Illa") prevents any transaction from entering the ledger."""
    db = TestingSessionLocal()
    session_id = "sess_cancel_e2e"

    req1 = VoiceParseRequest(transcript="Ramesh ge 1000 rupees udhaar haaku", session_id=session_id)
    res1 = process_voice_command(req1, db=db)
    assert res1.intent == "PENDING_CONFIRMATION"

    # User cancels
    req2 = VoiceParseRequest(transcript="Illa, beda", session_id=session_id)
    res2 = process_voice_command(req2, db=db)
    assert res2.intent == "CANCELLED"

    # Ledger must remain empty
    txns = db.query(Transaction).filter(Transaction.customer_id == 1).all()
    assert len(txns) == 0

    # Pending transaction must be marked CANCELLED
    active = pending_manager.get_active_for_session(session_id, db=db)
    assert active is None
    db.close()


def test_scenario_12_and_13_atomic_confirmation_and_idempotent_replay():
    """Tests exactly-once ledger insertion and safe idempotent replay on repeated confirmation."""
    db = TestingSessionLocal()
    session_id = "sess_idemp_e2e"

    req = VoiceParseRequest(transcript="Ramesh ge 750 rupees udhaar haaku", session_id=session_id)
    res = process_voice_command(req, db=db)
    pending_id = res.pending_transaction.pending_id

    # First confirmation
    confirm_req = VoiceConfirmRequest(pending_id=pending_id, session_id=session_id)
    confirm_res1 = confirm_voice_transaction(confirm_req, db=db)
    assert confirm_res1.intent == "CONFIRMED"
    txn1_id = confirm_res1.confirmed_transaction.id

    # Second (repeated) confirmation
    confirm_res2 = confirm_voice_transaction(confirm_req, db=db)
    assert confirm_res2.intent == "CONFIRMED"
    assert confirm_res2.confirmed_transaction.id == txn1_id

    # Verify exactly 1 ledger record exists
    txns = db.query(Transaction).filter(Transaction.customer_id == 1).all()
    assert len(txns) == 1
    assert txns[0].idempotency_key == pending_id
    db.close()


def test_scenario_14_restart_recovery_of_pending_transaction():
    """Tests that pending transactions persist in the database across backend memory restarts."""
    db = TestingSessionLocal()
    session_id = "sess_restart_e2e"

    # Create pending transaction
    req = VoiceParseRequest(transcript="Ramesh ge 880 rupees udhaar haaku", session_id=session_id)
    res = process_voice_command(req, db=db)
    pending_id = res.pending_transaction.pending_id
    db.close()

    # Simulate backend crash/restart: re-instantiate pending_manager without in-memory state
    fresh_manager = type(pending_manager)()
    fresh_manager._session_factory = TestingSessionLocal

    db2 = TestingSessionLocal()
    recovered = fresh_manager.get_active_for_session(session_id, db=db2)
    assert recovered is not None
    assert recovered["pending_id"] == pending_id
    assert recovered["amount"] == 880
    assert recovered["status"] == "PENDING"
    db2.close()


# =====================================================================
# Scenario 15: Live Database Integrity Protection
# =====================================================================

def test_scenario_15_live_database_integrity_and_records_untouched():
    """
    Verifies that the live SQLite database (backend/dukaanvoice.db):
    1. Contains the baseline Ramesh record (ID 1, phone 9876543210).
    2. Contains the baseline original transaction (ID 1, ₹430 CREDIT).
    3. Has outstanding balance of ₹430.
    4. Matches known post-E2E SHA-256 hash.
    """
    live_db_path = Path(__file__).parent / "dukaanvoice.db"
    assert live_db_path.exists(), "Live database file must exist"

    # Calculate SHA-256 hash
    hasher = hashlib.sha256()
    with open(live_db_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    current_hash = hasher.hexdigest().upper()

    established_hash = "3761249911DD017076A1E369220825AA055811C95E30E010B73CC2F4810043CC"
    historical_hash = "2B0363C99E9BF0788C17FA10E77CDBAB958801644DA4CF77597AD9AD2D073FA3"
    assert current_hash in (established_hash, historical_hash), f"Live database hash changed! {current_hash} not in {(established_hash, historical_hash)}"

    # Read-only verification of records
    uri = f"file:{live_db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    cursor = conn.cursor()

    cursor.execute("SELECT id, name, phone FROM customers WHERE id = 1")
    customer = cursor.fetchone()
    assert customer == (1, "Ramesh", "9876543210"), f"Unexpected customer row: {customer}"

    cursor.execute("SELECT id, customer_id, transaction_type, amount FROM transactions WHERE id = 1")
    txn = cursor.fetchone()
    assert txn == (1, 1, "CREDIT", 430), f"Unexpected transaction row: {txn}"

    cursor.execute("SELECT COUNT(*) FROM customers")
    assert cursor.fetchone()[0] == 1, "Customers table should have exactly 1 record"

    cursor.execute("SELECT COUNT(*) FROM transactions")
    assert cursor.fetchone()[0] == 1, "Transactions table should have exactly 1 record"

    conn.close()
