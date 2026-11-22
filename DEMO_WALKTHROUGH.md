# DukaanVoice — Evaluator Demonstration Walkthrough
**Voice-Powered Credit (*Udhaar*) & Payment (*Jama*) Ledger for Kirana Stores**

---

## 1. Project Introduction

Local Indian retail shopkeepers (*kirana stores*) conduct daily business on trust, offering short-term credit (*udhaar*) and collecting payments (*jama*) throughout the day. In the midst of busy store operations, manually maintaining physical paper ledgers (*khata books*) leads to forgotten entries, balance miscalculations, disputes with customers, and financial loss.

**DukaanVoice** solves this by providing a voice-first, hands-free credit ledger specifically engineered for local retail counters.

### Core Value Proposition:
- **Hands-Free Speed:** Record transactions while weighing goods, handling cash, or packing groceries.
- **Multilingual Native Interaction:** Understands natural speech in **Kannada, Kanglish, and English**.
- **Financial Safety (Mandatory 2-Step Confirmation):** Voice commands **never** write directly to the ledger. Every action is staged durably in SQLite with a 15-minute TTL, presenting an authoritative balance preview that requires explicit confirmation (`"Howdu"` / Yes) before committing.
- **Durable & Idempotent:** Pending transactions survive backend restarts; duplicate confirmations return existing records without creating duplicate ledger entries.
- **Advance & Settle Semantics:** Correctly tracks when payments exceed credit, maintaining an advance balance without confusing negative debt numbers.

### Technology Stack:
- **Frontend:** React 19, Vite 8, Modular Web Speech & HTML5 Audio Service, Responsive CSS (mobile to desktop).
- **Backend:** FastAPI, SQLAlchemy 2.0 (with SQLite foreign-key enforcement), Uvicorn ASGI server.
- **Voice AI:** Dual-provider architecture supporting **Gnani Prisma v3.0 (STT)** and **Gnani Timbre v3.0 (TTS)** with automatic, deterministic fallback to the **Browser Web Speech API** (`webkitSpeechRecognition` and `window.speechSynthesis`).
- **Database:** SQLite with WAL-compatible ACID transactions and unique idempotency keys.

---

## 2. Prerequisites & Environment Configuration

### Software Requirements:
- **Python:** 3.11+ (installed and accessible in terminal).
- **Node.js:** Node.js 18+ and npm (Node 20+ recommended).
- **Operating System:** Cross-platform (Windows, Linux, macOS).
- **Recommended Browser:** **Google Chrome** or **Microsoft Edge** (provides native Web Speech API support for offline fallback speech recognition).
- **Audio Hardware:** Built-in or external microphone and speakers/headphones.

### Environment Variable Specifications:

#### Backend Environment Variables (`backend/.env`):
Create `backend/.env` by copying `backend/.env.example`:
- `HOST`: Host IP to bind server (e.g. `127.0.0.1`).
- `PORT`: Port to bind server (e.g. `8000`).
- `DATABASE_URL`: SQLite connection URI (defaults to `sqlite:///./dukaanvoice.db`).
- `DUKAANVOICE_DB_URL`: (Optional) Overrides database location (e.g. `sqlite:///./demo.db` for isolated evaluator testing).
- `GNANI_API_KEY`: API Key for Gnani Voice AI (Vachana platform). *Note: If left empty or if Gnani services are unreachable, the system automatically runs using Browser Web Speech fallback.*
- `GNANI_STT_URL`: Gnani Prisma v3.0 endpoint (default: `https://api.vachana.ai/stt/v3`).
- `GNANI_TTS_URL`: Gnani Timbre v3.0 endpoint (default: `https://api.vachana.ai/api/v1/tts/inference`).
- `GNANI_STT_MODEL`: STT model identifier (`prisma-v3.0`).
- `GNANI_TTS_MODEL`: TTS model identifier (`timbre-v3.0`).
- `GNANI_TTS_VOICE`: Regional Indic voice persona (`Shivani`).
- `GNANI_TIMEOUT_SECONDS`: Request timeout boundary (`10.0`).

#### Frontend Environment Variables (`frontend/.env`):
Create `frontend/.env` by copying `frontend/.env.example`:
- `VITE_API_BASE_URL`: Base URL for FastAPI backend (default: `http://localhost:8000`).
- `VITE_WS_BASE_URL`: WebSocket endpoint URL (default: `ws://localhost:8000/api/voice/ws`).

---

## 3. Application Startup Instructions

