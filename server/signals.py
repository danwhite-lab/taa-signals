"""Signals-page orchestration/presentation; all decisions remain in haa.

No app.py import, evaluation, user settings, alternate data or JS calculations.
"""
from dataclasses import fields
import inspect
import os
from time import perf_counter

import pandas as pd

from haa import data, signals as engine_signals, tase_data
from haa.constants import ASSETS, FRED_ASSETS, OECD_CLI_DIFFUSION_ASSET
from haa.model_catalog import definition_for_label, strategies, variants, implementations, resolve
from haa.portfolio import execution_security_label
from haa.portfolio_signals import monthly_strategy_input

from .cache import ResultCache, data_version, digest
from .signals_presentation import display_allocation, rationale
from .signals_wire import clean, table

DISCLAIMER = "Rules-based informational signal only; not investment advice. You are responsible for any trading decision and execution."
LIVE_NOTICE = "Public inputs use complete original-loader snapshots cached for up to five minutes, or the existing live Yahoo/TASE/macro loaders on a miss. Original source fields and dates are preserved. No cached/live splice, gap fill or substituted source."
RESULTS = ResultCache()


def safe_error(exc):
    text = str(exc)
    for name in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_PUBLISHABLE_KEY", "CRON_SECRET"):
        key = os.environ.get(name)
        if key:
            text = text.replace(key, "[redacted]")
    return text


def mode_for(strategy, definition):
    return "daily" if getattr(strategy, "execution_frequency", "monthly") == "daily" else (
        "buy_and_hold" if definition.strategy_mode == "buy_and_hold" else "monthly")


def selector(definition):
    selected = resolve(definition.strategy, definition.variant, definition.implementation)
    return {"selected": {field.name: getattr(selected, field.name) for field in fields(selected) if field.name != "model_class"},
            "strategies": strategies(), "variants": variants(selected.strategy),
            "implementations": implementations(selected.strategy, selected.variant)}


def load_inputs(definition, *, daily_bars=False):
    from .input_cache import inputs
    return inputs(definition.model_class(), daily_bars,
                  lambda: live_inputs(definition, daily_bars=daily_bars))


def live_inputs(definition, *, daily_bars=False):
    strategy = definition.model_class()
    assets = tuple(getattr(strategy, "data_assets", ASSETS))
    # Same selected-model scope as app.assets_for_models, including its benchmark.
    runtime = tuple(dict.fromkeys((*assets, getattr(strategy, "benchmark_asset", "SPY"))))
    tase = tuple(asset for asset in runtime if asset in tase_data.TASE_ISRAEL_ASSET_IDS)
    fred = tuple(asset for asset in runtime if asset in FRED_ASSETS)
    oecd = OECD_CLI_DIFFUSION_ASSET in runtime
    yahoo = tuple(asset for asset in runtime if asset not in (*tase, *fred, OECD_CLI_DIFFUSION_ASSET))
    mapping = data.default_ticker_map(yahoo)
    strict = tuple(getattr(strategy, "us_data_assets", ())) if getattr(strategy, "signal_calendar", None) == "XNYS" else ()
    try:
        opens = None
        if daily_bars:
            downloaded, opens = data.download_yahoo_daily_bars(mapping)
        else:
            downloaded = (data.download_yahoo_prices(mapping, require_adjusted_assets=strict) if strict
                      else data.download_yahoo_prices(mapping)) if yahoo else pd.DataFrame()
    except Exception as exc:
        raise RuntimeError(f"Yahoo Finance download failed: {safe_error(exc)}") from None
    metadata = pd.DataFrame({"source": "Yahoo Finance", "identifier": [mapping[a] for a in yahoo],
                             "price_field": "Adj Close (Close fallback)"}, index=pd.Index(yahoo, name="asset"))
    failures = []
    for needed, loader, columns, prefix in (
        (bool(fred), lambda: data.download_fred_series(FRED_ASSETS), FRED_ASSETS, "FRED retrieval issue: "),
        (oecd, data.download_oecd_cli_diffusion, (OECD_CLI_DIFFUSION_ASSET,), "OECD CLI retrieval issue: "),
    ):
        if not needed:
            continue
        try:
            auxiliary = loader()
        except Exception as exc:
            detail = safe_error(exc)
            suffix = ". This signal is using the disclosed SPY/BIL failsafe." if columns == (OECD_CLI_DIFFUSION_ASSET,) else ""
            failures.append(prefix + detail + suffix)
            auxiliary = pd.DataFrame(columns=columns, dtype=float)
        downloaded = downloaded.join(auxiliary, how="outer")
    if tase:
        try:
            local, local_meta = tase_data.download_tase_israel_prices(tase)
        except tase_data.TaseDataError as exc:
            failures.append(f"Public TASE/Maya retrieval issue: {safe_error(exc)}")
            local = pd.DataFrame(columns=tase, dtype=float)
            local_meta = pd.DataFrame({"source": "TASE/Maya via tasekit (unavailable)",
                "identifier": [tase_data.TASE_ISRAEL_ASSET_IDS[a] for a in tase], "price_field": "Unavailable"},
                index=pd.Index(tase, name="asset"))
        downloaded = downloaded.join(local.reindex(columns=tase), how="outer")
        metadata = pd.concat([metadata, local_meta.reindex(tase)])
    metadata = metadata.reindex(runtime)
    if strict:
        metadata.loc[list(strict), "price_field"] = "Required adjusted close; no raw Close fallback"
    if daily_bars:
        metadata.loc[list(yahoo), "price_field"] = "Adjusted close and adjusted open from the same source; no raw Close fallback"
    for asset in fred:
        metadata.loc[asset] = {"source": "FRED", "identifier": asset, "price_field": "Daily observation"}
    if oecd:
        metadata.loc[OECD_CLI_DIFFUSION_ASSET] = {"source": "OECD SDMX", "identifier": "CLI diffusion (dynamic country panel)", "price_field": "Monthly observation; one-month lag"}
    result = data.combine_replacements(downloaded, {}, runtime), metadata, failures
    return (*result, opens) if daily_bars else result


