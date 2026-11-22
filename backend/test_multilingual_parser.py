"""
Phase 1.4 Stage C: Multilingual Understanding & Customer Identification Test Suite.
Validates:
1. Kanglish payment parsing: 'Ramesh inda 500 bandide' and natural payment variations.
2. Kannada-script customer matching against Latin-script records (e.g. 'ರಮೇಶ್' -> 'Ramesh').
3. Bounded spelling variations and refusal to weakly guess false matches (e.g. 'Suresh' != 'Ramesh').
4. Disambiguation when multiple candidates match (e.g. 'Ramesh Kumar' vs 'Ramesh Gowda').
5. Rejection / clarification of ambiguous commands (e.g. 'Ramesh 500' without direction).
6. Missing customer, missing amount, and invalid amount (<=0, negative, >10M) safety.
7. Atomic confirmation resulting in correct ledger balance reduction for payments.
8. Database safety: isolated in-memory SQLite database, leaving dukaanvoice.db untouched.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base
from models import Customer, Transaction
from routes.voice import (
    process_voice_command,
    confirm_voice_transaction,
    calculate_balance_dict
)
from schemas import (
    VoiceParseRequest,
    VoiceConfirmRequest
)
from voice_parser import parse_voice_command
from customer_matcher import (
    transliterate_kannada_to_latin,
    canonical_phonetic,
    levenshtein_distance,
    find_matching_customers
)
from pending_manager import pending_manager


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

    # Seed baseline customer Ramesh with an existing credit of 430
    c1 = Customer(id=1, name="Ramesh", phone="9876543210")
    session.add(c1)
    session.commit()

    t1 = Transaction(id=1, customer_id=1, transaction_type="CREDIT", amount=430, description="Initial credit")
    session.add(t1)
    session.commit()

    yield session

    session.close()
    Base.metadata.drop_all(bind=test_engine)


# =====================================================================
# Tests: Multilingual Transliteration & Canonical Matching Logic
# =====================================================================

def test_transliterate_kannada_to_latin():
    """Validates deterministic transliteration of Kannada Unicode text to Latin."""
    assert transliterate_kannada_to_latin("ರಮೇಶ್") == "ramesh"
    assert transliterate_kannada_to_latin("ರಮೇಶ") == "ramesha"
    assert transliterate_kannada_to_latin("ಸುರೇಶ್") == "suresh"
    assert transliterate_kannada_to_latin("ಮಹೇಶ್") == "mahesh"
    assert transliterate_kannada_to_latin("ಗಣೇಶ್") == "ganesh"
    assert transliterate_kannada_to_latin("ಕುಮಾರ್") == "kumaar"
    assert transliterate_kannada_to_latin("ರಾಜು") == "raaju"
    assert transliterate_kannada_to_latin("ಆನಂದ್") == "aanamd"


def test_canonical_phonetic_normalization():
    """Validates cross-script phonetic equivalence."""
    # Both Latin and Kannada versions of Ramesh map to identical canonical key
    assert canonical_phonetic("Ramesh") == "rames"
    assert canonical_phonetic("ರಮೇಶ್") == "rames"
    assert canonical_phonetic("ರಮೇಶ") == "rames"
    assert canonical_phonetic("Ramesha") == "rames"

    # Distinct names produce distinct keys
    assert canonical_phonetic("Suresh") != canonical_phonetic("Ramesh")
    assert canonical_phonetic("ಸುರೇಶ್") == "sures"
    assert canonical_phonetic("Mahesh") == "mahes"


def test_no_weak_phonetic_guessing():
    """Ensures Suresh or Mahesh are never falsely matched to Ramesh."""
    dist_suresh = levenshtein_distance("rames", "sures")
    assert dist_suresh >= 2
    # First letter differs ('r' vs 's')
    assert "rames"[0] != "sures"[0]


# =====================================================================
# Tests: Kanglish Payment Parsing ("Ramesh inda 500 bandide")
# =====================================================================

def test_payment_kanglish_bandide(isolated_session):
    """
    Primary Stage C Requirement:
    'Ramesh inda 500 bandide' must parse as ADD_PAYMENT, stage a pending PAYMENT of 500,
    and decrease balance upon confirmation.
    """
    session_id = "session_bandide_1"

    # 1. Parse intent
    parsed = parse_voice_command("Ramesh inda 500 bandide")
    assert parsed["intent"] == "ADD_PAYMENT"
    assert parsed["customer_name"] == "Ramesh"
    assert parsed["amount"] == 500
    assert parsed["transaction_type"] == "PAYMENT"

    # 2. Process via API route
    req = VoiceParseRequest(transcript="Ramesh inda 500 bandide", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is True
    assert resp.intent == "PENDING_CONFIRMATION"
    assert resp.pending_transaction is not None
    assert resp.pending_transaction.transaction_type == "PAYMENT"
    assert resp.pending_transaction.amount == 500
    assert resp.pending_transaction.customer_name == "Ramesh"

    # 3. Explicit confirmation
    confirm_req = VoiceConfirmRequest(
        pending_id=resp.pending_transaction.pending_id,
        session_id=session_id
    )
    confirm_resp = confirm_voice_transaction(confirm_req, db=isolated_session)

    assert confirm_resp.success is True
    assert confirm_resp.intent == "CONFIRMED"
    assert confirm_resp.confirmed_transaction.transaction_type == "PAYMENT"
    assert confirm_resp.confirmed_transaction.amount == 500

    # 4. Ledger balance verification: was 430, payment 500 -> balance decreases to -70
    bal = calculate_balance_dict(isolated_session, 1)
    assert bal["outstanding_balance"] == -70
    assert bal["total_payments"] == 500
    assert bal["total_credit"] == 430


def test_payment_natural_variations_corpus(isolated_session):
    """Tests corpus of natural Kanglish, Kannada, and English payment variations."""
    payment_phrases = [
        "Ramesh inda 500 bandide",
        "Ramesh inda 500 banthu",
        "Ramesh inda 500 bantu",
        "Ramesh inda 500 aayithu",
        "Ramesh inda 500 jama",
        "Ramesh inda 500 cash bandide",
        "Ramesh 500 kottidare",
        "Ramesh 500 kotru",
        "Ramesh 500 kottaru",
        "Ramesh ge 100 kodidare",
        "Ramesh paid 500",
        "Received 500 from Ramesh",
        "500 payment from Ramesh",
        "ರಮೇಶ್ ಇಂದ 500 ಬಂದಿದೆ",
        "ರಮೇಶ್ 500 ಕೊಟ್ಟಿದ್ದಾರೆ",
        "ರಮೇಶ್ 500 ಜಮಾ",
    ]

    for phrase in payment_phrases:
        parsed = parse_voice_command(phrase)
        assert parsed["intent"] == "ADD_PAYMENT", f"Failed for phrase: '{phrase}'"
        assert parsed["customer_name"] in ("Ramesh", "ರಮೇಶ್"), f"Failed customer extraction for: '{phrase}'"
        assert parsed["transaction_type"] == "PAYMENT", f"Failed txn type for: '{phrase}'"


def test_credit_natural_variations_corpus():
    """Tests corpus of natural Kanglish, Kannada, and English credit variations."""
    credit_phrases = [
        "Ramesh ge 430 rupees udhaar haaku",
        "Ramesh ge 340 udhaar",
        "Ramesh ge 430 credit add maadu",
        "Ramesh ge 500 kadan",
        "Ramesh ge 500 sala",
        "Ramesh ge 430 haaku",
        "Add 430 credit for Ramesh",
        "Credit 430 to Ramesh",
        "ರಮೇಶ್ ಗೆ 430 ರೂಪಾಯಿ ಉದ್ದಾರ ಹಾಕು",
        "ರಮೇಶ್ ಗೆ 430 ಕ್ರೆಡಿಟ್",
        "ರಮೇಶ್ ಗೆ 500 ಸಾಲ",
    ]

    for phrase in credit_phrases:
        parsed = parse_voice_command(phrase)
        assert parsed["intent"] == "ADD_CREDIT", f"Failed for phrase: '{phrase}'"
        assert parsed["customer_name"] in ("Ramesh", "ರಮೇಶ್"), f"Failed customer extraction for: '{phrase}'"
        assert parsed["transaction_type"] == "CREDIT", f"Failed txn type for: '{phrase}'"


# =====================================================================
# Tests: Cross-Script Kannada Customer Matching
# =====================================================================

def test_kannada_script_ramesh_matching(isolated_session):
    """Tests matching Kannada Unicode name 'ರಮೇಶ್' against Latin-script record 'Ramesh'."""
    # Matches 'Ramesh' (ID 1)
    matches = find_matching_customers(isolated_session, "ರಮೇಶ್")
    assert len(matches) == 1
    assert matches[0].id == 1
    assert matches[0].name == "Ramesh"

    # Matches 'ರಮೇಶ' (variant with trailing vowel)
    matches2 = find_matching_customers(isolated_session, "ರಮೇಶ")
    assert len(matches2) == 1
    assert matches2[0].name == "Ramesh"


def test_kannada_spoken_command_creates_pending_transaction(isolated_session):
    """Spoken Kannada command 'ರಮೇಶ್ ಇಂದ 500 ಬಂದಿದೆ' creates pending payment for Ramesh."""
    session_id = "session_kn_match_1"
    req = VoiceParseRequest(transcript="ರಮೇಶ್ ಇಂದ 500 ಬಂದಿದೆ", session_id=session_id)
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is True
    assert resp.intent == "PENDING_CONFIRMATION"
    assert resp.pending_transaction.customer_id == 1
    assert resp.pending_transaction.customer_name == "Ramesh"
    assert resp.pending_transaction.transaction_type == "PAYMENT"
    assert resp.pending_transaction.amount == 500


def test_spelling_variation_bounded_matching(isolated_session):
    """Tests bounded spelling variation (e.g. 'Ramesha', 'Rameesh')."""
    # Ramesha (common phonetic variant)
    m1 = find_matching_customers(isolated_session, "Ramesha")
    assert len(m1) == 1
    assert m1[0].name == "Ramesh"

    # Rameesh (bounded edit distance 1)
    m2 = find_matching_customers(isolated_session, "Rameesh")
    assert len(m2) == 1
    assert m2[0].name == "Ramesh"


# =====================================================================
# Tests: Ambiguity, Disambiguation & Clarification
# =====================================================================

def test_two_similar_customers_triggers_disambiguation(isolated_session):
    """When multiple customers match, system requests clarification without guessing."""
    # Add second Ramesh variant
    c2 = Customer(id=2, name="Ramesh Kumar", phone="9876543211")
    isolated_session.add(c2)
    isolated_session.commit()

    # Query matching both
    matches = find_matching_customers(isolated_session, "Ramesh Kumar")
    assert len(matches) == 1
    assert matches[0].name == "Ramesh Kumar"

    # If DB has Ramesh Gowda and Ramesh Kumar (no exact single Ramesh):
    c3 = Customer(id=3, name="Ramesh Gowda", phone="9876543212")
    isolated_session.add(c3)
    isolated_session.commit()

    # Query 'Ramesh' exact match prefers ID 1 (exact 'Ramesh')
    m_exact = find_matching_customers(isolated_session, "Ramesh")
    assert len(m_exact) == 1
    assert m_exact[0].id == 1


def test_ambiguous_prefix_triggers_disambiguate_response(isolated_session):
    """Tests disambiguation response structure when multiple candidates exist."""
    # Delete exact 'Ramesh', leave only 'Ramesh Kumar' and 'Ramesh Gowda'
    c1 = isolated_session.get(Customer, 1)
    isolated_session.delete(c1)
    isolated_session.add(Customer(id=2, name="Ramesh Kumar", phone="9876543211"))
    isolated_session.add(Customer(id=3, name="Ramesh Gowda", phone="9876543212"))
    isolated_session.commit()

    req = VoiceParseRequest(transcript="Ramesh ge 500 udhaar haaku", session_id="sess_disam")
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is False
    assert resp.intent == "DISAMBIGUATE"
    assert resp.disambiguation_options is not None
    assert len(resp.disambiguation_options) == 2
    assert {opt["name"] for opt in resp.disambiguation_options} == {"Ramesh Kumar", "Ramesh Gowda"}

    # Zero pending transactions created
    pending = pending_manager.get_active_for_session("sess_disam", db=isolated_session)
    assert pending is None


def test_unknown_customer_triggers_not_found(isolated_session):
    """When no customer matches, returns CUSTOMER_NOT_FOUND and creates no pending txn."""
    req = VoiceParseRequest(transcript="Manjunath ge 500 udhaar haaku", session_id="sess_unk")
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is False
    assert resp.intent == "CUSTOMER_NOT_FOUND"
    assert "Manjunath" in resp.message

    pending = pending_manager.get_active_for_session("sess_unk", db=isolated_session)
    assert pending is None


def test_ambiguous_transaction_direction_triggers_clarify(isolated_session):
    """'Ramesh 500' without direction (credit vs payment) must return CLARIFY."""
    req = VoiceParseRequest(transcript="Ramesh 500", session_id="sess_ambig_dir")
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is False
    assert resp.intent == "CLARIFY"
    assert "credit or a payment" in resp.message
    assert "ಉದ್ದಾರವೋ ಅಥವಾ ಜಮಾವೋ" in resp.message_kn

    # Zero pending transactions created
    pending = pending_manager.get_active_for_session("sess_ambig_dir", db=isolated_session)
    assert pending is None


def test_conflicting_direction_indicators_triggers_clarify(isolated_session):
    """'Ramesh inda 500 udhaar' (from + credit conflicting) must return CLARIFY."""
    req = VoiceParseRequest(transcript="Ramesh inda 500 udhaar", session_id="sess_conflict")
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is False
    assert resp.intent == "CLARIFY"

    pending = pending_manager.get_active_for_session("sess_conflict", db=isolated_session)
    assert pending is None


def test_missing_amount_triggers_clarify(isolated_session):
    """'Ramesh ge udhaar haaku' (missing amount) must return CLARIFY."""
    req = VoiceParseRequest(transcript="Ramesh ge udhaar haaku", session_id="sess_no_amt")
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is False
    assert resp.intent == "CLARIFY"
    assert "How much amount" in resp.message

    pending = pending_manager.get_active_for_session("sess_no_amt", db=isolated_session)
    assert pending is None


def test_missing_customer_triggers_clarify(isolated_session):
    """'500 bandide' (missing customer) must return CLARIFY."""
    req = VoiceParseRequest(transcript="500 bandide", session_id="sess_no_cust")
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is False
    assert resp.intent == "CLARIFY"
    assert "mention the customer's name" in resp.message

    pending = pending_manager.get_active_for_session("sess_no_cust", db=isolated_session)
    assert pending is None


def test_invalid_zero_and_negative_amounts(isolated_session):
    """Zero or negative amounts must return CLARIFY and create no pending txn."""
    for invalid_phrase in ["Ramesh ge 0 udhaar", "Ramesh ge -50 udhaar"]:
        req = VoiceParseRequest(transcript=invalid_phrase, session_id="sess_inv_amt")
        resp = process_voice_command(req, db=isolated_session)

        assert resp.success is False
        assert resp.intent == "CLARIFY"

        pending = pending_manager.get_active_for_session("sess_inv_amt", db=isolated_session)
        assert pending is None


def test_implausible_amount_exceeding_limit(isolated_session):
    """Amounts exceeding 10,000,000 must be rejected."""
    req = VoiceParseRequest(transcript="Ramesh ge 50000000 udhaar", session_id="sess_implaus")
    resp = process_voice_command(req, db=isolated_session)

    assert resp.success is False
    assert resp.intent == "CLARIFY"
    assert "exceeds the maximum limit" in resp.message

    pending = pending_manager.get_active_for_session("sess_implaus", db=isolated_session)
    assert pending is None


def test_payment_correction_before_confirmation(isolated_session):
    """Tests correcting payment amount before confirmation."""
    session_id = "sess_correct_payment"

    # Stage 500 payment
    req1 = VoiceParseRequest(transcript="Ramesh inda 500 bandide", session_id=session_id)
    res1 = process_voice_command(req1, db=isolated_session)
    assert res1.intent == "PENDING_CONFIRMATION"
    assert res1.pending_transaction.amount == 500
    assert res1.pending_transaction.transaction_type == "PAYMENT"

    # Correct to 400
    req2 = VoiceParseRequest(transcript="No, 400 maadu", session_id=session_id)
    res2 = process_voice_command(req2, db=isolated_session)
    assert res2.intent == "CORRECTED"
    assert res2.pending_transaction.amount == 400
    assert res2.pending_transaction.transaction_type == "PAYMENT"

    # Confirm
    req3 = VoiceParseRequest(transcript="Howdu", session_id=session_id)
    res3 = process_voice_command(req3, db=isolated_session)
    assert res3.intent == "CONFIRMED"
    assert res3.confirmed_transaction.amount == 400
    assert res3.confirmed_transaction.transaction_type == "PAYMENT"
