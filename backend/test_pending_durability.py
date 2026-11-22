import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import threading
from datetime import datetime, timedelta
import pytest
from sqlalchemy import create_engine, select, func, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.exc import IntegrityError

from database import Base
from models import Customer, Transaction, PendingTransaction
from pending_manager import PendingTransactionManager

# Isolated in-memory SQLite database dedicated exclusively to durability tests.
TEST_DATABASE_URL = "sqlite:///:memory:"

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    if type(dbapi_connection).__module__.startswith("sqlite3"):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=test_engine
)


@pytest.fixture(autouse=True)
def setup_isolated_db():
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    # Seed baseline customer
    db = TestingSessionLocal()
    ramesh = Customer(id=1, name="Ramesh", phone="9876543210")
    suresh = Customer(id=2, name="Suresh", phone="9123456789")
    db.add_all([ramesh, suresh])
    db.commit()
    db.close()

    yield

    Base.metadata.drop_all(bind=test_engine)


def test_scenario_1_and_2_create_and_restart_recovery():
    """Scenarios 1 & 2: Create pending transaction, simulate backend restart, and retrieve it."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    sess_id = "test_restart_session"

    # 1. Create pending transaction
    created = mgr.create_pending(
        session_id=sess_id,
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=500,
        transaction_type="CREDIT",
        description="Pre-restart credit"
    )
    pending_id = created["pending_id"]
    assert created["status"] == "PENDING"
    assert created["amount"] == 500

    # 2. Simulate Backend Restart by destroying manager instance
    del mgr

    # 3. Fresh manager instance (simulates new server process connecting to DB)
    new_mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    recovered = new_mgr.get_pending(pending_id)
    assert recovered is not None
    assert recovered["pending_id"] == pending_id
    assert recovered["amount"] == 500
    assert recovered["customer_name"] == "Ramesh"
    assert recovered["status"] == "PENDING"

    # 4. Verify session lookup after restart
    active_recovered = new_mgr.get_active_for_session(sess_id)
    assert active_recovered is not None
    assert active_recovered["pending_id"] == pending_id


def test_scenario_3_correction_and_persistence_across_restart():
    """Scenario 3: Correct amount and verify persistence across simulated restart."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    sess_id = "test_corr_session"

    # 1. Create with ₹340
    p = mgr.create_pending(
        session_id=sess_id,
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=340,
        transaction_type="CREDIT"
    )
    pid = p["pending_id"]

    # 2. Correct to ₹430
    corrected = mgr.correct_pending(pid, amount=430)
    assert corrected["amount"] == 430

    # 3. Simulate Restart
    del mgr
    fresh_mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    loaded = fresh_mgr.get_pending(pid)
    assert loaded["amount"] == 430
    # Verify audit trail contains correction record
    actions = [a["action"] for a in loaded["audit_trail"]]
    assert "CREATED" in actions
    assert "CORRECTED" in actions


def test_scenario_4_atomic_confirmation_exactly_once():
    """Scenario 4: Confirm transaction exactly once and verify ledger row."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    db = TestingSessionLocal()

    p = mgr.create_pending(
        session_id="test_atomic_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=430,
        transaction_type="CREDIT"
    )
    pid = p["pending_id"]

    # Confirm
    confirmed_record, db_txn = mgr.confirm_pending(pid, db=db)
    assert confirmed_record["status"] == "CONFIRMED"
    assert db_txn is not None
    assert db_txn.amount == 430
    assert db_txn.idempotency_key == pid

    # Verify exactly 1 transaction in DB
    txns = db.scalars(select(Transaction).where(Transaction.idempotency_key == pid)).all()
    assert len(txns) == 1
    db.close()


def test_scenario_5_repeat_confirmation_idempotency_replay():
    """Scenario 5: Repeat confirmation after commit; returns existing transaction without duplicate."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    db = TestingSessionLocal()

    p = mgr.create_pending(
        session_id="test_idemp_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=250,
        transaction_type="PAYMENT"
    )
    pid = p["pending_id"]

    # First confirmation
    rec1, txn1 = mgr.confirm_pending(pid, db=db)
    orig_txn_id = txn1.id

    # Second confirmation (replay / double-click)
    rec2, txn2 = mgr.confirm_pending(pid, db=db)
    assert rec2["status"] == "CONFIRMED"
    assert txn2.id == orig_txn_id

    # Third confirmation after simulated server restart
    del mgr
    fresh_mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    rec3, txn3 = fresh_mgr.confirm_pending(pid, db=db)
    assert txn3.id == orig_txn_id

    # Verify ledger only has 1 transaction row
    count = db.scalar(select(func.count(Transaction.id)).where(Transaction.idempotency_key == pid))
    assert count == 1
    db.close()


