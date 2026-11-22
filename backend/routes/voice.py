import base64
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, Response
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session

from database import get_db, SessionLocal
from models import Customer, Transaction
from schemas import (
    VoiceParseRequest,
    VoiceActionResponse,
    VoiceConfirmRequest,
    VoiceCancelRequest,
    VoiceCorrectRequest,
    PendingTransaction,
    TransactionResponse,
    AudioTranscribeRequest,
    AudioTranscribeResponse,
    TTSRequest,
    SpeechProviderStatusResponse,
    AudioVoiceCommandRequest
)
from voice_parser import parse_voice_command
from pending_manager import pending_manager
from speech_provider import (
    speech_provider_manager,
    GnaniError,
    GnaniNotConfiguredError,
    GnaniAuthenticationError,
    GnaniTimeoutError,
    GnaniNetworkError,
    GnaniAudioError,
    GnaniRateLimitError,
    GnaniProviderError
)

router = APIRouter()


from customer_matcher import find_matching_customers


def calculate_balance_dict(db: Session, customer_id: int) -> dict[str, Any]:
    cust = db.get(Customer, customer_id)
    if not cust:
        return {}

    credit_total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.customer_id == customer_id,
            Transaction.transaction_type == "CREDIT"
        )
    ) or 0

    payment_total = db.scalar(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .where(
            Transaction.customer_id == customer_id,
            Transaction.transaction_type == "PAYMENT"
        )
    ) or 0

    net_balance = int(credit_total - payment_total)
    outstanding = max(0, net_balance)
    advance = max(0, -net_balance)

    return {
        "customer_id": cust.id,
        "customer_name": cust.name,
        "customer_phone": cust.phone,
        "total_credit": int(credit_total),
        "total_payments": int(payment_total),
        "outstanding_balance": net_balance,
        "display_outstanding": outstanding,
        "advance_balance": advance,
        "net_balance": net_balance
    }