To start DukaanVoice for evaluation, open two terminal windows (one for the backend, one for the frontend).

### Terminal 1: Start the Backend Server

1. Navigate to the `backend` directory:
   ```powershell
   cd backend
   ```
2. Activate the Python virtual environment:
   ```powershell
   # Windows PowerShell:
   .\venv\Scripts\Activate.ps1
   # Linux / macOS:
   # source venv/bin/activate
   ```
3. Start Uvicorn:
   ```powershell
   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```

**Expected Successful Backend Output:**
```
INFO:     Started server process [pid]
INFO:     Waiting for application startup.
INFO:dukaanvoice:Database schema verification and migrations completed successfully.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

### Terminal 2: Start the Frontend Client

1. Navigate to the `frontend` directory:
   ```powershell
   cd frontend
   ```
2. Start the Vite development server:
   ```powershell
   npm run dev
   ```

**Expected Successful Frontend Output:**
```
  VITE v8.3.8  ready in 250 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
  ➜  press h + enter to show help
```

### Verification of Application Health:
- **API Health Check:** Open `http://127.0.0.1:8000/health` in your browser. Expected response:
  ```json
  {"status":"healthy","database":"connected","service":"DukaanVoice FastAPI Backend"}
  ```
- **Interactive OpenAPI Documentation:** Available at `http://127.0.0.1:8000/docs`.
- **Client Application:** Open `http://localhost:5173` in **Google Chrome** or **Microsoft Edge**.
- **Header Status Indicators:**
  - `FastAPI Connected`: Green dot confirms active backend communication.
  - `Speech Provider Badge`: Displays active voice engine (`Gnani Voice AI` or `Browser Web Speech API (Fallback)`).

---

## 4. Step-by-Step Demonstration Scenarios

DukaanVoice supports both **real microphone speech input** and **one-click interactive Demo Chips**. If microphone access is blocked or speech recognition is unavailable in your browser, clicking the demo chips executes the exact same underlying parsing and confirmation pipeline.

---

### Scenario A: Add a Customer

*This establishes a new customer account in the ledger.*

1. Click on the **ಗ್ರಾಹಕರು / Customers** tab in the top navigation bar.
2. Click the blue **➕ ಹೊಸ ಗ್ರಾಹಕ / Add Customer** button in the header.
3. In the modal:
   - **ಹೆಸರು / Name:** Enter `Suresh`
   - **ದೂರವಾಣಿ / Phone:** Enter `9876543211`
4. Click **ಉಳಿಸಿ / Save Customer**.
5. **Expected Result:**
   - A green toast appears: `"Customer 'Suresh' added successfully!"`.
   - Suresh appears in the customer table with:
     - **ಒಟ್ಟು ಉದ್ದಾರ (Credit):** `₹ 0`
     - **ಒಟ್ಟು ಜಮಾ (Payments):** `₹ 0`
     - **ಬಾಕಿ (Balance Tag):** `ಚುಕ್ತಾ / Settled (₹0)`

---

### Scenario B: Record a Credit (*Udhaar*) Transaction

*Demonstrates natural voice credit capture, customer matching, balance preview, and 2-step confirmation.*

1. Click on the **ಧ್ವನಿ ಸಹಾಯಕ / Voice** tab.
2. Click the microphone button 🎙️ (or click the demo chip: `"Ramesh ge 340 rupees udhaar haaku."`).
3. Speak clearly:
   > **`"Ramesh ge 500 udhaar haaku"`**
4. **Parser & Matching Behavior:**
   - **Parsed Intent:** `ADD_CREDIT`
   - **Matched Customer:** `Ramesh` (Customer ID: 1)
   - **Amount:** `₹500`
   - **Transaction Type:** `CREDIT`
5. **Expected Confirmation Card (Staged Pending Transaction):**
   - The card appears in the conversation stream with status **PENDING**.
   - **Current Balance:** `₹ 430` (Existing debt)
   - **New Credit:** `+ ₹ 500`
   - **Expected Outstanding Balance:** `₹ 930`
   - **Explanation:** *"Customer will owe ₹930"* (`ಗ್ರಾಹಕರು ₹930 ಬಾಕಿ ಉಳಿಸಿಕೊಳ್ಳುತ್ತಾರೆ`).
   - *Note: At this stage, zero records have been written to the ledger.*
6. **Explicit Confirmation:**
   - Click the microphone button and speak: **`"Howdu"`** (or click the green **✓ Confirm & Commit** button).
