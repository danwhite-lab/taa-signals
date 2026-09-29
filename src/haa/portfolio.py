"""Pure helpers for combining already-calculated strategy sleeve signals."""
from __future__ import annotations

from collections import defaultdict
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Iterable, Mapping


SUPPORTED_CURRENCIES = ("USD", "ILS")
PORTFOLIO_CONFIG_VERSION = 1

# Execution labels are deliberately separate from canonical strategy asset
# codes.  The latter remain stable for data retrieval and signal calculation.
EXECUTION_SECURITY_LABELS = {
    ("ILS", "CSPX_IL"): "CSPX — 1159250",
    ("ILS", "IEF_IL"): "IEF — iShares $ Treasury Bond 7–10yr UCITS — 1159268",
    ("ILS", "SPMO_IL"): "MTF Tracking S&P 500 Momentum (4D) — 5140850",
    ("ILS", "AYALON_KASPIT"): "Keren Kaspit — 5136866",
    ("ILS", "IEF"): "IEF — iShares $ Treasury Bond 7–10yr UCITS — 1159268",
    ("ILS", "XLK"): "XLK — iShares S&P 500 IT UCITS — 1159193",
    ("ILS", "XLU"): "XLU — MTF S&P Utilities — 1150507",
    ("ILS", "XLE"): "XLE — KSM ETF S&P Energy — 1145903",
    ("ILS", "XLP"): "XLP — MTF S&P Consumer Staples — 1150366",
    ("ILS", "TA125_SMART_MOMENTUM"): "Migdal MTF TA-125 Smart Momentum — 5134713",
    ("ILS", "XLE_IL"): "KSM ETF S&P Energy — 1145903",
    ("ILS", "XLK_IL"): "iShares S&P 500 IT UCITS — 1159193",
    ("ILS", "XLV_IL"): "MTF סל S&P Health Care (4D) — 1150390",
    ("ILS", "XLP_IL"): "MTF S&P Consumer Staples — 1150366",
    ("USD", "BIL"): "BIL USD - 5139076",
}


def execution_security_label(asset: str, currency: str) -> str:
    """Return the broker-facing security label without changing canonical symbols."""
    return EXECUTION_SECURITY_LABELS.get((currency, asset), asset)


def total_weight(sleeves: Iterable[Mapping[str, object]]) -> float:
    return sum(float(sleeve["weight"]) for sleeve in sleeves)


def aggregate_holdings(sleeves: Iterable[Mapping[str, object]]) -> dict[str, dict[str, object]]:
    """Aggregate executable target weights from valid, fully weighted sleeves."""
    holdings: dict[str, dict[str, object]] = defaultdict(lambda: {"weight": 0.0, "sleeves": []})
    for sleeve in sleeves:
        sleeve_weight = float(sleeve["weight"]) / 100
        for asset, target_weight in dict(sleeve["target_weights"]).items():
            row = holdings[asset]
            row["weight"] = float(row["weight"]) + sleeve_weight * float(target_weight)
            row["sleeves"].append(str(sleeve["name"]))
    return dict(holdings)


def aggregate_holdings_by_currency(sleeves: Iterable[Mapping[str, object]]) -> dict[str, dict[str, dict[str, object]]]:
    """Aggregate holdings without ever combining different execution currencies."""
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for sleeve in sleeves:
        grouped[str(sleeve["currency"])].append(sleeve)
    return {currency: aggregate_holdings(currency_sleeves) for currency, currency_sleeves in grouped.items()}


def convert_currency(amount: float, from_currency: str, to_currency: str, ils_per_usd: float) -> float:
    """Convert an amount using an ILS-per-USD quote."""
    if ils_per_usd <= 0:
        raise ValueError("ILS per USD exchange rate must be positive.")
    if from_currency == to_currency:
        return float(amount)
    if {from_currency, to_currency} != {"USD", "ILS"}:
        raise ValueError(f"Unsupported currency conversion: {from_currency} to {to_currency}.")
    return float(amount) * ils_per_usd if from_currency == "USD" else float(amount) / ils_per_usd


