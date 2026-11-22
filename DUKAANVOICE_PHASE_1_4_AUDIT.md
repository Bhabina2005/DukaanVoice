# DukaanVoice — Phase 1.4 Application & Architecture Audit Report

**Date:** 2026-11-20  
**Audit Stage:** Stage A — Full Application & Workflow Inspection  
**Auditor:** Antigravity Engineering  
**Application Baseline:** React 19 + Vite Frontend, FastAPI Backend, SQLite DB (`2B0363C99E9BF0788C17FA10E77CDBAB958801644DA4CF77597AD9AD2D073FA3`)  

---

## 1. Executive Summary & Audit Scope

This audit performs an end-to-end inspection of DukaanVoice across the entire frontend and backend codebases to prepare the application for **Phase 1.4 Production Readiness**.

The inspection audited:
- User interaction workflows (VoiceAssistant, Dashboard, Customers, Ledger).
- Audio and speech pipelines (MediaRecorder, Gnani Prisma v3.0 STT adapter, Gnani Timbre v3.0 TTS adapter, Browser Web Speech fallback).
- Natural language parsing and intent extraction (Kannada, Kanglish, English).
- Financial ledger safety, database atomicity, idempotency, and TTL expirations.
- Responsive design and accessibility across mobile and desktop.
- Security, configuration, and data isolation.

The live development database ([backend/dukaanvoice.db](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/dukaanvoice.db)) was verified in read-only mode and remains strictly untouched at SHA-256 `2B0363C99E9BF0788C17FA10E77CDBAB958801644DA4CF77597AD9AD2D073FA3`.

---

## 2. Existing Capabilities Matrix

