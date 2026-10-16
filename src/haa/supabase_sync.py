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


def _client(url: str, key: str, session: dict[str, str]):
    client = create_client(url, key)
    # The browser owns refresh-token rotation. Database requests only need the
    # current access token, avoiding concurrent refreshes on browser and server.
    client.postgrest.auth(session["access_token"])
    return client


def verified_session(url: str, key: str, tokens: dict) -> dict[str, str]:
    """Verify browser-supplied credentials with Auth before admitting the user."""
    user = create_client(url, key).auth.get_user(tokens['access_token']).user
    if user is None:
        raise RuntimeError('The sign-in session is invalid.')
    return {**tokens, 'user_id': user.id, 'email': user.email or 'Google account'}


def load_workspace(url, key, session):
    rows = _client(url, key, session).table('user_settings').select('payload,revision').eq('user_id', session['user_id']).execute().data
    return rows[0] if rows else None


def save_workspace(url, key, session, payload, revision):
    """Compare-and-swap prevents a stale device overwriting newer preferences."""
    client = _client(url, key, session)
    row = {'payload': payload, 'revision': revision + 1, 'updated_at': datetime.now(timezone.utc).isoformat()}
    if revision == 0:
        try:
            rows = client.table('user_settings').insert({**row, 'user_id': session['user_id']}).execute().data
        except Exception as exc:
            if getattr(exc, 'code', None) == '23505':
                return None
            raise
    else:
        rows = client.table('user_settings').update(row).eq('user_id', session['user_id']).eq('revision', revision).execute().data
    return revision + 1 if rows else None


def list_portfolios(url: str, key: str, session: dict[str, str]) -> list[dict[str, Any]]:
    response = (
        _client(url, key, session)
        .table("portfolios")
        .select("id,name,payload,is_default,updated_at")
        .order("updated_at", desc=True)
        .execute()
    )
    return list(response.data or [])


def save_holdings_workspace(url, key, session, payload, revision):
    """Save holdings and their operation ID in the same revision-checked row.

    A lost response must not cause a duplicate purchase on retry. Read back the
    exact candidate holdings after any uncertain result, never blindly retry a
    mutation or claim that a local session edit has been synced.
    """
    from .rebalance_holdings import validate_account
    account = validate_account(payload['holdings_account'])
    if not account.get('last_operation_id'):
        raise ValueError('Holdings save requires a unique operation ID.')
    try:
        saved_revision = save_workspace(url, key, session, payload, revision)
        if saved_revision is not None:
            return {'revision': saved_revision, 'payload': payload}
    except Exception:
        # The server may have committed before the connection failed.
        pass
    remote = load_workspace(url, key, session)
    if remote and remote['payload'].get('holdings_account') == account:
        return remote
    raise RuntimeError('Save could not be confirmed or this workspace changed on another device. Reload the synced workspace before editing further.')


def save_portfolio(
    url: str,
    key: str,
    session: dict[str, str],
    payload: dict[str, Any],
    *,
    is_default: bool = False,
    existing_id: str | None = None,
    expected_updated_at: str | None = None,
) -> dict[str, Any]:
    """Insert or replace one named portfolio for the authenticated user."""
    row = _client(url, key, session).rpc("save_private_portfolio", {
        "p_payload": payload, "p_id": existing_id,
        "p_expected_updated_at": expected_updated_at,
        "p_make_default": is_default,
    }).execute().data
    if not isinstance(row, dict) or not row.get("id"):
        raise RuntimeError("The portfolio save was not confirmed by the database.")
    return row


def clear_default(url: str, key: str, session: dict[str, str]) -> None:
    _client(url, key, session).table("portfolios").update({"is_default": False}).eq("user_id", session["user_id"]).execute()


def delete_portfolio(url: str, key: str, session: dict[str, str], portfolio_id: str) -> None:
    _client(url, key, session).table("portfolios").delete().eq("id", portfolio_id).execute()