def funding_plan(
    sleeves: Iterable[Mapping[str, object]],
    total_ils: float,
    ils_per_usd: float,
) -> dict[str, object]:
    """Calculate native-currency sleeve funding from one ILS portfolio value."""
    if total_ils < 0:
        raise ValueError("Total available capital cannot be negative.")
    required = {"USD": 0.0, "ILS": 0.0}
    sleeve_allocations = []
    for sleeve in sleeves:
        currency = str(sleeve["currency"])
        if currency not in SUPPORTED_CURRENCIES:
            raise ValueError(f"Unsupported sleeve currency: {currency}.")
        target_ils = float(total_ils) * float(sleeve["weight"]) / 100
        target_native = convert_currency(target_ils, "ILS", currency, ils_per_usd)
        required[currency] += target_native
        sleeve_allocations.append({
            **dict(sleeve),
            "allocation_ils": target_ils,
            "allocation_native": target_native,
        })
    return {
        "total_ils": float(total_ils),
        "total_usd": convert_currency(total_ils, "ILS", "USD", ils_per_usd),
        "required": required,
        "sleeves": sleeve_allocations,
    }


def export_portfolio_config(name: str, sleeves: Iterable[Mapping[str, object]], total_ils: float, ils_per_usd: float) -> bytes:
    """Create a portable, user-owned portfolio configuration file."""
    payload = {
        "version": PORTFOLIO_CONFIG_VERSION,
        "name": str(name).strip() or "Portfolio",
        "total_ils": float(total_ils),
        "ils_per_usd": float(ils_per_usd),
        "sleeves": [{"model": str(sleeve["model"]), "weight": float(sleeve["weight"])} for sleeve in sleeves],
    }
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def import_portfolio_config(content: bytes, valid_models: Iterable[str]) -> dict[str, object]:
    """Validate a saved configuration before it can replace an active portfolio."""
    try:
        payload = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Saved portfolio must be a valid UTF-8 JSON file.") from exc
    if not isinstance(payload, dict) or payload.get("version") != PORTFOLIO_CONFIG_VERSION:
        raise ValueError("This is not a supported portfolio configuration file.")
    valid = set(valid_models)
    sleeves = payload.get("sleeves")
    if not isinstance(sleeves, list) or not sleeves:
        raise ValueError("Saved portfolio must contain at least one sleeve.")
    restored = []
    for sleeve in sleeves:
        if not isinstance(sleeve, dict) or sleeve.get("model") not in valid:
            raise ValueError("Saved portfolio contains an unknown model.")
        try:
            weight = float(sleeve["weight"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Each saved sleeve needs a numeric weight.") from exc
        if not 0 <= weight <= 100:
            raise ValueError("Each saved sleeve weight must be between 0% and 100%.")
        restored.append({"model": sleeve["model"], "weight": weight})
    try:
        total_ils = float(payload["total_ils"])
        ils_per_usd = float(payload["ils_per_usd"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("Saved portfolio is missing a valid capital or FX value.") from exc
    if total_ils < 0 or ils_per_usd <= 0:
        raise ValueError("Saved portfolio contains invalid capital or FX values.")
    return {"name": str(payload.get("name") or "Portfolio"), "sleeves": restored, "total_ils": total_ils, "ils_per_usd": ils_per_usd}


class PortfolioGistError(RuntimeError):
    """Raised when the private Gist portfolio store cannot be used."""


def _gist_request(token: str, gist_id: str, method: str = "GET", payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = Request(f"https://api.github.com/gists/{gist_id}", data=body, method=method, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "Content-Type": "application/json", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raise PortfolioGistError(f"Private portfolio store returned GitHub error {exc.code}. Check the Gist ID and token's Gist permission.") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise PortfolioGistError("Could not reach the private portfolio store. Check your connection and try again.") from exc


def load_portfolio_from_gist(token: str, gist_id: str, filename: str = "portfolio.json") -> bytes:
    response = _gist_request(token, gist_id)
    file = response.get("files", {}).get(filename)
    if not isinstance(file, dict) or not isinstance(file.get("content"), str):
        raise PortfolioGistError("No saved portfolio exists in the configured private Gist yet.")
    return file["content"].encode("utf-8")


def save_portfolio_to_gist(token: str, gist_id: str, content: bytes, filename: str = "portfolio.json") -> None:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PortfolioGistError("Portfolio content must be UTF-8 text.") from exc
    _gist_request(token, gist_id, "PATCH", {"files": {filename: {"content": text}}})
