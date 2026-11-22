import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from database import Base, engine, run_migrations
import models
from routes.customers import router as customers_router
from routes.transactions import router as transactions_router
from routes.voice import router as voice_router

logger = logging.getLogger("dukaanvoice")


DEFAULT_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]


def get_cors_origins() -> list[str]:
    """
    Returns allowed CORS origins combining local development defaults
    with any comma-separated origins configured in CORS_ORIGINS.
    Excludes wildcard '*' to preserve safe credential transmission.
    """
    origins = list(DEFAULT_CORS_ORIGINS)
    custom_origins_env = os.environ.get("CORS_ORIGINS")
    if custom_origins_env:
        for origin in custom_origins_env.split(","):
            cleaned = origin.strip()
            if cleaned and cleaned != "*" and cleaned not in origins:
                origins.append(cleaned)
    return origins


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Explicit, controlled database initialization on application startup.
    Executed only when the ASGI server runs the application, never during module import.
    Skipped entirely when in test mode (DUKAANVOICE_TEST_MODE).
    """
    auto_migrate = os.environ.get("DUKAANVOICE_AUTO_MIGRATE", "true").lower() in ("true", "1")
    is_test_mode = bool(os.environ.get("DUKAANVOICE_TEST_MODE"))

    if auto_migrate and not is_test_mode:
        try:
            run_migrations(bind_engine=engine)
            logger.info("Database schema verification and migrations completed successfully.")
        except Exception as e:
            # Log sanitized failure without exposing credentials
            logger.error("Database migration failed during application startup: %s", type(e).__name__)
            # Fail startup clearly so corrupted or inaccessible databases halt startup
            raise RuntimeError(f"Database migration failed on startup: {type(e).__name__}") from e
    yield


app = FastAPI(
    title="DukaanVoice API",
    description="Voice-powered credit and payment ledger for kirana shopkeepers",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration supporting local dev and cloud production deployments
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "message": "Welcome to DukaanVoice API",
        "status": "running",
        "version": "1.0.0"
    }


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "database": "connected",
        "service": "DukaanVoice FastAPI Backend"
    }


app.include_router(
    customers_router,
    prefix="/api/customers",
    tags=["Customers"]
)

app.include_router(
    transactions_router,
    prefix="/api/transactions",
    tags=["Transactions"]
)

app.include_router(
    voice_router,
    prefix="/api/voice",
    tags=["Voice"]
)
