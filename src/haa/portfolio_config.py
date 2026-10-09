"""Validate saved portfolio JSON without mutating browser/default state."""
import math


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
