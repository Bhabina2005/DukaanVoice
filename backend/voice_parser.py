import re
from typing import TypedDict, Literal

IntentType = Literal[
    "ADD_CREDIT",
    "ADD_PAYMENT",
    "CHECK_BALANCE",
    "CONFIRM",
    "CANCEL",
    "CORRECT",
    "SEARCH_CUSTOMER",
    "AMBIGUOUS_DIRECTION",
    "UNKNOWN"
]


class ParsedVoiceIntent(TypedDict):
    intent: IntentType
    raw_text: str
    customer_name: str | None
    amount: int | None
    transaction_type: Literal["CREDIT", "PAYMENT"] | None
    confidence: float
    is_correction: bool


STOP_WORDS = {
    # English & Kanglish prepositions / particles
    "ge", "ige", "nige", "vige", "inda", "ninda", "rinda", "kanna", "to", "for", "from", "with",
    "rupees", "rupee", "rs", "roopayi", "rupaayi", "inr", "bucks",
    # Credit verbs and nouns
    "udhaar", "kadan", "credit", "haaku", "add", "maadbekaa", "maadbeka", "maadu", "haku", "kodu",
    "sala", "saala", "kodbeku",
    # Payment verbs and nouns
    "kodidare", "kottidare", "kottaru", "kotru", "kotte", "kottidini", "payment", "jama", "paid",
    "gave", "settle", "settled", "receive", "received", "receipt", "cash", "bandide", "banthu", "bantu",
    # Balance words
    "total", "balance", "eshtu", "baaki", "outstanding", "how", "much", "is", "aagide", "idhe",
    # Confirmation / Cancellation
    "howdu", "haudu", "houdu", "sari", "yes", "confirm", "ok", "okay", "correct", "ha", "huu", "aayithu",
    "illa", "beda", "cancel", "no", "stop", "raddumaadu", "raddumadi", "alla",
    "please", "the", "a", "an", "and", "dukaan", "voice", "ledger",
    "make", "change", "it", "put", "record",
    # Kannada Unicode script stop words
    "ಗೆ", "ಿಗೆ", "ನಿಗೆ", "ರಿಗೆ", "ವರಿಗೆ", "ಇಂದ", "ನಿಂದ", "ರಿಂದ",
    "ರೂಪಾಯಿ", "ರೂ",
    "ಉದ್ದಾರ", "ಸಾಲ", "ಕ್ರೆಡಿಟ್", "ಹಾಕು", "ಕೊಡಬೇಕು",
    "ಕೊಟ್ಟಿದ್ದಾರೆ", "ಕೊಟ್ರು", "ಬಂದಿದೆ", "ಬಂತು", "ಪೇಮೆಂಟ್", "ಜಮಾ", "ಪಾವತಿ", "ಸ್ವೀಕರಿಸಲಾಗಿದೆ",
    "ಒಟ್ಟು", "ಬಾಕಿ", "ಎಷ್ಟು", "ಬ್ಯಾಲೆನ್ಸ್",
    "ಹೌದು", "ಸರಿ", "ಹಾ", "ಆಯಿತು", "ಇಲ್ಲ", "ಬೇಡ", "ಕ್ಯಾನ್ಸಲ್"
}


def clean_text(text: str) -> str:
    cleaned = re.sub(r"[^\w\s\u0C80-\u0CFF₹-]", " ", text)
    return " ".join(cleaned.strip().split())


def extract_amount(text: str) -> int | None:
    # 1. Check for explicit negative numbers (e.g. -500, minus 500)
    neg_match = re.search(r"(?:-\s*(\d{1,7})|minus\s+(\d{1,7}))", text, re.IGNORECASE)
    if neg_match:
        val = int(neg_match.group(1) or neg_match.group(2))
        return -val

    # 2. Check currency prefixed or suffixed amounts (e.g. ₹430, 430 rs, 430 rupees, 430 roopayi, 430 ರೂಪಾಯಿ)
    currency_patterns = [
        r"[₹]\s*(\d{1,7})",
        r"(?:rs\.?|inr)\s*(\d{1,7})",
        r"(\d{1,7})\s*(?:rupees?|rs\.?|roopayi|rupaayi|inr|ರೂಪಾಯಿ|ರೂ)",
    ]
    for pattern in currency_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return int(match.group(1))

    # 3. Match standalone numbers, ignoring 10-digit phone numbers
    matches = re.findall(r"\b(\d+)\b", text)
    for m in matches:
        if len(m) != 10:  # Skip phone numbers
            return int(m)

    return None