def test_scenario_6_concurrent_confirmation_race():
    """Scenario 6: Simulate concurrent confirmation attempts from multiple threads."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    p = mgr.create_pending(
        session_id="test_concurrent_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=750,
        transaction_type="CREDIT"
    )
    pid = p["pending_id"]

    results = []
    errors = []

    def confirm_worker():
        db = TestingSessionLocal()
        try:
            rec, txn = mgr.confirm_pending(pid, db=db)
            results.append((rec, txn.id if txn else None))
        except Exception as e:
            errors.append(e)
        finally:
            db.close()

    t1 = threading.Thread(target=confirm_worker)
    t2 = threading.Thread(target=confirm_worker)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Both threads must succeed without raising unhandled errors
    assert len(errors) == 0
    assert len(results) == 2
    # Both must reference the exact same transaction ID
    assert results[0][1] == results[1][1]

    # Verify ledger has exactly 1 row
    verify_db = TestingSessionLocal()
    total = verify_db.scalar(select(func.count(Transaction.id)).where(Transaction.idempotency_key == pid))
    assert total == 1
    verify_db.close()


def test_scenario_7_cancellation_safety():
    """Scenario 7: Cancel pending transaction; never creates ledger entry, cannot be confirmed later."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    db = TestingSessionLocal()

    p = mgr.create_pending(
        session_id="test_cancel_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=600,
        transaction_type="CREDIT"
    )
    pid = p["pending_id"]

    # Cancel
    cancelled = mgr.cancel_pending(pid, db=db)
    assert cancelled["status"] == "CANCELLED"

    # Confirming a cancelled transaction must fail
    with pytest.raises(ValueError, match="Cannot confirm a cancelled transaction"):
        mgr.confirm_pending(pid, db=db)

    # Verify zero ledger records were created
    count = db.scalar(select(func.count(Transaction.id)).where(Transaction.idempotency_key == pid))
    assert count == 0
    db.close()


def test_scenario_8_rejection_of_expired_transactions():
    """Scenario 8: Reject confirmation and correction of expired transactions (TTL)."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    db = TestingSessionLocal()

    p = mgr.create_pending(
        session_id="test_expiry_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=300,
        transaction_type="CREDIT"
    )
    pid = p["pending_id"]

    # Manually expire the record in database (simulate 16 minutes elapsed)
    db_p = db.get(PendingTransaction, pid)
    db_p.expires_at = datetime.now() - timedelta(minutes=16)
    db.commit()

    # Attempt to confirm expired transaction
    with pytest.raises(ValueError, match="Transaction has expired"):
        mgr.confirm_pending(pid, db=db)

    # Attempt to correct expired transaction
    with pytest.raises(ValueError, match=r"(?i)expired"):
        mgr.correct_pending(pid, amount=350, db=db)

    # Verify get_pending marks it EXPIRED
    expired_rec = mgr.get_pending(pid, db=db)
    assert expired_rec["status"] == "EXPIRED"

    # Verify zero ledger rows
    count = db.scalar(select(func.count(Transaction.id)).where(Transaction.idempotency_key == pid))
    assert count == 0
    db.close()


def test_scenario_9_commit_failure_rollback():
    """Scenario 9: Simulated database failure rolls back cleanly without inconsistent state."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)
    db = TestingSessionLocal()

    p = mgr.create_pending(
        session_id="test_rollback_sess",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=400,
        transaction_type="CREDIT"
    )
    pid = p["pending_id"]

    # Corrupt the pending record's customer_id to a non-existent customer in-memory
    # to trigger an integrity violation on commit
    db_p = db.get(PendingTransaction, pid)
    db_p.customer_id = 99999  # Does not exist in Customers table

    with pytest.raises(Exception):
        mgr.confirm_pending(pid, db=db)

    # Verify no transaction was recorded
    count = db.scalar(select(func.count(Transaction.id)).where(Transaction.amount == 400))
    assert count == 0
    db.close()