def call_decisions(strategy, prices, as_of, **kwargs):
    if "as_of" in inspect.signature(strategy.decisions).parameters:
        kwargs["as_of"] = as_of
    return strategy.decisions(prices, **kwargs)


def decision_record(decision):
    if decision is None:
        return None
    return clean({"signal_date": pd.Timestamp(decision.name), **decision.to_dict(),
                  "target_weights": decision.get("target_weights", {decision["selected_asset"]: 1.0})})


def history_payload(decisions, prices, strategy, daily):
    if daily:
        dates = [c for c in ("decision_date", "scheduled_execution_date") if c in decisions]
        ordered = dates + [c for c in decisions.columns if c not in dates]
        return {"table": table(decisions.loc[:, ordered].sort_index(ascending=False)),
                "count": len(decisions), "csv": decisions.to_csv(), "filename": "rvol_shifter_daily_signals.csv",
                "download_label": "Download daily signal history CSV"}
    columns = ["regime", "selected_asset", "previous_asset", "trade"]
    if "target_weights" in decisions:
        columns.insert(2, "target_weights")
    if decisions.empty:
        history = pd.DataFrame(columns=[*columns, "effective_start"])
        history.index.name = "signal_date"
    else:
        history = decisions.loc[:, columns].copy()
        history["effective_start"] = [engine_signals.first_trading_day_after(prices, date, engine_signals.execution_assets(history.loc[date])) for date in history.index]
        if "target_weights" in history:
            history["target_weights"] = history["target_weights"].map(lambda weights: ", ".join(f"{asset} {weight:.0%}" for asset, weight in weights.items()))
        history.index = pd.to_datetime(history.index).strftime("%Y-%m-%d")
        history = history.rename_axis("signal_date")
    return {"table": table(history.sort_index(ascending=False)), "count": len(history), "csv": history.to_csv(),
            "filename": f"{strategy.name.lower().replace(' ', '_').replace('(', '').replace(')', '')}_signal_history.csv",
            "download_label": "Download signal history CSV"}


def unavailable(definition, reason):
    strategy = definition.model_class()
    return {"mode": mode_for(strategy, definition), "selector": selector(definition),
            "current": {"available": False, "reason": reason}, "error": reason,
            "heading": "Signal unavailable", "captions": [], "warnings": [getattr(strategy, "risk_warning", "")],
            "preview": None, "rationale": None, "history": None, "data": None, "disclaimer": DISCLAIMER}