7. **Expected Final Ledger Result:**
   - The card updates to **CONFIRMED** with Transaction ID (e.g. `Txn #2`).
   - The audio assistant announces confirmation in Kannada/English.
   - Ramesh's total outstanding balance updates authoritatively to **₹930**.

---

### Scenario C: Record a Customer Payment (*Jama*)

*Demonstrates recording cash payments that reduce customer outstanding dues.*

1. In the **Voice** tab, click the microphone button (or demo chip: `"Ramesh ge 100 kodidare."`).
2. Speak:
   > **`"Ramesh ge 200 kodidare"`** *(or Kanglish: `"Ramesh 200 bandide"`)*
3. **Parser & Matching Behavior:**
   - **Parsed Intent:** `ADD_PAYMENT`
   - **Matched Customer:** `Ramesh`
   - **Amount:** `₹200`
   - **Transaction Type:** `PAYMENT`
4. **Expected Confirmation Card:**
   - **Current Balance:** `₹ 930`
   - **Payment Received:** `- ₹ 200`
   - **Expected Outstanding Balance:** `₹ 730`
   - **Explanation:** *"Customer will owe ₹730"*.
5. **Confirmation Action:**
   - Speak: **`"Howdu"`** (or click **✓ Confirm & Commit**).
6. **Expected Final Ledger Result:**
   - Transaction committed (`PAYMENT ₹200`).
   - Outstanding balance reduced to **₹730**.

---

### Scenario D: Query Outstanding Customer Balance

*Demonstrates real-time voice inquiry without altering ledger records.*

1. In the **Voice** tab, click the microphone button (or demo chip: `"Ramesh total eshtu?"`).
2. Speak:
   > **`"Ramesh total eshtu?"`** *(or English: `"What is Ramesh balance?"`)*
3. **Parser & Matching Behavior:**
   - **Parsed Intent:** `CHECK_BALANCE`
   - **Matched Customer:** `Ramesh`
4. **Expected Audio & Visual Response:**
   - The assistant visually displays:
     > *"Ramesh balance is ₹730 (ಉದ್ದಾರ: ₹730)"*
   - Audio synthesized speech announces the balance.
   - **Zero ledger writes occur.**

---

### Scenario E: Demonstrate Advance Balance / Overpayment Handling

*Demonstrates DukaanVoice's financial accounting semantics when a customer pays more than their outstanding dues.*

1. In the **Voice** tab, speak:
   > **`"Ramesh ge 1000 kodidare"`**
2. **Parser & Preview Behavior:**
   - Current Debt: `₹ 730`
   - Payment Received: `₹ 1000`
   - Expected Net Balance: `- ₹ 270`
   - **DukaanVoice Advance Logic:** Instead of displaying confusing negative debt (`-₹270`), the preview explicitly explains:
     - **Expected Outstanding:** `₹ 0`
     - **Expected Advance (ಮುಂಗಡ):** `₹ 270`
     - **Explanation:** *"Customer will have an advance balance of ₹270"* (`ಗ್ರಾಹಕರ ಖಾತೆಯಲ್ಲಿ ₹270 ಮುಂಗಡ (ಜಮಾ) ಇರುತ್ತದೆ`).
3. **Confirm the Transaction:**
   - Speak **`"Howdu"`** or click **✓ Confirm & Commit**.
4. **Verification in Customers Tab:**
   - Navigate to **Customers** tab:
   - Ramesh's balance tag turns purple: **`ಮುಂಗಡ / Advance: ₹ 270`**.
   - Navigate to **Dashboard** tab:
   - Net Outstanding card displays: **`₹ 0 (Adv ₹270)`** with note: *"Store holds customer advance deposits"*.

---

### Scenario F: Demonstrate Kannada Unicode Script & Cross-Script Matching

*Demonstrates the parser and customer matcher's ability to process native Kannada script.*

1. In the text input box of the **Voice** tab, paste or type the native Kannada script command:
   > **`ರಮೇಶ್ ಗೆ 500 ರೂಪಾಯಿ ಉದ್ದಾರ ಹಾಕು`**
2. Press **Enter** or click **Send**.
3. **Internal Processing:**
   - `customer_matcher.py` identifies Kannada Unicode characters (`U+0C80 - U+0CFF`).
   - Transliterates `"ರಮೇಶ್"` to canonical phonetic representation `"rames"`.
   - Authoritatively matches with the existing database Latin record `"Ramesh"`.
   - `voice_parser.py` extracts amount `500` and intent `ADD_CREDIT`.
