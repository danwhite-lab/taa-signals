"""Small, user-scoped Supabase helpers for portfolio synchronisation.

The client is always authenticated with the current user's session.  It never
uses a service-role key, so the database's row-level-security rules are part of
every portfolio operation.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import create_client


def config_from_secrets(secrets: Any) -> tuple[str, str] | None:
    """Return the public connection details when sync is configured."""
    try:
        config = secrets["supabase"]
        url = str(config["url"])
        key = str(config["publishable_key"])
    except (FileNotFoundError, KeyError, TypeError):
        return None
    return (url, key) if url and key else None


def sign_up(url: str, key: str, email: str, password: str) -> None:
    create_client(url, key).auth.sign_up({"email": email, "password": password})


def sign_in(url: str, key: str, email: str, password: str) -> dict[str, str]:
    response = create_client(url, key).auth.sign_in_with_password(
        {"email": email, "password": password}
    )
    if response.session is None or response.user is None:
        raise RuntimeError("Supabase did not return a signed-in session.")
    return {
        "access_token": response.session.access_token,
        "refresh_token": response.session.refresh_token,
        "user_id": response.user.id,
        "email": response.user.email or email,
    }


def _client(url: str, key: str, session: dict[str, str]):
    client = create_client(url, key)
    client.auth.set_session(session["access_token"], session["refresh_token"])
    return client


def list_portfolios(url: str, key: str, session: dict[str, str]) -> list[dict[str, Any]]:
    response = (
        _client(url, key, session)
        .table("portfolios")
        .select("id,name,payload,is_default,updated_at")
        .order("updated_at", desc=True)
        .execute()
    )
    return list(response.data or [])


def save_portfolio(
    url: str,
    key: str,
    session: dict[str, str],
    payload: dict[str, Any],
    *,
    is_default: bool = False,
    existing_id: str | None = None,
) -> None:
    """Insert or replace one named portfolio for the authenticated user."""
    client = _client(url, key, session)
    now = datetime.now(timezone.utc).isoformat()
    row = {
        "user_id": session["user_id"],
        "name": payload["name"],
        "payload": payload,
        "is_default": is_default,
        "updated_at": now,
    }
    if is_default:
        client.table("portfolios").update({"is_default": False, "updated_at": now}).eq(
            "user_id", session["user_id"]
        ).execute()
    if existing_id:
        client.table("portfolios").update(row).eq("id", existing_id).execute()
    else:
        client.table("portfolios").insert(row).execute()


def delete_portfolio(url: str, key: str, session: dict[str, str], portfolio_id: str) -> None:
    _client(url, key, session).table("portfolios").delete().eq("id", portfolio_id).execute()
