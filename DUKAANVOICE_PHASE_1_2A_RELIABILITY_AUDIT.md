# DukaanVoice – Phase 1.2A: Application Reliability Audit
**Document:** Application Reliability & Transaction Durability Audit  
**Date:** November 19, 2026  
**Status:** Investigation Complete (Read-Only Audit — No Code or Database Changes Made)  

---

## 1. Files Inspected

The following files across the DukaanVoice codebase were inspected in detail for this audit:

| Subsystem | File Path | Scope of Inspection |
| :--- | :--- | :--- |
| **Pending Management** | [backend/pending_manager.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/pending_manager.py) | In-memory storage, thread locking, lifecycle methods (`create`, `correct`, `confirm`, `cancel`), audit logging, idempotency cache. |
| **Voice Processing** | [backend/voice_parser.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/voice_parser.py) | Rule-based intent parser, confirmation/cancellation token matching, correction detection, amount and customer name extraction. |
| **API Endpoints** | [backend/routes/voice.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/routes/voice.py) | Voice command orchestration (`/process`, `/confirm`, `/cancel`, `/correct`, `/pending`, `/ws`), customer resolution, balance calculation. |
| **Transaction Routes** | [backend/routes/transactions.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/routes/transactions.py) | Direct transaction creation, dashboard metrics, customer balance queries. |
| **Customer Routes** | [backend/routes/customers.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/routes/customers.py) | Customer CRUD, phone normalization, unique phone constraints. |
| **Database Models** | [backend/models.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/models.py) | SQLAlchemy model definitions (`Customer`, `Transaction`), database check constraints, cascade definitions. |
| **Database Engine** | [backend/database.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/database.py) | Engine initialization, sessionmaker setup, `get_db` dependency provider. |
| **Data Schemas** | [backend/schemas.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/schemas.py) | Pydantic request/response models for voice, transactions, customers, and pending state. |
| **Frontend Voice Client**| [frontend/src/components/VoiceAssistant.jsx](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/components/VoiceAssistant.jsx) | Client-side session ID generation, pending state tracking, confirmation/cancellation buttons, voice feedback loop. |
| **Frontend API Service** | [frontend/src/services/api.js](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/src/services/api.js) | Fetch client wrappers for voice and transaction endpoints. |

---

## 2. Current Architecture & Transaction Lifecycle

### 2.1 Component Interaction Diagram

```
[Kirana Shopkeeper]
        |
        v Voice Utterance ("Ramesh ge 430 udhaar haaku")
[React 19 Frontend (VoiceAssistant.jsx)]
        |
        |  POST /api/voice/process { transcript, session_id }
        v
[FastAPI Router (routes/voice.py)]
        |
        +---> [voice_parser.py] (Rule NLP -> Intent: ADD_CREDIT, Customer: Ramesh, Amount: 430)
        |
        +---> [Customer Lookup (models.py)] (Matches "Ramesh" -> Customer ID: 1)
        |
        v
[In-Memory Pending Manager (pending_manager.py)]
   - Generates pending_id (UUIDv4)
   - Stores in self._transactions: dict[str, dict] (RAM ONLY)
   - Stores in self._session_active: dict[str, str] (RAM ONLY)
   - Status: "PENDING"
   - [DATABASE IS NOT TOUCHED]
        |
        v Returns { intent: PENDING_CONFIRMATION, pending_id }
[Frontend UI Prompt: "Ramesh ge ₹430 credit add maadbekaa?"]
        |
        v Shopkeeper: "Howdu" / Clicks [Confirm]
[POST /api/voice/confirm { pending_id, session_id }]
        |
        v
[pending_manager.confirm_pending]
   - Validates status == "PENDING"
   - Writes to SQLite transactions table
   - Updates status to "CONFIRMED" in RAM
   - Returns confirmed Transaction #ID
```

### 2.2 Detailed Lifecycle States

1. **Creation:**
   - Initiated via `/api/voice/process` when parser classifies intent as `ADD_CREDIT` or `ADD_PAYMENT`.
   - The route handler validates that the customer exists in the database.
   - `pending_manager.create_pending()` is invoked under a Python thread lock (`self._lock`).
   - Generates a UUIDv4 `pending_id`, initial audit log entry, and stores the state strictly inside `self._transactions` and `self._session_active` in memory.
   - **Persistence:** **None**. Zero disk writes occur.