def build_payload(definition, all_prices, metadata, failures, as_of):
    strategy = definition.model_class()
    assets = tuple(getattr(strategy, "data_assets", ASSETS))
    market = getattr(strategy, "market_data_assets", assets)
    prices = all_prices.loc[:, assets]
    mode = mode_for(strategy, definition)
    # Freeze completed-month eligibility before calling the unchanged shared
    # helper (which otherwise uses wall-clock now). No partial month is relabelled.
    completed_prices = prices.loc[prices.index.to_period("M") < as_of.tz_localize(None).to_period("M")]
    monthly, monthly_input = monthly_strategy_input(completed_prices, market)
    decision_prices = prices if getattr(strategy, "uses_daily_signals", False) else monthly_input
    if mode != "daily" and getattr(strategy, "uses_daily_signals", False):
        decision_prices = completed_prices
    decisions = call_decisions(strategy, decision_prices, as_of)
    status = engine_signals.latest_actionable_signal(decisions, prices if mode == "daily" else monthly, market, as_of=as_of)
    signal = status.decision
    risk = getattr(strategy, "risk_warning", None)
    result = {"mode": mode, "selector": selector(definition), "heading": "Signals",
              "captions": [f"Model: {definition.label} · Completed month-end signal"],
              "warnings": [risk] if risk else [], "error": None,
              "current": {"available": signal is not None, "reason": status.reason, "decision": decision_record(signal)},
              "preview": None, "rationale": None, "history": history_payload(decisions, prices, strategy, mode == "daily"),
              "data": {"sources": table(metadata.loc[list(assets)]), "ranges": table(data.date_ranges(prices)),
                       "completed_through": clean(status.completed_through), "warnings": failures,
                       "captions": ["This signal uses completed month-end data only. Backtest settings do not affect it.",
                           f"Latest eligible completed month: {status.completed_through.date()}. A partial current month is never presented as a final signal."]},
              "disclaimer": DISCLAIMER}
    if getattr(strategy, "actual_history_only", False):
        provenance = tase_data.plain_holding_provenance(metadata, assets)
        result["data"]["provenance"] = table(provenance)
        result["captions"].append("Plain buy-and-hold assets: actual available fund history only; no automatic proxy or pre-fund extension. Fund expenses are already embedded in prices.")
        for asset, row in provenance.iterrows():
            if row.history_kind != "Actual fund history":
                result["warnings"].append(f"{asset}: {row.history_kind}. Any stand-in or pre-fund period belongs to the selected replacement/source, not verified actual fund history.")
            elif row.price_field in {"Published ETF NAV", "End-of-day close"}:
                result["warnings"].append(f"{asset}: using {row.price_field}; dividend/distribution-adjusted total return is not verified.")
    if mode == "daily":
        local = decisions.attrs.get("local_daily_execution", False)
        result["heading"] = engine_signals.daily_signal_heading(signal)
        result["captions"] = [f"Model: {definition.label} · EXPERIMENTAL · closing-price decision · next-session-{'close/NAV' if local else 'open'} execution"]
        result["data"]["captions"] = []  # Original daily Data tab has sources only.
        if getattr(strategy, "signal_calendar", None) == "XNYS" and not decisions.empty:
            result["captions"].append(f"US signals through {decisions.index.max():%Y-%m-%d}; actual TASE prices through {decisions.attrs['execution_prices_completed_through']:%Y-%m-%d}. The US close and TASE execution session are separate dates.")
        if signal is not None:
            result["current"]["table"] = table(pd.DataFrame([{"Decision date": signal.decision_date.date(),
                "Execution date (scheduled close/NAV)" if local else "Execution date (scheduled open)": signal.scheduled_execution_date.date(),
                "Target": signal.selected_asset, "State transition": signal.transition_reason, "RVol": signal.rvol,
                "VR": signal.vr, "SPY vs SMA": signal.trend, "Credit 20-session change": signal.credit,
                "Donchian lock": signal.donchian_lock, "Defensive sessions": signal.defensive_age}]), index=False)
            if getattr(strategy, "signal_calendar", None) == "XNYS":
                result["captions"].append("US data is considered complete after 17:00 New York. Execute at the first TASE session after the US close, modeled at closing/NAV prices; verify broker dealing deadlines. Targets are not actual holdings. US holidays retain the previous state without another indicator observation.")
            else:
                result["captions"].append("Israel: next TASE session's closing/NAV execution assumption; verify fund dealing deadlines with your broker. A session is considered complete after 20:00 Jerusalem time. The QLD substitute drifts between entry and annual resets; displayed weights are targets, not live holdings. No confirmed broker fill is implied." if local else "This closing-price decision applies at the next trading session's OPEN. If the target changes, switch at that open; otherwise hold. The date is a schedule, not a confirmed broker fill. Targets reflect model state, not your actual holding. Today's close is considered complete only after 17:00 New York time.")
        return clean(result)
    if mode == "buy_and_hold":
        result["heading"] = definition.label
        result["captions"] = [caption for caption in result["captions"] if not caption.startswith("Model:")]
        result["captions"].append("Continuous holding · no app-generated timing signal")
        if signal is not None:
            if definition.label == "TA-125 Smart Momentum":
                row = {"Current allocation": "100% TA-125 Smart Momentum (5134713)", "External signal": "None — Buy & Hold", "Internal strategy": "Momentum weighting handled by the underlying index"}
                result["current"]["information"] = "This fund is held continuously. The TA-125 Smart Momentum index performs its own momentum selection and reweighting; the app does not produce BUY, SELL, or CASH timing instructions."
                result["captions"].append("Fund 5134713 uses public TASE/Maya history only. No synthetic or pre-fund history is used; Backtest and Compare begin at the actual available fund history.")
            else:
                holding = execution_security_label(str(signal["selected_asset"]), definition.execution_currency)
                row = {"Current allocation": f"100% {holding}", "External signal": "None — Buy & Hold", "Implementation": f"Continuous {holding} holding"}
                result["current"]["information"] = f"{holding} is held continuously. There is no app-generated timing signal."
                result["captions"].append("Backtest and Compare use the actual available security history.")
            result["current"]["table"] = table(pd.DataFrame([row]), index=False)
        return clean(result)
    if signal is None:
        result["heading"] = "Signal"
        return clean(result)
    weights = signal.get("target_weights", {signal["selected_asset"]: 1.0})
    previous = signal["previous_asset"] if pd.notna(signal["previous_asset"]) else "No prior allocation"
    if getattr(strategy, "is_multi_asset", False):
        instruction = "Hold allocation" if not bool(signal["trade"]) else ("Establish allocation" if previous == "No prior allocation" else "Rebalance allocation")
        allocation = display_allocation(weights, definition.execution_currency)
    else:
        selected = execution_security_label(signal["selected_asset"], definition.execution_currency)
        previous_security = execution_security_label(str(previous), definition.execution_currency) if previous != "No prior allocation" else previous
        instruction = "Hold" if not bool(signal["trade"]) else (f"Buy {selected}" if previous == "No prior allocation" else f"Switch {previous_security} → {selected}")
        allocation = f"100% {selected}"
    effective = engine_signals.first_trading_day_after(prices, pd.Timestamp(signal.name), engine_signals.execution_assets(signal))
    result["current"].update(allocation=allocation, instruction=instruction, effective_start=clean(effective),
        signal_date=pd.Timestamp(signal.name).date().isoformat(), regime=str(signal["regime"]).replace("-", " ").title(),
        effective_text=f"Effective holding period: **{effective.date()}** until the next month-end decision." if effective is not None else "No later trading observation is available yet, so an effective start date cannot be shown.")
    result["rationale"] = rationale(strategy, signal, definition.execution_currency, getattr(strategy, "signal_assets", assets))
    preview_monthly, price_as_of, preview_reason = engine_signals.month_to_date_snapshot(monthly, prices, market, as_of=as_of)
    if preview_reason is not None:
        preview_status = engine_signals.latest_preview_signal(pd.DataFrame(), price_as_of)
    elif getattr(strategy, "uses_daily_signals", False):
        preview_status = engine_signals.latest_preview_signal(call_decisions(strategy, prices.loc[:price_as_of], as_of, include_current_month=True), price_as_of)
    else:
        auxiliary = prices.drop(columns=list(market), errors="ignore").reindex(preview_monthly.index, method="ffill")
        preview_status = engine_signals.latest_preview_signal(call_decisions(strategy, preview_monthly.join(auxiliary), as_of), price_as_of)
    preview = preview_status.decision
    result["preview"] = {"decision": decision_record(preview), "reason": preview_status.reason,
        "price_as_of": clean(preview_status.price_as_of), "heading": "Next month preview (provisional)",
        "unavailable_text": "No preview is available yet because a common current-month price row is not available."}
    if preview is not None:
        projected_weights = preview.get("target_weights", {preview["selected_asset"]: 1.0})
        projected = display_allocation(projected_weights, definition.execution_currency) if getattr(strategy, "is_multi_asset", False) else f"100% {execution_security_label(preview['selected_asset'], definition.execution_currency)}"
        result["preview"].update(allocation=projected, changed=projected_weights != weights,
            regime=str(preview["regime"]).replace("-", " ").title(),
            warning="**Provisional only — not a trading instruction.** This estimates the next month-end decision " f"from prices available through **{preview_status.price_as_of.date()}**. It can change before month-end.",
            caption="The official signal remains the completed month-end decision above. This preview uses the latest common trading-day close in the current month and does not assume a future close.")
    return clean(result)