def test_scenario_10_multi_user_session_isolation():
    """Scenario 10: Verify multiple users cannot access or overwrite each other's pending transactions."""
    mgr = PendingTransactionManager(session_factory=TestingSessionLocal)

    # User A initiates ₹300 credit for Ramesh
    p_a = mgr.create_pending(
        session_id="user_session_A",
        customer_id=1,
        customer_name="Ramesh",
        customer_phone="9876543210",
        amount=300,
        transaction_type="CREDIT"
    )

    # User B simultaneously initiates ₹700 payment for Suresh
    p_b = mgr.create_pending(
        session_id="user_session_B",
        customer_id=2,
        customer_name="Suresh",
        customer_phone="9123456789",
        amount=700,
        transaction_type="PAYMENT"
    )

    # Verify isolation
    active_a = mgr.get_active_for_session("user_session_A")
    active_b = mgr.get_active_for_session("user_session_B")

    assert active_a["pending_id"] == p_a["pending_id"]
    assert active_a["customer_name"] == "Ramesh"
    assert active_a["amount"] == 300

    assert active_b["pending_id"] == p_b["pending_id"]
    assert active_b["customer_name"] == "Suresh"
    assert active_b["amount"] == 700

    # User A confirms; User B's transaction must remain intact
    db = TestingSessionLocal()
    mgr.confirm_pending(p_a["pending_id"], db=db)

    active_b_after = mgr.get_active_for_session("user_session_B")
    assert active_b_after["status"] == "PENDING"
    assert active_b_after["amount"] == 700
    db.close()


def test_scenario_11_sqlite_foreign_key_enforcement():
    """Scenario 11: Verify SQLite foreign-key constraint enforcement is active."""
    db = TestingSessionLocal()

    # Attempt to insert transaction for non-existent customer 9999
    bad_txn = Transaction(
        customer_id=9999,
        transaction_type="CREDIT",
        amount=100
    )
    db.add(bad_txn)

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()

    # Attempt to insert pending transaction for non-existent customer 9999
    bad_pending = PendingTransaction(
        id="bad-uuid",
        session_id="sess_bad",
        customer_id=9999,
        customer_name="Ghost",
        amount=100,
        transaction_type="CREDIT",
        expires_at=datetime.now() + timedelta(minutes=15)
    )
    db.add(bad_pending)

    with pytest.raises(IntegrityError):
        db.commit()

    db.rollback()
    db.close()


def test_scenario_12_live_database_records_untouched():
    """Scenario 12: Verify live database records and files remain intact and untouched."""
    import sqlite3
    live_db_path = Path(__file__).resolve().parent / "dukaanvoice.db"
    conn = sqlite3.connect(f"file:{live_db_path}?mode=ro", uri=True)
    cur = conn.cursor()

    custs = cur.execute("SELECT id, name, phone FROM customers").fetchall()
    txns = cur.execute("SELECT id, customer_id, transaction_type, amount FROM transactions").fetchall()
    conn.close()

    assert len(custs) == 1, f"Expected 1 customer in live DB, found {len(custs)}"
    assert custs[0][0] == 1 and custs[0][1] == "Ramesh" and custs[0][2] == "9876543210"

    assert len(txns) == 1, f"Expected 1 transaction in live DB, found {len(txns)}"
    assert txns[0][0] == 1 and txns[0][2] == "CREDIT" and txns[0][3] == 430