| Subsystem | Component / Module | Verified Capabilities | Status |
| :--- | :--- | :--- | :--- |
| **Voice In** | [frontend/src/services/speechService.js](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/services/speechService.js) | Dual-mode capture: `MediaRecorder` for Gnani STT; `webkitSpeechRecognition` fallback for native speech. | **WORKING** |
| **STT Adapter** | [backend/speech_provider.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/speech_provider.py#L95-L205) | Gnani Prisma v3.0 REST client (`POST https://api.vachana.ai/stt/v3`) with headers, error wrapping, and model selection. | **WORKING** |
| **NLU / Parser** | [backend/voice_parser.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/voice_parser.py) | Multilingual regex parsing for credits, payments, balance checks, confirmations, cancellations, and corrections. | **WORKING (Gaps noted)** |
| **Pending Staging** | [backend/pending_manager.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/pending_manager.py) | Database-backed pending transactions (`pending_transactions` table), 15-minute TTL, thread lock `self._lock`. | **WORKING** |
| **Idempotency** | [backend/models.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/models.py#L42) | Unique constraint on `transactions.idempotency_key` preventing duplicate commits. | **WORKING** |
| **TTS Adapter** | [backend/speech_provider.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/speech_provider.py#L208-L285) | Gnani Timbre v3.0 REST client (`POST https://api.vachana.ai/api/v1/tts/inference`) streaming binary audio. | **WORKING** |
| **Voice Out** | [frontend/src/services/speechService.js](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/services/speechService.js#L235-L280) | Dual-mode playback: HTML5 `Audio` for Timbre v3.0 audio; `window.speechSynthesis` for fallback. | **WORKING** |
| **Dashboard** | [frontend/src/components/DashboardView.jsx](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/components/DashboardView.jsx) | Live SQL aggregation: Total Credit, Total Payments, Net Outstanding, Customer Count, Recent Txns. | **WORKING** |
| **Customers** | [frontend/src/components/CustomersView.jsx](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/components/CustomersView.jsx) | Search by name/phone, customer balance calculation, creation modal, transaction history drawer. | **WORKING** |
| **Ledger** | [frontend/src/components/LedgerView.jsx](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/components/LedgerView.jsx) | Chronological transaction table, filter by CREDIT/PAYMENT, search, totals summary. | **WORKING** |

---

## 3. End-to-End Voice Workflow Trace & Gaps

We traced the complete 10-step voice-to-ledger workflow:

```
[1. Microphone] ──> [2. Audio Capture] ──> [3. STT (Prisma)] ──> [4. Transcript]
                                                                        │
[8. Database Commit] <── [7. User Confirm] <── [6. Pending Card] <── [5. NLU Parsing]
        │
        └──> [9. Balance Recalculation] ──> [10. TTS (Timbre v3.0) / Audio Playback]
```

### Detailed Trace Evaluation:

1. **Microphone Activation:**
   - User clicks mic button in `VoiceAssistant.jsx`.
   - *Status:* Working.
   - *Gap:* No explicit browser permission pre-check or dedicated warning banner when mic permission is denied (`NotAllowedError`).
2. **Audio Capture:**
   - Captured via `MediaRecorder` (webm/mp4) in `speechService.js`.
   - *Status:* Working.
   - *Gap:* No 30-second client-side auto-stop timer. If the user does not tap stop, the recording continues indefinitely and gets rejected by Gnani REST STT (which has a strict 30-second limit).
3. **STT Transcription (Prisma v3.0):**
   - Transcribed at `POST /api/voice/transcribe`.
   - *Status:* Working. Returns `{success: true, transcript: "..."}`.
   - *Gap:* When silence or empty audio is sent, STT returns `transcript: ""`. In `speechService.js`, an empty transcript silently exits without notifying the user why no action occurred.
4. **Transcript Display:**
   - Transcript displayed in live box or user chat bubble.
   - *Status:* Working.
5. **NLU Parsing & Customer Identification:**
   - Parsed by `parse_voice_command()` in `voice_parser.py`, customer matched via `find_matching_customers()` in `voice.py`.
   - *Status:* Working for standard phrases.
   - *Gaps Identified:*
     - Regional Kanglish payment phrase `"Ramesh inda 500 bandide"` ("received 500 from Ramesh") is misclassified as `ADD_CREDIT` because `"bandide"` (received) is not in the payment keyword pattern.
     - Kannada script matching: If customer is stored in English (`"Ramesh"`), spoken Kannada name `"ರಮೇಶ್"` does not match unless a transliteration or alias mapping exists.
6. **Pending Transaction Staging (Confirmation Card):**
   - Staged in `pending_transactions` table via `pending_manager.create_pending()`.
   - *Status:* Working.
   - *Critical UX Gap:* The confirmation card displays customer name, amount, and prompt question, but **does NOT display the customer's current balance, proposed change, or expected resulting balance** (e.g., `Current: ₹430 | Credit: +₹500 | New Balance: ₹930`).
7. **Explicit User Confirmation / Cancellation / Correction:**
   - User speaks `"Howdu"`, `"Illa"`, or `"No, 430 maadu"`, or clicks buttons.
   - *Status:* Fully functional with 15-minute TTL.
8. **Database Commit:**
   - Committed atomically via `confirm_voice_transaction()` with unique `idempotency_key`.
   - *Status:* Working. Ledger entries are strictly prevented prior to confirmation.
9. **Balance Recalculation:**
   - Calculated via `calculate_balance_dict()`.
   - *Status:* Working.
10. **TTS Response Synthesis (Timbre v3.0):**
    - Synthesized via `POST /api/voice/tts` and played via HTML5 `Audio`.
    - *Status:* Working with automatic fallback to `speechSynthesis`.
    - *Gap:* Overlapping audio playback can occur if a previous utterance audio is still playing when a new one begins.

---

## 4. Identified Defects, Missing Features & Edge Cases

| ID | Category | Defect / Missing Feature Description | Exact Files Involved | Severity | Priority |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DEF-01** | Documentation | `Nalini` listed under Timbre v3.0 in Phase 1.3 report; belongs to v2.5. | `DUKAANVOICE_PHASE_1_3_REPORT.md` | **Low** | **P0 (Resolved)** |
| **DEF-02** | Confirmation UX | Pending confirmation card does not display existing balance or resulting balance before commit. | `backend/routes/voice.py`, `VoiceAssistant.jsx` | **High** | **P1** |
| **DEF-03** | Voice Reliability | Empty audio or silence from STT silently exits without giving user audible or visual feedback. | `frontend/src/services/speechService.js`, `VoiceAssistant.jsx` | **Medium** | **P1** |
| **DEF-04** | STT Audio Limit | No client-side 30-second duration cutoff on `MediaRecorder`, risking server rejection. | `frontend/src/services/speechService.js` | **Medium** | **P1** |
| **DEF-05** | Parsing Accuracy | `"Ramesh inda 500 bandide"` (cash inflow) parsed as CREDIT instead of PAYMENT. | `backend/voice_parser.py` | **High** | **P1** |
| **DEF-06** | Parsing / Names | Name matching across scripts (e.g. `"ರಮೇಶ್"` vs `"Ramesh"`) lacks phonetic transliteration fallback. | `backend/voice_parser.py`, `backend/routes/voice.py` | **Medium** | **P2** |
| **DEF-07** | Audio Playback | Previous audio not systematically stopped when user initiates new mic recording or speech playback. | `frontend/src/services/speechService.js` | **Low** | **P2** |
| **DEF-08** | Mobile UX | Limited responsive media queries for screens `< 600px` (e.g. small Android screens used by kirana owners). | `frontend/src/App.css` | **Medium** | **P2** |
| **DEF-09** | Error Recovery | Network retry button missing when voice command or transaction fails due to network glitch. | `frontend/src/components/VoiceAssistant.jsx` | **Low** | **P2** |
| **DEF-10** | Mic Permissions | Permission denied on `getUserMedia` triggers generic warning instead of explicit mic permission guidance. | `frontend/src/services/speechService.js`, `VoiceAssistant.jsx` | **Low** | **P2** |

---

## 5. Existing Tests Protecting Current Behavior

Current test suites provide high regression protection across modules:

1. [backend/test_pending_durability.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/test_pending_durability.py) (**11 tests passed**):
   - Protects restart recovery, persistent idempotency, atomic commits, rollback on commit failure, 15-minute TTL, thread safety, and foreign key enforcement.
2. [backend/test_gnani_integration.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/test_gnani_integration.py) (**14 tests passed**):
   - Protects Gnani Prisma v3.0 STT, Timbre v3.0 TTS, 401 auth failures, timeouts, network disconnection, silence handling, amount corrections, cancellation safety, and live DB integrity.
3. **Frontend Linter:**
   - `npm run lint` passing with **0 errors, 0 warnings**.

---

## 6. Recommended Implementation Order (Controlled Stages)

To maintain safety and satisfy all project rules, the recommended execution order is:

```
[Stage A: Doc Correction & Application Audit] (COMPLETE)
                     │
[Stage B: Voice Lifecycle & Audio Reliability]
- 30s auto-stop timer, silence feedback, mic permission guidance, overlapping audio release.
                     │
[Stage C: Multilingual Parsing & Customer Identification]
- "bandide" / "kotru" / "kodbeku" payment/credit disambiguation, cross-script transliteration helper.
                     │
[Stage D: Confirmation Experience & Ledger Consistency]
- Display current balance and expected new balance on pending card before commit.
                     │
[Stage E: TTS Fallback & Mobile Responsive UI]
- Responsive media queries for kirana mobile devices (< 480px / < 600px), touch targets.
                     │
[Stage F: Security Review, End-to-End Regression Suite & Final Verification]
- 20-scenario automated test suite, live DB hash verification, final report.
```

---

## 7. Stage A Verification Summary

1. **Step 0 Completed:**
   - Modified [DUKAANVOICE_PHASE_1_3_REPORT.md](file:///C:/Users/bhabi/Downloads/DukaanVoice/DUKAANVOICE_PHASE_1_3_REPORT.md#L77): Removed `Nalini` from Timbre v3.0 voice catalog; retained valid v3.0 voices (`Avinash`, `Shivani`, `Lakshmi`, etc.); retained `Shivani` as default.
   - Provider adapters were **not** modified.
2. **Database Integrity:**
   - Live database ([backend/dukaanvoice.db](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/dukaanvoice.db)) SHA-256: `2B0363C99E9BF0788C17FA10E77CDBAB958801644DA4CF77597AD9AD2D073FA3` (Identical, untouched).
   - Baseline customer (`Ramesh`, ID 1) and original transaction (`CREDIT ₹430`, ID 1) remain verified.
3. **Audit Delivered:**
   - [DUKAANVOICE_PHASE_1_4_AUDIT.md](file:///C:/Users/bhabi/Downloads/DukaanVoice/DUKAANVOICE_PHASE_1_4_AUDIT.md) completed with full gap identification and prioritization.