@router.post("/process", response_model=VoiceActionResponse)
def process_voice_command(
    req: VoiceParseRequest,
    db: Session = Depends(get_db)
):
    session_id = req.session_id or "default"
    active_pending = pending_manager.get_active_for_session(session_id, db=db)
    has_pending = active_pending is not None

    parsed = parse_voice_command(req.transcript, has_pending_transaction=has_pending)
    intent = parsed["intent"]

    # 1. Handle Confirmation
    if intent == "CONFIRM":
        if not active_pending:
            return VoiceActionResponse(
                success=False,
                intent="CONFIRM",
                message="No pending transaction to confirm.",
                message_kn="Confirm maadalu yaavude pending transaction illa.",
                spoken_text="Confirm maadalu yaavude pending transaction illa."
            )

        try:
            pending_record, db_txn = pending_manager.confirm_pending(
                active_pending["pending_id"],
                db
            )
        except ValueError as e:
            err_str = str(e)
            refreshed = pending_manager.get_pending(active_pending["pending_id"], db=db)
            refreshed_obj = PendingTransaction(**refreshed) if refreshed else None
            if "Customer balance has changed" in err_str:
                return VoiceActionResponse(
                    success=False,
                    intent="STALE_PREVIEW",
                    message=err_str,
                    message_kn="ದೃಢೀಕರಣದ ಮೊದಲು ಗ್ರಾಹಕರ ಬಾಕಿ ಬದಲಾಗಿದೆ. ದಯವಿಟ್ಟು ಹೊಸ ವಿವರಗಳನ್ನು ಪರಿಶೀಲಿಸಿ.",
                    spoken_text="Customer balance has changed. Please review and confirm again.",
                    pending_transaction=refreshed_obj,
                    balance_preview=refreshed_obj.balance_preview if refreshed_obj else None
                )
            return VoiceActionResponse(
                success=False,
                intent="CONFIRM_FAILED",
                message=err_str,
                message_kn="ದೃಢೀಕರಣ ವಿಫಲವಾಗಿದೆ.",
                spoken_text="Confirmation failed.",
                pending_transaction=refreshed_obj
            )

        bal_info = calculate_balance_dict(db, pending_record["customer_id"])

        txn_resp = None
        if db_txn:
            txn_resp = TransactionResponse(
                id=db_txn.id,
                customer_id=db_txn.customer_id,
                transaction_type=db_txn.transaction_type,
                amount=db_txn.amount,
                description=db_txn.description,
                created_at=db_txn.created_at
            )

        amt = pending_record["amount"]
        c_name = pending_record["customer_name"]
        t_type = pending_record["transaction_type"].lower()

        p_obj = PendingTransaction(**pending_record)
        return VoiceActionResponse(
            success=True,
            intent="CONFIRMED",
            message=f"₹{amt} successfully recorded for {c_name}.",
            message_kn=f"{c_name} ge ₹{amt} {t_type} daakhalu maadalaagide.",
            spoken_text=f"₹{amt} successfully recorded for {c_name}.",
            pending_transaction=p_obj,
            confirmed_transaction=txn_resp,
            customer_balance=bal_info,
            balance_preview=p_obj.balance_preview
        )

    # 2. Handle Cancellation
    if intent == "CANCEL":
        if not active_pending:
            return VoiceActionResponse(
                success=False,
                intent="CANCEL",
                message="No pending transaction to cancel.",
                message_kn="Cancel maadalu yaavude pending transaction illa.",
                spoken_text="Cancel maadalu yaavude pending transaction illa."
            )

        cancelled_record = pending_manager.cancel_pending(active_pending["pending_id"], db=db)
        return VoiceActionResponse(
            success=True,
            intent="CANCELLED",
            message="Transaction cancelled.",
            message_kn="Transaction raddumaadalaagide.",
            spoken_text="Transaction cancelled."
        )

    # 3. Handle Correction
    if intent == "CORRECT":
        if not active_pending:
            return VoiceActionResponse(
                success=False,
                intent="CORRECT",
                message="No active transaction to correct. Please speak a new transaction.",
                message_kn="Correct maadalu yaavude transaction illa.",
                spoken_text="No active transaction to correct."
            )

        new_amount = parsed["amount"]
        new_customer_name = parsed["customer_name"]
        new_type = parsed["transaction_type"]

        new_cust_id = None
        new_cust_phone = None
        if new_customer_name:
            matches = find_matching_customers(db, new_customer_name)
            if len(matches) == 1:
                new_cust_id = matches[0].id
                new_customer_name = matches[0].name
                new_cust_phone = matches[0].phone
            elif len(matches) > 1:
                return VoiceActionResponse(
                    success=False,
                    intent="DISAMBIGUATE",
                    message=f"Multiple customers found matching '{new_customer_name}'. Please select one.",
                    message_kn=f"'{new_customer_name}' hesarinalli hechchina graahakariddaare. Obarannu aayke maadi.",
                    spoken_text=f"Multiple customers found for {new_customer_name}. Please choose one.",
                    disambiguation_options=[
                        {"id": c.id, "name": c.name, "phone": c.phone} for c in matches
                    ]
                )

        updated_record = pending_manager.correct_pending(
            pending_id=active_pending["pending_id"],
            amount=new_amount,
            customer_id=new_cust_id,
            customer_name=new_customer_name,
            customer_phone=new_cust_phone,
            transaction_type=new_type,
            db=db
        )

        amt = updated_record["amount"]
        c_name = updated_record["customer_name"]
        t_type = updated_record["transaction_type"].lower()

        p_obj = PendingTransaction(**updated_record)
        return VoiceActionResponse(
            success=True,
            intent="CORRECTED",
            message=f"Okay, confirm ₹{amt} {t_type} for {c_name}?",
            message_kn=f"Okay, {c_name} ge ₹{amt} {t_type} add maadbekaa?",
            spoken_text=f"Okay, {c_name} ge ₹{amt} {t_type} add maadbekaa?",
            pending_transaction=p_obj,
            balance_preview=p_obj.balance_preview
        )

    # 4. Handle Balance Inquiries
    if intent == "CHECK_BALANCE":
        cust_name = parsed["customer_name"]
        if not cust_name:
            return VoiceActionResponse(
                success=False,
                intent="CLARIFY",
                message="Whose balance would you like to check? (e.g., 'Ramesh total eshtu?')",
                message_kn="Yaara balance nodabeku? (Udahaaranega: 'Ramesh total eshtu?')",
                spoken_text="Whose balance would you like to check?"
            )

        matches = find_matching_customers(db, cust_name)
        if not matches:
            return VoiceActionResponse(
                success=False,
                intent="CUSTOMER_NOT_FOUND",
                message=f"Customer '{cust_name}' not found in database.",
                message_kn=f"Graahaka '{cust_name}' sigalilla.",
                spoken_text=f"Customer {cust_name} not found."
            )

        if len(matches) > 1:
            return VoiceActionResponse(
                success=False,
                intent="DISAMBIGUATE",
                message=f"Multiple customers match '{cust_name}'. Please select one.",
                message_kn=f"'{cust_name}' hesarinalli halavu graahakariddaare.",
                spoken_text=f"Multiple customers found for {cust_name}.",
                disambiguation_options=[
                    {"id": c.id, "name": c.name, "phone": c.phone} for c in matches
                ]
            )

        cust = matches[0]
        bal_info = calculate_balance_dict(db, cust.id)
        balance = bal_info["outstanding_balance"]
        advance = bal_info["advance_balance"]

        if balance > 0:
            msg = f"{cust.name}'s total outstanding balance is ₹{balance}."
            msg_kn = f"{cust.name} total baaki ₹{balance} aagide."
            spoken = f"{cust.name} total baaki {balance} rupees aagide."
        elif advance > 0:
            msg = f"{cust.name} has an advance balance of ₹{advance} (₹0 due)."
            msg_kn = f"{cust.name} avara khatheyalli ₹{advance} mungada (jama) ide."
            spoken = f"{cust.name} has advance balance of {advance} rupees."
        else:
            msg = f"{cust.name}'s account is fully settled (₹0 balance)."
            msg_kn = f"{cust.name} khathe poorna chuktha aagide."
            spoken = f"{cust.name} balance is zero."

        return VoiceActionResponse(
            success=True,
            intent="CHECK_BALANCE",
            message=msg,
            message_kn=msg_kn,
            spoken_text=spoken,
            customer_balance=bal_info
        )

    # 4.5. Handle Ambiguous Direction (e.g. 'Ramesh 500' without credit/payment direction)
    if intent == "AMBIGUOUS_DIRECTION":
        cust_name = parsed["customer_name"]
        amount = parsed["amount"]

        if not cust_name:
            return VoiceActionResponse(
                success=False,
                intent="CLARIFY",
                message="Please mention the customer's name and whether it is a credit or payment (e.g., 'Ramesh ge 430 rupees udhaar' or 'Ramesh inda 500 bandide').",
                message_kn="ದಯವಿಟ್ಟು ಗ್ರಾಹಕರ ಹೆಸರು ಮತ್ತು ಉದ್ದಾರವೋ ಅಥವಾ ಜಮಾವೋ ಎಂಬುದನ್ನು ತಿಳಿಸಿ.",
                spoken_text="Please mention customer name and credit or payment."
            )

        matches = find_matching_customers(db, cust_name)
        if not matches:
            return VoiceActionResponse(
                success=False,
                intent="CUSTOMER_NOT_FOUND",
                message=f"Customer '{cust_name}' does not exist in ledger.",
                message_kn=f"Graahaka '{cust_name}' ledger alli illa.",
                spoken_text=f"Customer {cust_name} not found."
            )

        if len(matches) > 1:
            return VoiceActionResponse(
                success=False,
                intent="DISAMBIGUATE",
                message=f"Multiple customers found matching '{cust_name}'. Please select one.",
                message_kn=f"'{cust_name}' hesarinalli halavu graahakariddaare.",
                spoken_text=f"Multiple customers found for {cust_name}.",
                disambiguation_options=[
                    {"id": c.id, "name": c.name, "phone": c.phone} for c in matches
                ]
            )

        target_customer = matches[0]
        amt_str = f"₹{amount}" if amount else "the amount"
        return VoiceActionResponse(
            success=False,
            intent="CLARIFY",
            message=f"Is {amt_str} for {target_customer.name} a credit or a payment? (e.g., '{target_customer.name} ge {amount or 500} udhaar' or '{target_customer.name} inda {amount or 500} bandide').",
            message_kn=f"{target_customer.name} ಅವರಿಗೆ {amt_str} ಉದ್ದಾರವೋ ಅಥವಾ ಜಮಾವೋ? ದಯವಿಟ್ಟು ತಿಳಿಸಿ.",
            spoken_text=f"Is {amt_str} for {target_customer.name} credit or payment?"
        )

    # 5. Handle Credit and Payment Intents
    if intent in ("ADD_CREDIT", "ADD_PAYMENT"):
        cust_name = parsed["customer_name"]
        amount = parsed["amount"]
        txn_type = parsed["transaction_type"] or ("CREDIT" if intent == "ADD_CREDIT" else "PAYMENT")

        if not cust_name:
            return VoiceActionResponse(
                success=False,
                intent="CLARIFY",
                message="Please mention the customer's name (e.g., 'Ramesh ge 430 rupees udhaar haaku' or 'Ramesh inda 500 bandide').",
                message_kn="Dayavittu graahakara hesaru tilisi (udahaaranege: 'Ramesh ge 430 rupees udhaar' athava 'Ramesh inda 500 bandide').",
                spoken_text="Please mention customer name."
            )

        matches = find_matching_customers(db, cust_name)
        if not matches:
            return VoiceActionResponse(
                success=False,
                intent="CUSTOMER_NOT_FOUND",
                message=f"Customer '{cust_name}' does not exist in ledger. Would you like to create them?",
                message_kn=f"Graahaka '{cust_name}' ledger alli illa. Hosa graahakarannu add maadbekaa?",
                spoken_text=f"Customer {cust_name} not found."
            )

        if len(matches) > 1:
            return VoiceActionResponse(
                success=False,
                intent="DISAMBIGUATE",
                message=f"Multiple customers found matching '{cust_name}'. Please select one.",
                message_kn=f"'{cust_name}' hesarinalli halavu graahakariddaare.",
                spoken_text=f"Multiple customers found for {cust_name}.",
                disambiguation_options=[
                    {"id": c.id, "name": c.name, "phone": c.phone} for c in matches
                ]
            )

        target_customer = matches[0]

        if amount is not None and amount <= 0:
            return VoiceActionResponse(
                success=False,
                intent="CLARIFY",
                message="Please specify a valid amount greater than zero.",
                message_kn="ದಯವಿಟ್ಟು ಶೂನ್ಯಕ್ಕಿಂತ ಹೆಚ್ಚಿನ ಸರಿಯಾದ ಮೊತ್ತವನ್ನು ತಿಳಿಸಿ.",
                spoken_text="Please specify a valid amount greater than zero."
            )

        if not amount:
            return VoiceActionResponse(
                success=False,
                intent="CLARIFY",
                message=f"How much amount should be recorded for {target_customer.name}?",
                message_kn=f"{target_customer.name} ge eshtu amount haakbeku?",
                spoken_text=f"{target_customer.name} ge eshtu amount haakbeku?"
            )

        if amount > 10000000:
            return VoiceActionResponse(
                success=False,
                intent="CLARIFY",
                message=f"Amount ₹{amount} exceeds the maximum limit of ₹10,000,000. Please specify a valid amount.",
                message_kn="ಮೊತ್ತವು ಗರಿಷ್ಠ ಮಿತಿಗಿಂತ ಹೆಚ್ಚಾಗಿದೆ. ದಯವಿಟ್ಟು ಸರಿಯಾದ ಮೊತ್ತವನ್ನು ತಿಳಿಸಿ.",
                spoken_text="Amount exceeds maximum limit."
            )

        # Create Pending Transaction (Ledger is NOT touched yet!)
        pending_record = pending_manager.create_pending(
            session_id=session_id,
            customer_id=target_customer.id,
            customer_name=target_customer.name,
            customer_phone=target_customer.phone,
            amount=amount,
            transaction_type=txn_type,
            db=db
        )

        if txn_type == "CREDIT":
            msg = f"{target_customer.name} ge ₹{amount} credit add maadbekaa?"
            msg_en = f"Add ₹{amount} credit for {target_customer.name}?"
        else:
            msg = f"{target_customer.name} inda ₹{amount} payment add maadbekaa?"
            msg_en = f"Add ₹{amount} payment from {target_customer.name}?"

        p_obj = PendingTransaction(**pending_record)
        return VoiceActionResponse(
            success=True,
            intent="PENDING_CONFIRMATION",
            message=msg_en,
            message_kn=msg,
            spoken_text=msg,
            pending_transaction=p_obj,
            balance_preview=p_obj.balance_preview
        )

    # 6. Unknown Intent
    return VoiceActionResponse(
        success=False,
        intent="UNKNOWN",
        message="Could not understand the instruction. Please try again (e.g., 'Ramesh ge 430 rupees udhaar haaku').",
        message_kn="Artha aagalilla, dayavittu mathe heli.",
        spoken_text="Artha aagalilla, dayavittu mathe heli."
    )


