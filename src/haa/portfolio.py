"""Pure helpers for combining already-calculated strategy sleeve signals."""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Mapping


SUPPORTED_CURRENCIES = ("USD", "ILS")


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
