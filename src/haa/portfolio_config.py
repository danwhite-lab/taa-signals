"""Validate saved portfolio JSON without mutating browser/default state."""
import math

TRANSFER_ERROR = "Saved transfer rule is invalid or its RVol sleeve is unavailable."


def portfolio_transfer_config(payload, sleeves=None):
    """Translate saved model identity to current row IDs; never calculate transfers.

    Percentages are percentage points, just like Backtest request inputs.
    Absent metadata is the legacy no-transfer configuration.
    """
    settings = dict(sleeve_rebalance_mode="none", rebalance_sleeve=None,
                    rebalance_cap=15., rebalance_target=10.)
    if not isinstance(payload, dict):
        raise ValueError(TRANSFER_ERROR)
    rule = payload.get("transfer_rule", {"mode": "none"})
    if not isinstance(rule, dict) or not isinstance(rule.get("mode"), str) or rule["mode"] not in {"none", "annual_target", "rvol_cap"}:
        raise ValueError(TRANSFER_ERROR)
    settings["sleeve_rebalance_mode"] = rule["mode"]
    if rule["mode"] != "rvol_cap":
        return settings
    model = rule.get("sleeve_model")
    rows = sleeves if sleeves is not None else payload.get("sleeves", [])
    if not isinstance(rows, list):
        raise ValueError(TRANSFER_ERROR)
    matches = [i for i, row in enumerate(rows, 1) if isinstance(row, dict) and row.get("model") == model]
    if not isinstance(model, str) or "RVol" not in model or len(matches) != 1:
        raise ValueError(TRANSFER_ERROR)
    try:
        if any(isinstance(rule.get(key), bool) for key in ("cap_percent", "target_percent")):
            raise ValueError()
        cap, target = float(rule["cap_percent"]), float(rule["target_percent"])
        if not all(math.isfinite(v) for v in (cap, target)) or not 1 <= cap <= 99 or not 1 <= target <= 98 or target >= cap:
            raise ValueError()
    except (KeyError, TypeError, ValueError, OverflowError):
        raise ValueError(TRANSFER_ERROR) from None
    # The cleaned sleeve IDs are assigned by backtest_portfolio_config. Never
    # reuse arbitrary IDs from a saved JSON file or silently pick another RVol.
    row = rows[matches[0]-1]
    settings.update(rebalance_sleeve=row["id"] if sleeves is not None else matches[0],
                    rebalance_cap=cap, rebalance_target=target)
    return settings

# Deliberately exact mappings: no silent Israel/leveraged/variant substitutions.
DEEP_HISTORY_MODEL_MAP = {
    "Century Momentum": "century_momentum", "HAA-Simple": "haa_simple",
    "Inflation Compass Standard": "inflation_compass", "GEM": "gem",
    "Chimeric Asset Allocation": "chimeric", "Buy and Hold SPY": "buy_and_hold_sp500",
    "Buy and Hold ACWI": "buy_and_hold_global",
    "Buy and Hold Gold GLD": "buy_and_hold_gld",
    "Buy and Hold IEF": "buy_and_hold_ief",
    "A-RVol Shifter V3 Cash-Only": "rvol_synthetic",
}


def deep_history_portfolio_config(payload, models, specs):
    # Reject before backtest_portfolio_config can divide ILS capital by saved FX.
    if isinstance(payload, dict) and isinstance(payload.get("sleeves"), list):
        if any(isinstance(row, dict) and row.get("model") in specs
               and specs[row["model"]].currency != "USD" for row in payload["sleeves"]):
            from .deep_history import ILS_RESEARCH_FX_ERROR
            raise ValueError(ILS_RESEARCH_FX_ERROR)
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


def backtest_portfolio_config(payload, models, *, require_total=True):
    """Strict for all consumers; only confirmed draft saves may relax the total."""
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
    if require_total and abs(sum(s["weight"] for s in cleaned)-100) > 1e-9:
        raise ValueError("Saved sleeve weights must total 100%.")
    capital, fx = float(payload.get("total_ils", 0)), float(payload.get("ils_per_usd", 0))
    if not math.isfinite(capital) or not math.isfinite(fx) or capital <= 0 or fx <= 0:
        raise ValueError("Saved capital and FX rate must be positive and finite.")
    return cleaned, capital/fx
