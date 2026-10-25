"""One real account, whole-unit, buy-only funding. No brokerage execution."""
from __future__ import annotations

from copy import deepcopy
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR
from datetime import date
import hashlib
import json
import re
from uuid import uuid4

from .portfolio import execution_security_label
from .tase_data import TASE_ISRAEL_ASSET_IDS
from .allocation_mode import validate_allocation_mode


class CompanionError(ValueError):
    """Safe companion configuration errors, with no account amounts."""


def number(value, *, positive=False):
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError("Enter a valid number.") from exc
    if not result.is_finite() or result < 0 or (positive and result == 0):
        raise ValueError("Amounts and units must be finite and non-negative.")
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def security(identifier, market, currency=None, label=None):
    identifier = str(identifier).strip().upper()
    if market not in {"US", "TASE"}:
        raise ValueError("Choose US or TASE.")
    currency = currency or ("ILS" if market == "TASE" else "USD")
    if currency not in {"USD", "ILS"} or (market == "US" and currency != "USD"):
        raise ValueError("Unsupported execution currency.")
    if market == "TASE":
        if not re.fullmatch(r"\d{6,8}", identifier):
            raise ValueError("Enter an actual numeric TASE security ID, not an index.")
        identifier = identifier.lstrip("0")
    elif not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,14}", identifier):
        raise ValueError("Enter a US ticker.")
    return {"id": f"{market}:{identifier}", "identifier": identifier, "market": market,
            "currency": currency, "label": label or identifier}


def execution_security(asset, currency):
    label = execution_security_label(asset, currency)
    matches = re.findall(r"\b\d{7}\b", label)
    identifier = TASE_ISRAEL_ASSET_IDS.get(asset) or (matches[-1] if matches else None)
    if currency == "ILS" and not identifier:
        raise ValueError(f"{asset}: no verified executable TASE security mapping.")
    return security(identifier or asset, "TASE" if identifier else "US", currency, label)


def combined_targets(sleeves):
    if not sleeves or abs(sum(float(s["weight"]) for s in sleeves) - 100) > 1e-8:
        raise ValueError("Portfolio sleeve weights must total 100%.")
    instruments, targets = {}, {}
    for sleeve in sleeves:
        weight = number(sleeve["weight"], positive=True) / 100
        allocation = sleeve["target_weights"]
        if abs(sum(float(w) for w in allocation.values()) - 1) > 1e-8:
            raise ValueError("A sleeve's executable targets do not total 100%.")
        for asset, asset_weight in allocation.items():
            target = weight * number(asset_weight)
            if not target:
                continue
            instrument = execution_security(asset, sleeve["currency"])
            key = instrument["id"]
            if key in instruments and instruments[key]["currency"] != instrument["currency"]:
                raise ValueError("Conflicting execution currencies for the same security.")
            instruments.setdefault(key, instrument)
            targets[key] = targets.get(key, Decimal(0)) + target
    return instruments, {key: float(value) for key, value in targets.items()}


def empty_account():
    return {"version": 1, "revision": 0, "positions": {}, "cash_ils": "0", "last_operation_id": None}


def validate_account(account):
    if not isinstance(account, dict) or account.get("version") != 1:
        raise ValueError("Unrecognised holdings record; refusing to overwrite it.")
    if not isinstance(account.get("revision"), int) or account["revision"] < 0:
        raise ValueError("Invalid holdings revision.")
    number(account["cash_ils"])
    positions = account.get("positions")
    if not isinstance(positions, dict) or len(positions) > 200:
        raise ValueError("Holdings must contain at most 200 funds.")
    for key, row in positions.items():
        if not isinstance(row, dict) or not {"id", "identifier", "market", "currency", "label", "units"}.issubset(row):
            raise ValueError("A holding is missing its security details or units.")
        if not isinstance(row["label"], str) or not row["label"].strip():
            raise ValueError("A holding needs a fund label.")
        instrument = security(row["identifier"], row["market"], row["currency"])
        if instrument["id"] != key or row.get("id") != key:
            raise ValueError("Holdings security ID mismatch.")
        units = number(row["units"])
        if not isinstance(row.get("outside_rebalance", False), bool):
            raise ValueError("Outside the rebalance must be on or off.")
        anchor = row.get("companion_of")
        if anchor is not None:
            try:
                market, identifier = anchor.split(":", 1)
                valid = isinstance(anchor, str) and security(identifier, market)["id"] == anchor
            except (ValueError, AttributeError):
                valid = False
            if not valid:
                raise CompanionError("Companion of must be a valid security ID, or empty.")
            if row.get("outside_rebalance", False):
                raise CompanionError("A holding cannot be both a companion and outside the rebalance.")
            if anchor == key:
                raise CompanionError("A holding cannot be its own companion.")
            if positions.get(anchor, {}).get("companion_of"):
                raise CompanionError("Companion chains are not supported; choose a target fund as the anchor.")
        if row["market"] == "TASE" and units != units.to_integral_value():
            raise ValueError("TASE holdings require whole units.")
        if row.get("manual_price") is not None:
            number(row["manual_price"], positive=True)
            if not row.get("manual_price_date"):
                raise ValueError("Manual prices need an observation date.")
            date.fromisoformat(row["manual_price_date"])
        number(row.get("minimum_ils", "0"))
    if account.get("manual_fx") is not None:
        number(account["manual_fx"], positive=True)
        if not account.get("manual_fx_date"):
            raise ValueError("Manual FX needs an observation date.")
        date.fromisoformat(account["manual_fx_date"])
    return deepcopy(account)


