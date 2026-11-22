"""
DukaanVoice — Phase 1.4 Stage F: Comprehensive Security & Integrity Test Suite.
Tests:
1. API Input Validation (negative, zero, excessive amounts, invalid types, missing fields).
2. Pending Transaction Authorization & Lifecycle Guard (non-existent, cancelled, expired, stale).
3. Database Integrity & Idempotency (foreign keys, atomic commit, repeat confirmation replay).
4. Secrets & Configuration Security (provider status leaks, error redaction, environment isolation).
5. Audio & Upload Boundaries (10MB limit, empty audio, oversized TTS text, speed bounds).
6. CORS Origin Security (allowed localhost origins vs rejected untrusted origins).
7. Live Database Protection (zero mutations, SHA-256 baseline verification).
"""

import hashlib
import importlib
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
import sys

# Ensure backend root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pytest
from pydantic import ValidationError
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError

from main import app
from database import Base
from models import Customer, Transaction, PendingTransaction
from pending_manager import (
    pending_manager,
    PendingTransactionManager,
    compute_balance_preview,
    get_customer_net_balance
)
from routes.transactions import create_transaction
from routes.voice import (
    confirm_voice_transaction,
    cancel_voice_transaction,
    get_provider_status
)
from schemas import (
    TransactionCreate,
    VoiceConfirmRequest,
    VoiceCancelRequest
)
from speech_provider import (
    GnaniConfig,
    GnaniPrismaSTTProvider,
    GnaniTimbreTTSProvider,
    speech_provider_manager,
    GnaniAudioError,
    GnaniNotConfiguredError
)

