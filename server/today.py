"""Today: public sleeve calculations, fresh private read-only composition."""
from time import perf_counter
import math
import json
from pathlib import Path
import pandas as pd
from haa.constants import ASSETS
from haa.tase_data import plain_holding_provenance
from haa.model_catalog import MODEL_CATALOG, definition_for_label
from haa.portfolio_signals import portfolio_signal, monthly_strategy_input
from haa.portfolio import aggregate_holdings_by_currency, convert_currency, execution_security_label, total_weight
from haa.signals import month_to_date_snapshot, latest_preview_signal
from . import signals as signals_page
from .cache import ResultCache, data_version, digest
from .signals_presentation import display_allocation
from .signals_wire import clean, table

MODEL_OPTIONS = {m.label: m.model_class for m in MODEL_CATALOG}
RESULTS = ResultCache()
WORDS = json.loads((Path(__file__).resolve().parents[1]/"web/content/today.json").read_text())


def preview_for(model_label, all_prices):
    # The inner helper is verbatim app.py source; the frame is request-local,
    # never a mutable process-global frame shared by concurrent users.
    def next_portfolio_preview(model_label: str):
        """Return one sleeve's non-actionable current-month estimate."""
        if definition_for_label(model_label).strategy_mode == "buy_and_hold":
            return None, "This sleeve is held continuously and has no next-month timing preview."
        strategy = MODEL_OPTIONS[model_label]()
        if getattr(strategy, "execution_frequency", "monthly") == "daily":
            return None, "This sleeve uses completed daily signals, not a next-month preview. Review its daily Signals page."
        assets = getattr(strategy, "data_assets", ASSETS)
        prices = all_prices.loc[:, assets]
        market_assets = getattr(strategy, "market_data_assets", assets)
        monthly, _ = monthly_strategy_input(prices, market_assets)
        preview_monthly, price_as_of, reason = month_to_date_snapshot(monthly, prices, market_assets)
        if reason is not None or price_as_of is None:
            return None, reason or "No common current-month price row is available."
        if getattr(strategy, "uses_daily_signals", False):
            preview_decisions = strategy.decisions(prices.loc[:price_as_of], include_current_month=True)
        else:
            preview_input = preview_monthly.join(
                prices.drop(columns=list(market_assets), errors="ignore").reindex(preview_monthly.index, method="ffill")
            )
            preview_decisions = strategy.decisions(preview_input)
        status = latest_preview_signal(preview_decisions, price_as_of)
        if status.decision is None:
            return None, status.reason or "No preview is available."
        decision = status.decision
        weights = decision.get("target_weights", {decision["selected_asset"]: 1.0})
        return {"decision": decision, "weights": dict(weights), "price_as_of": status.price_as_of}, None
    return next_portfolio_preview(model_label)


class Unavailable(Exception):
    def __init__(self, payload):
        self.payload = payload


def utc_now():
    return pd.Timestamp.now(tz="UTC")


def cached_sleeve(definition, prices, metadata, warnings, code, clock, include_preview=True):
    """Public observations in, public cached piece out. No private inputs."""
    rows = {str(asset): [{"date": day.isoformat(), "value": clean(value)} for day, value in prices[asset].items()] for asset in prices}
    version = data_version(rows)
    strategy = definition.model_class()
    cutoff = str(strategy.completed_cutoff(clock)) if hasattr(strategy, "completed_cutoff") else None
    params = {"engine_code": code, "utc_date": str(clock.date()), "daily_cutoff": cutoff,
              "sources": digest(table(metadata)), "presentation": "today-v2", "content":digest(WORDS), "include_preview": include_preview}
    try:
        if warnings:
            # Retrieval failures must not be hidden by an earlier valid hit.
            result = build_sleeve(definition, prices, metadata, warnings, include_preview)
            return result, {"hit": None, "warnings": ["Unavailable or degraded sleeve result was not cached."]}, version
        result, info = RESULTS.run(model=definition.label, params=params, start=str(prices.index.min()), end=str(prices.index.max()),
                                  version=version, compute=lambda: build_sleeve(definition, prices, metadata, warnings, include_preview))
    except Unavailable as exc:
        result = exc.payload
        info = {"hit": None, "warnings": ["Unavailable or degraded sleeve result was not cached."]}
    return result, info, version


