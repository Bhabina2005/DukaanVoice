# DukaanVoice — Phase 1.6 Task 1: PostgreSQL & Cloud Deployment Compatibility Audit
**Technical Readiness Assessment for Neon PostgreSQL, Render Backend, and Vercel Frontend**

**Date:** November 23, 2026  
**Audit Scope:** Read-Only Technical Compatibility Assessment  
**Execution Boundary:** Assessment only. Zero source modifications, zero dependency changes, zero database mutations, zero cloud provisioning.  
**Live SQLite Database SHA-256 (Baseline):** `3761249911DD017076A1E369220825AA055811C95E30E010B73CC2F4810043CC` (Strictly Preserved)  
**Read-Only Logical Baseline Records:**
- Customers: Exactly 1 (`Ramesh`, Phone: `9876543210`)
- Transactions: Exactly 1 (`CREDIT ₹430`, Description: `Voice demo - credit purchase`, Idempotency Key: `None`)
- Pending Transactions: Exactly 0 (`[]`)
- Net Balance: ₹430 Credit Due

---

## 1. Executive Summary

Phase 1.6 Task 1 conducted a comprehensive, read-only technical audit of DukaanVoice to evaluate its architectural and code-level readiness for migrating from local SQLite to PostgreSQL and deploying to cloud infrastructure (**Frontend: Vercel Hobby, Backend: Render Web Service, Database: Neon Serverless PostgreSQL**).

### High-Level Verdict: **CONDITIONAL GO**

The core accounting logic, relational data model, multilingual NLP, and two-step confirmation safeguards are **fully compatible with PostgreSQL**. However, successful cloud deployment requires resolving specific configuration blockers:
1. **Missing PostgreSQL Driver:** `backend/requirements.txt` lacks `psycopg2-binary` or `psycopg`.
2. **SQLite-Specific Engine Argument:** `backend/database.py` passes `connect_args={"check_same_thread": False}`, which is invalid for PostgreSQL drivers.
3. **Hardcoded CORS Origins:** `backend/main.py` restricts origins strictly to `localhost` and `127.0.0.1`, which will block all cross-origin requests from Vercel (`https://*.vercel.app`).
4. **Hardcoded Host Binding:** Startup scripts assume `127.0.0.1`, whereas Render requires binding to `0.0.0.0` and listening on the dynamic `$PORT` environment variable.
5. **Connection Pool Resilience for Serverless DB:** Neon compute endpoints suspend after inactivity; SQLAlchemy requires `pool_pre_ping=True` and connection recycling to handle waking databases cleanly.

---

## 2. Current Architecture & Cloud Target Topology

```
CURRENT LOCAL ARCHITECTURE:
+-------------------------------+        HTTP REST (Port 5173 -> 8000)        +-------------------------------+
|   React 19 + Vite Frontend    | -----------------------------------------> |        FastAPI Backend        |
|  - Host: 127.0.0.1:5173       |                                            |  - Host: 127.0.0.1:8000       |
|  - Web Speech Fallback        | <----------------------------------------- |  - Single-Process Uvicorn     |
+-------------------------------+                                            +---------------+---------------+
                                                                                             | SQLAlchemy 2.0
                                                                                             v (connect_args)
                                                                             +---------------+---------------+
                                                                             |     Local SQLite Database     |
                                                                             |     (dukaanvoice.db)          |
                                                                             +-------------------------------+

TARGET CLOUD DEPLOYMENT TOPOLOGY:
+-------------------------------+                                            +-------------------------------+
|         Vercel Hobby          |        HTTPS / WSS (Cross-Origin)          |       Render Web Service      |
|  - React 19 Production SPA    | -----------------------------------------> |  - FastAPI on Python 3.11/3.12|
|  - Automatic SSL/TLS          |                                            |  - Host: 0.0.0.0, Port: $PORT |
|  - Domain: *.vercel.app       | <----------------------------------------- |  - Dynamic CORS via Env       |
+-------------------------------+                                            +---------------+---------------+
                                                                                             | SQLAlchemy 2.0
                                                                                             | (psycopg2-binary + SSL)
                                                                                             v (pool_pre_ping=True)
                                                                             +---------------+---------------+
                                                                             |     Neon PostgreSQL (Cloud)   |
                                                                             |  - Serverless Compute         |
                                                                             |  - PgBouncer Pooled (Port 6543)|
                                                                             +-------------------------------+
```

---

## 3. SQLite-to-PostgreSQL Compatibility Findings