def extract_customer_name(text: str) -> str | None:
    raw = text.strip()

    # Pattern 1: Kannada dative / ablative suffix
    # Handles Latin: "Ramesh ge", "Ramesh inda", "Ramesh-ige", "Ramesh ninda"
    # Handles Kannada Unicode: "ರಮೇಶ್ ಗೆ", "ರಮೇಶ್ ಇಂದ", "ರಮೇಶನಿಗೆ", "ರಮೇಶನಿಂದ"
    match = re.search(
        r"(?:^|[\s])([A-Za-z\u0C80-\u0CFF]{2,30})(?:[- ]?(?:ge|ige|nige|vige|inda|ninda|rinda|ಗೆ|ಿಗೆ|ನಿಗೆ|ರಿಗೆ|ವರಿಗೆ|ಇಂದ|ನಿಂದ|ರಿಂದ))(?:$|[\s.,!?;])",
        raw,
        re.IGNORECASE
    )
    if match:
        name = match.group(1).strip()
        if name.lower() not in STOP_WORDS:
            return name.capitalize()

    # Pattern 2: English "to <Name>", "for <Name>", "from <Name>", "with <Name>"
    match = re.search(
        r"\b(?:to|for|from|with)\s+([A-Za-z\u0C80-\u0CFF]{2,30})\b",
        raw,
        re.IGNORECASE
    )
    if match:
        name = match.group(1).strip()
        if name.lower() not in STOP_WORDS:
            return name.capitalize()

    # Pattern 3: Balance question: "<Name> total eshtu", "<Name> balance eshtu", "<Name> eshtu", "<Name> ಒಟ್ಟು ಎಷ್ಟು"
    match = re.search(
        r"(?:^|[\s])([A-Za-z\u0C80-\u0CFF]{2,30})\s+(?:total|balance|eshtu|baaki|ಒಟ್ಟು|ಬಾಕಿ|ಎಷ್ಟು|ಬ್ಯಾಲೆನ್ಸ್)(?:$|[\s.,!?;])",
        raw,
        re.IGNORECASE
    )
    if match:
        name = match.group(1).strip()
        if name.lower() not in STOP_WORDS:
            return name.capitalize()

    # Pattern 4: Name at the beginning followed by amount or action:
    # "Ramesh 500 bandide", "Ramesh 200 kodidare", "Ramesh credit 430", "ರಮೇಶ್ 500 ಬಂದಿದೆ"
    words = raw.split()
    if words:
        first_word = re.sub(r"[^\w\u0C80-\u0CFF]", "", words[0])
        if (
            len(first_word) >= 2
            and not first_word.isdigit()
            and first_word.lower() not in STOP_WORDS
        ):
            return first_word.capitalize()

    return None


