# DukaanVoice – BolBharat Phase 1 Audit Report
**Existing Project Audit & Safe Baseline**  
**Challenge:** BolBharat Gnani Voice AI Innovation Challenge  
**Date:** November 18, 2026  
**Status:** Audit Complete (Safe Baseline Established)

---

## 1. Executive Summary

DukaanVoice is an existing, functional voice-first ledger application designed for kirana shopkeepers. It facilitates recording credit (*udhaar*), payments (*jama*), and outstanding balance inquiries using Kannada and English voice instructions.

The system features an active SQLite database with real historical ledger records, a FastAPI backend, and a React 19 + Vite frontend. Prior to this audit, a complete pristine backup of the database and source codebase was created at `C:\Users\bhabi\.gemini\antigravity-cli\brain\e849a086-4173-40ff-ab54-35a81081bfb7\backup_phase1\dukaanvoice.db`.

**Key Finding on Gnani Integration:**  
Gnani Voice AI (Prisma v3.0 STT / Timbre v3.0 TTS) is **NOT currently integrated or connected**. The application currently relies entirely on browser Web Speech API fallback (`webkitSpeechRecognition` / `window.speechSynthesis`).

---

## 2. Audit Matrix: Passed, Failed, and Not Tested Checks

| Check Category | Item | Status | Details / Evidence |
| :--- | :--- | :---: | :--- |
| **Backend Startup** | Health Endpoint (`/health`) | **PASSED** | Responded `200 OK`: `{"status": "healthy", "database": "connected", "service": "DukaanVoice FastAPI Backend"}` |
| **Backend Startup** | Root Endpoint (`/`) | **PASSED** | Responded `200 OK`: `{"message": "Welcome to DukaanVoice API", "status": "running", "version": "1.0.0"}` |
| **Dependencies** | Python Import Tree | **PASSED** | All backend modules (`main`, `database`, `models`, `schemas`, `pending_manager`, `voice_parser`, `routes.*`) imported without error. |
| **Dependencies** | Python Requirements File | **FAILED** | Missing `backend/requirements.txt` and root `requirements.txt`. |
| **Database** | Database Integrity & Retention | **PASSED** | `backend/dukaanvoice.db` (28 KB) verified intact. Exactly 1 customer (`Ramesh`, `9876543210`) and 1 transaction (`CREDIT`, ₹430). Zero data loss or reset. |
| **Frontend Code** | Code Quality & Linting | **PASSED** | `npm run lint` (`eslint .`) completed with exit code 0 across all JSX and JS files. |
| **Frontend Build** | `npm run build` (`vite build`) | **FAILED** | Failed in sandbox with `EPERM` on `.vite-temp` file creation (Windows sandbox restriction). Pre-existing build artifacts verified in `frontend/dist`. |
| **API Routes** | Customers API (`/api/customers/`) | **PASSED** | Routes defined for CRUD, telephone normalization (+91), uniqueness constraint, and balance summary (`/api/customers/summary`). |
| **API Routes** | Transactions API (`/api/transactions/`) | **PASSED** | Routes defined for CREDIT/PAYMENT creation, balance calculation, recent transactions, and dashboard statistics (`/api/transactions/stats`). |
| **Voice Processing**| Rule-based Voice Parser | **PASSED** | `voice_parser.py` maps Kannada/Kanglish keywords (`ge`, `udhaar`, `kodidare`, `eshtu`, `howdu`, `illa`, `maadu`) to structured intents. |
| **Voice Safety** | 2-Step Pending Confirmation | **PASSED** | `pending_manager.py` holds unconfirmed transactions in memory. Ledger database is only committed upon confirmation (`Howdu`). |
| **Voice Safety** | Amount Correction Flow | **PASSED** | State-aware parsing allows phrases like `"No, 430 maadu"` to modify pending amount without writing to DB. |
| **Voice Safety** | Cancellation Flow | **PASSED** | Phrases like `"Illa"` cancel pending transactions immediately without any database write. |
| **Voice Safety** | Idempotent Confirmations | **PASSED** | Re-confirming a pending transaction returns the existing transaction ID rather than duplicating records. |
| **Gnani AI** | Gnani Prisma v3.0 (STT) | **FAILED** | Not implemented. No API client, credentials, or WebSocket integration exists. |
| **Gnani AI** | Gnani Timbre v3.0 (TTS) | **FAILED** | Not implemented. No API client, credentials, or audio playback endpoint exists. |
| **Test Suite** | Existing Tests (`test_app.py`) | **FAILED (Safety)** | `test_app.py` has an autouse fixture that deletes transactions and customers where `id > 1` from the live database. Cannot be run safely against production DB. |
| **Repository** | Git Configuration & Hygiene | **FAILED** | Missing root `.gitignore`, `README.md`, `.env.example`. Virtual environments (`venv`, `backend/venv`) and caches are currently in the directory tree. |

