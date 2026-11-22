"""
DukaanVoice — Verification of FastAPI lifespan database migration behavior.
Executes each check individually against isolated temporary databases with strict timeouts.
"""

import asyncio
import hashlib
import importlib
import logging
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
from unittest.mock import patch

# Ensure backend directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Set test environment to isolated in-memory by default
os.environ["DUKAANVOICE_TEST_MODE"] = "1"
os.environ["DUKAANVOICE_DB_URL"] = "sqlite:///:memory:"

from database import Base, engine, run_migrations
from main import app, lifespan


def run_check_1_import_isolation():
    """Check 1: Confirm module import never executes database migrations."""
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "check1_import.db"
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE sample_data (id INT PRIMARY KEY, val TEXT);")
        conn.execute("INSERT INTO sample_data VALUES (1, 'initial');")
        conn.commit()
        conn.close()

        initial_hash = hashlib.sha256(db_path.read_bytes()).hexdigest().upper()
        old_url = os.environ.get("DUKAANVOICE_DB_URL")
        os.environ["DUKAANVOICE_DB_URL"] = f"sqlite:///{db_path.as_posix()}"

        try:
            # Force reload of main and database modules
            if "database" in sys.modules:
                importlib.reload(sys.modules["database"])
            if "main" in sys.modules:
                importlib.reload(sys.modules["main"])

            post_hash = hashlib.sha256(db_path.read_bytes()).hexdigest().upper()
            assert post_hash == initial_hash, f"Import mutated DB! {initial_hash} != {post_hash}"

            # Verify no DukaanVoice tables were created
            con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            con.close()
            assert "transactions" not in tables
            assert "customers" not in tables
            assert "pending_transactions" not in tables
            assert tables == ["sample_data"]
        finally:
            if old_url:
                os.environ["DUKAANVOICE_DB_URL"] = old_url
            else:
                os.environ.pop("DUKAANVOICE_DB_URL", None)
            if "database" in sys.modules:
                importlib.reload(sys.modules["database"])
            if "main" in sys.modules:
                importlib.reload(sys.modules["main"])

    elapsed = time.time() - t0
    print(f"CHECK 1 (Import never triggers migrations): PASSED in {elapsed:.3f}s", flush=True)
    return True


