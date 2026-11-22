import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from main import app
from database import Base, get_db
from models import Customer, Transaction
from pending_manager import pending_manager

# Isolated in-memory SQLite database dedicated exclusively to tests.
# StaticPool ensures that all connections share the same in-memory database across threads.
TEST_DATABASE_URL = "sqlite:///:memory:"
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

pending_manager._session_factory = TestingSessionLocal


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


# Override FastAPI dependency so all routes use the isolated in-memory test database
app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def isolated_test_database():
    """
    Sets up a clean in-memory database with initial baseline seed records for each test.
    Never interacts with or modifies the live development database (dukaanvoice.db).
    """
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)

    # Seed baseline customer and transaction expected by tests
    db = TestingSessionLocal()
    ramesh = Customer(
        id=1,
        name="Ramesh",
        phone="9876543210"
    )
    db.add(ramesh)
    db.commit()

    initial_txn = Transaction(
        id=1,
        customer_id=1,
        transaction_type="CREDIT",
        amount=430,
        description="Voice demo - credit purchase"
    )
    db.add(initial_txn)
    db.commit()
    db.close()

    yield

    # Clean teardown strictly within the isolated in-memory test database
    Base.metadata.drop_all(bind=test_engine)


def test_health():
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"


def test_customer_ramesh_exists():
    res = client.get("/api/customers/1")
    assert res.status_code == 200
    data = res.json()
    assert data["name"] == "Ramesh"
    assert data["phone"] == "9876543210"


def test_scenario_e_duplicate_customer():
    # Attempt to create customer with duplicate phone 9876543210
    res = client.post("/api/customers/", json={
        "name": "Ramesh Duplicate",
        "phone": "9876543210"
    })
    assert res.status_code == 409
    assert "already exists" in res.json()["detail"]


def test_customer_validation():
    # Name too short
    res = client.post("/api/customers/", json={"name": "A"})
    assert res.status_code == 422

    # Invalid phone format
    res = client.post("/api/customers/", json={"name": "Test User", "phone": "123"})
    assert res.status_code == 422


def test_customer_search():
    res = client.get("/api/customers/?search=Ramesh")
    assert res.status_code == 200
    items = res.json()
    assert len(items) >= 1
    assert any(c["name"] == "Ramesh" for c in items)

    # Search by phone
    res2 = client.get("/api/customers/?search=9876543210")
    assert res2.status_code == 200
    items2 = res2.json()
    assert len(items2) >= 1
    assert items2[0]["phone"] == "9876543210"