2. **Storage:**
   - Stored in process heap memory as a standard Python dictionary:
     ```python
     self._transactions[pending_id] = {
         "pending_id": pending_id,
         "session_id": session_id,
         "customer_id": customer_id,
         "customer_name": customer_name,
         "amount": amount,
         "transaction_type": transaction_type,
         "status": "PENDING",
         "audit_trail": [...],
         "created_at": now_iso,
         "updated_at": now_iso,
         "confirmed_transaction_id": None
     }
     ```
   - No SQLite table, no WAL log, no Redis cache, and no local file backing.

3. **Retrieval:**
   - Stored records are retrieved by `pending_id` (`get_pending`) or by `session_id` (`get_active_for_session`).
   - Polling endpoint `GET /api/voice/pending?session_id=...` inspects active status.

4. **Correction:**
   - Supported via voice ("No, 430 maadu") or REST endpoint `POST /api/voice/correct`.
   - Updates `amount`, `customer_id`, or `transaction_type` in the in-memory dictionary.
   - Appends a `"CORRECTED"` entry to the in-memory `audit_trail`.
   - Database remains untouched.

5. **Confirmation:**
   - Initiated via voice ("Howdu") or REST endpoint `POST /api/voice/confirm`.
   - Verifies `status == "PENDING"`.
   - Verifies customer still exists in SQLite via `db.get(Customer, record["customer_id"])`.
   - Creates a new `Transaction` model and calls `db.add()`, `db.commit()`, `db.refresh()`.
   - Mutates `record["status"] = "CONFIRMED"` and stores `confirmed_transaction_id = db_txn.id`.
   - Clears the session mapping `self._session_active.pop(session_id)`.

6. **Cancellation:**
   - Initiated via voice ("Illa") or REST endpoint `POST /api/voice/cancel`.
   - Sets `record["status"] = "CANCELLED"`.
   - Clears `self._session_active`.
   - Database is untouched.

7. **Expiration (TTL):**
   - **NOT IMPLEMENTED.** There is no time-to-live (TTL), expiration timestamp, or cleanup worker. Unconfirmed transactions remain in process memory indefinitely until the application terminates.

---

## 3. Identified Reliability Risks (Ranked by Severity)

| Severity | Risk Category | Vulnerability Summary | Impact |
| :---: | :--- | :--- | :--- |
| **CRITICAL** | **Process Durability** | Pending transactions reside solely in Python process memory (`dict`). | Process crash, deployment, or OS restart permanently erases all active pending transactions, causing shopkeeper confirmation failures. |
| **CRITICAL** | **Idempotency Volatility** | Idempotency records are kept in memory and never written to SQLite. | If the backend restarts after confirmation, a duplicate confirmation request from the frontend cannot be detected and may create duplicate ledger rows or return 400. |
| **HIGH** | **Split-Brain on Commit Crash** | Database `db.commit()` and in-memory status update are not atomic. | If the backend crashes immediately after `db.commit()` before updating RAM or returning the HTTP response, the customer is billed, but the user receives an error and may re-enter the charge. |
| **HIGH** | **Multi-Worker Inconsistency** | Concurrency control relies on a single-process `threading.Lock()`. | Running `uvicorn main:app --workers 4` partitions memory across 4 processes. A confirmation routed to Worker B cannot find a pending transaction created by Worker A. |
| **HIGH** | **SQLite Foreign Key Disabled** | SQLite engine does not enforce `PRAGMA foreign_keys = ON;`. | Direct SQL inserts or session errors can link transactions to non-existent customer IDs without database-level constraint enforcement. |
| **MEDIUM** | **Session Leak & Unbounded Growth** | No expiration or eviction strategy for stale pending transactions. | Long-running servers will experience unbounded memory growth as abandoned pending transactions accumulate in `self._transactions`. |
| **MEDIUM** | **Default Session Collision** | API defaults `session_id` to `"default"` if missing or empty. | Two simultaneous calls without explicit session IDs will overwrite each other's active pending transaction in `self._session_active["default"]`. |
| **MEDIUM** | **WebSocket Session Mismanagement** | WebSocket endpoint keeps one `SessionLocal()` open indefinitely without explicit rollback on error. | An error during a WebSocket transaction can poison the SQLAlchemy session for subsequent messages on that connection. |

---

## 4. Exact Failure Scenarios

### Scenario 1: Backend Restarts with an Active Pending Transaction
1. Shopkeeper speaks: *"Ramesh ge 500 udhaar haaku"*.
2. Backend creates pending transaction `p-101` in RAM. Frontend displays confirmation card.
3. Backend service restarts (e.g. uvicorn auto-reload, server reboot, memory kill).
4. `pending_manager._transactions` is re-initialized to `{}`.
5. Shopkeeper confirms: *"Howdu"*.
6. Frontend calls `POST /api/voice/confirm` with `pending_id: "p-101"`.
7. Backend looks up `"p-101"` in RAM -> Not found.
8. Backend returns `HTTP 400 Bad Request`: `{"detail": "Pending transaction not found"}`.
9. **Outcome:** Transaction is lost. Shopkeeper experiences confusion and workflow failure.