Each finding is evaluated against actual source code and classified according to the required readiness scale:

| Area | Component / File | Current Implementation | PostgreSQL Compatibility Finding | Status | Verification Tier |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **DB Driver** | [backend/requirements.txt](backend/requirements.txt) | `SQLAlchemy==2.1.8`, no DBAPI driver | Missing PostgreSQL driver. SQLAlchemy cannot connect to PostgreSQL without `psycopg2-binary` or `psycopg`. | **BLOCKED** | **SOURCE-CODE VERIFIED** |
| **Engine Args** | [backend/database.py#L22-L25](backend/database.py#L22-L25) | `connect_args={"check_same_thread": False}` | `check_same_thread` is an SQLite-only argument. Passing it to `psycopg2` raises `TypeError`. Must be conditional on dialect. | **READY WITH CHANGES** | **SOURCE-CODE VERIFIED** |
| **URL Scheme** | [backend/database.py#L8-L11](backend/database.py#L8-L11) | Reads `DUKAANVOICE_DB_URL` | Neon URLs often start with `postgres://`. SQLAlchemy 1.4+ requires `postgresql://` or `postgresql+psycopg2://`. Needs normalization. | **READY WITH CHANGES** | **SOURCE-CODE VERIFIED** |
| **Pragma Listener** | [backend/database.py#L14-L20](backend/database.py#L14-L20) | `set_sqlite_pragma` checks `type(dbapi_connection).__module__.startswith("sqlite3")` | Cross-compatible guard already present. It safely skips non-SQLite connections without error. | **READY** | **SOURCE-CODE VERIFIED** |
| **Primary Keys** | [backend/models.py](backend/models.py) | `Integer, primary_key=True` on `customers` & `transactions` | In PostgreSQL, SQLAlchemy maps `Integer, primary_key=True` to `SERIAL` or `IDENTITY` sequence automatically. | **READY** | **SOURCE-CODE VERIFIED** |
| **UUID Keys** | [backend/models.py#L90](backend/models.py#L90) | `id: Mapped[str] = mapped_column(String(36), primary_key=True)` | Storing UUIDv4 as `VARCHAR(36)` is 100% portable across SQLite and PostgreSQL. No type coercion required. | **READY** | **SOURCE-CODE VERIFIED** |
| **Check Constraints**| [backend/models.py#L40-L45](backend/models.py#L40-L45) | `amount > 0`, `transaction_type IN ('CREDIT', 'PAYMENT')` | PostgreSQL supports SQL check constraints natively. Enforced identically. | **READY** | **SOURCE-CODE VERIFIED** |
| **Unique Indexes** | [backend/models.py#L61-L63](backend/models.py#L61-L63) | `idempotency_key: String(64), unique=True, nullable=True` | PostgreSQL handles unique nullable indexes cleanly (allows multiple NULLs, enforces uniqueness on non-nulls). | **READY** | **SOURCE-CODE VERIFIED** |
| **JSON Field** | [backend/models.py#L107-L109](backend/models.py#L107-L109) | `audit_trail: Mapped[list] = mapped_column(JSON)` | Supported natively. In PostgreSQL, SQLAlchemy maps `JSON` to native `json` type. Fully serializable. | **READY** | **SOURCE-CODE VERIFIED** |
| **Case-Insensitive Match** | [backend/routes/customers.py#L75](backend/routes/customers.py#L75) | `Customer.name.ilike(term)` | In PostgreSQL, `ilike` is a native, highly optimized SQL operator. | **READY** | **SOURCE-CODE VERIFIED** |
| **Aggregations** | [backend/routes/transactions.py#L61](backend/routes/transactions.py#L61) | `func.coalesce(func.sum(Transaction.amount), 0)` | Supported identically in PostgreSQL. Returns integer/numeric safely. | **READY** | **SOURCE-CODE VERIFIED** |
| **Date/Time Handling** | [backend/models.py](backend/models.py) | `DateTime, default=datetime.now` | In local SQLite, timestamps are naive local time. In distributed cloud hosting, `server_default=func.now()` or UTC timestamps (`datetime.utcnow`) are recommended to avoid host timezone drift. | **READY WITH CHANGES** | **SOURCE-CODE VERIFIED** |

---

## 4. SQLAlchemy and Migration Readiness

### Migration Engine Analysis ([backend/database.py#L46-L70](backend/database.py#L46-L70)):
```python
def run_migrations(bind_engine=None):
    target_engine = bind_engine or engine
    inspector = inspect(target_engine)
    table_names = inspector.get_table_names()
    # 1. Update existing transactions table with idempotency_key if missing
    if "transactions" in table_names:
        columns = [c["name"] for c in inspector.get_columns("transactions")]
        if "idempotency_key" not in columns:
            with target_engine.begin() as conn:
                conn.execute(text("ALTER TABLE transactions ADD COLUMN idempotency_key VARCHAR(64)"))
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_idempotency_key ON transactions(idempotency_key)"))
    # 2. Create pending_transactions and new tables
    Base.metadata.create_all(bind=target_engine)
```

### Readiness Findings:
1. **DDL Portability:**
   - `inspector.get_table_names()` and `inspector.get_columns()` are standard SQLAlchemy inspection primitives that function identically on PostgreSQL.
   - `ALTER TABLE transactions ADD COLUMN ...` and `CREATE UNIQUE INDEX IF NOT EXISTS ...` are valid syntax in PostgreSQL (>= 9.5).
   - `Base.metadata.create_all()` is dialect-agnostic and creates missing tables with appropriate PostgreSQL sequences and constraints.
2. **Startup Migration Concurrency:**
   - In [backend/main.py#L17-L35](backend/main.py#L17-L35), `run_migrations` runs inside the FastAPI ASGI `lifespan` handler.
   - In Render, if multiple worker processes or auto-scaling web instances boot simultaneously, concurrent `Base.metadata.create_all()` calls can cause transient PostgreSQL lock contention (`duplicate table` race condition).
   - **Recommended Change:** Provide an explicit environment flag `DUKAANVOICE_AUTO_MIGRATE=false` on web workers, and execute migrations as a standalone Render **Release Command** (`python -c "import database; database.init_db()"`) before new web instances receive traffic.
3. **Database Schema Versioning:**
   - The current ad-hoc migration logic only handles adding `idempotency_key` and creating missing tables. It lacks downgrade/rollback tracking.
   - **Status:** Sufficient for initial cloud deployment; Alembic migration tracking is recommended for future schema evolutions.

---

## 5. Render Backend Deployment Readiness

### Render Configuration Assessment:

| Operational Dimension | Current Implementation | Render Cloud Requirement | Adaptation Required | Status |
| :--- | :--- | :--- | :--- | :--- |
| **ASGI Server** | `uvicorn` in `requirements.txt` | Standard Uvicorn / Gunicorn+Uvicorn worker | Command: `uvicorn main:app --host 0.0.0.0 --port $PORT` | **READY WITH CHANGES** |
| **Port & Host Binding** | Hardcoded `127.0.0.1:8000` in dev scripts | Render assigns dynamic `$PORT` and routes to `0.0.0.0` | Bind host `0.0.0.0`, port from `$PORT` (default 8000 fallback). | **READY WITH CHANGES** |
| **CORS Middleware** | [backend/main.py#L48-L59](backend/main.py#L48-L59) allows `localhost:[5173,3000,4173]` | Vercel production frontend domain (`https://*.vercel.app`) | Make `allow_origins` configurable via `CORS_ORIGINS` env var (comma-separated list). | **BLOCKED** |
| **Health Check** | `GET /health` returns JSON `{"status": "healthy"}` | Render health check path (`/health`) | Set Render Health Check Path to `/health`. Zero code change required. | **READY** |
| **File System Assumptions** | SQLite local file `dukaanvoice.db` | Render web services have ephemeral disks | With Neon PostgreSQL configured, backend is completely stateless; zero local disk writes required. | **READY** |
| **Audio File Handling** | [backend/routes/voice.py](backend/routes/voice.py) processes in-memory Base64 buffers | Stateless memory buffers (10MB limit) | Audio is never written to disk; processed entirely in RAM and streamed to Gnani. Ideal for ephemeral cloud containers. | **READY** |
| **WebSocket Support** | `/api/voice/ws` implemented with `websockets==17.4` | Render supports WebSockets natively on all plans | Native support confirmed; requires handling Render's 100s idle timeout via client ping/pong. | **READY** |
| **Worker Process Concurrency**| `threading.Lock()` in `pending_manager.py` | Multi-process Uvicorn (`--workers 2+`) | In-memory `threading.Lock()` does not sync across separate OS processes. PostgreSQL unique constraint (`idempotency_key`) protects database integrity across processes, but row locking (`SELECT FOR UPDATE`) is recommended. | **READY WITH CHANGES** |

---

## 6. Vercel Frontend Deployment Readiness

### Vercel Configuration Assessment:

| Operational Dimension | Current Implementation | Vercel Cloud Requirement | Adaptation Required | Status |
| :--- | :--- | :--- | :--- | :--- |
| **Build Tooling** | Vite v8.3.8, React 19 | Vercel Native Vite Preset | Build Command: `npm run build`<br/>Output Directory: `dist` | **READY** |
| **API Base URL** | [frontend/src/services/api.js#L1-L3](frontend/src/services/api.js#L1-L3): `import.meta.env.VITE_API_BASE_URL \|\| 'http://localhost:8000'` | Render backend URL (`https://*.onrender.com`) | Configure Vercel Project Environment Variable: `VITE_API_BASE_URL=https://<your-render-backend>.onrender.com` | **READY** |
| **WebSocket URL** | [frontend/.env.example#L7](frontend/.env.example#L7): `VITE_WS_BASE_URL` | Render WebSocket URL (`wss://*.onrender.com/api/voice/ws`) | Configure Vercel Project Environment Variable: `VITE_WS_BASE_URL=wss://<your-render-backend>.onrender.com/api/voice/ws` | **READY** |
| **SPA Client Routing** | Single-page app with React state navigation | Direct URL requests must route to `index.html` | Add `vercel.json` with route rewrite: `{"rewrites": [{"source": "/(.*)", "destination": "/index.html"}]}` | **READY WITH CHANGES** |
| **Secure Context (HTTPS)**| Localhost HTTP | `getUserMedia` microphone access requires HTTPS | Vercel provides automatic HTTPS certificates (`https://*.vercel.app`), completely satisfying browser microphone security constraints. | **READY** |
| **Audio Autoplay** | Speech synthesized after user button/chip click | WebKit/Blink user gesture policy | User interaction gate already implemented in UI (click mic, demo chip, or volume toggle). | **READY** |

---

## 7. Neon PostgreSQL Readiness

### Neon Serverless PostgreSQL Analysis:

1. **Connection String Syntax & Driver:**
   - Neon connection string format:
     `postgresql://user:password@ep-xyz-123456.us-east-2.aws.neon.tech/neondb?sslmode=require`
   - Neon mandates SSL (`sslmode=require`).
   - Using `psycopg2-binary`, SQLAlchemy establishes secure TLS encryption automatically when `sslmode=require` is present in the query string.
2. **Cold-Start Resilience (`pool_pre_ping`):**
   - On Neon's free tier, compute endpoints automatically suspend after 5 minutes of inactivity. When a new query arrives, Neon wakes up within 500ms to 2.5s.
   - Without connection health checks, SQLAlchemy's pool would hand dead TCP connections to FastAPI workers, causing `psycopg2.OperationalError: server closed the connection unexpectedly`.
   - **Essential Configuration in `backend/database.py`:**
     ```python
     if not DATABASE_URL.startswith("sqlite"):
         engine = create_engine(
             DATABASE_URL,
             pool_pre_ping=True,      # Discards stale connections before query execution
             pool_recycle=300,        # Recycles connections every 5 minutes
             pool_size=5,             # Bounded pool size suited for Neon serverless
             max_overflow=10
         )
     ```
3. **Connection Pooling Modes (Direct vs PgBouncer):**
   - Neon provides two ports:
     - **Port 5432 (Direct Compute):** Standard PostgreSQL connection. Required for DDL migrations (`create_all`, `ALTER TABLE`).
     - **Port 6543 (PgBouncer Pooler):** Uses endpoint suffix `-pooler`. Optimized for high-concurrency stateless web traffic.
   - For FastAPI on Render, connecting via Neon's pooled connection string with `pool_pre_ping=True` provides optimal throughput and avoids exhausting Neon connection quotas.
4. **Data Separation:**
   - Evaluator / Demo database must be isolated from production tables using separate databases (e.g. `neondb_dev` vs `neondb_prod`) or distinct PostgreSQL schemas.

---

## 8. Security and Production Limitations

Classification of known security boundaries and required remedies:

| Security Domain | Finding / Current State | Severity | Academic Demo Readiness | Real Public Production Requirement |
| :--- | :--- | :--- | :--- | :--- |
| **Authentication** | REST and WebSocket endpoints lack shopkeeper session tokens (JWT/OAuth2). | **MEDIUM** | **ACCEPTABLE:** Single shopkeeper local/demo scenario. | **MANDATORY:** Must implement OAuth2 / JWT bearer tokens to prevent unauthorized ledger writes. |
| **Tenant Isolation** | All customers and transactions exist in a global unscoped table (`shop_id` missing). | **HIGH** | **ACCEPTABLE:** Single kirana store evaluation. | **MANDATORY:** Must add `shop_id` foreign key on all tables and scope all queries by authenticated shopkeeper. |
| **Rate Limiting** | `/api/voice/*` and `/api/transactions/*` lack request throttling. | **MEDIUM** | **ACCEPTABLE:** Mitigated by 10MB payload size limits and 1000-char TTS caps. | **MANDATORY:** Must add `slowapi` or Redis token-bucket limiter to prevent DoS or upstream API quota drainage. |
| **API Exposure** | Interactive Swagger `/docs` and `/redoc` are public by default. | **LOW** | **ACCEPTABLE:** Highly useful for evaluators inspecting schemas. | **RECOMMENDED:** Disable in production via `FastAPI(docs_url=None, redoc_url=None)`. |
| **CORS Policy** | Whitelist hardcoded to localhost. | **CRITICAL (for Cloud)** | **BLOCKER:** Vercel frontend cannot communicate with Render backend until parameterized. | Must set `allow_origins` to explicit production frontend domain (`https://*.vercel.app`). |
| **Secrets Protection** | Gnani API credentials loaded from environment; provider status redacts keys. | **INFORMATIONAL** | **VERIFIED CLEAN:** Zero secrets exposed in git, build artifacts, or endpoints. | Continue using Render encrypted environment variables. |
| **Input Validation** | Pydantic enforces `amount <= 10,000,000`, phone regex, and name lengths. | **INFORMATIONAL** | **VERIFIED CLEAN:** Rejects out-of-bounds payloads with HTTP 422. | Maintain current defensive Pydantic schema validation. |

---

## 9. Speech Provider Deployment Readiness

### Gnani Voice AI Cloud Integration Status:

1. **Current Provider Capabilities:**
   - **Gnani Timbre v3.0 (TTS):** **OPERATIONAL** (Verified via automated test suites and previous live tests with valid binary audio returned).
   - **Gnani Prisma v3.0 (STT):** **UNVERIFIED / UPSTREAM OUTAGE** (Target endpoint `https://api.vachana.ai/stt/v3` returns HTTP 500 `TRANSCRIPTION_FAILED`).
2. **Cloud Backend Proxy Behavior on Render:**
   - Render web services will execute `backend/speech_provider.py` identically to local execution:
     - Outbound HTTPS calls to `api.vachana.ai` are supported across all Render tiers.
     - Server-side timeouts are bounded by `GNANI_TIMEOUT_SECONDS=10.0`.
     - In the event of upstream Gnani 500 errors, the backend returns a structured error object without crashing.
3. **Client-Side Speech Behavior on Vercel:**
   - When deployed to Vercel with automatic HTTPS, the client's Web Speech API fallback (`webkitSpeechRecognition`) functions reliably on Google Chrome, Microsoft Edge, and Android Chrome.
   - Interactive Demo Chips (`DEMO_CHIPS`) in `VoiceAssistant.jsx` provide 100% deterministic speech simulation during live presentations if cloud voice APIs or browser microphones encounter issues.

---

## 10. Risks and Blockers Matrix

| Risk / Blocker | Category | Impact | Mitigation / Solution |
| :--- | :--- | :--- | :--- |
| **Missing `psycopg2-binary`** | Dependency | Backend will fail to start on Render if `DATABASE_URL` is PostgreSQL. | Add `psycopg2-binary>=2.9.9` to `backend/requirements.txt`. |
| **CORS Rejection on Vercel** | Network / Security | Frontend cannot fetch data or send voice commands to Render backend. | Update `backend/main.py` to read `CORS_ORIGINS` from environment. |
| **Neon Cold-Start Connection Drops**| Database Stability | First user request after 5 minutes of inactivity may fail with 500 error. | Configure `create_engine` with `pool_pre_ping=True` and `pool_recycle=300`. |
| **SQLite `check_same_thread` Error**| Database Engine | SQLAlchemy crashes during engine creation if PostgreSQL URL is provided. | Make `connect_args` conditional: apply `check_same_thread: False` only if `sqlite` dialect. |
| **Upstream Gnani STT HTTP 500** | External Service | Real audio transcription fails if user relies exclusively on cloud STT. | Browser Web Speech API fallback and demo chips ensure uninterrupted demonstration. |

---

## 11. Exact Files Requiring Changes in Future Implementation Tasks

The audit confirms that the following **5 files** are the ONLY files requiring modification during Phase 1.6 cloud enablement:

1. [backend/requirements.txt](backend/requirements.txt):
   - Add `psycopg2-binary>=2.9.9` (PostgreSQL DBAPI driver).
2. [backend/database.py](backend/database.py):
   - Normalize PostgreSQL URL scheme (`postgres://` → `postgresql://`).
   - Make `connect_args={"check_same_thread": False}` conditional on `sqlite` dialect.
   - Add `pool_pre_ping=True`, `pool_recycle=300`, and pool sizing for PostgreSQL connections.
3. [backend/main.py](backend/main.py):
   - Update `CORSMiddleware` to read allowed origins from `os.environ.get("CORS_ORIGINS")` with fallback to localhost.
4. [backend/.env.example](backend/.env.example):
   - Document `DATABASE_URL` PostgreSQL syntax, `CORS_ORIGINS`, and Render host settings.
5. `frontend/vercel.json` (New File to Create):
   - Add SPA client rewrite rule (`{"rewrites": [{"source": "/(.*)", "destination": "/index.html"}]}`).

*No changes are required to SQLAlchemy models, Pydantic schemas, customer matching algorithms, voice parsing logic, or UI component views.*

---

## 12. Recommended Implementation Sequence for Phase 1.6

```mermaid
flowchart TD
    Step1["Step 1: Driver & Engine Normalization<br/>(Add psycopg2-binary, update database.py for pool_pre_ping & dialect check)"] --> Step2
    Step2["Step 2: CORS & Environment Parameterization<br/>(Update main.py for dynamic CORS_ORIGINS & host binding)"] --> Step3
    Step3["Step 3: Isolated PostgreSQL Verification<br/>(Run isolated backend test suite against PostgreSQL/SQLite to verify 81/81 pass)"] --> Step4
    Step4["Step 4: Provision Neon PostgreSQL<br/>(Create Neon project, configure serverless pooled connection string)"] --> Step5
    Step5["Step 5: Deploy Backend to Render<br/>(Set DATABASE_URL, GNANI keys, and CORS_ORIGINS; verify /health)"] --> Step6
    Step6["Step 6: Deploy Frontend to Vercel<br/>(Set VITE_API_BASE_URL, add vercel.json, verify HTTPS & mic access)"] --> Step7
    Step7["Step 7: End-to-End Cloud Verification<br/>(Verify live transactions, fallback behavior, and zero local DB impact)"]
```

---

## 13. Estimated Complexity and Dependencies

- **Estimated Implementation Effort:** Low to Moderate (Estimated 2 to 3 focused tasks).
- **External Dependencies:**
  - `psycopg2-binary` (Standard pre-compiled C-extension wheel for Python).
  - Free-tier accounts on Neon (PostgreSQL), Render (Web Service), and Vercel (Static Hosting).
- **Backward Compatibility:** 100% backward compatible with local SQLite development when `DUKAANVOICE_DB_URL` is unset or points to a `.db` file.

---

## 14. Explicit List of Unverified Assumptions

In strict accordance with audit guidelines, the following items are classified as **UNVERIFIED** and must be tested in subsequent tasks:
1. **Real Neon Network Latency:** Cold-start latency (500ms–2.5s) on Neon compute wake-up has not been benchmarked with live FastAPI queries.
2. **Render Free-Tier Spin-Down:** Render free-tier web services spin down after 15 minutes of inactivity; initial evaluator cold-start delay (30–50s) requires verification.
3. **Live Gnani STT Recovery:** Whether Gnani will resolve the upstream HTTP 500 error on `https://api.vachana.ai/stt/v3` remains outside project control.
4. **Physical Mobile Device Browser Audio:** Web Speech API behavior on physical iOS Safari and Android Chrome across varying cellular networks requires real-device field validation.

---

## 15. Final Recommendation: CONDITIONAL GO

DukaanVoice is architecturally well-designed and ready for cloud deployment. The database schema, relationship constraints, atomic transaction logic, and responsive UI require **zero rewrites**.

**Recommendation:** Proceed to **Phase 1.6 Implementation Tasks** following the sequence outlined in Section 12, beginning with driver installation and engine compatibility updates in an isolated environment.
