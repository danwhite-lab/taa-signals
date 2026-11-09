"""Account-scoped, provider-verified fund registry."""
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from haa import supabase_sync
from haa.fund_verification import FundVerificationError, WORDS, verify_fund
from haa.my_funds import PREFIX
from .fund_scope import read_funds, signature as _signature, signing_key as _secret, verified_row
from . import private_api


router = APIRouter(prefix="/api/my-funds")


def _table(session):
    return supabase_sync._client(*private_api.public_config(), session).table("my_funds")


class Lookup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market: str = Field(pattern="^(TASE|Global)$")
    identifier: str = Field(min_length=1, max_length=24)


class Confirm(Lookup):
    name: str = Field(min_length=1, max_length=300)


def verified(body):
    if not _secret():
        raise HTTPException(503, WORDS["storageUnavailable"])
    try:
        fund, first_price = verify_fund(body.market, body.identifier)
        return {"fund": fund, "quote": first_price}
    except FundVerificationError as exc:
        raise HTTPException(422, str(exc)) from None


@router.get("")
def list_funds(response: Response, session=Depends(private_api.authenticated)):
    response.headers["Cache-Control"] = "no-store, private"
    funds, rejected = read_funds(session)
    return {"funds": funds, "configured": bool(_secret()), "rejected": rejected,
            "status": "rejected_rows" if rejected else "ok"}


@router.post("/check")
def check(body: Lookup, session=Depends(private_api.authenticated)):
    return verified(body)


@router.post("")
def add(body: Confirm, session=Depends(private_api.authenticated)):
    result = verified(body)
    fund = result["fund"]
    if body.name != fund["name"]:
        raise HTTPException(409, WORDS["nameChanged"])
    identifier = str(uuid4())
    key = f'{fund["market"]}:{fund["identifier"]}'
    owner = session["user_id"]
    try:
        _table(session).insert({"user_id": owner, "id": identifier, "listing_key": key, "verified": fund,
                                "signature": _signature(owner, identifier, key, fund)}).execute()
    except Exception as exc:
        if getattr(exc, "code", None) == "23505":
            try:
                rows = (_table(session).select("id,listing_key,verified,signature")
                        .eq("user_id", owner).eq("listing_key", key).execute().data)
            except Exception:
                raise HTTPException(503, WORDS["registryUnavailable"]) from None
            message = "duplicateRejected" if any(not verified_row(owner, row) for row in rows) else "duplicate"
            raise HTTPException(409, WORDS[message]) from None
        raise private_api.failure() from None
    return {"model": PREFIX + identifier, **fund, "archived": False}


@router.post("/{identifier}/archive")
def archive(identifier: UUID, session=Depends(private_api.authenticated)):
    funds, rejected = read_funds(session)
    if PREFIX + str(identifier) not in {fund["model"] for fund in funds}:
        if rejected:
            raise HTTPException(503, WORDS["rejectedRows"])
        raise HTTPException(404, WORDS["unavailable"])
    try:
        _table(session).update({"archived": True}).eq("user_id", session["user_id"]).eq("id", str(identifier)).execute()
    except Exception:
        raise private_api.failure() from None
    return {"archived": True}