### Scenario 2: Backend Crashes Post-Commit Before Response
1. Shopkeeper confirms: *"Howdu"*.
2. `pending_manager.confirm_pending` calls `db.add(db_txn)` and `db.commit()`.
3. SQLite writes the new transaction row (e.g., ID 2, ₹500) to disk.
4. Server crashes or suffers power interruption before executing `record["status"] = "CONFIRMED"` or transmitting the HTTP 200 response.
5. Server restarts.
6. The frontend receives a network error (`ECONNRESET` / `Failed to fetch`).
7. The shopkeeper assumes the voice confirmation failed and repeats the action: *"Ramesh ge 500 udhaar haaku"* -> *"Howdu"*.
8. A second transaction of ₹500 is committed to SQLite (ID 3).
9. **Outcome:** Duplicate financial entry (Ramesh is billed ₹1,000 instead of ₹500).

### Scenario 3: Multiple Uvicorn Workers (Horizontal Concurrency Failure)
1. Application is launched with multi-process concurrency: `uvicorn main:app --workers 4`.
2. Worker 1 handles `POST /api/voice/process`, storing `pending_id` in Worker 1's memory space.
3. Shopkeeper clicks "Confirm". The reverse proxy / OS load balancer routes `POST /api/voice/confirm` to Worker 2.
4. Worker 2 checks its own `self._transactions` -> `pending_id` does not exist.
5. Worker 2 returns `HTTP 400`: `"Pending transaction not found"`.
6. **Outcome:** Random failure rate (~75% failure probability with 4 workers).

### Scenario 4: Concurrent Duplicate Confirmations
1. A shopkeeper on a slow mobile connection double-clicks the "Confirm" button rapidly.
2. In a single-process deployment, `self._lock` serializes the requests. The first sets status to `CONFIRMED`. The second encounters `if record["status"] == "CONFIRMED"` and returns the cached transaction.
3. **Failure under multi-worker or restart:** If the requests hit two different worker processes simultaneously, both execute `db.add()` concurrently, inserting two identical rows into the ledger database.

### Scenario 5: Default Session Collisions
1. Terminal or integration client A calls `/api/voice/process` without a `session_id`. It defaults to `"default"`.
2. Terminal or integration client B simultaneously calls `/api/voice/process` without a `session_id`. It also defaults to `"default"`.
3. Client B's call overwrites `self._session_active["default"]`.
4. Client A speaks *"Howdu"*. The backend confirms Client B's transaction under Client A's command.
5. **Outcome:** Erroneous transaction committed under the wrong user intent.

---

## 5. Existing Safeguards

The existing implementation already incorporates several thoughtful safeguards:

1. **Two-Step Voice Confirmation Gate:**
   - Unconfirmed voice commands are never committed directly to the database.
   - The ledger is only mutated when the user explicitly confirms (`CONFIRM` / `Howdu`).
2. **Thread Locking in Memory:**
   - `self._lock = threading.Lock()` protects reads and writes to `_transactions` and `_session_active` against race conditions within a single Python process.
3. **In-Memory Idempotency Cache:**
   - If confirmation is received twice within the same process lifecycle, `confirm_pending()` returns the existing transaction ID rather than creating a duplicate row.
4. **Pre-Commit Customer Re-Verification:**
   - `confirm_pending()` re-checks `db.get(Customer, record["customer_id"])` immediately prior to writing the transaction, preventing commits for deleted customers.
5. **Database-Level Check Constraints:**
   - In `backend/models.py`, `positive_transaction_amount` (`amount > 0`) and `valid_transaction_type` (`transaction_type IN ('CREDIT', 'PAYMENT')`) prevent corrupted data rows at the database level.
6. **Frontend State Clearing:**
   - `VoiceAssistant.jsx` clears local pending state upon receiving `CANCELLED` or `CONFIRMED` responses to prevent stale button clicks.

---

## 6. Missing Safeguards

1. **No Persistent Pending Storage:**
   - No database table exists to store pending transactions. They vanish upon process exit.
2. **No Persistent Idempotency Keys:**
   - The `transactions` table has no `idempotency_key`, `pending_id`, or `request_id` column with a unique constraint. Duplicate prevention cannot survive process restarts.