# Establish isolated in-memory test database with StaticPool
TEST_DB_URL = "sqlite:///:memory:"
test_engine = create_engine(
    TEST_DB_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

LIVE_DB_PATH = Path(__file__).resolve().parent / "dukaanvoice.db"
CURRENT_ESTABLISHED_SHA256 = "3761249911DD017076A1E369220825AA055811C95E30E010B73CC2F4810043CC"
HISTORICAL_PRE_STAGE_F_SHA256 = "2B0363C99E9BF0788C17FA10E77CDBAB958801644DA4CF77597AD9AD2D073FA3"


@pytest.fixture(autouse=True)
def setup_isolated_db():
    """Sets up an isolated database for each test, leaving dukaanvoice.db untouched."""
    Base.metadata.create_all(bind=test_engine)
    with test_engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=ON;"))
        conn.commit()

    db = TestingSessionLocal()
    pending_manager._session_factory = TestingSessionLocal

    # Seed baseline isolated customer Ramesh
    cust = Customer(id=1, name="Ramesh", phone="9876543210")
    db.add(cust)
    db.commit()

    # Seed baseline transaction matching project baseline (CREDIT 430)
    txn = Transaction(
        id=1,
        customer_id=1,
        transaction_type="CREDIT",
        amount=430,
        description="Baseline credit purchase",
        idempotency_key="baseline_txn_001"
    )
    db.add(txn)
    db.commit()
    db.close()

    yield

    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session():
    """Provides a thread-safe test session for direct route invocation."""
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============================================================================
# 1. API & Input Validation
# ============================================================================

def test_negative_and_zero_amount_rejected(db_session):
    """Rejects amounts <= 0 via Pydantic validation or route HTTP 422."""
    # Zero amount rejection
    with pytest.raises((HTTPException, ValidationError)) as exc_info:
        data = TransactionCreate(
            customer_id=1,
            transaction_type="CREDIT",
            amount=0,
            description="Zero amount test"
        )
        create_transaction(data, db=db_session)
    if isinstance(exc_info.value, HTTPException):
        assert exc_info.value.status_code == 422

    # Negative amount rejection
    with pytest.raises((HTTPException, ValidationError)) as exc_info:
        data = TransactionCreate(
            customer_id=1,
            transaction_type="CREDIT",
            amount=-500,
            description="Negative amount test"
        )
        create_transaction(data, db=db_session)
    if isinstance(exc_info.value, HTTPException):
        assert exc_info.value.status_code == 422


def test_excessive_amount_rejected(db_session):
    """Rejects implausibly large transaction amounts exceeding ₹10,000,000."""
    with pytest.raises(ValidationError):
        TransactionCreate(
            customer_id=1,
            transaction_type="CREDIT",
            amount=10_000_001,
            description="Excessive amount test"
        )

    # Pending manager boundary enforcement
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    with pytest.raises(ValueError, match="exceeds maximum limit of"):
        mgr.create_pending(
            session_id="overflow_sess",
            customer_id=1,
            customer_name="Ramesh",
            customer_phone="9876543210",
            amount=10_000_001,
            transaction_type="CREDIT",
            db=db_session
        )


def test_invalid_transaction_type_rejected(db_session):
    """Rejects invalid transaction types outside ('CREDIT', 'PAYMENT')."""
    with pytest.raises((HTTPException, ValidationError)):
        data = TransactionCreate(
            customer_id=1,
            transaction_type="UNSUPPORTED_TYPE",
            amount=500
        )
        create_transaction(data, db=db_session)


def test_nonexistent_customer_rejected(db_session):
    """Rejects transaction creation for non-existent customer ID with 404."""
    data = TransactionCreate(
        customer_id=999999,
        transaction_type="CREDIT",
        amount=500
    )
    with pytest.raises(HTTPException) as exc_info:
        create_transaction(data, db=db_session)
    assert exc_info.value.status_code == 404
    assert "Customer not found" in exc_info.value.detail


# ============================================================================
# 2. Pending Transaction Authorization & Lifecycle Guard
# ============================================================================

def test_confirm_nonexistent_pending_fails(db_session):
    """Rejects confirmation of non-existent pending ID with HTTP 400."""
    req = VoiceConfirmRequest(
        pending_id="nonexistent-pending-uuid-0000",
        session_id="test_sess"
    )
    with pytest.raises(HTTPException) as exc_info:
        confirm_voice_transaction(req, db=db_session)
    assert exc_info.value.status_code == 400
    assert "Pending transaction not found" in exc_info.value.detail


def test_confirm_cancelled_pending_fails(db_session):
    """Rejects confirmation of a cancelled pending transaction."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    p = mgr.create_pending(
        session_id="cancel_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=250,
        transaction_type="CREDIT",
        db=db_session
    )
    # Cancel it
    mgr.cancel_pending(p["pending_id"], db=db_session)

    req = VoiceConfirmRequest(
        pending_id=p["pending_id"],
        session_id="cancel_sess"
    )
    with pytest.raises(HTTPException) as exc_info:
        confirm_voice_transaction(req, db=db_session)
    assert exc_info.value.status_code == 400
    assert "Cannot confirm a cancelled transaction" in exc_info.value.detail


def test_confirm_expired_pending_fails(db_session):
    """Rejects confirmation of an expired pending transaction."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    p = mgr.create_pending(
        session_id="expire_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=250,
        transaction_type="CREDIT",
        db=db_session
    )
    # Manually expire
    rec = db_session.get(PendingTransaction, p["pending_id"])
    rec.expires_at = datetime.now() - timedelta(minutes=5)
    rec.status = "EXPIRED"
    db_session.commit()

    req = VoiceConfirmRequest(
        pending_id=p["pending_id"],
        session_id="expire_sess"
    )
    with pytest.raises(HTTPException) as exc_info:
        confirm_voice_transaction(req, db=db_session)
    assert exc_info.value.status_code == 400
    assert "expired" in exc_info.value.detail.lower()