---

## 3. Detailed Technical Findings

### 3.1 Architecture Overview

```
                      +---------------------------------------+
                      |       React 19 + Vite Frontend        |
                      |  - VoiceAssistant (Chat + Controls)   |
                      |  - DashboardView (Stats + Recents)   |
                      |  - CustomersView (Balances + Search)  |
                      |  - LedgerView (Transaction History)   |
                      +-------------------+-------------------+
                                          |
                        Browser Web Speech API (Fallback)
                        [Gnani Prisma/Timbre: NOT CONNECTED]
                                          |
                                HTTP / WebSocket (WS)
                                          |
                      +-------------------v-------------------+
                      |         FastAPI Backend               |
                      |  - /health & /                        |
                      |  - /api/customers                     |
                      |  - /api/transactions                  |
                      |  - /api/voice/process, confirm, etc.  |
                      +---------+-------------------+---------+
                                |                   |
                      In-Memory Pending Manager     |
                      - Thread-safe Lock            |
                      - Audit Trail                 |
                      - Idempotency Cache           |
                                                    | SQLAlchemy 2.0
                                          +---------v---------+
                                          | SQLite Database   |
                                          | (dukaanvoice.db)  |
                                          | - customers       |
                                          | - transactions    |
                                          +-------------------+
```

### 3.2 Database Status
- **Location:** `backend/dukaanvoice.db` (28,672 bytes)
- **Engine:** SQLite 3 via SQLAlchemy 2.1.8
- **Integrity:** Verified healthy, no corruption.
- **Records Retained:**
  - `customers`: 1 record
    - `id`: 1
    - `name`: `Ramesh`
    - `phone`: `9876543210`
    - `created_at`: `2026-11-11 20:11:31.463866`
  - `transactions`: 1 record
    - `id`: 1
    - `customer_id`: 1
    - `transaction_type`: `CREDIT`
    - `amount`: `430`
    - `description`: `Voice demo - credit purchase`
    - `created_at`: `2026-11-11 20:19:00.954646`
- **Computed Balance for Ramesh:** ₹430 credit, ₹0 payments -> **₹430 outstanding balance**.

### 3.3 Gnani Integration Audit (Challenge Gap)
1. **Current Provider:** `frontend/src/services/speechService.js` explicitly returns:
   - `providerName`: `'Browser Web Speech API (Fallback)'`
   - `isGnaniActive`: `false`
   - `gnaniStatusNote`: `'Gnani Prisma v3.0 & Timbre v3.0 credentials are not configured in environment; active fallback is Web Speech API.'`
2. **Missing Components:**
   - No backend or frontend proxy for Gnani Prisma ASR.
   - No backend or frontend proxy for Gnani Timbre TTS.
   - No Gnani API key, Access Key, or Token defined in `.env` files.
   - No streaming audio capture (e.g. PCM / Opus MediaRecorder or AudioWorklet) for sending voice data to Gnani WebSocket/REST endpoints.