@router.post("/confirm", response_model=VoiceActionResponse)
def confirm_voice_transaction(
    req: VoiceConfirmRequest,
    db: Session = Depends(get_db)
):
    try:
        pending_record, db_txn = pending_manager.confirm_pending(
            req.pending_id,
            db,
            expected_baseline=req.expected_baseline
        )
    except ValueError as e:
        err_str = str(e)
        if "Customer balance has changed" in err_str:
            raise HTTPException(status_code=409, detail=err_str)
        raise HTTPException(status_code=400, detail=err_str)

    bal_info = calculate_balance_dict(db, pending_record["customer_id"])
    txn_resp = None
    if db_txn:
        txn_resp = TransactionResponse(
            id=db_txn.id,
            customer_id=db_txn.customer_id,
            transaction_type=db_txn.transaction_type,
            amount=db_txn.amount,
            description=db_txn.description,
            created_at=db_txn.created_at
        )

    amt = pending_record["amount"]
    c_name = pending_record["customer_name"]

    p_obj = PendingTransaction(**pending_record)
    return VoiceActionResponse(
        success=True,
        intent="CONFIRMED",
        message=f"₹{amt} successfully recorded for {c_name}.",
        message_kn=f"{c_name} ge ₹{amt} daakhalu maadalaagide.",
        spoken_text=f"₹{amt} successfully recorded for {c_name}.",
        pending_transaction=p_obj,
        confirmed_transaction=txn_resp,
        customer_balance=bal_info,
        balance_preview=p_obj.balance_preview
    )