def signals_payload(label, as_of, engine_code):
    started = perf_counter()
    definition = definition_for_label(label)
    clock = pd.Timestamp.now(tz="UTC") if as_of is None else pd.Timestamp(as_of)
    strategy = definition.model_class()
    failures = []
    metadata = None
    try:
        prices, metadata, failures = load_inputs(definition)
        prices = prices.loc[prices.index <= clock.tz_localize(None)]
        loaded = perf_counter()
        rows = {str(asset): [{"date": day.isoformat(), "value": clean(value)} for day, value in prices[asset].items()] for asset in prices}
        version = data_version(rows)
        # Default-now hits stay reusable within a UTC date and the daily strategy
        # cutoff; observed-row revisions and completed-session boundaries invalidate.
        cutoff = str(strategy.completed_cutoff(clock)) if hasattr(strategy, "completed_cutoff") else None
        params = {"as_of": as_of, "utc_date": str(clock.date()), "daily_cutoff": cutoff,
                  "engine_code": engine_code, "sources": digest(table(metadata)), "presentation": "signals-v1"}
        if failures:
            result = build_payload(definition, prices, metadata, failures, clock)
            cache = {"hit": None, "warnings": ["Input retrieval failed; this degraded result was not cached."]}
        else:
            # Empty/unavailable/failed computations must not become a cache hit.
            def compute():
                payload = build_payload(definition, prices, metadata, failures, clock)
                if not payload["current"]["available"]:
                    raise UnavailableSignal(payload)
                return payload
            try:
                result, cache = RESULTS.run(model=label, params=params, start=str(prices.index.min()), end=str(prices.index.max()), version=version, compute=compute)
            except UnavailableSignal as exc:
                result, cache = exc.payload, {"hit": None, "warnings": ["Unavailable signal was not cached."]}
        result.update(as_of=clock.isoformat(), data_version=version, cache=cache,
                      data_origin="Existing live loaders; complete selected-model input", fallback_warnings=[LIVE_NOTICE],
                      timing={"load_seconds": round(loaded-started, 6), "calculation_or_cache_seconds": round(perf_counter()-loaded, 6), "total_seconds": round(perf_counter()-started, 6)})
        return clean(result)
    except Exception as exc:
        result = unavailable(definition, safe_error(exc))
        if metadata is not None:
            result["data"] = {"sources": table(metadata), "ranges": table(data.date_ranges(prices)),
                "completed_through": None, "warnings": failures, "captions": []}
        result.update(as_of=clock.isoformat(), cache={"hit": None, "warnings": ["Failed signal was not cached."]},
                      data_origin="Existing live loaders", fallback_warnings=[LIVE_NOTICE], timing={"total_seconds": round(perf_counter()-started, 6)})
        return clean(result)


class UnavailableSignal(Exception):
    def __init__(self, payload):
        self.payload = payload
