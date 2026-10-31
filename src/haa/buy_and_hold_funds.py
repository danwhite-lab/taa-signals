"""Data-driven definitions for standalone buy-and-hold fund implementations."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class BuyAndHoldFund:
    key: str
    name: str
    holding_asset: str
    currency: str
    source_status: str
    source_note: str
    catalog_variant: str
    catalog_implementation: str
    yahoo_ticker: str | None = None
    tase_security_id: str | None = None
    tase_security_type: str | None = None
    price_only: bool = False
    trading_fees: tuple[tuple[str, float], ...] = ()

    @property
    def is_tase_etf(self) -> bool:
        return self.tase_security_type == "etf"

    @property
    def fee_options(self) -> dict[str, float]:
        return dict(self.trading_fees)


def _definition_path() -> Path:
    return Path(__file__).resolve().parents[2] / "data" / "buy_and_hold_funds.json"


def _fund_from_raw(key: str, raw: dict[str, Any]) -> BuyAndHoldFund:
    required = ("name", "holding_asset", "currency", "source_status", "source_note", "catalog_variant", "catalog_implementation")
    missing = [field for field in required if not raw.get(field)]
    if missing:
        raise ValueError(f"{key}: buy-and-hold definition is missing {', '.join(missing)}.")
    has_yahoo = bool(raw.get("yahoo_ticker"))
    has_tase = bool(raw.get("tase_security_id"))
    if has_yahoo == has_tase:
        raise ValueError(f"{key}: define exactly one Yahoo ticker or TASE security ID.")
    if has_tase and raw.get("tase_security_type") not in {"etf", "mutual_fund"}:
        raise ValueError(f"{key}: TASE fund type must be etf or mutual_fund.")
    return BuyAndHoldFund(
        key=key,
        name=str(raw["name"]),
        holding_asset=str(raw["holding_asset"]),
        currency=str(raw["currency"]),
        source_status=str(raw["source_status"]),
        source_note=str(raw["source_note"]),
        catalog_variant=str(raw["catalog_variant"]),
        catalog_implementation=str(raw["catalog_implementation"]),
        yahoo_ticker=str(raw["yahoo_ticker"]) if has_yahoo else None,
        tase_security_id=str(raw["tase_security_id"]) if has_tase else None,
        tase_security_type=str(raw["tase_security_type"]) if has_tase else None,
        price_only=bool(raw.get("price_only", False)),
        trading_fees=tuple((str(name), float(value)) for name, value in dict(raw.get("trading_fees", {})).items()),
    )


def _load_funds() -> dict[str, BuyAndHoldFund]:
    with _definition_path().open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if not isinstance(raw, dict):
        raise ValueError("Buy-and-hold fund definitions must be a JSON object.")
    return {key: _fund_from_raw(key, value) for key, value in raw.items()}


BUY_AND_HOLD_FUNDS = _load_funds()


def fund(key: str) -> BuyAndHoldFund:
    return BUY_AND_HOLD_FUNDS[key]


def tase_asset_ids() -> dict[str, str]:
    return {item.holding_asset: item.tase_security_id for item in BUY_AND_HOLD_FUNDS.values() if item.tase_security_id}


def tase_etf_assets() -> frozenset[str]:
    return frozenset(item.holding_asset for item in BUY_AND_HOLD_FUNDS.values() if item.is_tase_etf)


def yahoo_tickers() -> dict[str, str]:
    return {item.holding_asset: item.yahoo_ticker for item in BUY_AND_HOLD_FUNDS.values() if item.yahoo_ticker}


def price_only_yahoo_assets() -> frozenset[str]:
    return frozenset(item.holding_asset for item in BUY_AND_HOLD_FUNDS.values() if item.price_only)


def declared_proxy_assets() -> frozenset[str]:
    return frozenset(item.holding_asset for item in BUY_AND_HOLD_FUNDS.values() if item.source_status == "proxy")