@router.post("/cancel", response_model=VoiceActionResponse)
def cancel_voice_transaction(
    req: VoiceCancelRequest,
    db: Session = Depends(get_db)
):
    try:
        record = pending_manager.cancel_pending(req.pending_id, db=db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return VoiceActionResponse(
        success=True,
        intent="CANCELLED",
        message="Transaction cancelled.",
        message_kn="Transaction raddumaadalaagide.",
        spoken_text="Transaction cancelled.",
        pending_transaction=PendingTransaction(**record)
    )


@router.post("/correct", response_model=VoiceActionResponse)
def correct_voice_transaction(
    req: VoiceCorrectRequest,
    db: Session = Depends(get_db)
):
    try:
        updated = pending_manager.correct_pending(
            pending_id=req.pending_id,
            amount=req.amount,
            customer_id=req.customer_id,
            customer_name=req.customer_name,
            transaction_type=req.transaction_type,
            db=db
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    amt = updated["amount"]
    c_name = updated["customer_name"]
    t_type = updated["transaction_type"].lower()

    return VoiceActionResponse(
        success=True,
        intent="CORRECTED",
        message=f"Okay, confirm ₹{amt} {t_type} for {c_name}?",
        message_kn=f"Okay, {c_name} ge ₹{amt} {t_type} add maadbekaa?",
        spoken_text=f"Okay, {c_name} ge ₹{amt} {t_type} add maadbekaa?",
        pending_transaction=PendingTransaction(**updated)
    )


@router.get("/pending")
def get_pending_status(
    session_id: str = Query(default="default"),
    db: Session = Depends(get_db)
):
    record = pending_manager.get_active_for_session(session_id, db=db)
    if not record:
        return {"has_pending": False, "pending_transaction": None}
    return {
        "has_pending": True,
        "pending_transaction": PendingTransaction(**record)
    }


# =====================================================================
# Gnani Voice AI (Prisma v3.0 STT & Timbre v3.0 TTS) Routes
# =====================================================================

@router.get("/provider-status", response_model=SpeechProviderStatusResponse)
def get_provider_status():
    """Returns the current Gnani Voice AI configuration and fallback status."""
    return SpeechProviderStatusResponse(**speech_provider_manager.get_status())


@router.post("/transcribe", response_model=AudioTranscribeResponse)
def transcribe_audio_endpoint(req: AudioTranscribeRequest):
    """
    Transcribes spoken audio using Gnani Prisma v3.0 Speech-to-Text.
    Accepts base64-encoded audio. If Gnani is not configured, returns graceful fallback hint.
    """
    try:
        audio_bytes = base64.b64decode(req.audio_base64)
    except Exception as e:
        return AudioTranscribeResponse(
            success=False,
            error=f"Invalid base64 audio encoding: {e}",
            fallback_hint="Browser Web Speech API fallback active."
        )

    content_type = f"audio/{req.format}"
    filename = f"utterance.{req.format}"

    try:
        result = speech_provider_manager.stt_provider.transcribe_audio(
            audio_bytes=audio_bytes,
            filename=filename,
            content_type=content_type,
            language_code=req.language
        )
        return AudioTranscribeResponse(
            success=True,
            transcript=result["transcript"],
            detected_language=result.get("detected_language"),
            model=result.get("model", "prisma-v3.0"),
            request_id=result.get("request_id"),
            processing_time=result.get("processing_time")
        )
    except GnaniNotConfiguredError as e:
        return AudioTranscribeResponse(
            success=False,
            error=str(e),
            fallback_hint="Gnani API key not configured. Browser Web Speech API fallback is active."
        )
    except GnaniAuthenticationError as e:
        return AudioTranscribeResponse(
            success=False,
            error=str(e),
            fallback_hint="Authentication failed with Gnani API. Browser Web Speech API fallback is active."
        )
    except GnaniAudioError as e:
        return AudioTranscribeResponse(
            success=False,
            error=str(e)
        )
    except (GnaniTimeoutError, GnaniNetworkError, GnaniRateLimitError, GnaniProviderError) as e:
        return AudioTranscribeResponse(
            success=False,
            error=str(e),
            fallback_hint="Gnani provider temporarily unavailable. Falling back to Browser Web Speech API."
        )
    except Exception as e:
        return AudioTranscribeResponse(
            success=False,
            error=f"Unexpected transcription failure: {e}",
            fallback_hint="Browser Web Speech API fallback active."
        )


@router.post("/tts")
def text_to_speech_endpoint(req: TTSRequest):
    """
    Synthesizes spoken audio from text using Gnani Timbre v3.0 TTS.
    Returns binary audio (audio/wav or audio/mp3).
    """
    try:
        audio_bytes, content_type = speech_provider_manager.tts_provider.synthesize_speech(
            text=req.text,
            language=req.language,
            voice=req.voice,
            speed=req.speed,
            container=req.container
        )
        return Response(content=audio_bytes, media_type=content_type)
    except GnaniNotConfiguredError as e:
        raise HTTPException(
            status_code=503,
            detail=f"Gnani Timbre TTS is not configured: {e}. Use browser speech synthesis."
        )
    except GnaniAuthenticationError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Gnani Timbre TTS authentication failed: {e}"
        )
    except GnaniAudioError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid TTS request parameters: {e}"
        )
    except GnaniTimeoutError as e:
        raise HTTPException(
            status_code=504,
            detail=f"Gnani Timbre TTS timed out: {e}"
        )
    except (GnaniNetworkError, GnaniProviderError, GnaniRateLimitError) as e:
        raise HTTPException(
            status_code=502,
            detail=f"Gnani Timbre TTS unavailable: {e}"
        )


