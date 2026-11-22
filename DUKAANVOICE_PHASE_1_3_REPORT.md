# DukaanVoice — Phase 1.3: Gnani Voice AI Integration Report

**Date:** 2026-11-20  
**Phase:** Phase 1.3 — Gnani Voice AI Integration  
**Challenge:** BolBharat Gnani Voice AI Innovation Challenge  
**Status:** **COMPLETE (Adapters Implemented, Fully Tested with Mocks, Ready for Live Credentials)**  

---

## 1. Existing Architecture Inspected

Prior to modifying code, a comprehensive read-only audit of the existing application was conducted across the following components:

- **Reports & Audits:**
  - [DUKAANVOICE_PHASE_1_1_REPORT.md](file:///C:/Users/bhabi/Downloads/DukaanVoice/DUKAANVOICE_PHASE_1_1_REPORT.md)
  - [DUKAANVOICE_PHASE_1_2A_RELIABILITY_AUDIT.md](file:///C:/Users/bhabi/Downloads/DukaanVoice/DUKAANVOICE_PHASE_1_2A_RELIABILITY_AUDIT.md)
  - [DUKAANVOICE_PHASE_1_2B_REPORT.md](file:///C:/Users/bhabi/Downloads/DukaanVoice/DUKAANVOICE_PHASE_1_2B_REPORT.md)
  - [DUKAANVOICE_PHASE_1_2B_VERIFICATION_REPORT.md](file:///C:/Users/bhabi/Downloads/DukaanVoice/DUKAANVOICE_PHASE_1_2B_VERIFICATION_REPORT.md)
- **Backend Core:**
  - [backend/main.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/main.py) — FastAPI routing, lifecycle, CORS.
  - [backend/routes/voice.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/routes/voice.py) — Voice interaction endpoints (`/process`, `/confirm`, `/cancel`, `/correct`, `/pending`, `/ws`).
  - [backend/voice_parser.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/voice_parser.py) — Rule-based multilingual intent extractor for Kannada, Kanglish, and English.
  - [backend/pending_manager.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/pending_manager.py) — Database-backed pending transaction lifecycle with atomic confirmation and 15-minute TTL.
  - [backend/models.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/models.py) & [backend/schemas.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/schemas.py) — ORM and Pydantic schemas.
  - [backend/database.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/database.py) — SQLite engine with foreign key enforcement and migration hooks.
- **Frontend Core:**
  - [frontend/src/components/VoiceAssistant.jsx](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/components/VoiceAssistant.jsx) — Voice interaction component.
  - [frontend/src/services/speechService.js](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/services/speechService.js) — Speech provider adapter.
  - [frontend/src/services/api.js](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/services/api.js) — Backend API client.
- **Configuration:**
  - `backend/.env`, `backend/.env.example`, `frontend/.env`, `frontend/.env.example`.

### Existing Workflow Baseline
The user activates the microphone, speech is captured, parsed into financial intent (Credit, Payment, Balance, Confirm, Cancel, Correct), staged in the database as a pending transaction, and executed **only** upon explicit confirmation (`"Howdu"` / Yes).

---

## 2. Official Gnani API Contracts & Specifications

Official Gnani AI (Vachana Speech Platform) API documentation and specifications were retrieved:

### 2.1 Gnani Prisma v3.0 — Speech-to-Text (STT)
- **Base URL:** `https://api.vachana.ai`
- **REST Inference Endpoint:** `POST https://api.vachana.ai/stt/v3`
- **Streaming WebSocket Endpoint:** `WSS wss://api.vachana.ai/stt/v3/stream`
- **Authentication:** HTTP Header `X-API-Key-ID: <GNANI_API_KEY>`
- **Model Identifier:** `prisma-v3.0`
- **Supported Audio Formats:** WAV, MP3, raw 16-bit PCM (16 kHz / 8 kHz mono)
- **Request Format:** `multipart/form-data`:
  - `audio_file`: Binary audio payload
  - `model`: `"prisma-v3.0"`
  - `language_code`: `"kn-IN"` (Kannada), `"en-IN"`, or `"indic-auto"`
- **Response Format (200 OK):**
  ```json
  {
    "success": true,
    "request_id": "5c1f0a52-6d62-4e0b-9a38-2f2b8a8f7a10",
    "transcript": "ರಮೇಶ್ ಗೆ 430 ರೂಪಾಯಿ ಉದ್ದಾರ ಹಾಕು",
    "model": "prisma-v3.0",
    "detected_language_code": "kn-IN",
    "processing_time": 0.58,
    "end_to_end_latency": 0.65
  }
  ```
- **Error Formats:**
  - `401 Unauthorized`: `{"detail": {"error_code": "INVALID_API_KEY", "message": "Invalid API key", "status_code": 401}}`
  - `400 Bad Request`: `{"success": false, "message": "Invalid audio file", "status_code": 400}`
  - `429 Too Many Requests`: `{"detail": {"error_code": "RATE_LIMITED", "message": "Rate limit exceeded", "status_code": 429}}`

### 2.2 Gnani Timbre v3.0 — Text-to-Speech (TTS)
- **Base URL:** `https://api.vachana.ai`
- **REST Inference Endpoint:** `POST https://api.vachana.ai/api/v1/tts/inference`
- **Streaming SSE Endpoint:** `POST https://api.vachana.ai/api/v1/tts/sse`
- **Realtime WebSocket:** `WSS wss://api.vachana.ai/api/v1/tts`
- **Authentication:** HTTP Header `X-API-Key-ID: <GNANI_API_KEY>`
- **Model Identifier:** `timbre-v3.0`
- **Available Voices:** `Shivani` (default), `Avinash`, `Lakshmi`, `Chetana`, `Devansh`, `Harshad`, `Kalpana`, `Prakash`, `Riyaa`, `Shubham`, `Tarika`, `Vasudha`, `Yashraj` (Note: `Nalini` belongs exclusively to legacy Timbre v2.5 and is omitted)
- **Request Format:** `application/json`:
  ```json
  {
    "text": "Ramesh ge ₹430 credit add maadbekaa?",
    "model": "timbre-v3.0",
    "voice": "Shivani",
    "language": "kn-IN",
    "speed": 1.0,
    "audio_config": {
      "container": "wav",
      "sample_rate": 24000,
      "encoding": "linear_pcm"
    }
  }
  ```
- **Response Format (200 OK):** Binary audio stream with `Content-Type: audio/wav` (or `audio/mpeg`).
- **Error Formats:**
  - `401 Unauthorized`: `{"detail": {"error_code": "MISSING_API_KEY", "message": "...", "status_code": 401}}`
  - `400 Bad Request`: `{"success": false, "message": "...", "status_code": 400}`

---

## 3. Files Created and Modified

| File Path | Action | Description |
| :--- | :--- | :--- |
| [backend/speech_provider.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/speech_provider.py) | **Created** | Modular provider adapters: `GnaniPrismaSTTProvider`, `GnaniTimbreTTSProvider`, `SpeechProviderManager`. |
| [backend/test_gnani_integration.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/test_gnani_integration.py) | **Created** | Comprehensive 14-scenario automated test suite validating STT, TTS, error handling, and transaction durability. |
| [backend/schemas.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/schemas.py) | **Modified** | Added `AudioTranscribeRequest`, `AudioTranscribeResponse`, `TTSRequest`, `SpeechProviderStatusResponse`, `AudioVoiceCommandRequest`. |
| [backend/routes/voice.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/routes/voice.py) | **Modified** | Added `/provider-status`, `/transcribe`, `/tts`, and `/audio-command` endpoints. |
| [backend/main.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/main.py) | **Modified** | Protected migration hook against read-only test collection errors. |
| [backend/.env.example](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/.env.example) | **Modified** | Added official Gnani Prisma and Timbre environment variables. |
| [frontend/src/services/api.js](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/services/api.js) | **Modified** | Added `getSpeechProviderStatus()`, `transcribeAudio()`, `synthesizeSpeech()`, `sendAudioVoiceCommand()`. |
| [frontend/src/services/speechService.js](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/services/speechService.js) | **Modified** | Implemented dual-mode audio capture (MediaRecorder -> Prisma STT) and playback (Timbre TTS -> HTML5 Audio) with Web Speech fallback. |
| [frontend/src/components/VoiceAssistant.jsx](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/components/VoiceAssistant.jsx) | **Modified** | Dynamically loads speech provider status, displays active badge, connects mic and audio replies. |
| [README.md](file:///C:/Users/bhabi/Downloads/DukaanVoice/README.md) | **Modified** | Updated architecture diagram, capabilities, testing documentation, and challenge attribution. |

---

## 4. STT Implementation Details (`GnaniPrismaSTTProvider`)

Located in [backend/speech_provider.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/speech_provider.py#L79-L185):
- **Safety Validations:** Validates that audio is non-empty and enforces a 10MB maximum payload limit.
- **Header Management:** Automatically injects `X-API-Key-ID: <GNANI_API_KEY>`. Never logs keys or sensitive audio payload.
- **Error Mapping:**
  - `401` -> `GnaniAuthenticationError`
  - `400` / `422` -> `GnaniAudioError`
  - `429` -> `GnaniRateLimitError`
  - Timeout -> `GnaniTimeoutError`
  - Network disconnection -> `GnaniNetworkError`
- **Route Endpoint:** `POST /api/voice/transcribe`
  - Accepts base64 audio payload.
  - If Gnani is unconfigured or fails, returns structured JSON response with `fallback_hint` so frontend triggers browser speech recognition immediately.

---

## 5. TTS Implementation Details (`GnaniTimbreTTSProvider`)

Located in [backend/speech_provider.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/speech_provider.py#L188-L277):
- **Input Validation:** Enforces non-empty string and a 1000-character safety bound.
- **Configurable Synthesis:** Supports voice selection (`Shivani`, `Avinash`, etc.), speed scaling (0.5 to 2.0), and audio container format (`wav` / `mp3`).
- **Binary Streaming:** Returns raw audio bytes with matching `Content-Type: audio/wav`.
- **Route Endpoint:** `POST /api/voice/tts`
  - Returns `Response(content=audio_bytes, media_type="audio/wav")`.
  - Non-blocking: TTS failures do not abort ledger transactions. Frontend catches TTS errors and falls back to browser synthesis.

---

## 6. Environment Variables Required

The following environment variables configure the Gnani Voice AI integration:

```bash
# Gnani Platform API Key (Generated from Gnani developer console)
GNANI_API_KEY=your_gnani_api_key_here

# Optional Endpoint Overrides (defaults shown)
GNANI_STT_URL=https://api.vachana.ai/stt/v3
GNANI_TTS_URL=https://api.vachana.ai/api/v1/tts/inference
GNANI_STT_MODEL=prisma-v3.0
GNANI_TTS_MODEL=timbre-v3.0
GNANI_TTS_VOICE=Shivani
GNANI_TIMEOUT_SECONDS=10.0
```

---

## 7. Frontend Workflow & UI Changes

1. **Dynamic Engine Discovery:** On component mount, [frontend/src/services/speechService.js](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/services/speechService.js) calls `GET /api/voice/provider-status` to inspect whether Gnani credentials are valid on the backend.
2. **Provider Badge:** [frontend/src/components/VoiceAssistant.jsx](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/components/VoiceAssistant.jsx) displays:
   - When Gnani Active: `⚡ Gnani Voice AI (Prisma v3.0 / Timbre v3.0)`
   - When Fallback Active: `🎙️ Browser Web Speech API (Fallback)` with note explaining credentials status.
3. **Audio Capture:** When user clicks mic, if Gnani is active, `MediaRecorder` records audio and submits it to `/api/voice/transcribe`.
4. **Playback:** Spoken responses from DukaanVoice are synthesized using `/api/voice/tts` and played via HTML5 `Audio`. If unavailable, `speechSynthesis` is used.
5. **Preserved Workflows:** Confirmation (`Howdu`), cancellation (`Illa`), amount corrections (`No, 430 maadu`), and balance checks operate identically with zero deviation.

---

## 8. Fallback Behavior

DukaanVoice strictly enforces deterministic, non-silent fallbacks:
- **Missing API Key:** When `GNANI_API_KEY` is not present, backend returns `fallback_hint` and `is_configured: false`. The frontend immediately enables Browser Web Speech API.
- **Provider Downtime / Timeout:** If Gnani API times out or returns HTTP 5xx, the frontend catches the error and activates `startWebSpeechFallback` without disrupting the user.
- **TTS Failure:** If Timbre TTS fails, the ledger transaction response is still displayed, and the response text is spoken via `window.speechSynthesis`.
- **Honest Attribution:** Browser speech is never misrepresented as Gnani.

---

## 9. Tests Executed & Actual Results

### Automated Integration Test Suite (`backend/test_gnani_integration.py`)
Executed on Python 3.11 with an isolated in-memory SQLite database (`sqlite:///:memory:`):

| # | Test Function Name | Tested Scenario | Result |
| :--- | :--- | :--- | :--- |
| 1 | `test_scenario_1_stt_success_prisma_v3` | Prisma v3.0 STT mock response parsing | **PASSED** |
| 2 | `test_scenario_2_multilingual_kannada_kanglish_english_parsing` | Kannada, Kanglish & English transcript parsing | **PASSED** |
| 3 | `test_scenario_3_invalid_audio_rejection` | Empty & oversized (>10MB) audio rejection | **PASSED** |
| 4 | `test_scenario_4_empty_transcription_silence_handling` | Silence handling without ledger mutation | **PASSED** |
| 5 | `test_scenario_5_provider_authentication_failure` | HTTP 401 INVALID_API_KEY handling | **PASSED** |
| 6 | `test_scenario_6_provider_timeout_handling` | Read/Connect timeout exception wrapping | **PASSED** |
| 7 | `test_scenario_7_provider_network_or_500_failure` | Network connection error handling | **PASSED** |
| 8 | `test_scenario_8_tts_success_timbre_v3` | Timbre v3.0 binary audio synthesis | **PASSED** |
| 9 | `test_scenario_9_tts_failure_does_not_abort_transaction` | TTS failure fallback without blocking txn | **PASSED** |
| 10 | `test_scenario_10_amount_correction_before_confirmation` | Voice correction: ₹340 -> ₹430 before confirm | **PASSED** |
| 11 | `test_scenario_11_cancellation_safety_zero_ledger_entries` | Spoken cancellation ("Illa") writes 0 ledger rows | **PASSED** |
| 12 | `test_scenario_12_and_13_atomic_confirmation_and_idempotent_replay` | Atomic confirmation & idempotent replay | **PASSED** |
| 13 | `test_scenario_14_restart_recovery_of_pending_transaction` | Pending transaction recovery across restarts | **PASSED** |
| 14 | `test_scenario_15_live_database_integrity_and_records_untouched` | Live `dukaanvoice.db` integrity verification | **PASSED** |

**Integration Test Run Summary:** **14 passed in 3.88s.**

### Regression Verification (`backend/test_pending_durability.py`)
- **Result:** **11 passed in 0.96s** (All Phase 1.2B durability, locking, TTL, and atomicity safeguards remain intact).

### Frontend Static Code Quality
- **Command:** `cd frontend; npm run lint`
- **Result:** **0 errors, 0 warnings.**

---

## 10. Mocked vs. Live Integration Status

- **Mocked Integration Status:** **100% COMPLETE & VERIFIED.**
  All request schemas, headers (`X-API-Key-ID`), multipart payloads, model tags (`prisma-v3.0`, `timbre-v3.0`), and error envelopes match official Gnani AI specifications and pass automated tests.
- **Live Integration Status:** **PENDING API CREDENTIALS.**
  Because `GNANI_API_KEY` is not yet configured in the environment, live external HTTP requests to `api.vachana.ai` have not been executed. Once a real key is placed in `backend/.env`, live processing will immediately activate.

---

## 11. Database Integrity Verification

The live development database ([backend/dukaanvoice.db](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/dukaanvoice.db)) was verified before and after all changes:

- **Original SHA-256 Hash:** `2B0363C99E9BF0788C17FA10E77CDBAB958801644DA4CF77597AD9AD2D073FA3`
- **Current SHA-256 Hash:** `2B0363C99E9BF0788C17FA10E77CDBAB958801644DA4CF77597AD9AD2D073FA3`
- **Hash Match:** **EXACT MATCH (100% UNTOUCHED)**
- **Baseline Record Verification (Read-Only SQLite):**
  - Customers: exactly 1 (`id=1`, `name=Ramesh`, `phone=9876543210`)
  - Transactions: exactly 1 (`id=1`, `customer_id=1`, `transaction_type=CREDIT`, `amount=430`)
  - Outstanding Balance: **₹430**

---

## 12. Known Limitations

1. **Live Gnani Credentials:** Live speech recognition and synthesis against `api.vachana.ai` require setting `GNANI_API_KEY` in `backend/.env`.
2. **Browser Permissions:** Browser audio recording (`MediaRecorder`) requires microphone access permission from the user.
3. **Sandbox Sockets:** Windows sandbox security tokens restrict loopback TCP connections; live server verification should be run in the host terminal.

---

## 13. Remaining Work

1. Provide a valid `GNANI_API_KEY` in `backend/.env` for live production deployment.
2. Conduct an end-to-end voice test with shopkeeper microphone speech directly through the browser.
3. Proceed to Phase 1.4 / final submission packaging as requested.
