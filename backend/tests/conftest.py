"""Offline suite: no real dotenv, external sockets, or PostgreSQL connections.

SQL repository tests use disposable in-memory SQLite only. Test data never comes
from the developer's configuration. Temporary dotenv fixtures are explicit.
"""
import os
from pathlib import Path
import socket
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))


def _audit(event, args):
    if event == "open" and isinstance(args[0], (str, bytes, os.PathLike)):
        path = Path(os.fsdecode(args[0])).resolve()
        if path.is_relative_to(ROOT) and path.name.startswith(".env") and not path.name.endswith(".example"):
            raise RuntimeError("Tests must not read real repository dotenv files")
    if event in {"socket.connect", "socket.getaddrinfo"}:
        # Windows asyncio uses a private loopback socketpair as its wakeup pipe.
        # Allow only that stdlib implementation, not arbitrary loopback clients.
        fallback = getattr(socket, "_fallback_socketpair", None)
        if fallback is not None and sys._getframe(1).f_code is fallback.__code__:
            return
        raise RuntimeError("External network is disabled in offline tests")


sys.addaudithook(_audit)
# Establish a fully dummy canonical import configuration before importing app.
_bootstrap = {
    "APP_ENV": "production", "DATABASE_URL": "postgresql://unused/unused",
    "ADMIN_OIDC_ENABLED": "true", "ADMIN_OIDC_ISSUER": "https://identity.invalid",
    "ADMIN_OIDC_AUDIENCE": "offline-client", "ADMIN_OIDC_JWKS_URL": "https://identity.invalid/jwks",
    "ADMIN_OIDC_ALGORITHMS": "RS256", "ADMIN_INTERNAL_API_BEARER_TOKEN": "offline-incoming",
    "ADMIN_INTERNAL_API_SCOPES": '{"offline-service":"offline-org"}',
    "CURRENT_DB_BUSINESS_CENTERS": '{"offline-org":"offline-center"}',
    "ADMIN_NOTIFICATION_RUNNER_SERVICE_IDS": "offline-service",
    "ADMIN_LINE_INTERNAL_API_BASE_URL": "https://line.invalid",
    "ADMIN_LINE_INTERNAL_API_BEARER_TOKEN": "offline-outgoing",
}
# Never let unrelated inherited deployment variables influence test providers.
for _key in list(os.environ):
    if _key.startswith("ADMIN_") or _key == "CURRENT_DB_BUSINESS_CENTERS":
        del os.environ[_key]
os.environ.update(_bootstrap)
from app.core import settings_admin
settings_admin.ADMIN_ENV_FILE = ROOT / "backend/tests/nonexistent-owner-dotenv"
from app import main_admin
from app.db.engine import set_engine
set_engine(None)
for _key in _bootstrap:
    if _key not in {"APP_ENV", "DATABASE_URL"}:
        os.environ.pop(_key, None)


@pytest.fixture(autouse=True)
def no_postgres(monkeypatch):
    import psycopg
    def forbidden(*args, **kwargs):
        raise AssertionError("Real DB connections are a manual gate")
    monkeypatch.setattr(psycopg, "connect", forbidden)
    monkeypatch.setattr(psycopg.AsyncConnection, "connect", forbidden)
