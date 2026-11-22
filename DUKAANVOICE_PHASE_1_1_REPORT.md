# DukaanVoice – Phase 1.1 Final Verification Report
**Challenge:** BolBharat Gnani Voice AI Innovation Challenge  
**Date:** November 19, 2026  
**Status:** **Phase 1.1 Complete & Verified Baseline Established**  

---

## 1. Executive Summary

Phase 1.1 focused on securing the test harness, establishing an isolated database architecture, creating repository hygiene assets, and completing end-to-end and static verifications.

With the execution of host-level integration tests, end-to-end API scenarios, and the frontend production build, **Phase 1.1 verification is complete**.

### Key Milestones Achieved
- **Test Safety Secured:** Eliminated destructive teardown logic in `backend/test_app.py`; unit/ASGI tests now run against an isolated in-memory SQLite database (`sqlite:///:memory:`).
- **11/11 ASGI Tests Passed:** `pytest test_app.py -v` achieved 100% pass rate across two consecutive runs.
- **E2E Verification Succeeded:** All voice ledger scenarios (Add Credit, Payment, Balance Check, Voice Correction, Cancellation, and Idempotent Confirmation) passed in `backend/e2e_verify.py`.
- **Frontend Production Build Succeeded:** `npm run build` completed cleanly using Vite 8.3.8.
- **Logical Database Integrity Intact:** Read-only inspection confirms the live SQLite database retains exactly the original baseline records (1 customer, 1 transaction, ₹430 balance).
- **Repository Hygiene Complete:** Pinned `backend/requirements.txt`, root `.gitignore`, environment variable templates (`.env.example`), and root `README.md` created.

---

## 2. Task 1: Fix Test Database Safety

### Identified Hazard in Original Code
In the original `backend/test_app.py` (lines 14–22), an `autouse=True` pytest fixture performed destructive operations directly against `SessionLocal()` (which bound to the live SQLite file `dukaanvoice.db`):
```python
# PREVIOUS DANGEROUS FIXTURE (REMOVED)
@pytest.fixture(autouse=True)
def preserve_seed_data():
    yield
    db = SessionLocal()
    db.query(Transaction).filter(Transaction.id > 1).delete()
    db.query(Customer).filter(Customer.id > 1).delete()
    db.commit()
    db.close()
```
Executing this suite against the development database dropped all user-created records where `id > 1`.

### Implemented Fixes
1. **Pristine Backup:** Original test suite backed up to [backend/test_app.py.bak](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/test_app.py.bak).
2. **Dedicated In-Memory SQLite Engine:** Created an isolated in-memory engine using `StaticPool` so that test operations run entirely in memory:
   ```python
   TEST_DATABASE_URL = "sqlite:///:memory:"
   test_engine = create_engine(
       TEST_DATABASE_URL,
       connect_args={"check_same_thread": False},
       poolclass=StaticPool
   )
   TestingSessionLocal = sessionmaker(
       autocommit=False, autoflush=False, bind=test_engine
   )
   ```
3. **FastAPI Dependency Override:** Overrode `get_db` on the application instance so all router endpoints interact solely with the test engine:
   ```python
   def override_get_db():
       db = TestingSessionLocal()
       try:
           yield db
       finally:
           db.close()

   app.dependency_overrides[get_db] = override_get_db
   ```
4. **Per-Test Table Teardown and Re-seeding:** Replaced the live database deletion with a fixture that drops and recreates tables only within `test_engine`, seeding standard baseline customer and transaction records in-memory:
   ```python
   @pytest.fixture(autouse=True)
   def isolated_test_database():
       Base.metadata.drop_all(bind=test_engine)
       Base.metadata.create_all(bind=test_engine)
       ...
       yield
       Base.metadata.drop_all(bind=test_engine)
   ```
5. **Preserved All 11 Integration Tests:** Every original test in [backend/test_app.py](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/test_app.py) was retained with zero omissions. Direct queries were updated to query `TestingSessionLocal()` instead of `SessionLocal()`.
6. **Deprecation Notice Observed:**
   > [!NOTE]
   > During test suite initialization, Starlette issues the following warning:  
   > `StarletteDeprecationWarning: Using 'httpx' with 'starlette.testclient' is deprecated; install 'httpx2' instead.`  
   > This warning does not block test execution or cause test failures; it relates to upstream Starlette/FastAPI transport packaging.