4. **Result:**
   - Generates the confirmation preview card for customer **Ramesh** for ₹500 without error.

---

### Scenario G: Demonstrate Voice Correction and Cancellation Safety

*Proves that shopkeepers can safely alter amounts or cancel pending transactions before commitment.*

1. In the **Voice** tab, speak:
   > **`"Ramesh ge 500 udhaar haaku"`**
2. When the Confirmation Card appears for ₹500, speak:
   > **`"No, 430 maadu"`** *(or click the chip: `"No, 430 maadu."`)*
3. **Correction Observed:**
   - The card immediately updates the amount from ₹500 to **₹430**.
   - The expected balance calculation authoritatively updates.
   - The internal audit trail records the correction timestamp.
4. **Cancel the Transaction:**
   - Speak: **`"Illa"`** *(or English: `"Cancel"`, or click the red **✕ Cancel** button)*.
5. **Expected Cancellation Result:**
   - The card changes to **CANCELLED** with note: *"Cancelled by shopkeeper. No ledger record was created."*.
   - Check the **Ledger** tab: **Zero rows** were added. The balance remains unchanged.

---

### Scenario H: Demonstrate Duplicate Confirmation Protection (Idempotency)

*Proves that duplicate voice confirmations, network replays, or double-clicks cannot produce duplicate ledger entries.*

1. In the **Voice** tab, speak:
   > **`"Ramesh ge 100 kodidare"`**
2. The Confirmation Card appears with pending ID (e.g. `b4f8...`).
3. Click the **✓ Confirm & Commit** button.
4. If a network lag occurs or if the shopkeeper speaks `"Howdu"` again immediately:
   - The backend `PendingTransactionManager` intercepts the request via the database unique index on `transactions.idempotency_key`.
   - The server returns the **already committed transaction** with status HTTP 200.
   - Check the **Ledger** tab: Exactly **one** transaction row exists for this confirmation.

---

### Scenario I: Demonstrate Browser Speech Fallback (When Gnani STT is Unavailable)

*Demonstrates architectural resilience when external cloud voice APIs experience outages.*

1. Currently, the external Gnani Prisma v3.0 REST endpoint (`https://api.vachana.ai/stt/v3`) returns an upstream HTTP 500 (`TRANSCRIPTION_FAILED`).
2. **DukaanVoice's Built-in Resilient Fallback:**
   - When speaking into Google Chrome / Microsoft Edge, DukaanVoice detects provider unavailability and automatically activates the **Browser Web Speech API** (`webkitSpeechRecognition`).
   - If the browser does not have speech recognition enabled, shopkeepers can click any of the **Demo Chips** or type commands into the text bar.
   - When synthesizing audio responses, if Gnani Timbre TTS fails or is unconfigured, the system automatically routes playback to the browser's native **SpeechSynthesis** engine.
   - **Evaluator Observation:** The shopkeeper experiences zero workflow interruption regardless of cloud provider status.

---

## 5. Dashboard, Customers, and Ledger Inspection

### Dashboard View (`/dashboard`):
- **4 Core Metrics:**
  1. **ಒಟ್ಟು ಉದ್ದಾರ / Total Credit Given:** Sum of all committed credit purchases.
  2. **ಒಟ್ಟು ಜಮಾ / Total Payments Received:** Sum of all committed payments.
  3. **ನಿವ್ವಳ ಬಾಕಿ / Net Outstanding:** Total credit minus total payments. If customers have overpaid, shows `₹ 0 (Adv ₹X)`.
  4. **ಗ್ರಾಹಕರು / Active Customers:** Total count of registered customers.
- **Top Debtors List:** Ranks customers with highest outstanding balances for quick credit recovery.
- **Recent Transactions Feed:** Shows the 10 most recent transactions with real-time status.

### Customers View (`/customers`):
- **Instant Search:** Type any name (e.g. `Ram`) or phone digits to filter instantly.
- **Balance Tags:**
  - Red: `ಉದ್ದಾರ / Credit Due: ₹X` (Customer owes money).
  - Purple: `ಮುಂಗಡ / Advance: ₹X` (Customer deposited advance money).
  - Green: `ಚುಕ್ತಾ / Settled (₹0)` (Account clean).
- **Customer Statement Modal:** Click any customer row to view their complete individual transaction history and balance summary.