3. **No Atomicity Between State Transition and Ledger Write:**
   - The status change from `PENDING` to `CONFIRMED` occurs in Python RAM, whereas the transaction insert occurs in SQLite. They cannot be committed in a single unified atomic transaction.
4. **No Expiration Policy (TTL):**
   - Pending transactions never expire. If a shopkeeper starts a command at 9:00 AM and says "Howdu" at 5:00 PM, the stale morning transaction is confirmed.
5. **No SQLite Foreign Key Enforcement:**
   - `backend/database.py` does not issue `PRAGMA foreign_keys = ON;` on connection. SQLite does not automatically reject orphaned customer transactions.
6. **No Distributed Concurrency Support:**
   - Thread locks cannot synchronize across multiple worker processes or containers.
7. **No Session Cleanup Worker:**
   - Orphaned pending records remain in memory forever.

---

## 7. Recommended Architecture

To achieve enterprise-grade reliability and durability without breaking existing application behavior, the pending transaction lifecycle should be moved into SQLite (and PostgreSQL-compatible) persistent tables.

### 7.1 Architecture Diagram (Durable Model)

```
[Voice / REST Request]
          |
          v
[FastAPI Route Handler]
          |
          +---> [SQLAlchemy Session (Atomic db.begin())]
                   |
                   |---> [pending_transactions Table]
                   |     - id: UUID (Primary Key)
                   |     - session_id: String (Indexed)
                   |     - customer_id: FK -> customers.id
                   |     - amount, transaction_type, description
                   |     - status: PENDING / CONFIRMED / CANCELLED / EXPIRED
                   |     - expires_at: DateTime (NOW + 15 min TTL)
                   |     - audit_log: JSON
                   |
                   | [When Shopkeeper Confirms:]
                   |
                   |---> ATOMIC COMMIT IN SINGLE DB TRANSACTION:
                   |     1. Lock pending_transactions row (status=='PENDING')
                   |     2. Insert into transactions table:
                   |        - customer_id, amount, type, description
                   |        - idempotency_key = pending_id (UNIQUE CONSTRAINT)
                   |     3. Update pending_transactions:
                   |        - status = 'CONFIRMED'
                   |        - confirmed_transaction_id = transactions.id
                   v
[SQLite WAL Mode + Foreign Keys ON]
```

### 7.2 Database Schema Design

#### Table 1: `pending_transactions`
```sql
CREATE TABLE pending_transactions (
    id VARCHAR(36) PRIMARY KEY,                   -- UUIDv4 pending_id
    session_id VARCHAR(64) NOT NULL,              -- Client session identifier
    customer_id INTEGER NOT NULL,                 -- Target customer
    customer_name VARCHAR(100) NOT NULL,          -- Cached customer name
    customer_phone VARCHAR(20),                   -- Cached customer phone
    amount INTEGER NOT NULL,                      -- Transaction amount (> 0)
    transaction_type VARCHAR(20) NOT NULL,        -- 'CREDIT' or 'PAYMENT'
    description VARCHAR(255),                     -- Transaction notes
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',-- 'PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED'
    confirmed_transaction_id INTEGER,             -- Linked transaction ID upon confirmation
    expires_at TIMESTAMP NOT NULL,                -- Expiration timestamp (e.g., created_at + 15m)
    audit_trail JSON NOT NULL,                    -- Array of timestamped actions
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_pending_customer FOREIGN KEY (customer_id) REFERENCES customers(id),
    CONSTRAINT fk_pending_txn FOREIGN KEY (confirmed_transaction_id) REFERENCES transactions(id),
    CONSTRAINT chk_pending_amount CHECK (amount > 0),
    CONSTRAINT chk_pending_type CHECK (transaction_type IN ('CREDIT', 'PAYMENT')),
    CONSTRAINT chk_pending_status CHECK (status IN ('PENDING', 'CONFIRMED', 'CANCELLED', 'EXPIRED'))
);

CREATE INDEX idx_pending_session_active ON pending_transactions(session_id, status);
CREATE INDEX idx_pending_expires ON pending_transactions(status, expires_at);
```

#### Table 2: Updated `transactions` (with Idempotency Key)
```sql
-- Add idempotency_key to existing transactions table
ALTER TABLE transactions ADD COLUMN idempotency_key VARCHAR(36) UNIQUE;
```

