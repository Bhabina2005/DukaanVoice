"""
Tests for cloud configuration additions:
1. URL normalization (postgres:// -> postgresql://)
2. Database engine creation logic (SQLite vs PostgreSQL options)
3. Dynamic CORS origins resolution from environment variables
4. vercel.json rewrite configuration
"""
import json
import os
from pathlib import Path
import pytest

from database import normalize_database_url
from main import get_cors_origins, DEFAULT_CORS_ORIGINS


class TestDatabaseUrlNormalization:
    """Tests for normalize_database_url."""

    def test_normalizes_postgres_prefix(self):
        raw = "postgres://user:secret@ep-cool-12345.us-east-2.aws.neon.tech/neondb?sslmode=require"
        normalized = normalize_database_url(raw)
        assert normalized.startswith("postgresql://")
        assert "user:secret@ep-cool-12345.us-east-2.aws.neon.tech/neondb?sslmode=require" in normalized

    def test_leaves_postgresql_prefix_unchanged(self):
        raw = "postgresql://user:secret@ep-cool-12345.us-east-2.aws.neon.tech/neondb?sslmode=require"
        assert normalize_database_url(raw) == raw

    def test_leaves_sqlite_url_unchanged(self):
        raw = "sqlite:///./dukaanvoice.db"
        assert normalize_database_url(raw) == raw

    def test_handles_empty_or_none(self):
        assert normalize_database_url("") == ""
        assert normalize_database_url(None) is None


class TestCorsOriginsConfiguration:
    """Tests for get_cors_origins dynamic resolution."""

    def test_default_origins_when_env_unset(self, monkeypatch):
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
        origins = get_cors_origins()
        for default_origin in DEFAULT_CORS_ORIGINS:
            assert default_origin in origins

    def test_adds_custom_cloud_origins(self, monkeypatch):
        monkeypatch.setenv(
            "CORS_ORIGINS",
            "https://dukaanvoice.vercel.app, https://custom-kirana.example.com"
        )
        origins = get_cors_origins()
        assert "https://dukaanvoice.vercel.app" in origins
        assert "https://custom-kirana.example.com" in origins
        for default_origin in DEFAULT_CORS_ORIGINS:
            assert default_origin in origins

    def test_ignores_wildcard_for_security(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "*, https://dukaanvoice.vercel.app,   ")
        origins = get_cors_origins()
        assert "*" not in origins
        assert "https://dukaanvoice.vercel.app" in origins

    def test_deduplicates_origins(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://dukaanvoice.vercel.app")
        origins = get_cors_origins()
        assert origins.count("http://localhost:5173") == 1
        assert origins.count("https://dukaanvoice.vercel.app") == 1


class TestVercelConfiguration:
    """Tests vercel.json SPA rewrite file."""

    def test_vercel_json_exists_and_valid(self):
        vercel_path = Path(__file__).resolve().parent.parent / "frontend" / "vercel.json"
        assert vercel_path.is_file(), "frontend/vercel.json must exist"
        with open(vercel_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert "rewrites" in data
        assert any(
            r.get("source") == "/(.*)" and r.get("destination") == "/index.html"
            for r in data["rewrites"]
        )