def test_stale_balance_preview_rejected_with_409(db_session):
    """Rejects confirmation with HTTP 409 Conflict if balance changed since preview."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    p = mgr.create_pending(
        session_id="stale_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=500,
        transaction_type="CREDIT",
        db=db_session
    )
    # Intervening transaction changes Ramesh's balance from ₹430 to ₹530
    intervening = Transaction(
        customer_id=1,
        transaction_type="CREDIT",
        amount=100,
        description="Intervening transaction",
        idempotency_key="intervening_001"
    )
    db_session.add(intervening)
    db_session.commit()

    # Attempt to confirm against outdated preview
    req = VoiceConfirmRequest(
        pending_id=p["pending_id"],
        session_id="stale_sess"
    )
    with pytest.raises(HTTPException) as exc_info:
        confirm_voice_transaction(req, db=db_session)
    assert exc_info.value.status_code == 409
    assert "Customer balance has changed" in exc_info.value.detail


# ============================================================================
# 3. Database Integrity & Idempotency
# ============================================================================

def test_duplicate_confirmation_idempotent(db_session):
    """Repeated confirmation replay returns existing transaction without duplicate rows."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    p = mgr.create_pending(
        session_id="idemp_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=150,
        transaction_type="PAYMENT",
        db=db_session
    )

    req = VoiceConfirmRequest(
        pending_id=p["pending_id"],
        session_id="idemp_sess"
    )
    # First confirmation
    res1 = confirm_voice_transaction(req, db=db_session)
    assert res1.success is True
    assert res1.confirmed_transaction is not None
    txn_id = res1.confirmed_transaction.id

    # Replay confirmation
    res2 = confirm_voice_transaction(req, db=db_session)
    assert res2.success is True
    assert res2.confirmed_transaction is not None
    assert res2.confirmed_transaction.id == txn_id

    # Verify database has exactly 2 transactions total (1 baseline + 1 confirmed)
    txns = db_session.scalars(select(Transaction)).all()
    assert len(txns) == 2


def test_sqlite_foreign_key_constraint_enforced(db_session):
    """Validates that PRAGMA foreign_keys=ON rejects orphaned records."""
    orphan_txn = Transaction(
        customer_id=999999,  # Non-existent customer ID
        transaction_type="CREDIT",
        amount=100,
        description="Orphan test"
    )
    db_session.add(orphan_txn)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


# ============================================================================
# 4. Secrets & Configuration Security
# ============================================================================

def test_provider_status_no_secret_leak():
    """Validates that GET /api/voice/provider-status does not expose secret keys."""
    data = get_provider_status().model_dump()
    assert "api_key" not in data
    assert "key" not in data
    assert "token" not in data
    assert "password" not in data
    assert "secret" not in data
    assert data["is_configured"] in (True, False)


def test_gitignore_protects_env_files():
    """Confirms .gitignore includes all sensitive configuration files."""
    gitignore_path = Path(__file__).resolve().parent.parent / ".gitignore"
    assert gitignore_path.exists()
    content = gitignore_path.read_text(encoding="utf-8")
    assert ".env" in content
    assert "backend/.env" in content
    assert "frontend/.env" in content


# ============================================================================
# 5. Audio & Upload Boundaries
# ============================================================================

def test_audio_payload_size_limits():
    """Validates that audio > 10MB or 0 bytes is rejected safely."""
    config = GnaniConfig()
    config.api_key = "dummy_test_key"
    stt = GnaniPrismaSTTProvider(config)

    # Empty audio
    with pytest.raises(GnaniAudioError, match="empty"):
        stt.transcribe_audio(b"")

    # Audio exceeding 10MB limit
    oversized = b"0" * (10 * 1024 * 1024 + 1)
    with pytest.raises(GnaniAudioError, match="exceeds 10MB"):
        stt.transcribe_audio(oversized)


def test_tts_text_limits():
    """Validates that TTS text > 5000 chars or empty text is rejected safely."""
    config = GnaniConfig()
    config.api_key = "dummy_test_key"
    tts = GnaniTimbreTTSProvider(config)

    # Empty text
    with pytest.raises(GnaniAudioError, match="empty"):
        tts.synthesize_speech("")

    with pytest.raises(GnaniAudioError, match="empty"):
        tts.synthesize_speech("   ")

    # Text exceeding maximum character limit
    long_text = "A" * 5001
    with pytest.raises(GnaniAudioError, match="exceeds maximum limit"):
        tts.synthesize_speech(long_text)


# ============================================================================
# 6. CORS Origin Security
# ============================================================================

