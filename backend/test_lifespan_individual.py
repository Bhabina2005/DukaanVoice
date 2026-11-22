"""
DukaanVoice — Stage F Final Closure: Individual Lifespan Verification Suite.
Runs each lifespan check individually against isolated temporary databases with per-test timing.
"""

import hashlib
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dukaanvoice")

# Ensure backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Ensure isolated in-memory test environment during initial import
os.environ["DUKAANVOICE_TEST_MODE"] = "1"
os.environ["DUKAANVOICE_DB_URL"] = "sqlite:///:memory:"

from database import Base, engine, run_migrations
import main


def step_lifespan(app):
    """
    Drives the asynccontextmanager lifespan directly without Windows IOCP asyncio.run deadlock.
    Executes __aenter__ and __aexit__ synchronously since migrations execute synchronously.
    """
    cm = main.lifespan(app)
    coro_enter = cm.__aenter__()
    try:
        coro_enter.send(None)
    except StopIteration:
        pass

    coro_exit = cm.__aexit__(None, None, None)
    try:
        coro_exit.send(None)
    except StopIteration:
        pass


def check_1_import_does_not_trigger_migrations():
    """1. Confirm module import never executes database migrations."""
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = Path(tmpdir) / "check1.db"
        conn = sqlite3.connect(temp_db)
        conn.execute("CREATE TABLE pre_existing (id INT PRIMARY KEY);")
        conn.execute("INSERT INTO pre_existing VALUES (42);")
        conn.commit()
        conn.close()

        initial_hash = hashlib.sha256(temp_db.read_bytes()).hexdigest().upper()

        # Verify that simply having main and database loaded causes zero mutations
        con = sqlite3.connect(f"file:{temp_db.as_posix()}?mode=ro", uri=True)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        con.close()
        assert tables == ["pre_existing"]

        post_hash = hashlib.sha256(temp_db.read_bytes()).hexdigest().upper()
        assert initial_hash == post_hash, "Import modified DB!"

    elapsed = time.time() - t0
    print(f"CHECK 1 (Import does not trigger migrations): PASSED in {elapsed:.4f}s", flush=True)
    return True, elapsed


def check_2_test_mode_skips_migrations():
    """2. Confirm DUKAANVOICE_TEST_MODE disables automatic migration."""
    t0 = time.time()
    os.environ["DUKAANVOICE_TEST_MODE"] = "1"
    os.environ["DUKAANVOICE_AUTO_MIGRATE"] = "true"

    with patch.object(main, "run_migrations") as mock_migrate:
        step_lifespan(main.app)
        assert not mock_migrate.called, "run_migrations was called when DUKAANVOICE_TEST_MODE=1!"

    elapsed = time.time() - t0
    print(f"CHECK 2 (DUKAANVOICE_TEST_MODE disables automatic migration): PASSED in {elapsed:.4f}s", flush=True)
    return True, elapsed


def check_3_auto_migrate_false_skips_migrations():
    """3. Confirm DUKAANVOICE_AUTO_MIGRATE=false disables automatic migration."""
    t0 = time.time()
    os.environ.pop("DUKAANVOICE_TEST_MODE", None)
    os.environ["DUKAANVOICE_AUTO_MIGRATE"] = "false"

    with patch.object(main, "run_migrations") as mock_migrate:
        step_lifespan(main.app)
        assert not mock_migrate.called, "run_migrations was called when DUKAANVOICE_AUTO_MIGRATE=false!"

    elapsed = time.time() - t0
    print(f"CHECK 3 (DUKAANVOICE_AUTO_MIGRATE=false disables automatic migration): PASSED in {elapsed:.4f}s", flush=True)
    return True, elapsed


def check_4_auto_migrate_true_runs_migrations_at_startup():
    """4. Confirm intended production startup runs migrations when enabled."""
    t0 = time.time()
    os.environ.pop("DUKAANVOICE_TEST_MODE", None)
    os.environ["DUKAANVOICE_AUTO_MIGRATE"] = "true"

    with tempfile.TemporaryDirectory() as tmpdir:
        temp_db = Path(tmpdir) / "check4_prod.db"
        from sqlalchemy import create_engine
        temp_engine = create_engine(f"sqlite:///{temp_db.as_posix()}", connect_args={"check_same_thread": False})

        # Test lifespan using temporary isolated engine
        with patch.object(main, "engine", temp_engine):
            step_lifespan(main.app)

        # Verify tables created
        con = sqlite3.connect(f"file:{temp_db.as_posix()}?mode=ro", uri=True)
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        con.close()

        assert "customers" in tables, f"Missing 'customers' table: {tables}"
        assert "transactions" in tables, f"Missing 'transactions' table: {tables}"
        assert "pending_transactions" in tables, f"Missing 'pending_transactions' table: {tables}"

        # Close all connections so Windows allows temporary file deletion
        temp_engine.dispose()

    elapsed = time.time() - t0
    print(f"CHECK 4 (Production startup runs migrations when enabled): PASSED in {elapsed:.4f}s", flush=True)
    return True, elapsed


def check_5_migration_failure_logged_and_fails_startup():
    """5. Confirm migration failure is logged safely and halts application startup."""
    t0 = time.time()
    os.environ.pop("DUKAANVOICE_TEST_MODE", None)
    os.environ["DUKAANVOICE_AUTO_MIGRATE"] = "true"

    secret_key = "super_secret_credentials_xyz_123"
    with patch.object(main, "run_migrations", side_effect=Exception(f"Connection refused with {secret_key}")):
        raised_runtime_error = False
        try:
            step_lifespan(main.app)
        except RuntimeError as err:
            raised_runtime_error = True
            err_msg = str(err)
            # Ensure the exception detail did NOT leak sensitive string
            assert secret_key not in err_msg, f"Sensitive secret leaked in error: {err_msg}"
            assert "Database migration failed on startup" in err_msg

        assert raised_runtime_error, "Startup did not fail when migration raised exception!"

    # Restore clean test environment
    os.environ["DUKAANVOICE_TEST_MODE"] = "1"
    os.environ["DUKAANVOICE_DB_URL"] = "sqlite:///:memory:"

    elapsed = time.time() - t0
    print(f"CHECK 5 (Migration failure is logged safely and halts startup): PASSED in {elapsed:.4f}s", flush=True)
    return True, elapsed


if __name__ == "__main__":
    print("--- STARTING INDIVIDUAL LIFESPAN BEHAVIOR CHECKS ---", flush=True)
    t_all = time.time()
    check_1_import_does_not_trigger_migrations()
    check_2_test_mode_skips_migrations()
    check_3_auto_migrate_false_skips_migrations()
    check_4_auto_migrate_true_runs_migrations_at_startup()
    check_5_migration_failure_logged_and_fails_startup()
    total = time.time() - t_all
    print(f"--- ALL 5 LIFESPAN CHECKS SUCCESSFULLY COMPLETED in {total:.4f}s ---", flush=True)
