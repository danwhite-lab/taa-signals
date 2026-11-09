"""Verified private fund context for authenticated synchronous routes."""
from contextvars import ContextVar
from functools import wraps
import hashlib
import hmac
import inspect
import json
import os

from fastapi import HTTPException

from haa.my_funds import PREFIX, use_funds

owner = ContextVar("my_funds_owner", default=None)


def signing_key():
    return os.environ.get("MY_FUNDS_SIGNING_KEY", "")


def signature(user_id, identifier, listing, fund):
    data = json.dumps([user_id, identifier, listing, fund], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hmac.new(signing_key().encode(), data.encode(), hashlib.sha256).hexdigest()


def read_funds(session):
    if not signing_key():
        return []
    from .fund_registry import _table
    from .private_api import failure

    try:
        user_id = session["user_id"]
        rows = _table(session).select("id,listing_key,verified,signature,archived").eq("user_id", user_id).execute().data
        return [{**row["verified"], "model": PREFIX + row["id"], "archived": row["archived"]}
                for row in rows if hmac.compare_digest(row["signature"],
                    signature(user_id, row["id"], row["listing_key"], row["verified"]))]
    except Exception:
        raise failure() from None


def account_scope(function):
    arguments = inspect.signature(function)

    @wraps(function)
    def wrapped(*args, **kwargs):
        if not signing_key():
            return function(*args, **kwargs)
        session = arguments.bind(*args, **kwargs).arguments["session"]
        try:
            funds = read_funds(session)
        except HTTPException:
            funds = []
        token = owner.set(session["user_id"])
        try:
            with use_funds(funds):
                return function(*args, **kwargs)
        finally:
            owner.reset(token)
    return wrapped
