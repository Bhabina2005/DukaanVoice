"""
Global pytest configuration for DukaanVoice backend tests.
Executed automatically by pytest before collecting or importing any test modules.
Guarantees:
1. DUKAANVOICE_TEST_MODE is active globally.
2. DUKAANVOICE_DB_URL defaults to isolated in-memory SQLite.
3. No module import can target or mutate backend/dukaanvoice.db.
"""

import os
import sys
from pathlib import Path

# Add backend directory to sys.path
backend_dir = str(Path(__file__).resolve().parent)
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Set test environment flags before any module is imported or collected
os.environ["DUKAANVOICE_TEST_MODE"] = "1"
os.environ.setdefault("DUKAANVOICE_DB_URL", "sqlite:///:memory:")


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "live: marks tests as requiring external live network access")