---

## 3. Task 2: Live Database Integrity & Hash Transition Analysis

### Cryptographic Hash Comparison
- **Original Baseline SHA-256:**  
  `940CB8C9C9BE654B72B63B60D346724F653C44DCEB8CB3D99D8973C55F621A73`
- **Post-E2E Execution SHA-256:**  
  `2B0363C99E9BF0788C17FA10E77CDBAB958801644DA4CF77597AD9AD2D073FA3`

### Technical Explanation of Physical Hash Change
**Byte-for-byte physical integrity is NOT claimed.**

The physical cryptographic hash of `backend/dukaanvoice.db` changed following execution of `backend/e2e_verify.py`. This occurred because:
1. `backend/e2e_verify.py` sends live HTTP requests to the running backend service, which commits transactions directly to the development database during scenarios B, C, and H.
2. At the conclusion of the test run (lines 251–256 of `backend/e2e_verify.py`), the script executes:
   ```python
   con = sqlite3.connect(DB_PATH)
   cur = con.cursor()
   cur.execute("DELETE FROM transactions WHERE id > 1")
   con.commit()
   con.close()
   ```
3. While all test records were deleted, SQLite's B-Tree engine marks the deleted data pages on its internal freelist, increments the internal database change counter (bytes 24–27 of the SQLite header), and updates the schema cookie. This alters the raw byte sequence of the `.db` file, resulting in a new SHA-256 digest (`2B0363C9...`).

### Logical Integrity Verification
Read-only inspection confirms that the **final logical records match the original baseline exactly**:

| Check Attribute | Baseline Value | Final Inspected Value | Status |
| :--- | :--- | :--- | :---: |
| **Customer Count** | Exactly 1 | Exactly 1 | **Match** |
| **Customer ID** | 1 | 1 | **Match** |
| **Customer Name** | `Ramesh` | `Ramesh` | **Match** |
| **Customer Phone** | `9876543210` | `9876543210` | **Match** |
| **Transaction Count**| Exactly 1 | Exactly 1 | **Match** |
| **Transaction ID** | 1 | 1 | **Match** |
| **Transaction Type** | `CREDIT` | `CREDIT` | **Match** |
| **Transaction Amount**| ₹430 | ₹430 | **Match** |
| **Outstanding Balance**| ₹430 | ₹430 | **Match** |

Zero baseline rows were lost, modified, or corrupted.

---

## 4. Task 3: Complete Repository Preparation

The following configuration and documentation files were established using verified environment parameters:

1. **[backend/requirements.txt](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/requirements.txt):**
   Exact pinned versions extracted from `pip freeze`:
   ```
   fastapi==0.162.4
   uvicorn==0.54.0
   SQLAlchemy==2.1.8
   pydantic==2.14.3
   python-dotenv==1.2.4
   httpx==0.28.1
   pytest==9.2.0
   websockets==17.4
   watchfiles==1.3.0
   anyio==4.16.0
   ```