def test_cors_origin_restriction():
    """Validates that allowed localhost origins are configured and untrusted origins rejected."""
    allowed_origins = []
    for middleware in app.user_middleware:
        if "CORSMiddleware" in str(middleware.cls):
            allowed_origins = middleware.kwargs.get("allow_origins", [])

    assert "http://localhost:5173" in allowed_origins
    assert "http://127.0.0.1:5173" in allowed_origins
    assert "https://malicious-attacker.evil.com" not in allowed_origins
    assert "*" not in allowed_origins  # Wildcard must NOT be allowed when credentials supported


# ============================================================================
# 7. Live Database Protection & Import Isolation
# ============================================================================

def test_live_database_remains_strictly_untouched():
    """
    Validates dukaanvoice.db cryptographic SHA-256 matches established baseline perfectly
    and read-only checks confirm zero test mutations occurred.
    """
    assert LIVE_DB_PATH.exists()
    hasher = hashlib.sha256()
    with open(LIVE_DB_PATH, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    current_hash = hasher.hexdigest().upper()
    assert current_hash == CURRENT_ESTABLISHED_SHA256, (
        f"LIVE DATABASE WAS MUTATED! Expected {CURRENT_ESTABLISHED_SHA256}, got {current_hash}"
    )

    # Read-only verification of customer, transaction, and pending records
    con = sqlite3.connect(f"file:{LIVE_DB_PATH}?mode=ro", uri=True)
    cur = con.cursor()
    customers = cur.execute("SELECT id, name, phone FROM customers").fetchall()
    transactions = cur.execute("SELECT id, customer_id, transaction_type, amount FROM transactions").fetchall()
    pending = cur.execute("SELECT * FROM pending_transactions").fetchall()
    con.close()

    assert customers == [(1, "Ramesh", "9876543210")]
    assert transactions == [(1, 1, "CREDIT", 430)]
    assert pending == []


def test_application_import_does_not_mutate_configured_database(tmp_path):
    """
    Regression Test: Proves importing the application module cannot create tables,
    modify schema, or mutate a configured database file.
    Uses a disposable temporary database with known pre-existing content and hash.
    """
    # 1. Create a disposable temporary SQLite database with a custom sample table
    disposable_db = tmp_path / "disposable_import_test.db"
    conn = sqlite3.connect(disposable_db)
    conn.execute("CREATE TABLE test_sample (id INTEGER PRIMARY KEY, note TEXT);")
    conn.execute("INSERT INTO test_sample (id, note) VALUES (1, 'initial_state');")
    conn.commit()
    conn.close()

    # 2. Record exact initial cryptographic hash
    initial_hash = hashlib.sha256(disposable_db.read_bytes()).hexdigest().upper()

    # 3. Configure environment to point DUKAANVOICE_DB_URL to the disposable db
    old_db_url = os.environ.get("DUKAANVOICE_DB_URL")
    os.environ["DUKAANVOICE_DB_URL"] = f"sqlite:///{disposable_db.as_posix()}"

    try:
        # Re-import / reload database and main modules
        if "database" in sys.modules:
            importlib.reload(sys.modules["database"])
        if "main" in sys.modules:
            importlib.reload(sys.modules["main"])
        else:
            importlib.import_module("main")

        # 4. Verify the database file was NOT mutated at all (hash matches 100%)
        post_import_hash = hashlib.sha256(disposable_db.read_bytes()).hexdigest().upper()
        assert post_import_hash == initial_hash, (
            f"Importing main mutated the database! Initial: {initial_hash}, After import: {post_import_hash}"
        )

        # 5. Verify no DukaanVoice tables (customers, transactions, pending_transactions) were created
        conn = sqlite3.connect(f"file:{disposable_db.as_posix()}?mode=ro", uri=True)
        cur = conn.cursor()
        tables = [row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        conn.close()
        assert "transactions" not in tables
        assert "pending_transactions" not in tables
        assert "customers" not in tables
        assert tables == ["test_sample"]
    finally:
        if old_db_url is not None:
            os.environ["DUKAANVOICE_DB_URL"] = old_db_url
        else:
            os.environ.pop("DUKAANVOICE_DB_URL", None)
        # Restore database module
        if "database" in sys.modules:
            importlib.reload(sys.modules["database"])
        if "main" in sys.modules:
            importlib.reload(sys.modules["main"])