def build_sleeve(definition, prices, metadata, warnings, include_preview=True):
    model = definition.model_class
    signal, reason = portfolio_signal(model, prices)
    result = {"model": definition.label, "currency": definition.execution_currency,
              "current": None, "reason": reason, "preview": None, "preview_reason": None,
              "metadata": table(metadata), "warnings": list(warnings), "data_ranges": table(signals_page.data.date_ranges(prices))}
    if getattr(model, "actual_history_only", False):
        assets = getattr(model, "data_assets", ASSETS)
        provenance = plain_holding_provenance(metadata, assets)
        result["provenance"] = table(provenance)
        result["provenance_csv"] = provenance.to_csv()
        result["history_note"] = WORDS["buyHoldNote"]
        for asset, row in provenance.iterrows():
            if row.history_kind != "Actual fund history":
                result["warnings"].append(WORDS["proxyWarning"].format(asset=asset,kind=row.history_kind))
            elif row.price_field in {"Published ETF NAV", "End-of-day close"}:
                result["warnings"].append(WORDS["totalReturnWarning"].format(asset=asset,field=row.price_field))
    if signal is not None:
        decision = signal["decision"]
        result["current"] = {"decision": signals_page.decision_record(decision), "weights": signal["weights"],
            "signal_date": pd.Timestamp(decision.name).isoformat(), "regime": decision["regime"],
            "trade": bool(decision.get("trade", False)),
            "holding": display_allocation(signal["weights"], definition.execution_currency),
            "status": f"Ready · {decision['regime']}"}
    if not include_preview:
        result = clean(result)
        if warnings or signal is None: raise Unavailable(result)
        return result
    try:
        preview, error = preview_for(definition.label, prices)
    except Exception as exc:
        result["preview_reason"] = signals_page.safe_error(exc)
        raise Unavailable(clean(result)) from None
    result["preview_reason"] = error
    if preview is not None:
        result["preview"] = {"decision": signals_page.decision_record(preview["decision"]), "weights": preview["weights"],
                             "price_as_of": preview["price_as_of"].isoformat(),
                             "allocation": display_allocation(preview["weights"], definition.execution_currency)}
    skipped_preview = definition.strategy_mode == "buy_and_hold" or getattr(model, "execution_frequency", "monthly") == "daily"
    # Expected continuous/daily messages are not failures. Missing monthly
    # previews, failed inputs and unavailable current signals are not cached.
    result = clean(result)
    if warnings or signal is None or (preview is None and not skipped_preview):
        raise Unavailable(result)
    return result


def public_sleeve(label, code, clock=None, include_preview=True):
    """No portfolio, user, sleeve weight, capital or FX arguments enter here."""
    started = perf_counter()
    clock = utc_now() if clock is None else pd.Timestamp(clock)
    definition = definition_for_label(label)
    try:
        prices, metadata, warnings = signals_page.load_inputs(definition)
        prices = prices.loc[prices.index <= clock.tz_localize(None)]
        loaded = perf_counter()
        result, cache, version = cached_sleeve(definition, prices, metadata, warnings, code, clock, include_preview)
        result.update(cache=cache, data_version=version, fallback_warnings=[signals_page.LIVE_NOTICE],
                      timing={"load_seconds": round(loaded-started, 6), "calculation_or_cache_seconds": round(perf_counter()-loaded, 6),
                              "total_seconds": round(perf_counter()-started, 6)})
        return clean(result)
    except Exception as exc:
        return {"model": label, "currency": definition.execution_currency, "current": None,
                "reason": signals_page.safe_error(exc), "preview": None, "preview_reason": signals_page.safe_error(exc),
                "warnings": [], "fallback_warnings": [signals_page.LIVE_NOTICE], "metadata": None, "data_ranges": None,
                "cache": {"hit": None, "warnings": ["Failed sleeve result was not cached."]},
                "timing": {"total_seconds": round(perf_counter()-started, 6)}}


def finite(value, *, positive=False):
    if isinstance(value, bool) or value is None:
        raise ValueError()
    value = float(value)
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise ValueError()
    return value