def parse_voice_command(text: str, has_pending_transaction: bool = False) -> ParsedVoiceIntent:
    raw = text.strip()
    lower = raw.lower()
    tokens = {w.strip(".,!?\"':;") for w in lower.split()}

    # 1. Check for Confirmation
    # Examples: "Howdu", "haudu", "houdu", "yes", "sari", "sari maadu", "confirm", "ok", "okay", "correct", "ಹೌದು", "ಸರಿ", "ಹಾ", "huu", "aayithu"
    confirm_words = {
        "howdu", "haudu", "houdu", "yes", "sari", "confirm",
        "ok", "okay", "correct", "ಹೌದು", "ಸರಿ", "ಹಾ", "huu", "aayithu"
    }

    # If explicit confirm word is present without negation/cancellation
    if bool(tokens & confirm_words):
        if not re.search(r"\b(no|alla|illa|beda|change|eshtu|total|ಬದಲಾಯಿಸು|ಬೇಡ|ಇಲ್ಲ|ಅಲ್ಲ)\b", lower):
            amount = extract_amount(raw)
            if not amount or has_pending_transaction:
                if len(tokens) <= 3 or "confirm" in lower or "howdu" in lower or "haudu" in lower or "sari" in lower or "ಹೌದು" in tokens or "ಸರಿ" in tokens:
                    return {
                        "intent": "CONFIRM",
                        "raw_text": raw,
                        "customer_name": None,
                        "amount": None,
                        "transaction_type": None,
                        "confidence": 0.95,
                        "is_correction": False
                    }

    # 2. Check for Cancellation
    # Examples: "Illa", "beda", "cancel", "no", "stop", "raddumaadu", "ಇಲ್ಲ", "ಬೇಡ", "ಕ್ಯಾನ್ಸಲ್"
    cancel_words = {"illa", "beda", "cancel", "stop", "raddumaadu", "raddumadi", "ಇಲ್ಲ", "ಬೇಡ", "ಕ್ಯಾನ್ಸಲ್"}
    if bool(tokens & cancel_words):
        if not re.search(r"\b(\d+|maadu|change|make|ಮಾಡು|ಬದಲಾಯಿಸು)\b", lower):
            return {
                "intent": "CANCEL",
                "raw_text": raw,
                "customer_name": None,
                "amount": None,
                "transaction_type": None,
                "confidence": 0.95,
                "is_correction": False
            }

    # 3. Check for Correction (when a pending transaction exists or explicit correction phrases appear)
    # Examples: "No, 430 maadu", "alla 430 maadu", "make it 430", "change to 430", "430 maadu", "alla 430", "No, payment maadu"
    is_correction_phrase = bool(
        re.search(r"\b(no|alla|change|make\s+it|maadu|bedve|alla\s+alla|ಬದಲಾಯಿಸು|ಅಲ್ಲ|ಮಾಡು)\b", lower)
        or (has_pending_transaction and extract_amount(raw) is not None and not re.search(r"\b(udhaar|kadan|kodidare|kottidare|eshtu|total|bandide)\b", lower))
    )

    if has_pending_transaction and is_correction_phrase:
        amt = extract_amount(raw)
        cust = extract_customer_name(raw)
        txn_type = None
        if re.search(r"\b(udhaar|kadan|credit|ಉದ್ದಾರ|ಸಾಲ|ಕ್ರೆಡಿಟ್)\b", lower):
            txn_type = "CREDIT"
        elif re.search(r"\b(kodidare|kottidare|payment|jama|paid|bandide|banthu|ಕೊಟ್ಟಿದ್ದಾರೆ|ಜಮಾ|ಪೇಮೆಂಟ್)\b", lower):
            txn_type = "PAYMENT"

        return {
            "intent": "CORRECT",
            "raw_text": raw,
            "customer_name": cust,
            "amount": amt,
            "transaction_type": txn_type,
            "confidence": 0.92,
            "is_correction": True
        }

    # 4. Check for Balance Query
    # Examples: "Ramesh total eshtu?", "Ramesh balance eshtu?", "Ramesh baaki eshtu?", "What is Ramesh balance", "ರಮೇಶ್ ಒಟ್ಟು ಎಷ್ಟು?"
    if (
        re.search(r"\b(total\s+eshtu|balance\s+eshtu|baaki\s+eshtu|eshtu\s+baaki|eshtu|balance|total)\b", lower)
        or bool(tokens & {"ಒಟ್ಟು", "ಬಾಕಿ", "ಎಷ್ಟು", "ಬ್ಯಾಲೆನ್ಸ್"})
    ):
        if not re.search(r"\b(haaku|add|kodidare|kottidare|jama|maadu|bandide|ಹಾಕು|ಮಾಡು)\b", lower):
            cust = extract_customer_name(raw)
            return {
                "intent": "CHECK_BALANCE",
                "raw_text": raw,
                "customer_name": cust,
                "amount": None,
                "transaction_type": None,
                "confidence": 0.90,
                "is_correction": False
            }

    # 5. Intent Direction Extraction: Payment vs. Credit vs. Ambiguous
    amount = extract_amount(raw)
    cust = extract_customer_name(raw)

    pay_words = {
        "bandide", "banthu", "bantu", "aayithu", "kottaru", "kotru", "kottidare", "kodidare",
        "kotte", "kottidini", "payment", "jama", "paid", "gave", "settle", "settled",
        "received", "receipt", "cash", "ಬಂದಿದೆ", "ಬಂತು", "ಕೊಟ್ಟಿದ್ದಾರೆ", "ಕೊಟ್ರು", "ಪೇಮೆಂಟ್",
        "ಜಮಾ", "ಪಾವತಿ", "ಸ್ವೀಕರಿಸಲಾಗಿದೆ"
    }
    credit_words = {
        "udhaar", "kadan", "credit", "haaku", "haku", "sala", "saala", "kodbeku",
        "ಉದ್ದಾರ", "ಸಾಲ", "ಕ್ರೆಡಿಟ್", "ಹಾಕು", "ಕೊಡಬೇಕು"
    }

    has_pay_kw = bool(tokens & pay_words) or bool(re.search(r"\b(received|paid|gave|settle|receipt)\b", lower))
    has_credit_kw = bool(tokens & credit_words) or bool(re.search(r"\b(credit|add\s+credit)\b", lower))

    has_from = bool(re.search(r"(?:^|[\s])(?:inda|ninda|rinda|from|ಇಂದ|ನಿಂದ|ರಿಂದ)(?:$|[\s.,!?;])", lower))
    has_to = bool(re.search(r"(?:^|[\s])(?:ge|ige|nige|vige|to|ಗೆ|ಿಗೆ|ನಿಗೆ|ರಿಗೆ|ವರಿಗೆ)(?:$|[\s.,!?;])", lower))

    # 5a. Conflicting direction indicators: both from & credit, or both payment & credit
    if (has_from and has_credit_kw) or (has_pay_kw and has_credit_kw):
        return {
            "intent": "AMBIGUOUS_DIRECTION",
            "raw_text": raw,
            "customer_name": cust,
            "amount": amount,
            "transaction_type": None,
            "confidence": 0.40,
            "is_correction": False
        }

    # 5b. Clear Payment Intent (e.g. "Ramesh inda 500 bandide", "Ramesh 500 kottidare", "Received 500 from Ramesh")
    if has_pay_kw or (has_from and not has_credit_kw):
        return {
            "intent": "ADD_PAYMENT",
            "raw_text": raw,
            "customer_name": cust,
            "amount": amount,
            "transaction_type": "PAYMENT",
            "confidence": 0.94,
            "is_correction": False
        }

    # 5c. Clear Credit Intent (e.g. "Ramesh ge 430 rupees udhaar haaku", "Ramesh ge 500", "Credit 430 to Ramesh")
    if has_credit_kw or (has_to and not has_pay_kw):
        return {
            "intent": "ADD_CREDIT",
            "raw_text": raw,
            "customer_name": cust,
            "amount": amount,
            "transaction_type": "CREDIT",
            "confidence": 0.94,
            "is_correction": False
        }

    # 5d. Ambiguous Direction: Customer and Amount exist, but no direction keyword or particle was provided (e.g. "Ramesh 500")
    if cust and amount:
        return {
            "intent": "AMBIGUOUS_DIRECTION",
            "raw_text": raw,
            "customer_name": cust,
            "amount": amount,
            "transaction_type": None,
            "confidence": 0.40,
            "is_correction": False
        }

    # 6. Customer Search query
    if re.search(r"\b(search|find|huduku|look|ಹುಡುಕು)\b", lower) and cust:
        return {
            "intent": "SEARCH_CUSTOMER",
            "raw_text": raw,
            "customer_name": cust,
            "amount": None,
            "transaction_type": None,
            "confidence": 0.85,
            "is_correction": False
        }

    return {
        "intent": "UNKNOWN",
        "raw_text": raw,
        "customer_name": cust,
        "amount": amount,
        "transaction_type": None,
        "confidence": 0.20,
        "is_correction": False
    }
