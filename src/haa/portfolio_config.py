"""Validate saved portfolio JSON without mutating browser/default state."""
import math

# Deliberately exact mappings: no silent Israel/leveraged/variant substitutions.
DEEP_HISTORY_MODEL_MAP = {
    "Century Momentum": "century_momentum", "HAA-Simple": "haa_simple",
    "Inflation Compass Standard": "inflation_compass", "GEM": "gem",
    "Chimeric Asset Allocation": "chimeric", "Buy and Hold SPY": "buy_and_hold_sp500",
    "Buy and Hold ACWI": "buy_and_hold_global",
    "A-RVol Shifter V3 Cash-Only": "rvol_synthetic",
}


def deep_history_portfolio_config(payload, models, specs):
    sleeves, capital = backtest_portfolio_config(payload, {**models, **specs})
    for sleeve in sleeves:
        original = sleeve["model"]
        key = original if original in specs else DEEP_HISTORY_MODEL_MAP.get(original)
        if key not in specs or key == "rvol_daily":
            raise ValueError(f"No compatible bundled Deep History for {original}. Choose its proxy manually; no variant was substituted.")
        sleeve["model"] = key
    if len({s["model"] for s in sleeves}) != len(sleeves):
        raise ValueError("Saved portfolio maps to duplicate proxy sleeves.")
    return sleeves, capital


def backtest_portfolio_config(payload, models):
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise ValueError("Choose a version-1 saved portfolio JSON file.")
    sleeves = payload.get("sleeves")
    if not isinstance(sleeves, list) or not sleeves or len(sleeves) > 100:
        raise ValueError("Saved portfolio must contain 1–100 sleeves.")
    cleaned = []
    for index, sleeve in enumerate(sleeves, 1):
        if not isinstance(sleeve, dict) or sleeve.get("model") not in models:
            raise ValueError("Saved portfolio contains an unknown strategy.")
        weight = float(sleeve.get("weight", float("nan")))
        if not math.isfinite(weight) or weight <= 0:
            raise ValueError("Saved sleeve weights must be positive and finite.")
        cleaned.append({"id": index, "weight": weight, "model": sleeve["model"]})
    if abs(sum(s["weight"] for s in cleaned)-100) > 1e-9:
        raise ValueError("Saved sleeve weights must total 100%.")
    capital, fx = float(payload.get("total_ils", 0)), float(payload.get("ils_per_usd", 0))
    if not math.isfinite(capital) or not math.isfinite(fx) or capital <= 0 or fx <= 0:
        raise ValueError("Saved capital and FX rate must be positive and finite.")
    return cleaned, capital/fx
