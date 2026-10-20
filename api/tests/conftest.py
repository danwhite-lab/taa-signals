"""Tests cannot connect to Supabase, price providers, or any real account."""
import socket
import pytest


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network is forbidden in tests; use mocks.")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    for name in ("SUPABASE_URL", "SUPABASE_PUBLISHABLE_KEY", "SUPABASE_SERVICE_ROLE_KEY", "CRON_SECRET",
                 "TEST_LOGIN_ENABLED", "TEST_LOGIN_EMAIL", "TEST_LOGIN_PASSWORD", "TEST_LOGIN_ALLOW_PRODUCTION", "VERCEL", "VERCEL_ENV"):
        monkeypatch.delenv(name, raising=False)