### 7.3 Key Architectural Benefits
1. **Zero Data Loss on Restart:** If the backend restarts, pending transactions remain in SQLite. When the user confirms, the pending state is restored seamlessly.
2. **Guaranteed Idempotency:** The `idempotency_key UNIQUE` constraint at the database engine level physically prevents duplicate ledger entries, even across backend restarts or multi-worker race conditions.
3. **Atomic Commit Boundary:** Creating the transaction row and marking the pending row as `CONFIRMED` occur inside a single `with db.begin():` block. It either completely succeeds or completely rolls back.
4. **Multi-Worker Ready:** Database-backed locking works identically across 1 or 100 worker processes.
5. **Cross-Engine Compatibility:** Fully compatible with both SQLite (Kirana edge / desktop) and PostgreSQL (Cloud / enterprise).

---

## 8. Proposed Incremental Implementation Plan (Phase 1.2B)

To adhere strictly to safety rules, implementation should follow these disciplined steps:

1. **Step 1: Database Engine Hardening (Non-Breaking)**
   - Enable SQLite foreign key support in `backend/database.py` via SQLAlchemy event listener:
     ```python
     @event.listens_for(Engine, "connect")
     def set_sqlite_pragma(dbapi_connection, connection_record):
         cursor = dbapi_connection.cursor()
         cursor.execute("PRAGMA foreign_keys=ON")
         cursor.close()
     ```

2. **Step 2: Define Models & Migration**
   - Add `PendingTransactionModel` to `backend/models.py`.
   - Add `idempotency_key` column to `Transaction` model in `backend/models.py`.
   - Prepare a safe, non-destructive migration script that adds the new table and column without modifying existing data rows.

3. **Step 3: Database-Backed Pending Manager**
   - Refactor `backend/pending_manager.py` to use SQLAlchemy sessions instead of in-memory dictionaries.
   - Retain identical method signatures:
     - `create_pending(...)`
     - `get_pending(...)`
     - `get_active_for_session(...)`
     - `correct_pending(...)`
     - `confirm_pending(...)`
     - `cancel_pending(...)`
   - Implement automatic expiration checks (`expires_at < datetime.now()`).

4. **Step 4: Atomic Confirmation Logic**
   - Wrap confirmation in an atomic database transaction.
   - Query `pending_transactions` by ID. If already `CONFIRMED`, return the linked transaction immediately.
   - If `PENDING`, insert into `transactions` with `idempotency_key = pending_id` and update status to `CONFIRMED`.

5. **Step 5: Verification**
   - Verify zero regressions against the existing test suite.
   - Run simulated restart tests against an isolated in-memory test database.

---

## 9. Test Strategy (Using Isolated Test Database)

All validation for the new durable pending architecture must be conducted against an **isolated in-memory database (`sqlite:///:memory:`)**, completely decoupled from the live `dukaanvoice.db`.

### Planned Test Cases

| Test Case | Scenario | Expected Behavior |
| :--- | :--- | :--- |
| **`test_durable_pending_creation`** | Create pending transaction in isolated DB. | Row created in `pending_transactions` with status `PENDING`. No row in `transactions`. |
| **`test_restart_recovery_simulation`** | Simulate backend restart by instantiating a fresh `PendingManager` instance pointing to the same test DB. | Pending transaction is successfully loaded from DB; confirmation succeeds. |
| **`test_atomic_confirmation_integrity`** | Confirm pending transaction. | Exactly one `Transaction` row created. `pending_transactions` row marked `CONFIRMED`. Both have matching IDs. |
| **`test_persistent_idempotency_replay`** | Send confirmation request twice for the same `pending_id`. | Second request returns the existing transaction ID. Exactly 1 row exists in `transactions`. |
| **`test_duplicate_concurrent_confirmation`** | Simulate concurrent threads attempting confirmation on same pending ID. | Database constraint or transaction lock allows only one commit; second receives idempotent response. |
| **`test_expired_pending_rejection`** | Attempt to confirm a pending transaction whose `expires_at` has passed. | Confirmation rejected with error (`Transaction has expired`). No ledger record created. |
| **`test_foreign_key_enforcement`** | Attempt to create pending or confirmed transaction with non-existent customer ID. | Database rejects insert with `IntegrityError`. |

---

## 10. Explicit Confirmation of System Safety

In compliance with Phase 1.2A constraints:
- **No application code was modified** in `backend/` or `frontend/`.
- **No database schemas were modified**.
- **No database records were created, updated, deleted, or reset**.
- **No live database tests or E2E scripts were executed**.
- **The live database `backend/dukaanvoice.db` remains 100% unaltered**.
- Phase 1.2B implementation will **NOT** begin until this audit report is reviewed and approved.