@router.post("/audio-command")
def process_audio_voice_command(
    req: AudioVoiceCommandRequest,
    db: Session = Depends(get_db)
):
    """
    Full voice-in/voice-out transaction pipeline:
    1. Transcribe audio with Gnani Prisma v3.0 STT
    2. Parse intent and update ledger / pending state
    3. Generate spoken audio response with Gnani Timbre v3.0 TTS (if configured)
    """
    try:
        audio_bytes = base64.b64decode(req.audio_base64)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid base64 audio: {e}")

    try:
        stt_res = speech_provider_manager.stt_provider.transcribe_audio(
            audio_bytes=audio_bytes,
            filename=f"audio.{req.format}",
            content_type=f"audio/{req.format}",
            language_code=req.language
        )
        transcript = stt_res.get("transcript", "")
    except GnaniError as e:
        raise HTTPException(status_code=502, detail=f"Prisma STT failed: {e}")

    if not transcript.strip():
        return {
            "transcript": "",
            "action_response": VoiceActionResponse(
                success=False,
                intent="UNKNOWN",
                message="No speech detected in audio. Please try speaking again.",
                message_kn="Shabda kelisilla, dayavittu mathe heli.",
                spoken_text="No speech detected in audio. Please try speaking again."
            ).model_dump(),
            "synthesized_audio_base64": None
        }

    # Process through standard intent/ledger pipeline
    parse_req = VoiceParseRequest(transcript=transcript, session_id=req.session_id)
    action_resp = process_voice_command(parse_req, db=db)

    # Synthesize spoken response via Timbre if configured
    synth_b64 = None
    if speech_provider_manager.config.is_configured and action_resp.spoken_text:
        try:
            synth_bytes, _ = speech_provider_manager.tts_provider.synthesize_speech(
                text=action_resp.spoken_text,
                language=req.language
            )
            synth_b64 = base64.b64encode(synth_bytes).decode("ascii")
        except Exception:
            # TTS failure does not block the transaction response; frontend falls back to browser synthesis
            synth_b64 = None

    return {
        "transcript": transcript,
        "action_response": action_resp.model_dump(),
        "synthesized_audio_base64": synth_b64
    }



@router.websocket("/ws")
async def voice_websocket(websocket: WebSocket):
    await websocket.accept()
    session_id = str(websocket.query_params.get("session_id", "ws_default"))
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action", "process")
            with SessionLocal() as db:
                try:
                    if action == "process":
                        transcript = data.get("transcript", "")
                        req = VoiceParseRequest(transcript=transcript, session_id=session_id)
                        resp = process_voice_command(req, db=db)
                        await websocket.send_json(resp.model_dump())
                    elif action == "confirm":
                        pending_id = data.get("pending_id")
                        req = VoiceConfirmRequest(pending_id=pending_id, session_id=session_id)
                        resp = confirm_voice_transaction(req, db=db)
                        await websocket.send_json(resp.model_dump())
                    elif action == "cancel":
                        pending_id = data.get("pending_id")
                        req = VoiceCancelRequest(pending_id=pending_id, session_id=session_id)
                        resp = cancel_voice_transaction(req, db=db)
                        await websocket.send_json(resp.model_dump())
                except Exception as e:
                    await websocket.send_json({
                        "success": False,
                        "error": str(e),
                        "message": f"Error: {str(e)}",
                        "message_kn": "Dhosha sambhaviside."
                    })
    except WebSocketDisconnect:
        pass