2. **[.gitignore](file:///C:/Users/bhabi/Downloads/DukaanVoice/.gitignore) (Root):**
   Excludes Python bytecode, virtual environments (`venv/`, `backend/venv/`), node dependencies (`node_modules/`), build outputs (`dist/`, `.vite-temp/`), environment configs (`.env`), and backup files (`*.bak`, `*.backup`).

3. **[backend/.env.example](file:///C:/Users/bhabi/Downloads/DukaanVoice/backend/.env.example):**
   Documents `HOST=127.0.0.1`, `PORT=8000`, `DATABASE_URL`, and placeholder variables for future Gnani Voice AI integration.

4. **[frontend/.env.example](file:///C:/Users/bhabi/Downloads/DukaanVoice/frontend/.env.example):**
   Documents `VITE_API_BASE_URL=http://localhost:8000` and `VITE_WS_BASE_URL=ws://localhost:8000/api/voice/ws`.

5. **[README.md](file:///C:/Users/bhabi/Downloads/DukaanVoice/README.md) (Root):**
   Architecture guide, setup walkthrough, voice command catalog, and test execution instructions.

---

## 5. Verification Matrix: Complete Results

| Verification Category | Suite / Command | Execution Environment | Status | Evidence / Notes |
| :--- | :--- | :---: | :---: | :--- |
| **Python Imports** | `python -B -c "import ..."` | Sandbox | **PASSED** | Clean import of all 9 backend modules without errors. |
| **Voice Parser Unit Logic** | `voice_parser.py` | Sandbox | **PASSED** | Verified: `ADD_CREDIT`, `ADD_PAYMENT`, `CHECK_BALANCE`, `CORRECT`, `CONFIRM`, `CANCEL`. |
| **Pending Manager Unit Logic**| `pending_manager.py` | Sandbox | **PASSED** | Verified: creation, amount modification, confirmation, idempotency cache lookup, cancellation. |
| **Isolated SQLAlchemy Tests**| In-memory SQLite | Sandbox | **PASSED** | Verified: Customer CRUD, phone uniqueness, check constraints (`amount > 0`, valid types), balance computation, cascade delete. |
| **Frontend Linter** | `npm run lint` (`eslint .`) | Sandbox | **PASSED** | Exit code 0 across all JSX and JS files in `frontend/src`. |
| **ASGI Test Suite** | `pytest test_app.py -v` | Host (External) | **PASSED** | **11/11 passed across two consecutive runs.** Safe in-memory database isolation confirmed. |
| **E2E Voice Verification** | `python e2e_verify.py` | Host (External) | **PASSED** | All scenarios passed: health, customer check, duplicate check, unknown customer, cancellation, correction, payment, balance check, idempotency. |
| **Frontend Production Build** | `npm run build` | Host (External) | **PASSED** | Compiled cleanly using **Vite 8.3.8**. Bundle generated in `frontend/dist`. |

---

## 6. Environment & Platform Analysis

### 1. Loopback Socket Restriction (`WinError 10013`)
- **Diagnosis:** When processes run inside the Windows restricted sandbox, Winsock calls to `connect()`—even to `127.0.0.1` loopback—are blocked by Windows kernel network filtering policies, returning `PermissionError: [WinError 10013]`.
- **Impact on Tests:** FastAPI's `TestClient` uses `anyio`/`asyncio` on Windows, which executes `socket.socketpair()` for its self-pipe signal mechanism. `socketpair()` attempts a loopback connection that either hangs or fails inside the sandbox.
- **Resolution:** `pytest test_app.py -v` and `e2e_verify.py` run cleanly when executed in a standard host terminal outside the sandbox.

### 2. Filesystem Write Restriction (`EPERM` on `.vite-temp`)
- **Diagnosis:** `vite build` creates temporary ES module bundles inside `node_modules/.vite-temp`. The sandbox restricts write permissions to certain subdirectories within `node_modules`.
- **Resolution:** Running `npm run build` directly on the host using Vite 8.3.8 succeeds without restriction.

---

## 7. Remaining Limitations & Phase 2 Scope

1. **Gnani Voice AI Integration Not Implemented (Phase 2 Core):**
   - Gnani Prisma v3.0 (ASR) and Timbre v3.0 (TTS) are not yet integrated.
   - The application currently relies on Browser Web Speech API fallback (`webkitSpeechRecognition` / `window.speechSynthesis`).
2. **E2E Test Script Targets Development Database:**
   - `backend/e2e_verify.py` interacts directly with the live server database (`dukaanvoice.db`) and cleans up with `DELETE WHERE id > 1`. While logical integrity is maintained, this alters the physical file hash. In Phase 2, `e2e_verify.py` should be enhanced to target an isolated staging or temporary test database.
3. **In-Memory Pending State:**
   - Pending transactions staged via `backend/pending_manager.py` reside in application memory. An unplanned backend restart during an active voice flow resets pending state.
4. **Starlette Deprecation Warning:**
   - `StarletteDeprecationWarning` regarding `httpx` in `starlette.testclient` remains present and can be modernized during future dependency maintenance.

---

## 8. Conclusion
Phase 1.1 is **complete**. The test harness is safe and decoupled from production data, baseline customer and transaction records are preserved, and all static, unit, ASGI, and E2E verifications have passed.