def excluded_holdings(account, targets):
    """Unmatched companions act exactly like explicitly outside holdings."""
    outside = {k for k, row in account["positions"].items() if row.get("outside_rebalance", False)}
    return outside | {k for k, row in account["positions"].items() if row.get("companion_of")
                      and (row["companion_of"] not in targets or row["companion_of"] in outside)}


def rebalance_targets(account, targets):
    """Remove explicitly excluded funds, retaining relative included targets."""
    excluded = excluded_holdings(account, targets)
    if any(row.get("companion_of") and k in targets for k, row in account["positions"].items()):
        raise CompanionError("A target fund cannot also be a companion. Clear its companion selection first.")
    if not excluded.intersection(targets):
        return dict(targets)
    included = {k: number(w) for k, w in targets.items() if k not in excluded}
    weight = sum(included.values(), Decimal(0))
    return {k: float(w / weight) for k, w in included.items()} if weight else {}


def compare_holdings(account, instruments, targets, quotes, fx):
    validate_account(account)
    targets = rebalance_targets(account, targets)
    excluded = excluded_holdings(account, targets)
    values = {}
    for key in set(targets) | set(account["positions"]):
        if key in excluded:
            continue
        units = number(account["positions"].get(key, {}).get("units", 0))
        quote = quotes.get(key)
        if units and (not quote or quote.get("error")):
            raise ValueError(f"{key}: price unavailable; account weights cannot be calculated.")
        rate = number(fx, positive=True) if instruments[key]["currency"] == "USD" else Decimal(1)
        values[key] = units * number(quote["price"], positive=True) * rate if units else Decimal(0)
    total = sum(values.values()) + number(account["cash_ils"])
    combined = dict(values)
    companions = {k: p["companion_of"] for k, p in account["positions"].items() if p.get("companion_of")}
    for key, anchor in companions.items():
        if anchor in targets:
            combined[anchor] = combined.get(anchor, Decimal(0)) + values[key]
    rows = []
    for key in sorted(values):
        if key in companions:
            rows.append({"id": key, "Fund": instruments[key]["label"], "Value (₪)": float(values[key]),
                         "Target %": None, "Actual %": None, "Gap (₪)": None,
                         "Status": "Companion", "companion_of": companions[key]})
            continue
        target = number(targets.get(key, 0))
        actual = combined[key] / total if total else None
        gap = target * total - combined[key]
        rows.append({"id": key, "Fund": instruments[key]["label"], "Value (₪)": float(values[key]),
                     "Target %": float(target), "Actual %": float(actual) if actual is not None else None,
                     "Gap (₪)": float(gap), "Status": "Not held yet" if actual is None else
                     "Underweight" if gap > Decimal("0.01") else "Overweight" if gap < Decimal("-0.01") else "On target"})
    rows.extend({"id": key, "Fund": instruments[key]["label"], "Value (₪)": None,
                 "Target %": None, "Actual %": None, "Gap (₪)": None,
                 "Status": "Outside the rebalance",
                 **({"companion_of": companions[key]} if key in companions else {})} for key in sorted(excluded))
    return rows, combined, total


