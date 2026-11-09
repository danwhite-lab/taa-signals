"""Verified private fund context for authenticated synchronous routes."""
from contextvars import ContextVar
from functools import wraps
import hashlib
import hmac
import inspect
import json
import os

from fastapi import HTTPException

from haa.fund_verification import WORDS
from haa.my_funds import PREFIX, registered_fund, use_funds

owner = ContextVar("my_funds_owner", default=None)
registry_status = ContextVar("my_funds_registry_status", default=("ok", 0))


def signing_key():
    return os.environ.get("MY_FUNDS_SIGNING_KEY", "")


def signature(user_id, identifier, listing, fund):
    data = json.dumps([user_id, identifier, listing, fund], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(signing_key().encode(), data.encode(), hashlib.sha256).hexdigest()


def verified_row(user_id, row):
    try:
        return hmac.compare_digest(row["signature"],
                                   signature(user_id, row["id"], row["listing_key"], row["verified"]))
    except (KeyError, TypeError, ValueError):
        return False


def read_funds(session):
    if not signing_key():
        return [], 0
    from .fund_registry import _table

    try:
        user_id = session["user_id"]
        rows = _table(session).select("id,listing_key,verified,signature,archived").eq("user_id", user_id).execute().data
    except Exception:
        raise HTTPException(503, WORDS["registryUnavailable"]) from None

    funds = [{**row["verified"], "model": PREFIX + row["id"], "archived": row["archived"]}
             for row in rows if verified_row(user_id, row)]
    return funds, len(rows) - len(funds)


def require_fund(label):
    status, _ = registry_status.get()
    if (status != "ok" and isinstance(label, str) and label.startswith(PREFIX)
            and registered_fund(label) is None):
        message = {"unavailable": "registryUnavailable", "unconfigured": "registryUnconfigured",
                   "rejected_rows": "rejectedRows"}[status]
        raise HTTPException(503, WORDS[message])


def require_portfolio_funds(payload):
    sleeves = payload.get("sleeves") if isinstance(payload, dict) else None
    if isinstance(sleeves, list):
        for sleeve in sleeves:
            if isinstance(sleeve, dict):
                require_fund(sleeve.get("model"))


def require_holdings_funds(account):
    positions = account.get("positions") if isinstance(account, dict) else None
    if isinstance(positions, dict):
        for label, row in positions.items():
            require_fund(label)
            if isinstance(row, dict):
                require_fund(row.get("companion_of"))


def account_scope(function):
    arguments = inspect.signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        session = arguments.bind(*args, **kwargs).arguments["session"] if signing_key() else None
        if session is None:
            funds, status = [], ("unconfigured", 0)
        else:
            try:
                funds, rejected = read_funds(session)
                status = ("rejected_rows" if rejected else "ok", rejected)
            except HTTPException:
                funds, status = [], ("unavailable", 0)
        token = owner.set(session["user_id"] if session is not None else None)
        status_token = registry_status.set(status)
        try:
            with use_funds(funds):
                return function(*args, **kwargs)
        finally:
            registry_status.reset(status_token)
            owner.reset(token)
    return wrapped