### Ledger View (`/ledger`):
- **Chronological Audit Trail:** Every committed transaction recorded with SQLite ID, date/time, customer name, transaction badge, amount, and description.
- **Filter Tabs:** Toggle between `All`, `Credit (ಉದ್ದಾರ)`, and `Payment (ಜಮಾ)`.
- **Filtered Totals Strip:** Displays immediate sub-totals for whatever filter or search term is applied.

---

## 6. Troubleshooting & Common Questions

| Issue Encountered | Likely Cause | Resolution / Verified Workaround |
| :--- | :--- | :--- |
| **Microphone Permission Denied** | Browser blocked mic access for `localhost`. | Click the camera/microphone icon in the browser address bar, set to **Allow**, and refresh the page. |
| **"Speech recognition not supported"** | Non-Chromium browser (e.g. Firefox) without Web Speech API. | Use **Google Chrome** or **Microsoft Edge**, or click the interactive **Demo Chips** / text input. |
| **Audio Playback Blocked** | Browser autoplay policy blocked audio before user gesture. | Click anywhere on the application UI (e.g. the Volume icon 🔊 or a button) to grant audio playback permission. |
| **Backend Offline / Red Status Pill** | Uvicorn server is not running on port 8000. | Check Terminal 1. Ensure `uvicorn main:app --port 8000` is active and healthy. |
| **Stale Balance Preview Error (409)** | Another user or tab committed a transaction for this customer while the preview was open. | DukaanVoice prevents race conditions. Click the updated preview card to review the new balance and confirm safely. |
| **Port 8000 or 5173 Already in Use** | Previous dev process still running. | Kill existing process: `Stop-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess -Force` and restart. |

---

## 7. Demonstration Data Safety & Isolation

DukaanVoice strictly enforces data safety to protect existing records:

### Safety Boundaries:
- **Baseline Live Database:** The primary database (`backend/dukaanvoice.db`) contains baseline evaluation records (Customer `Ramesh` with initial credit `₹430`).
- **Read-Only Inquiries:** Balance questions (`"Ramesh total eshtu?"`) and cancelled transactions **never write to the database**.
- **Committed Transactions:** Only clicking **✓ Confirm & Commit** or speaking `"Howdu"` writes a row to SQLite.

### Running a Fresh, Disposable Demonstration:
If an evaluator wishes to start from an empty ledger without touching `backend/dukaanvoice.db`:

1. In Terminal 1, set the environment variable `DUKAANVOICE_DB_URL` before starting Uvicorn:
   ```powershell
   # Windows PowerShell:
   $env:DUKAANVOICE_DB_URL="sqlite:///./demo.db"
   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```
2. On startup, FastAPI's `lifespan` handler will automatically create a brand-new, clean database `demo.db` with all tables and indices.
3. When finished, delete `demo.db` with zero risk to the original project database.
4. **Never execute commands that delete or overwrite `backend/dukaanvoice.db`.**

---

## 8. Evaluator Assessment Checklist

Use this checklist during final review to verify project capabilities:

- [ ] **Startup & Health:** Backend and frontend start cleanly; health check returns HTTP 200.
- [ ] **Dual-Provider Transparency:** Header pill accurately reflects active speech provider and fallback status.
- [ ] **Multilingual Voice Recognition:** Successfully parses Kannada, Kanglish, and English voice intents.
- [ ] **Cross-Script Customer Matching:** Spoken or typed Kannada name (`ರಮೇಶ್`) authoritatively resolves to Latin database record (`Ramesh`).
- [ ] **Two-Step Confirmation:** Credit and payment commands generate an in-memory/SQLite pending card before any ledger write.
- [ ] **Authoritative Balance Preview:** Shows current balance, addition/subtraction, and expected net balance with bilingual explanations.
- [ ] **Voice Correction:** Can correct amount (`"No, 430 maadu"`) dynamically before confirmation.
- [ ] **Cancellation Safety:** Saying `"Illa"` discards pending transaction with zero ledger writes.
- [ ] **Accounting Accuracy:** Overpayment correctly creates an advance balance (`ಮುಂಗಡ`) rather than negative debt confusion.
- [ ] **Duplicate Confirmation Protection:** Replay of confirmation returns existing transaction; no duplicate rows created.
- [ ] **Instant UI Synchronization:** Committed transactions immediately update metrics across Voice, Dashboard, Customers, and Ledger tabs.
- [ ] **Clean Code & Test Coverage:** Passes 81 backend tests, 39 frontend tests, 5 lifespan checks, and 0 lint warnings.
