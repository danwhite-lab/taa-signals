"""User-scoped API: public key + verified user token, never a service key."""
import json
import os
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from haa import supabase_sync as sync
from haa.model_catalog import MODEL_CATALOG
from haa.portfolio_config import backtest_portfolio_config
from haa.rebalance_holdings import validate_account
from haa.workspace_sync import FIELDS

router = APIRouter()


def public_config():
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_PUBLISHABLE_KEY", "")
    if not url or not key:
        raise HTTPException(503, "Sign-in service is not configured.")
    return url, key


def authenticated(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer ") or not authorization[7:].strip():
        raise HTTPException(401, "Sign in to continue.", headers={"WWW-Authenticate": "Bearer"})
    url, key = public_config()
    try:
        return sync.verified_session(url, key, {"access_token": authorization[7:]})
    except Exception:
        raise HTTPException(401, "Your session is invalid or expired. Sign in again.") from None


def failure():
    # Provider exceptions can echo private payloads or tokens. Never return/log them.
    return HTTPException(502, "The private-data service could not confirm the operation. Reload before retrying.")


class WorkspaceWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict
    revision: int = Field(ge=0, strict=True)


class PortfolioWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    payload: dict
    id: UUID | None = None
    expected_updated_at: str | None = None
    is_default: bool = False


def valid_json(payload):
    try:
        if len(json.dumps(payload, allow_nan=False)) > 1_000_000:
            raise ValueError()
    except (TypeError, ValueError):
        raise HTTPException(422, "Enter valid JSON within the workspace size limit.") from None


@router.get("/api/me")
def me(session=Depends(authenticated)):
    return {"user_id": session["user_id"], "email": session["email"]}


@router.get("/api/workspace")
def workspace(session=Depends(authenticated)):
    try:
        return sync.load_workspace(*public_config(), session) or {"revision": 0, "payload": {}}
    except Exception:
        raise failure() from None


@router.put("/api/workspace")
def save_workspace(body: WorkspaceWrite, session=Depends(authenticated)):
    valid_json(body.payload)
    if set(body.payload) - FIELDS:
        raise HTTPException(422, "Workspace contains unsupported preference fields.")
    config = public_config()
    try:
        remote = sync.load_workspace(*config, session) or {"revision": 0, "payload": {}}
    except Exception:
        raise failure() from None
    # Patch only supplied preferences. Preserve holdings and all unmigrated settings.
    payload = {**remote["payload"], **body.payload}
    holdings_changed = ("holdings_account" in body.payload and
                        body.payload["holdings_account"] != remote["payload"].get("holdings_account"))
    if "holdings_account" in body.payload:
        try:
            account = validate_account(body.payload["holdings_account"])
            if not account.get("last_operation_id"):
                raise ValueError()
        except Exception:
            raise HTTPException(422, "Holdings require valid units and a unique operation ID.") from None
        if holdings_changed:
            old_id = remote["payload"].get("holdings_account", {}).get("last_operation_id")
            if account["last_operation_id"] == old_id:
                raise HTTPException(409, "This holdings operation ID was already used. Reload before editing.")
            old_revision = remote["payload"].get("holdings_account", {}).get("revision", 0)
            if account["revision"] != old_revision + 1:
                raise HTTPException(409, "Holdings changed. Reload before saving.")
        allowed = {"version", "revision", "positions", "cash_ils", "last_operation_id", "manual_fx", "manual_fx_date", "updated_at"}
        position_fields = {"id", "identifier", "market", "currency", "label", "units", "outside_rebalance", "minimum_ils", "manual_price", "manual_price_date", "manual_entered_at"}
        if set(account) - allowed or any(set(p) - position_fields for p in account["positions"].values()):
            raise HTTPException(422, "Holdings contain unsupported fields; prices and pending plans must not be saved.")
    # An identical operation retry needs no write, even if the response was lost.
    if payload == remote["payload"]:
        return remote
    if body.revision != remote["revision"]:
        raise HTTPException(409, "Workspace changed on another device. Reload before saving.")
    try:
        if holdings_changed:
            return sync.save_holdings_workspace(*config, session, payload, body.revision)
        revision = sync.save_workspace(*config, session, payload, body.revision)
    except RuntimeError:
        raise HTTPException(409, "Save not confirmed or workspace changed. Reload before editing.") from None
    except Exception:
        raise failure() from None
    if revision is None:
        raise HTTPException(409, "Workspace changed on another device. Reload before saving.")
    return {"revision": revision, "payload": payload}


@router.get("/api/portfolios")
def portfolios(session=Depends(authenticated)):
    try:
        return sync.list_portfolios(*public_config(), session)
    except Exception:
        raise failure() from None


@router.post("/api/portfolios")
def save_portfolio(body: PortfolioWrite, session=Depends(authenticated)):
    valid_json(body.payload)
    try:
        name = body.payload.get("name", "").strip()
        if not 1 <= len(name) <= 80:
            raise ValueError()
        backtest_portfolio_config(body.payload, {m.label: m for m in MODEL_CATALOG})
    except Exception:
        raise HTTPException(422, "Enter a valid named version-1 portfolio with known strategies, weights, capital and FX.") from None
    if body.id and not body.expected_updated_at:
        raise HTTPException(422, "An existing portfolio requires its loaded update timestamp.")
    try:
        return sync.save_portfolio(*public_config(), session, body.payload,
                                   is_default=body.is_default,
                                   existing_id=str(body.id) if body.id else None,
                                   expected_updated_at=body.expected_updated_at)
    except Exception as exc:
        # Only inspect known conflict messages; never expose the provider payload.
        if "changed on another device" in str(exc):
            raise HTTPException(409, "Portfolio changed on another device. Reload before saving.") from None
        raise failure() from None


@router.delete("/api/portfolios/{portfolio_id}")
def delete_portfolio(portfolio_id: UUID, expected_updated_at: str,
                     session=Depends(authenticated)):
    if not expected_updated_at:
        raise HTTPException(422, "Load the portfolio timestamp before deleting.")
    try:
        # A timestamp-filtered delete keeps the conflict check and write atomic.
        rows = (sync._client(*public_config(), session).table("portfolios").delete()
                .eq("id", str(portfolio_id)).eq("user_id", session["user_id"])
                .eq("updated_at", expected_updated_at).execute().data)
    except Exception:
        raise failure() from None
    if not rows:
        raise HTTPException(409, "Portfolio changed or was deleted. Reload before continuing.")
    return {"deleted": True}
