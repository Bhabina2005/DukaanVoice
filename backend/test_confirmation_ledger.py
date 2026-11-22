"""
Phase 1.4 Stage D: Confirmation Experience & Ledger Consistency Test Suite.
Validates:
1. Credit confirmation and expected balance preview.
2. Payment confirmation and expected balance preview.
3. Payment equal to outstanding balance (exact settlement).
4. Payment exceeding outstanding balance (advance balance created).
5. Advance balance representation in previews and inquiries.
6. Cancelled transaction creates zero ledger entries.
7. Expired pending transaction cannot be confirmed.
8. Duplicate confirmation creates only one transaction (idempotency replay).
9. Stale balance preview is safely detected, blocked, and allows review before commit.
10. Amount correction updates preview authoritatively.
11. Dashboard stats and ledger reflect the committed transaction.
12. Failed confirmation displays accurate error and allows safe recovery.
13. Database safety: isolated in-memory SQLite database, leaving dukaanvoice.db untouched.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from datetime import datetime, timedelta
import hashlib
import sqlite3
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Customer, Transaction, PendingTransaction
from routes.voice import (
    process_voice_command,
    confirm_voice_transaction,
    cancel_voice_transaction,
    correct_voice_transaction,
    calculate_balance_dict
)
from routes.transactions import (
    get_dashboard_stats,
    get_recent_transactions,
    get_customer_balance
)
from schemas import (
    VoiceParseRequest,
    VoiceConfirmRequest,
    VoiceCancelRequest,
    VoiceCorrectRequest
)
from pending_manager import (
    pending_manager,
    compute_balance_preview,
    get_customer_net_balance
)


# =====================================================================
# Isolated In-Memory Database Fixtures
# =====================================================================

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

    # Seed baseline customer Ramesh with an existing credit of ₹430
    ramesh = Customer(id=1, name="Ramesh", phone="9876543210")
    session.add(ramesh)
    session.flush()

    seed_txn = Transaction(
        id=1,
        customer_id=1,
        transaction_type="CREDIT",
        amount=430,
        description="Seed credit purchase",
        idempotency_key="seed_tx_001"
    )
    session.add(seed_txn)
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=test_engine)


# =====================================================================
# Test Scenarios
# =====================================================================

def test_1_credit_confirmation_and_expected_balance(isolated_session):
    """1. Credit confirmation: Current ₹430 + Credit ₹500 -> Expected ₹930."""
    session_id = "test_credit_confirm_session"
    req = VoiceParseRequest(transcript="Ramesh ge 500 rupees udhaar haaku", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is True
    assert resp.intent == "PENDING_CONFIRMATION"
    assert resp.pending_transaction is not None
    assert resp.balance_preview is not None

    preview = resp.balance_preview
    assert preview.current_outstanding == 430
    assert preview.current_advance == 0
    assert preview.expected_outstanding == 930
    assert preview.expected_advance == 0
    assert preview.expected_net_balance == 930
    assert "Customer will owe ₹930" in preview.balance_explanation
    assert "930" in preview.balance_explanation_kn

    # Confirm transaction
    confirm_req = VoiceConfirmRequest(pending_id=resp.pending_transaction.pending_id, session_id=session_id)
    conf_resp = confirm_voice_transaction(confirm_req, db=isolated_session)

    assert conf_resp.success is True
    assert conf_resp.intent == "CONFIRMED"
    assert conf_resp.confirmed_transaction is not None
    assert conf_resp.confirmed_transaction.amount == 500
    assert conf_resp.confirmed_transaction.transaction_type == "CREDIT"

    # Ledger state
    txns = isolated_session.scalars(select(Transaction).where(Transaction.customer_id == 1)).all()
    assert len(txns) == 2
    bal = calculate_balance_dict(isolated_session, 1)
    assert bal["outstanding_balance"] == 930
    assert bal["advance_balance"] == 0


def test_2_payment_confirmation_and_expected_balance(isolated_session):
    """2. Payment confirmation: Current ₹430 - Payment ₹200 -> Expected ₹230."""
    session_id = "test_payment_confirm_session"
    req = VoiceParseRequest(transcript="Ramesh inda 200 bandide", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is True
    assert resp.intent == "PENDING_CONFIRMATION"
    assert resp.balance_preview is not None

    preview = resp.balance_preview
    assert preview.current_outstanding == 430
    assert preview.current_advance == 0
    assert preview.expected_outstanding == 230
    assert preview.expected_advance == 0
    assert "Customer will owe ₹230" in preview.balance_explanation

    # Confirm transaction
    conf_resp = confirm_voice_transaction(
        VoiceConfirmRequest(pending_id=resp.pending_transaction.pending_id, session_id=session_id),
        db=isolated_session
    )

    assert conf_resp.success is True
    assert conf_resp.intent == "CONFIRMED"
    bal = calculate_balance_dict(isolated_session, 1)
    assert bal["outstanding_balance"] == 230
    assert bal["advance_balance"] == 0


def test_3_payment_equal_to_outstanding_balance(isolated_session):
    """3. Payment equal to outstanding: Current ₹430 - Payment ₹430 -> Expected ₹0 (Settled)."""
    session_id = "test_exact_pay_session"
    req = VoiceParseRequest(transcript="Ramesh paid 430", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is True
    preview = resp.balance_preview
    assert preview.current_outstanding == 430
    assert preview.expected_outstanding == 0
    assert preview.expected_advance == 0
    assert "Account will be fully settled" in preview.balance_explanation
    assert "ಚುಕ್ತಾ" in preview.balance_explanation_kn

    conf_resp = confirm_voice_transaction(
        VoiceConfirmRequest(pending_id=resp.pending_transaction.pending_id, session_id=session_id),
        db=isolated_session
    )

    assert conf_resp.success is True
    bal = calculate_balance_dict(isolated_session, 1)
    assert bal["outstanding_balance"] == 0
    assert bal["advance_balance"] == 0
    assert bal["display_outstanding"] == 0


def test_4_payment_exceeding_outstanding_balance(isolated_session):
    """4. Payment exceeding outstanding: Current ₹430 - Payment ₹500 -> Expected ₹0, Advance ₹70."""
    session_id = "test_overpay_session"
    req = VoiceParseRequest(transcript="Received 500 from Ramesh", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is True
    preview = resp.balance_preview
    assert preview.current_outstanding == 430
    assert preview.expected_outstanding == 0
    assert preview.expected_advance == 70
    assert preview.expected_net_balance == -70
    assert "Customer will have an advance balance of ₹70" in preview.balance_explanation
    assert "ಮುಂಗಡ" in preview.balance_explanation_kn

    conf_resp = confirm_voice_transaction(
        VoiceConfirmRequest(pending_id=resp.pending_transaction.pending_id, session_id=session_id),
        db=isolated_session
    )

    assert conf_resp.success is True
    bal = calculate_balance_dict(isolated_session, 1)
    assert bal["outstanding_balance"] == -70  # Raw net balance preserved
    assert bal["display_outstanding"] == 0     # Kirana display outstanding is 0
    assert bal["advance_balance"] == 70        # Clear advance representation


def test_5_advance_balance_representation(isolated_session):
    """5. Advance balance representation across inquiries and subsequent transactions."""
    # First record payment of ₹500 against ₹430 dues to create ₹70 advance
    pending = pending_manager.create_pending("session_adv", 1, "Ramesh", "9876543210", 500, "PAYMENT", db=isolated_session)
    pending_manager.confirm_pending(pending["pending_id"], db=isolated_session)

    # 1. Balance inquiry when customer has advance
    inq_resp = process_voice_command(
        VoiceParseRequest(transcript="Ramesh total eshtu?", session_id="inq_sess"),
        db=isolated_session
    )
    assert inq_resp.success is True
    assert inq_resp.intent == "CHECK_BALANCE"
    assert "advance balance of ₹70" in inq_resp.message
    assert "mungada" in inq_resp.message_kn

    # 2. Credit of ₹50 against ₹70 advance -> still ₹20 advance remaining
    credit_50 = pending_manager.create_pending("session_adv2", 1, "Ramesh", "9876543210", 50, "CREDIT", db=isolated_session)
    preview_50 = credit_50["balance_preview"]
    assert preview_50["current_outstanding"] == 0
    assert preview_50["current_advance"] == 70
    assert preview_50["expected_outstanding"] == 0
    assert preview_50["expected_advance"] == 20
    assert "advance balance of ₹20" in preview_50["balance_explanation"]

    # 3. Credit of ₹100 against ₹70 advance -> flips to ₹30 outstanding due
    credit_100 = pending_manager.create_pending("session_adv3", 1, "Ramesh", "9876543210", 100, "CREDIT", db=isolated_session)
    preview_100 = credit_100["balance_preview"]
    assert preview_100["current_outstanding"] == 0
    assert preview_100["current_advance"] == 70
    assert preview_100["expected_outstanding"] == 30
    assert preview_100["expected_advance"] == 0
    assert "Customer will owe ₹30" in preview_100["balance_explanation"]


def test_6_cancelled_transaction_creates_no_ledger_entry(isolated_session):
    """6. Cancelled transaction creates no ledger entry and cannot be confirmed."""
    initial_tx_count = isolated_session.scalar(select(func.count(Transaction.id)))

    pending = pending_manager.create_pending("sess_cancel", 1, "Ramesh", "9876543210", 500, "CREDIT", db=isolated_session)
    pending_id = pending["pending_id"]

    # Cancel
    cancel_resp = cancel_voice_transaction(
        VoiceCancelRequest(pending_id=pending_id, session_id="sess_cancel"),
        db=isolated_session
    )
    assert cancel_resp.success is True
    assert cancel_resp.intent == "CANCELLED"

    # Verify ledger untouched
    final_tx_count = isolated_session.scalar(select(func.count(Transaction.id)))
    assert final_tx_count == initial_tx_count

    # Confirmation of cancelled transaction must fail
    with pytest.raises(Exception):
        confirm_voice_transaction(
            VoiceConfirmRequest(pending_id=pending_id, session_id="sess_cancel"),
            db=isolated_session
        )


def test_7_expired_pending_transaction_cannot_be_confirmed(isolated_session):
    """7. Expired pending transaction cannot be confirmed."""
    initial_tx_count = isolated_session.scalar(select(func.count(Transaction.id)))

    pending = pending_manager.create_pending("sess_expire", 1, "Ramesh", "9876543210", 300, "CREDIT", db=isolated_session)
    pending_id = pending["pending_id"]

    # Manually expire
    rec = isolated_session.get(PendingTransaction, pending_id)
    rec.expires_at = datetime.now() - timedelta(seconds=1)
    isolated_session.commit()

    with pytest.raises(Exception) as excinfo:
        confirm_voice_transaction(
            VoiceConfirmRequest(pending_id=pending_id, session_id="sess_expire"),
            db=isolated_session
        )

    assert "expired" in str(excinfo.value).lower()
    final_tx_count = isolated_session.scalar(select(func.count(Transaction.id)))
    assert final_tx_count == initial_tx_count


def test_8_duplicate_confirmation_creates_only_one_transaction(isolated_session):
    """8. Duplicate confirmation is idempotent and creates only one transaction."""
    pending = pending_manager.create_pending("sess_dup", 1, "Ramesh", "9876543210", 150, "PAYMENT", db=isolated_session)
    pending_id = pending["pending_id"]

    # First confirmation
    res1, txn1 = pending_manager.confirm_pending(pending_id, db=isolated_session)
    assert res1["status"] == "CONFIRMED"
    assert txn1 is not None
    first_txn_id = txn1.id

    # Second confirmation (duplicate attempt)
    res2, txn2 = pending_manager.confirm_pending(pending_id, db=isolated_session)
    assert res2["status"] == "CONFIRMED"
    assert txn2 is not None
    assert txn2.id == first_txn_id

    # Verify exactly 1 new transaction in database (1 seed + 1 new = 2 total)
    total_txns = isolated_session.scalars(select(Transaction).where(Transaction.customer_id == 1)).all()
    assert len(total_txns) == 2


def test_9_stale_balance_preview_is_handled_safely(isolated_session):
    """9. Stale balance preview is safely blocked when balance changes during pending state."""
    session_id = "sess_stale_test"

    # Step 1: User prepares credit transaction of ₹500 based on current ₹430 balance
    req = VoiceParseRequest(transcript="Ramesh ge 500 rupees udhaar haaku", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)
    pending_id = resp.pending_transaction.pending_id
    assert resp.balance_preview.current_outstanding == 430
    assert resp.balance_preview.expected_outstanding == 930
    assert resp.balance_preview.baseline_balance == 430

    # Step 2: Intervening transaction occurs (e.g. customer makes ₹200 payment via cash or another device)
    intervening_tx = Transaction(
        customer_id=1,
        transaction_type="PAYMENT",
        amount=200,
        description="Intervening cash payment",
        idempotency_key="intervening_001"
    )
    isolated_session.add(intervening_tx)
    isolated_session.commit()

    # Authoritative balance is now ₹230, not ₹430!
    assert get_customer_net_balance(isolated_session, 1) == 230

    # Step 3: User attempts to confirm against the outdated preview
    # Via confirm_pending: must raise ValueError and update the preview to reality
    with pytest.raises(ValueError) as excinfo:
        pending_manager.confirm_pending(pending_id, db=isolated_session)

    assert "balance has changed" in str(excinfo.value).lower()

    # Step 4: Verify NO transaction was committed for the pending credit!
    # (Only seed credit + intervening payment exist)
    txns = isolated_session.scalars(select(Transaction).where(Transaction.customer_id == 1)).all()
    assert len(txns) == 2

    # Step 5: Verify pending transaction now has the refreshed balance preview
    refreshed_pending = pending_manager.get_pending(pending_id, db=isolated_session)
    updated_preview = refreshed_pending["balance_preview"]
    assert updated_preview["current_outstanding"] == 230
    assert updated_preview["expected_outstanding"] == 730
    assert updated_preview["baseline_balance"] == 230

    # Step 6: Confirmation of the updated reality now succeeds safely
    res_ok, txn_ok = pending_manager.confirm_pending(pending_id, db=isolated_session)
    assert res_ok["status"] == "CONFIRMED"
    assert txn_ok is not None
    assert txn_ok.amount == 500

    # Final balance: 430 - 200 + 500 = 730
    bal = calculate_balance_dict(isolated_session, 1)
    assert bal["outstanding_balance"] == 730


def test_10_amount_correction_updates_preview_authoritatively(isolated_session):
    """10. Amount correction updates preview authoritatively before commit."""
    session_id = "sess_correct_preview"

    # Create with ₹340
    req = VoiceParseRequest(transcript="Ramesh ge 340 rupees udhaar haaku", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)
    pending_id = resp.pending_transaction.pending_id
    assert resp.balance_preview.expected_outstanding == 770

    # Correct to ₹430
    corr_req = VoiceParseRequest(transcript="No, 430 maadu", session_id=session_id)
    corr_resp = process_voice_command(corr_req, db=isolated_session)
    assert corr_resp.intent == "CORRECTED"
    assert corr_resp.balance_preview.expected_outstanding == 860

    # Confirm
    conf_res, txn = pending_manager.confirm_pending(pending_id, db=isolated_session)
    assert conf_res["amount"] == 430
    assert txn.amount == 430
    bal = calculate_balance_dict(isolated_session, 1)
    assert bal["outstanding_balance"] == 860


def test_11_dashboard_and_ledger_reflect_committed_transaction(isolated_session):
    """11. Dashboard and ledger reflect the committed transaction."""
    stats_before = get_dashboard_stats(db=isolated_session)
    assert stats_before.total_credit == 430
    assert stats_before.total_payments == 0
    assert stats_before.outstanding_balance == 430
    assert stats_before.transaction_count == 1

    # Commit payment of ₹500
    pending = pending_manager.create_pending("dash_sess", 1, "Ramesh", "9876543210", 500, "PAYMENT", db=isolated_session)
    pending_manager.confirm_pending(pending["pending_id"], db=isolated_session)

    stats_after = get_dashboard_stats(db=isolated_session)
    assert stats_after.total_credit == 430
    assert stats_after.total_payments == 500
    assert stats_after.outstanding_balance == -70
    assert stats_after.transaction_count == 2

    # Verify ledger entries
    recent = get_recent_transactions(limit=10, db=isolated_session)
    assert len(recent) == 2
    latest = recent[0]
    assert latest.transaction_type == "PAYMENT"
    assert latest.amount == 500
    assert latest.customer_name == "Ramesh"


def test_12_failed_confirmation_displays_error_and_allows_safe_recovery(isolated_session):
    """12. Failed confirmation displays accurate error and allows safe recovery."""
    session_id = "sess_recovery"
    req = VoiceParseRequest(transcript="Ramesh inda 100 bandide", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)
    pending_id = resp.pending_transaction.pending_id

    # Create conflict: another payment commits
    isolated_session.add(Transaction(
        customer_id=1,
        transaction_type="PAYMENT",
        amount=50,
        description="Conflicting payment",
        idempotency_key="conflict_01"
    ))
    isolated_session.commit()

    # Voice confirmation returns STALE_PREVIEW with helpful message
    conf_voice = process_voice_command(
        VoiceParseRequest(transcript="Howdu", session_id=session_id),
        db=isolated_session
    )
    assert conf_voice.success is False
    assert conf_voice.intent == "STALE_PREVIEW"
    assert "Customer balance has changed" in conf_voice.message
    assert conf_voice.pending_transaction is not None
    # Preview has been updated to current state
    assert conf_voice.balance_preview.current_outstanding == 380

    # User re-confirms with voice -> succeeds cleanly
    conf_voice_2 = process_voice_command(
        VoiceParseRequest(transcript="Howdu", session_id=session_id),
        db=isolated_session
    )
    assert conf_voice_2.success is True
    assert conf_voice_2.intent == "CONFIRMED"


def test_13_live_database_records_untouched():
    """13. Live database verification: SHA-256 and records strictly untouched."""
    db_path = Path(__file__).parent / "dukaanvoice.db"
    assert db_path.exists(), "Live database file must exist"

    with open(db_path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest().upper()

    established_hash = "3761249911DD017076A1E369220825AA055811C95E30E010B73CC2F4810043CC"
    historical_hash = "2B0363C99E9BF0788C17FA10E77CDBAB958801644DA4CF77597AD9AD2D073FA3"
    assert file_hash in (established_hash, historical_hash), f"Hash mismatch! {file_hash} not in {(established_hash, historical_hash)}"

    # Read-only verification of records
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    cur = con.cursor()
    customers = cur.execute("SELECT id, name, phone FROM customers").fetchall()
    transactions = cur.execute("SELECT id, customer_id, transaction_type, amount FROM transactions").fetchall()
    con.close()

    assert customers == [(1, "Ramesh", "9876543210")]
    assert transactions == [(1, 1, "CREDIT", 430)]