def make_buy_plan(account, instruments, targets, quotes, fx, new_money, context, allocation_mode):
    """Buy whole units within gaps; proportional shares are never redistributed."""
    allocation_mode = validate_allocation_mode(allocation_mode)
    targets = rebalance_targets(account, targets)
    # A skipped, unpriced anchor is still a selected target. Its companion must
    # not become "unmatched" just because this partial plan cannot buy it.
    valuation_targets = context.get("targets", targets) if any(p.get("companion_of") for p in account["positions"].values()) else targets
    rows, values, total = compare_holdings(account, instruments, valuation_targets, quotes, fx)
    excluded = excluded_holdings(account, valuation_targets)
    new_money = number(new_money)
    budget = number(account["cash_ils"]) + new_money
    gaps, costs, minimums = {}, {}, {}
    for key, weight in targets.items():
        quote = quotes.get(key)
        if not quote or quote.get("error") or not quote.get("fresh"):
            raise ValueError(f"{key}: a fresh, actual per-unit price is required.")
        costs[key] = number(quote["price"], positive=True) * (number(fx, positive=True) if instruments[key]["currency"] == "USD" else 1)
        gaps[key] = max(Decimal(0), number(weight) * (total + new_money) - values.get(key, Decimal(0)))
        minimum = number(account["positions"].get(key, {}).get("minimum_ils", 0))
        minimums[key] = max(1, int((minimum / costs[key]).to_integral_value(rounding=ROUND_CEILING)))
    # A stale non-target holding also invalidates account weights and the plan.
    for key, position in account["positions"].items():
        if key in excluded:
            continue
        if number(position["units"]) and not quotes[key].get("fresh"):
            raise ValueError(f"{key}: holding valuation is stale; refresh or enter a dated broker price.")
    unspent = {}
    if allocation_mode == "proportional":
        gap_total = sum(gaps.values(), Decimal(0))
        shares = {key: min(gap, budget * gap / gap_total) if gap_total else Decimal(0)
                  for key, gap in gaps.items()}
        quantities = {key: int((shares[key] / costs[key]).to_integral_value(rounding=ROUND_FLOOR))
                      for key in gaps}
        quantities = {key: qty if qty >= minimums[key] else 0 for key, qty in quantities.items()}
        unspent = {key: str(shares[key] - costs[key] * quantities[key]) for key in gaps}
        remaining = budget - sum((costs[k] * q for k, q in quantities.items()), Decimal(0))
    else:
        low, high = Decimal(0), max(gaps.values(), default=Decimal(0))
        for _ in range(100):
            level = (low + high) / 2
            if sum(max(Decimal(0), gap-level) for gap in gaps.values()) > budget:
                low = level
            else:
                high = level
        quantities = {key: int((max(Decimal(0), gap-high) / costs[key]).to_integral_value(rounding=ROUND_FLOOR)) for key, gap in gaps.items()}
        quantities = {key: qty if qty >= minimums[key] else 0 for key, qty in quantities.items()}
        remaining = budget - sum(costs[k] * q for k, q in quantities.items())
        while True:
            eligible = []
            for key in quantities:
                gap = gaps[key] - quantities[key] * costs[key]
                lot = minimums[key] if quantities[key] == 0 else 1
                if lot * costs[key] <= min(gap, remaining):
                    eligible.append((gap, key, lot))
            if not eligible:
                break
            eligible.sort(key=lambda item: (-item[0], item[1]))
            gap, key, lot = eligible[0]
            next_gap = eligible[1][0] if len(eligible) > 1 else Decimal(0)
            batch = max(lot, int(((gap-next_gap) / costs[key]).to_integral_value(rounding=ROUND_CEILING)))
            batch = min(batch, int((min(gap, remaining) / costs[key]).to_integral_value(rounding=ROUND_FLOOR)))
            quantities[key] += batch
            remaining -= batch * costs[key]
    orders = [{"id": key, "units": qty, "price_native": str(number(quotes[key]["price"])),
               "estimated_ils": str(costs[key] * qty)} for key, qty in sorted(quantities.items()) if qty]
    return {"id": str(uuid4()), "account_hash": fingerprint(account), "context_hash": fingerprint(context),
            "new_money": str(new_money), "available_ils": str(budget), "orders": orders,
            "leftover_ils": str(remaining), "unspent_by_fund": unspent,
            "unit_costs_ils": {k: str(costs[k]) for k in unspent},
            "instruments": {k: instruments[k] for k in quantities}}


def apply_purchases(account, plan, confirmations, context):
    if account.get("last_operation_id") == plan["id"]:
        return deepcopy(account)
    if fingerprint(account) != plan["account_hash"] or fingerprint(context) != plan["context_hash"]:
        raise ValueError("Holdings, targets, prices or budget changed. Generate a fresh buy list.")
    updated = validate_account(account)
    orders = {order["id"]: order for order in plan["orders"]}
    if len({row["id"] for row in confirmations}) != len(confirmations):
        raise ValueError("Duplicate purchase confirmation.")
    spent = Decimal(0)
    for row in confirmations:
        key = row["id"]
        if key not in orders:
            raise ValueError("Purchase was not in this buy list.")
        units = number(row["units"])
        paid = number(row["paid_ils"])
        if units != units.to_integral_value() or units > orders[key]["units"]:
            raise ValueError("Confirm whole units, no greater than the proposed order.")
        if bool(units) != bool(paid):
            raise ValueError("Enter both units bought and the actual ₪ amount paid, or zero for both.")
        if units:
            position = updated["positions"].setdefault(key, {**plan["instruments"][key], "units": "0"})
            position["units"] = str(number(position["units"]) + units)
            spent += paid
    if spent > number(plan["available_ils"]):
        raise ValueError("Actual purchases exceed the cash budget. Correct the amounts or generate a new plan.")
    updated["cash_ils"] = str(number(plan["available_ils"]) - spent)
    updated["revision"] += 1
    updated["last_operation_id"] = plan["id"]
    return validate_account(updated)