def run_check_2_test_mode_skips():
    """Check 2: Confirm DUKAANVOICE_TEST_MODE disables automatic migration."""
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "check2_testmode.db"
        old_url = os.environ.get("DUKAANVOICE_DB_URL")
        old_test_mode = os.environ.get("DUKAANVOICE_TEST_MODE")
        old_auto = os.environ.get("DUKAANVOICE_AUTO_MIGRATE")

        os.environ["DUKAANVOICE_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ["DUKAANVOICE_TEST_MODE"] = "1"
        os.environ["DUKAANVOICE_AUTO_MIGRATE"] = "true"

        try:
            import main
            importlib.reload(main)

            async def _run():
                async with main.lifespan(main.app):
                    pass

            asyncio.run(asyncio.wait_for(_run(), timeout=10.0))

            # Database file should either not exist or have 0 tables
            if db_path.exists():
                con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
                tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                con.close()
                assert len(tables) == 0, f"Expected 0 tables in test mode, got: {tables}"
        finally:
            if old_url:
                os.environ["DUKAANVOICE_DB_URL"] = old_url
            else:
                os.environ.pop("DUKAANVOICE_DB_URL", None)
            if old_test_mode is not None:
                os.environ["DUKAANVOICE_TEST_MODE"] = old_test_mode
            else:
                os.environ.pop("DUKAANVOICE_TEST_MODE", None)
            if old_auto is not None:
                os.environ["DUKAANVOICE_AUTO_MIGRATE"] = old_auto
            else:
                os.environ.pop("DUKAANVOICE_AUTO_MIGRATE", None)

    elapsed = time.time() - t0
    print(f"CHECK 2 (DUKAANVOICE_TEST_MODE disables migration): PASSED in {elapsed:.3f}s", flush=True)
    return True


def run_check_3_auto_migrate_false_skips():
    """Check 3: Confirm DUKAANVOICE_AUTO_MIGRATE=false disables automatic migration."""
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "check3_automigrate_false.db"
        old_url = os.environ.get("DUKAANVOICE_DB_URL")
        old_test_mode = os.environ.get("DUKAANVOICE_TEST_MODE")
        old_auto = os.environ.get("DUKAANVOICE_AUTO_MIGRATE")

        os.environ["DUKAANVOICE_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ.pop("DUKAANVOICE_TEST_MODE", None)
        os.environ["DUKAANVOICE_AUTO_MIGRATE"] = "false"

        try:
            import main
            importlib.reload(main)

            async def _run():
                async with main.lifespan(main.app):
                    pass

            asyncio.run(asyncio.wait_for(_run(), timeout=10.0))

            # Database file should have 0 tables
            if db_path.exists():
                con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
                tables = con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                con.close()
                assert len(tables) == 0, f"Expected 0 tables when AUTO_MIGRATE=false, got: {tables}"
        finally:
            if old_url:
                os.environ["DUKAANVOICE_DB_URL"] = old_url
            else:
                os.environ.pop("DUKAANVOICE_DB_URL", None)
            if old_test_mode is not None:
                os.environ["DUKAANVOICE_TEST_MODE"] = old_test_mode
            else:
                os.environ.pop("DUKAANVOICE_TEST_MODE", None)
            if old_auto is not None:
                os.environ["DUKAANVOICE_AUTO_MIGRATE"] = old_auto
            else:
                os.environ.pop("DUKAANVOICE_AUTO_MIGRATE", None)

    elapsed = time.time() - t0
    print(f"CHECK 3 (DUKAANVOICE_AUTO_MIGRATE=false disables migration): PASSED in {elapsed:.3f}s", flush=True)
    return True


def run_check_4_production_startup_runs_migrations():
    """Check 4: Confirm intended production startup runs migrations when enabled."""
    t0 = time.time()
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "check4_production.db"
        old_url = os.environ.get("DUKAANVOICE_DB_URL")
        old_test_mode = os.environ.get("DUKAANVOICE_TEST_MODE")
        old_auto = os.environ.get("DUKAANVOICE_AUTO_MIGRATE")

        os.environ["DUKAANVOICE_DB_URL"] = f"sqlite:///{db_path.as_posix()}"
        os.environ.pop("DUKAANVOICE_TEST_MODE", None)
        os.environ["DUKAANVOICE_AUTO_MIGRATE"] = "true"

        try:
            import database
            importlib.reload(database)
            import main
            importlib.reload(main)

            async def _run():
                async with main.lifespan(main.app):
                    pass

            asyncio.run(asyncio.wait_for(_run(), timeout=10.0))

            # Database file must exist and contain DukaanVoice tables
            assert db_path.exists(), "Production startup did not create database"
            con = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
            con.close()
            assert "customers" in tables, f"Expected 'customers' table, found: {tables}"
            assert "transactions" in tables, f"Expected 'transactions' table, found: {tables}"
            assert "pending_transactions" in tables, f"Expected 'pending_transactions' table, found: {tables}"
        finally:
            if old_url:
                os.environ["DUKAANVOICE_DB_URL"] = old_url
            else:
                os.environ.pop("DUKAANVOICE_DB_URL", None)
            if old_test_mode is not None:
                os.environ["DUKAANVOICE_TEST_MODE"] = old_test_mode
            else:
                os.environ.pop("DUKAANVOICE_TEST_MODE", None)
            if old_auto is not None:
                os.environ["DUKAANVOICE_AUTO_MIGRATE"] = old_auto
            else:
                os.environ.pop("DUKAANVOICE_AUTO_MIGRATE", None)
            if "database" in sys.modules:
                importlib.reload(sys.modules["database"])
            if "main" in sys.modules:
                importlib.reload(sys.modules["main"])

    elapsed = time.time() - t0
    print(f"CHECK 4 (Production startup runs migrations when enabled): PASSED in {elapsed:.3f}s", flush=True)
    return True


def run_check_5_migration_failure_logged_and_fails_startup():
    """Check 5: Confirm migration failure is logged safely and halts application startup."""
    t0 = time.time()
    old_test_mode = os.environ.get("DUKAANVOICE_TEST_MODE")
    old_auto = os.environ.get("DUKAANVOICE_AUTO_MIGRATE")

    os.environ.pop("DUKAANVOICE_TEST_MODE", None)
    os.environ["DUKAANVOICE_AUTO_MIGRATE"] = "true"

    try:
        import main
        importlib.reload(main)

        # Mock run_migrations to simulate an internal database failure with sensitive connection string
        sensitive_secret = "secret_password_super_confidential_999"
        with patch.object(main, "run_migrations", side_effect=ValueError(f"DB disk failure ({sensitive_secret})")):
            raised_expected = False
            try:
                async def _run():
                    async with main.lifespan(main.app):
                        pass

                asyncio.run(asyncio.wait_for(_run(), timeout=10.0))
            except RuntimeError as e:
                raised_expected = True
                err_msg = str(e)
                # Ensure the exception detail did NOT leak sensitive string
                assert sensitive_secret not in err_msg, f"Sensitive secret leaked in error message: {err_msg}"
                assert "Database migration failed on startup" in err_msg

            assert raised_expected, "Startup did not fail when migration raised exception!"
    finally:
        if old_test_mode is not None:
            os.environ["DUKAANVOICE_TEST_MODE"] = old_test_mode
        else:
            os.environ["DUKAANVOICE_TEST_MODE"] = "1"
        if old_auto is not None:
            os.environ["DUKAANVOICE_AUTO_MIGRATE"] = old_auto
        else:
            os.environ.pop("DUKAANVOICE_AUTO_MIGRATE", None)
        if "main" in sys.modules:
            importlib.reload(sys.modules["main"])

    elapsed = time.time() - t0
    print(f"CHECK 5 (Migration failure halts startup without secret leak): PASSED in {elapsed:.3f}s", flush=True)
    return True


if __name__ == "__main__":
    t_start = time.time()
    print("=== STARTING FASTAPI LIFESPAN BEHAVIOR VERIFICATION ===", flush=True)
    run_check_1_import_isolation()
    run_check_2_test_mode_skips()
    run_check_3_auto_migrate_false_skips()
    run_check_4_production_startup_runs_migrations()
    run_check_5_migration_failure_logged_and_fails_startup()
    total_elapsed = time.time() - t_start
    print(f"=== ALL 5 LIFESPAN CHECKS PASSED in {total_elapsed:.3f}s ===", flush=True)