### 3.4 Security & Environmental Concerns
1. **Hardcoded Ports & CORS:**
   - `backend/main.py` explicitly allows origins: `http://localhost:5173`, `http://127.0.0.1:5173`, `http://localhost:3000`, `http://127.0.0.1:3000`, `http://localhost:4173`, `http://127.0.0.1:4173`.
2. **Unsafe Pytest Fixture:**
   - `backend/test_app.py` lines 14-22:
     ```python
     @pytest.fixture(autouse=True)
     def preserve_seed_data():
         yield
         db = SessionLocal()
         db.query(Transaction).filter(Transaction.id > 1).delete()
         db.query(Customer).filter(Customer.id > 1).delete()
         db.commit()
         db.close()
     ```
     *Impact:* Running `pytest` directly deletes all user records with `id > 1` from the live database file. Tests must be reconfigured to target an isolated test database.
3. **In-Memory Pending State:**
   - `backend/pending_manager.py` stores pending transactions in a Python dictionary. If the backend process restarts during an active voice session, the pending transaction is discarded.

---

## 4. Exact Files Requiring Changes

| File | Issue / Required Modification |
| :--- | :--- |
| `backend/requirements.txt` | **MISSING:** Must be created containing exact pinned dependencies (`fastapi`, `uvicorn`, `sqlalchemy`, `pydantic`, `python-dotenv`, `httpx`, `pytest`, `websockets`, `watchfiles`). |
| `.gitignore` (Root) | **MISSING:** Must be created to ignore `venv/`, `backend/venv/`, `node_modules/`, `dist/`, `*.pyc`, `__pycache__/`, `.pytest_cache/`, `.env`. |
| `backend/.env.example` | **MISSING:** Must be created documenting required backend environment variables (`PORT`, `HOST`, `DATABASE_URL`, and Gnani API keys). |
| `frontend/.env.example` | **MISSING:** Must be created documenting `VITE_API_BASE_URL` and `VITE_WS_BASE_URL`. |
| `README.md` (Root) | **MISSING:** Must be created documenting project setup, architecture, voice commands, and Gnani integration guide. |
| `backend/test_app.py` | **UNSAFE TEST FIXTURE:** Must isolate tests to an in-memory SQLite database (`sqlite:///:memory:`) so testing never alters `dukaanvoice.db`. |
| `backend/speech_provider.py` *(New)* | **NEW MODULE NEEDED:** Backend service for Gnani Prisma v3.0 (ASR) and Timbre v3.0 (TTS) API communication. |
| `frontend/src/services/speechService.js` | **GNANI ADAPTER:** Connect speech service to the Gnani backend integration while retaining Web Speech API fallback. |

---

## 5. Recommended Implementation Roadmap (Phase 2 & Beyond)

1. **Step 1: Safe Repository Hygiene (No Major Code Changes)**
   - Add `.gitignore` to prevent committing `venv/`, `backend/venv/`, `dist/`, and cache directories.
   - Generate `backend/requirements.txt` from current virtual environment freeze.
   - Create root `README.md` and `.env.example` files.
   - Fix `backend/test_app.py` to use a dedicated test database fixture.

2. **Step 2: Gnani API Integration (BolBharat Challenge Core)**
   - Obtain Gnani Prisma (ASR) and Timbre (TTS) API endpoint specifications and credentials.
   - Implement backend Gnani client (`backend/speech_provider.py`) with streaming audio support.
   - Connect frontend audio recorder to stream audio to Gnani ASR.
   - Connect synthesized speech audio returned from Gnani TTS to the frontend playback engine.
   - Maintain seamless automatic fallback to Browser Web Speech API if Gnani credentials are missing or network fails.

3. **Step 3: Verification & Packaging**
   - Run full end-to-end verification against the isolated test suite.
   - Verify zero regression on existing customer (`Ramesh`) and transaction records.
   - Package clean submission repository ready for GitHub.

---
*Report generated in compliance with Phase 1 constraints: No database reset, zero data loss, no dummy data introduced, safe backup retained.*