def compose(portfolios, code, clock=None, include_preview=True):
    """Fresh private composition, never passed to ResultCache or a save helper."""
    started = perf_counter()
    clock = utc_now() if clock is None else pd.Timestamp(clock)
    defaults = [p for p in portfolios if isinstance(p, dict) and p.get("is_default") is True]
    result = {"has_default": bool(defaults), "caption": None, "issues": [], "signals": [], "holdings": None,
              "monthly_action": "unavailable", "latest_caption": None, "stale": False,
              "previews": [], "preview_caption": None, "warnings": [], "public_sleeves": [], "shared_holdings": [], "timing": {}}
    if not defaults:
        return result
    if len(defaults) != 1:
        result["issues"].append("multiple_defaults")
        return result
    payload = defaults[0].get("payload")
    if not isinstance(payload, dict):
        result["issues"].append("invalid_payload")
        return result
    name = payload.get("name")
    if isinstance(name, str) and name.strip():
        result["caption"] = f"{name} · private synced portfolio"
    else:
        result["issues"].append("missing_name")
    saved_sleeves = payload.get("sleeves")
    if not isinstance(saved_sleeves, list) or not saved_sleeves:
        result["issues"].append("missing_sleeves")
        return result
    if len(saved_sleeves) > 100:
        result["issues"].append("invalid_sleeves")
        return result
    valid_sleeves, signal_dates, changed_models, current_weights_by_model, normalized = [], [], [], {}, []
    all_weights = True
    for raw in saved_sleeves:
        sleeve = raw if isinstance(raw, dict) else {}
        label = sleeve.get("model")
        row = {"label": label if isinstance(label, str) else None, "weight": None, "weight_text": None,
               "holding": None, "status": None, "error_code": None}
        try:
            weight = finite(sleeve.get("weight"), positive=True)
            row.update(weight=weight/100, weight_text=f"{weight/100:.2%}")
            normalized.append({"weight": weight})
        except (ValueError, TypeError, OverflowError):
            weight, all_weights, row["error_code"] = None, False, "invalid_weight"
        if not isinstance(label, str) or label not in MODEL_OPTIONS:
            row["error_code"] = "unknown_model"
            result["signals"].append(row)
            result["previews"].append({"label": row["label"], "allocation": None, "change": None, "price_as_of": None, "error_code": "unknown_model", "reason": None})
            continue
        # Only this public label goes into the public loader/calculation cache.
        public = public_sleeve(label, code, clock) if include_preview else public_sleeve(label, code, clock, False)
        result["public_sleeves"].append(public)
        result["warnings"] += public.get("warnings", []) + public.get("fallback_warnings", []) + public["cache"]["warnings"]
        signal = public["current"]
        if signal is not None and weight is not None:
            row.update(holding=signal["holding"], status=signal["status"])
            decision = signal["decision"]
            signal_dates.append(pd.Timestamp(signal["signal_date"]))
            if bool(decision.get("trade", False)):
                changed_models.append(label)
            current_weights_by_model[label] = signal["weights"]
            valid_sleeves.append({"name": label, "weight": weight, "currency": public["currency"], "target_weights": signal["weights"]})
        elif weight is not None:
            row["status"] = public["reason"]
        result["signals"].append(row)
        projected = public["preview"]
        result["previews"].append({"label": label, "allocation": projected["allocation"] if projected else None,
            "change": ("yes" if projected["weights"] != current_weights_by_model.get(label) else "no") if projected else None,
            "price_as_of": pd.Timestamp(projected["price_as_of"]).date().isoformat() if projected else None,
            "reason": public["preview_reason"], "error_code": None})
    saved_total_weight = total_weight(normalized) if all_weights else None
    valid = len(valid_sleeves) == len(saved_sleeves) and saved_total_weight is not None and abs(saved_total_weight - 100.0) < 1e-9
    if valid:
        try:
            total_ils = finite(payload.get("total_ils"))
            saved_fx = finite(payload.get("ils_per_usd"), positive=True)
            grouped_holdings = aggregate_holdings_by_currency(valid_sleeves)
            groups = []
            for currency, holdings in grouped_holdings.items():
                holding_rows = []
                for asset, values in sorted(holdings.items()):
                    ils_allocation = total_ils * values["weight"]
                    amount = convert_currency(ils_allocation, "ILS", currency, saved_fx)
                    if not math.isfinite(amount):
                        raise ValueError()
                    holding_rows.append({"holding": execution_security_label(asset, currency), "weight": values["weight"],
                        "amount": amount, "weight_text": f'{values["weight"]:.2%}', "amount_text": f"{amount:,.2f}"})
                    if len(values["sleeves"]) > 1:
                        result["shared_holdings"].append({"holding": execution_security_label(asset,currency), "currency":currency, "amount":amount})
                groups.append({"currency": currency, "rows": holding_rows})
            result["holdings"] = groups
            for row, sleeve in zip(result["signals"], valid_sleeves):
                own = aggregate_holdings_by_currency([sleeve])
                row["amounts"] = [{"holding": execution_security_label(asset, currency), "currency": currency,
                    "amount": convert_currency(total_ils*values["weight"], "ILS", currency, saved_fx)}
                    for currency, holdings in own.items() for asset, values in sorted(holdings.items())]
        except (ValueError, TypeError, OverflowError):
            result["issues"].append("invalid_capital_fx")
    result["monthly_action"] = "changed" if changed_models else "unchanged" if valid else "unavailable"
    if signal_dates:
        newest_signal_date = max(signal_dates)
        result["latest_caption"] = f"Latest completed signal: {newest_signal_date:%Y-%m-%d}"
        result["stale"] = (clock.tz_localize(None).normalize() - newest_signal_date.tz_localize(None).normalize()).days > 45
    preview_dates = [pd.Timestamp(p["price_as_of"]) for p in result["previews"] if p["price_as_of"]]
    if preview_dates:
        result["preview_caption"] = f"Uses the latest common eligible price data for each sleeve (latest: {max(preview_dates):%Y-%m-%d}). The official portfolio remains the completed-month signal above."
    result["warnings"] = list(dict.fromkeys(result["warnings"]))
    result["timing"] = {"total_seconds": round(perf_counter()-started, 6),
                        "sleeves": [{"model": p["model"], **p["timing"], "cache_hit": p["cache"]["hit"]} for p in result["public_sleeves"]]}
    return clean(result)