def test_scenario_f_unknown_customer_voice():
    res = client.post("/api/voice/process", json={
        "transcript": "NonexistentPerson ge 500 udhaar haaku",
        "session_id": "test_f"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "CUSTOMER_NOT_FOUND"
    assert data["success"] is False
    assert "does not exist" in data["message"] or "sigalilla" in data["message_kn"]


def test_scenario_g_cancel_voice_transaction():
    session_id = "test_g"
    # Initiate pending
    res = client.post("/api/voice/process", json={
        "transcript": "Ramesh ge 500 udhaar haaku",
        "session_id": session_id
    })
    assert res.status_code == 200
    data = res.json()
    assert data["intent"] == "PENDING_CONFIRMATION"
    pending_id = data["pending_transaction"]["pending_id"]

    # Cancel via voice "Illa"
    res_cancel = client.post("/api/voice/process", json={
        "transcript": "Illa",
        "session_id": session_id
    })
    assert res_cancel.status_code == 200
    assert res_cancel.json()["intent"] == "CANCELLED"

    # Verify no transaction with amount 500 was created
    db = TestingSessionLocal()
    txn = db.query(Transaction).filter_by(amount=500, customer_id=1).first()
    assert txn is None
    db.close()


def test_scenario_b_correction_flow():
    session_id = "test_b"
    # 1. Shopkeeper says: "Ramesh ge 340 rupees udhaar haaku."
    res1 = client.post("/api/voice/process", json={
        "transcript": "Ramesh ge 340 rupees udhaar haaku.",
        "session_id": session_id
    })
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["intent"] == "PENDING_CONFIRMATION"
    assert d1["pending_transaction"]["amount"] == 340
    assert d1["message_kn"] == "Ramesh ge ₹340 credit add maadbekaa?"
    pending_id = d1["pending_transaction"]["pending_id"]

    # Verify 340 is NOT yet in the database!
    db = TestingSessionLocal()
    assert db.query(Transaction).filter_by(amount=340, customer_id=1).first() is None
    db.close()

    # 2. Shopkeeper corrects: "No, 430 maadu."
    res2 = client.post("/api/voice/process", json={
        "transcript": "No, 430 maadu.",
        "session_id": session_id
    })
    assert res2.status_code == 200
    d2 = res2.json()
    assert d2["intent"] == "CORRECTED"
    assert d2["pending_transaction"]["amount"] == 430
    assert d2["message_kn"] == "Okay, Ramesh ge ₹430 credit add maadbekaa?"

    # Verify 340 is STILL NOT in database, and 430 is also not yet in database!
    db = TestingSessionLocal()
    assert db.query(Transaction).filter_by(amount=340, customer_id=1).first() is None
    db.close()

    # 3. Shopkeeper confirms: "Howdu."
    res3 = client.post("/api/voice/process", json={
        "transcript": "Howdu.",
        "session_id": session_id
    })
    assert res3.status_code == 200
    d3 = res3.json()
    assert d3["intent"] == "CONFIRMED"
    assert "₹430 successfully recorded for Ramesh" in d3["message"]
    confirmed_id = d3["confirmed_transaction"]["id"]

    # Verify: Exactly ONE new transaction of 430 was saved, and NO 340 transaction exists!
    db = TestingSessionLocal()
    assert db.query(Transaction).filter_by(amount=340, customer_id=1).first() is None
    confirmed_txn = db.get(Transaction, confirmed_id)
    assert confirmed_txn is not None
    assert confirmed_txn.amount == 430
    assert confirmed_txn.transaction_type == "CREDIT"
    db.close()

    # 4. Scenario H: Duplicate confirmation test!
    # If shopkeeper says "Howdu" again or confirm button clicked again:
    res4 = client.post("/api/voice/confirm", json={
        "pending_id": pending_id,
        "session_id": session_id
    })
    assert res4.status_code == 200
    # Must return the SAME transaction id, not create a duplicate row!
    assert res4.json()["confirmed_transaction"]["id"] == confirmed_id


def test_scenario_c_and_d_payment_and_balance():
    session_id = "test_cd"
    # Get initial balance
    res_init = client.get("/api/transactions/customer/1/balance")
    initial_balance = res_init.json()["outstanding_balance"]

    # Record Payment: "Ramesh ge 100 kodidare"
    res1 = client.post("/api/voice/process", json={
        "transcript": "Ramesh ge 100 kodidare",
        "session_id": session_id
    })
    assert res1.status_code == 200
    d1 = res1.json()
    assert d1["intent"] == "PENDING_CONFIRMATION"
    assert d1["pending_transaction"]["amount"] == 100
    assert d1["pending_transaction"]["transaction_type"] == "PAYMENT"

    # Confirm Payment
    res2 = client.post("/api/voice/process", json={
        "transcript": "Howdu",
        "session_id": session_id
    })
    assert res2.status_code == 200
    assert res2.json()["intent"] == "CONFIRMED"

    # Check Balance: "Ramesh total eshtu?"
    res3 = client.post("/api/voice/process", json={
        "transcript": "Ramesh total eshtu?",
        "session_id": session_id
    })
    assert res3.status_code == 200
    d3 = res3.json()
    assert d3["intent"] == "CHECK_BALANCE"
    expected_balance = initial_balance - 100
    assert d3["customer_balance"]["outstanding_balance"] == expected_balance
    assert f"₹{expected_balance}" in d3["message"]


def test_dashboard_stats():
    res = client.get("/api/transactions/stats")
    assert res.status_code == 200
    stats = res.json()
    assert stats["customer_count"] >= 1
    assert stats["total_credit"] >= 430
    assert stats["outstanding_balance"] == stats["total_credit"] - stats["total_payments"]


def test_recent_transactions():
    res = client.get("/api/transactions/recent")
    assert res.status_code == 200
    txns = res.json()
    assert len(txns) >= 1
    assert "customer_name" in txns[0]
