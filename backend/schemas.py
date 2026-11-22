from datetime import datetime
from typing import Literal, Any
from pydantic import BaseModel, ConfigDict, Field


class CustomerCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)
    phone: str | None = Field(default=None, max_length=20)


class CustomerResponse(BaseModel):
    id: int
    name: str
    phone: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class CustomerWithBalance(BaseModel):
    id: int
    name: str
    phone: str | None
    created_at: datetime
    total_credit: int = 0
    total_payments: int = 0
    outstanding_balance: int = 0
    advance_balance: int = 0
    last_transaction_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class TransactionCreate(BaseModel):
    customer_id: int = Field(gt=0)
    transaction_type: Literal["CREDIT", "PAYMENT"]
    amount: int = Field(gt=0, le=10_000_000)
    description: str | None = Field(default=None, max_length=255)


class TransactionResponse(BaseModel):
    id: int
    customer_id: int
    transaction_type: str
    amount: int
    description: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class TransactionWithCustomer(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    customer_phone: str | None = None
    transaction_type: str
    amount: int
    description: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class DashboardStats(BaseModel):
    total_credit: int
    total_payments: int
    outstanding_balance: int
    customer_count: int
    transaction_count: int


class AuditEntry(BaseModel):
    timestamp: str
    action: str
    details: str
    balance_preview: dict[str, Any] | None = None


class BalancePreview(BaseModel):
    current_outstanding: int
    current_advance: int = 0
    expected_outstanding: int
    expected_advance: int = 0
    expected_net_balance: int
    baseline_balance: int
    balance_explanation: str
    balance_explanation_kn: str


class PendingTransaction(BaseModel):
    pending_id: str
    session_id: str
    customer_id: int | None = None
    customer_name: str
    customer_phone: str | None = None
    amount: int
    transaction_type: Literal["CREDIT", "PAYMENT"]
    description: str | None = None
    status: Literal["PENDING", "CONFIRMED", "CANCELLED", "EXPIRED"] = "PENDING"
    audit_trail: list[AuditEntry] = []
    created_at: str
    updated_at: str
    expires_at: str | None = None
    confirmed_transaction_id: int | None = None
    balance_preview: BalancePreview | None = None


class VoiceParseRequest(BaseModel):
    transcript: str = Field(min_length=1)
    session_id: str = Field(default="default")


class VoiceActionResponse(BaseModel):
    success: bool = True
    intent: str
    message: str
    message_kn: str
    spoken_text: str
    pending_transaction: PendingTransaction | None = None
    confirmed_transaction: TransactionResponse | None = None
    customer_balance: dict[str, Any] | None = None
    balance_preview: BalancePreview | None = None
    disambiguation_options: list[dict[str, Any]] | None = None


class VoiceConfirmRequest(BaseModel):
    pending_id: str
    session_id: str = "default"
    expected_baseline: int | None = None


class VoiceCancelRequest(BaseModel):
    pending_id: str
    session_id: str = "default"


class VoiceCorrectRequest(BaseModel):
    pending_id: str
    session_id: str = "default"
    amount: int | None = Field(default=None, gt=0, le=10_000_000)
    customer_id: int | None = None
    customer_name: str | None = None
    transaction_type: Literal["CREDIT", "PAYMENT"] | None = None


# --- Phase 1.3: Gnani Voice AI Schemas ---

class AudioTranscribeRequest(BaseModel):
    audio_base64: str = Field(description="Base64-encoded audio payload")
    format: str = Field(default="wav", description="Audio format (wav, mp3, webm, etc.)")
    language: str = Field(default="kn-IN", description="Language code (kn-IN, en-IN, etc.)")


class AudioTranscribeResponse(BaseModel):
    success: bool
    transcript: str = ""
    detected_language: str | None = None
    provider: str = "Gnani Prisma v3.0"
    model: str = "prisma-v3.0"
    request_id: str | None = None
    processing_time: float | None = None
    error: str | None = None
    fallback_hint: str | None = None


class TTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000, description="Text to synthesize to speech")
    language: str = Field(default="kn-IN", description="Target language locale")
    voice: str | None = Field(default=None, description="Gnani voice name (e.g. Shivani)")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="Speech playback speed")
    container: str = Field(default="wav", description="Output audio container (wav, mp3)")


class SpeechProviderStatusResponse(BaseModel):
    provider: str
    is_configured: bool
    stt_model: str
    tts_model: str
    tts_voice: str
    stt_endpoint: str
    tts_endpoint: str
    fallback_active: bool
    fallback_provider: str
    status_note: str


class AudioVoiceCommandRequest(BaseModel):
    audio_base64: str = Field(description="Base64-encoded audio speech file")
    session_id: str = Field(default="default")
    format: str = Field(default="wav")
    language: str = Field(default="kn-IN")

