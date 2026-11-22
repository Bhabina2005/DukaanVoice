import httpx
import sqlite3
from pathlib import Path

BASE_URL = "http://localhost:8000"
DB_PATH = Path(__file__).resolve().parent / "dukaanvoice.db"


def run_e2e_tests():
    print("=== STARTING DUKAANVOICE E2E VERIFICATION ===")
    client = httpx.Client(base_url=BASE_URL, timeout=10.0)

    # 1. Health & Initial State Verification
    print("\n[1] Checking Backend Health...")
    r = client.get("/health")
    assert r.status_code == 200, f"Health check failed: {r.status_code}"
    print(" -> Health check passed:", r.json())

    print("\n[2] Checking Existing Customer 1 (Ramesh) & Seed Data...")
    r = client.get("/api/customers/1")
    assert r.status_code == 200, f"Customer 1 not found: {r.status_code}"
    customer = r.json()
    assert customer["name"] == "Ramesh"
    assert customer["phone"] == "9876543210"
    print(f" -> Found Customer: {customer['name']} (ID: {customer['id']}, Phone: {customer['phone']})")

    r_bal = client.get("/api/transactions/customer/1/balance")
    assert r_bal.status_code == 200
    bal_data = r_bal.json()
    print(f" -> Initial Balance: Total Credit = ₹{bal_data['total_credit']}, Total Payments = ₹{bal_data['total_payments']}, Outstanding = ₹{bal_data['outstanding_balance']}")

    # -------------------------------------------------------------
    # Scenario E: Duplicate Customer
    # -------------------------------------------------------------
    print("\n[Scenario E] Attempting to create duplicate customer with phone 9876543210...")
    r_dup = client.post("/api/customers/", json={"name": "Duplicate Ramesh", "phone": "9876543210"})
    assert r_dup.status_code == 409, f"Expected 409 Conflict, got {r_dup.status_code}"
    print(" -> PASS: Duplicate phone properly rejected with HTTP 409:", r_dup.json()["detail"])

    # -------------------------------------------------------------
    # Scenario F: Nonexistent Customer Voice Command
    # -------------------------------------------------------------
    print("\n[Scenario F] Voice command for nonexistent customer: 'Girish ge 500 udhaar haaku'...")
    r_unknown = client.post("/api/voice/process", json={
        "transcript": "Girish ge 500 udhaar haaku",
        "session_id": "session_unknown"
    })
    assert r_unknown.status_code == 200
    unknown_data = r_unknown.json()
    assert unknown_data["intent"] == "CUSTOMER_NOT_FOUND"
    assert unknown_data["success"] is False
    print(" -> PASS: Safely handled nonexistent customer without DB corruption:", unknown_data["message"])

    # -------------------------------------------------------------
    # Scenario G: Cancellation
    # -------------------------------------------------------------
    print("\n[Scenario G] Creating pending transaction and then cancelling with 'Illa'...")
    sess_g = "session_cancel_test"
    r_pend = client.post("/api/voice/process", json={
        "transcript": "Ramesh ge 500 udhaar haaku",
        "session_id": sess_g
    })
    assert r_pend.status_code == 200
    p_data = r_pend.json()
    assert p_data["intent"] == "PENDING_CONFIRMATION"
    pending_id_g = p_data["pending_transaction"]["pending_id"]
    print(f" -> Pending created (ID {pending_id_g}): ₹{p_data['pending_transaction']['amount']}")

    # Cancel via voice "Illa."
    r_cancel = client.post("/api/voice/process", json={
        "transcript": "Illa.",
        "session_id": sess_g
    })
    assert r_cancel.status_code == 200
    cancel_data = r_cancel.json()
    assert cancel_data["intent"] == "CANCELLED"
    print(" -> PASS: Voice cancellation succeeded:", cancel_data["message"])

    # Verify no transaction of 500 was committed to DB
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM transactions WHERE amount = 500 AND customer_id = 1")
    count_500 = cur.fetchone()[0]
    assert count_500 == 0, "Error: Cancelled transaction was erroneously written to DB!"
    con.close()
    print(" -> PASS: Verified SQLite ledger has 0 records of the cancelled ₹500 transaction.")

    # -------------------------------------------------------------
    # Scenario B: Amount Correction Flow
    # Shopkeeper: "Ramesh ge 340 rupees udhaar haaku."
    # DukaanVoice: "Ramesh ge ₹340 credit add maadbekaa?"
    # Shopkeeper: "No, 430 maadu."
    # DukaanVoice: "Okay, Ramesh ge ₹430 credit add maadbekaa?"
    # Shopkeeper: "Howdu."
    # DukaanVoice: "₹430 successfully recorded for Ramesh."
    # -------------------------------------------------------------
    print("\n[Scenario B] Full Voice Correction Flow...")
    sess_b = "session_correction_flow"

    # Step 1: Initial speech
    print(" Step 1: Shopkeeper says: 'Ramesh ge 340 rupees udhaar haaku.'")
    r1 = client.post("/api/voice/process", json={
        "transcript": "Ramesh ge 340 rupees udhaar haaku.",
        "session_id": sess_b
    })
    assert r1.status_code == 200
    d1 = r1.json()
    assert d1["intent"] == "PENDING_CONFIRMATION"
    assert d1["pending_transaction"]["amount"] == 340
    print(f" -> DukaanVoice: \"{d1['message_kn']}\" (Pending amount: ₹{d1['pending_transaction']['amount']})")

    # Verify 340 is NOT yet in database
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM transactions WHERE amount = 340")
    assert cur.fetchone()[0] == 0, "Error: Pending ₹340 was saved prematurely!"
    con.close()
    print(" -> PASS: Verified ₹340 is NOT in SQLite ledger (pending only).")

    # Step 2: Correction
    print(" Step 2: Shopkeeper says: 'No, 430 maadu.'")
    r2 = client.post("/api/voice/process", json={
        "transcript": "No, 430 maadu.",
        "session_id": sess_b
    })
    assert r2.status_code == 200
    d2 = r2.json()
    assert d2["intent"] == "CORRECTED"
    assert d2["pending_transaction"]["amount"] == 430
    print(f" -> DukaanVoice: \"{d2['message_kn']}\" (Updated pending amount: ₹{d2['pending_transaction']['amount']})")

    # Verify 340 is still NOT in database, and 430 is also not yet in database
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM transactions WHERE amount = 340")
    assert cur.fetchone()[0] == 0
    cur.execute("SELECT COUNT(*) FROM transactions WHERE amount = 430 AND id > 1")
    assert cur.fetchone()[0] == 0
    con.close()
    print(" -> PASS: Verified ledger is still UNTOUCHED after correction.")

    # Step 3: Confirmation
    print(" Step 3: Shopkeeper says: 'Howdu.'")
    r3 = client.post("/api/voice/process", json={
        "transcript": "Howdu.",
        "session_id": sess_b
    })
    assert r3.status_code == 200
    d3 = r3.json()
    assert d3["intent"] == "CONFIRMED"
    confirmed_id = d3["confirmed_transaction"]["id"]
    print(f" -> DukaanVoice: \"{d3['message']}\" (Recorded as Txn #{confirmed_id})")

    # Verify: Exactly one ₹430 transaction entered ledger, NO ₹340 transaction exists
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM transactions WHERE amount = 340")
    assert cur.fetchone()[0] == 0, "Error: ₹340 transaction was found in database!"
    cur.execute("SELECT id, transaction_type, amount, description FROM transactions WHERE id = ?", (confirmed_id,))
    row = cur.fetchone()
    assert row is not None
    assert row[1] == "CREDIT"
    assert row[2] == 430
    con.close()
    print(f" -> PASS: Verified only the confirmed ₹430 transaction (#{confirmed_id}) entered the SQLite database.")

    # -------------------------------------------------------------
    # Scenario H: Duplicate Confirmation Prevention (Idempotency)
    # -------------------------------------------------------------
    print("\n[Scenario H] Testing duplicate confirmation prevention (sending 'Howdu' / confirm again)...")
    pending_id_b = d2["pending_transaction"]["pending_id"]
    r_dup_confirm = client.post("/api/voice/confirm", json={
        "pending_id": pending_id_b,
        "session_id": sess_b
    })
    assert r_dup_confirm.status_code == 200
    dup_data = r_dup_confirm.json()
    assert dup_data["confirmed_transaction"]["id"] == confirmed_id
    # Check that no new row was added to SQLite
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM transactions WHERE id > 1")
    count_after_dup = cur.fetchone()[0]
    assert count_after_dup == 1, f"Expected exactly 1 new transaction, got {count_after_dup}"
    con.close()
    print(" -> PASS: Idempotent confirmation successfully prevented duplicate transaction entry.")

    # -------------------------------------------------------------
    # Scenario C: Payment Transaction
    # Shopkeeper: "Ramesh ge 100 kodidare."
    # -------------------------------------------------------------
    print("\n[Scenario C] Recording PAYMENT: 'Ramesh ge 100 kodidare'...")
    sess_c = "session_payment_flow"
    r_pay = client.post("/api/voice/process", json={
        "transcript": "Ramesh ge 100 kodidare",
        "session_id": sess_c
    })
    assert r_pay.status_code == 200
    pay_data = r_pay.json()
    assert pay_data["intent"] == "PENDING_CONFIRMATION"
    assert pay_data["pending_transaction"]["transaction_type"] == "PAYMENT"
    assert pay_data["pending_transaction"]["amount"] == 100
    print(f" -> DukaanVoice: \"{pay_data['message_kn']}\"")

    # Confirm Payment
    r_pay_confirm = client.post("/api/voice/process", json={
        "transcript": "Howdu.",
        "session_id": sess_c
    })
    assert r_pay_confirm.status_code == 200
    pay_confirm_data = r_pay_confirm.json()
    assert pay_confirm_data["intent"] == "CONFIRMED"
    print(f" -> DukaanVoice: \"{pay_confirm_data['message']}\"")

    # -------------------------------------------------------------
    # Scenario D: Balance Inquiry
    # Shopkeeper: "Ramesh total eshtu?"
    # -------------------------------------------------------------
    print("\n[Scenario D] Asking for balance: 'Ramesh total eshtu?'...")
    r_bal_voice = client.post("/api/voice/process", json={
        "transcript": "Ramesh total eshtu?",
        "session_id": "session_bal_check"
    })
    assert r_bal_voice.status_code == 200
    bal_voice_data = r_bal_voice.json()
    assert bal_voice_data["intent"] == "CHECK_BALANCE"
    real_balance = bal_voice_data["customer_balance"]["outstanding_balance"]
    print(f" -> DukaanVoice: \"{bal_voice_data['message_kn']}\"")
    print(f" -> Actual outstanding balance retrieved from SQLite: ₹{real_balance}")

    # Verify calculation: Initial 430 + 430 credit - 100 payment = 760
    assert real_balance == (430 + 430 - 100), f"Balance mismatch: expected 760, got {real_balance}"
    print(f" -> PASS: Outstanding balance accurately computed from SQLite records: ₹{real_balance}")

    # -------------------------------------------------------------
    # Dashboard & Ledger Verification
    # -------------------------------------------------------------
    print("\n[Dashboard & Ledger APIs] Verifying stats and recent transactions...")
    r_stats = client.get("/api/transactions/stats")
    assert r_stats.status_code == 200
    stats = r_stats.json()
    assert stats["outstanding_balance"] == stats["total_credit"] - stats["total_payments"]
    print(f" -> Dashboard Stats: Credit=₹{stats['total_credit']}, Payments=₹{stats['total_payments']}, Net=₹{stats['outstanding_balance']}")

    r_recent = client.get("/api/transactions/recent")
    assert r_recent.status_code == 200
    recent = r_recent.json()
    assert len(recent) >= 3
    print(f" -> Recent transactions retrieved: {len(recent)} records. Latest: {recent[0]['customer_name']} {recent[0]['transaction_type']} ₹{recent[0]['amount']}")

    # Clean up test transactions added during this e2e run to preserve seed data
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM transactions WHERE id > 1")
    con.commit()
    con.close()
    print("\n -> Cleaned up test transactions; preserved initial Customer 1 (Ramesh) and original Transaction 1 (₹430 credit).")

    # Verify seed balance
    r_final_bal = client.get("/api/transactions/customer/1/balance")
    final_bal = r_final_bal.json()
    assert final_bal["outstanding_balance"] == 430
    assert final_bal["total_credit"] == 430
    assert final_bal["total_payments"] == 0
    print(f" -> Confirmed Seed Balance: Ramesh outstanding balance = ₹{final_bal['outstanding_balance']}")

    print("\n=== ALL E2E SCENARIOS VERIFIED SUCCESSFULLY! ===")


if __name__ == "__main__":
    run_e2e_tests()
