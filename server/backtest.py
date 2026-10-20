"""Single-strategy Streamlit orchestration, not a second backtest engine."""
from dataclasses import fields
from datetime import date, datetime, timezone
import json
import logging
from time import perf_counter

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from typing import Literal
import numpy as np
import pandas as pd

from haa import data
from haa.constants import ASSETS
from haa.engine import run_backtest
from haa.backtest_options import result_metrics as backtest_result_metrics, unit_curves
from haa.metrics import annual_returns
from haa.model_catalog import MODEL_CATALOG, definition_for_label
from haa.portfolio_signals import monthly_strategy_input
from haa.signals import first_trading_day_after
from haa.tase_data import plain_holding_provenance

from . import cache as store, signals
from .cache import ResultCache, data_version, digest
from .signals_wire import clean, table

RESULTS = ResultCache()
PREVIEW_ROWS = 150
CHART_ROWS = 700
LOG = logging.getLogger("taa.backtest.timing")
if not LOG.handlers:
    LOG.addHandler(logging.StreamHandler())
LOG.setLevel(logging.INFO)
LOG.propagate = False
MINIMUM_NOTE = "Minimum fee of 2 NIS is not modelled by this backtest"
TAX_NOTE = "Modeled tax uses average cost per asset and carried-forward realized losses. Each modeled sale has its own ledger row. This is not FIFO, does not tax unsold gains at the end, and is not legal tax validation."


class Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    label: str = "HAA-Simple"
    start: date | None = None
    end: date | None = None
    initial: float = Field(default=100000., ge=1)
    fee_type: Literal["percentage", "fixed"] = "percentage"
    fee_value: float = Field(default=0., ge=0)
    tax_enabled: bool = True
    tax_rate: float = Field(default=25., ge=0, le=100)
    monthly_contribution: float = Field(default=0., ge=0)
    reference_replay: bool = False

    @model_validator(mode="after")
    def ordered(self):
        if self.start and self.end and self.start > self.end:
            raise ValueError("Start must not follow end.")
        if self.fee_type == "percentage" and self.fee_value > 10:
            raise ValueError("Percentage fee must be between 0 and 10 percent.")
        return self


def definition(label):
    try:
        selected = definition_for_label(label)
    except ValueError:
        raise HTTPException(400, "Unknown backtest model.") from None
    if not getattr(selected.model_class, "backtest_available", True):
        raise HTTPException(400, "Backtesting is unavailable for this implementation.")
    return selected


def load_data(selected):
    daily = getattr(selected.model_class, "execution_frequency", "monthly") == "daily"
    needs_opens = daily and selected.execution_currency != "ILS"
    bundle = signals.load_inputs(selected, daily_bars=needs_opens)
    if needs_opens:
        prices, metadata, warnings, opens = bundle
    else:
        prices, metadata, warnings = bundle
        opens = None
    return prices, metadata, warnings, opens


def prepare(selected, all_prices):
    strategy = selected.model_class()
    benchmark = getattr(strategy, "benchmark_asset", "SPY")
    assets = tuple(dict.fromkeys((*getattr(strategy, "data_assets", ASSETS), benchmark)))
    prices = all_prices.loc[:, assets]
    market = tuple(dict.fromkeys((*getattr(strategy, "market_data_assets", assets), benchmark)))
    monthly, monthly_input = monthly_strategy_input(prices, market)
    common_start, common_end = data.common_monthly_period(monthly)
    captions = []
    if common_start is None or common_end is None or common_start > common_end:
        raise ValueError("The selected model assets have no common month-end observations. Check the data sources or upload compatible CSV histories.")
    daily = getattr(strategy, "execution_frequency", "monthly") == "daily"
    if daily:
        available = strategy.decisions(prices)
        if available.empty:
            raise ValueError("Insufficient daily warm-up and actual ETF history for this strategy.")
        if getattr(strategy, "signal_calendar", None) == "XNYS":
            from haa.cross_market_daily import market_frame, tase_execution_schedule
            sessions = market_frame(prices, strategy.execution_assets, "TASE").loc[:available.attrs["completed_through"]].dropna().index
            executable = tase_execution_schedule(available, sessions)
            common_start = min(executable) if executable else None
        else:
            common_start = first_trading_day_after(prices, available.index.min(), strategy.data_assets)
        common_end = available.attrs["completed_through"]
        if available.attrs.get("pending_price_dates"):
            captions.append(f"Latest fund prices are still pending. Backtest history stops at the last complete session: {common_end.date()}.")
        if common_start is None or common_start > common_end:
            raise ValueError("No completed post-signal execution session is available.")
    end_limit = common_end if daily else prices.index.max()
    frequency = "daily execution" if daily else "monthly"
    bounds = {"start_min": common_start.date().isoformat(), "start_max": common_end.date().isoformat(),
              "end_min": common_start.date().isoformat(), "end_max": end_limit.date().isoformat()}
    captions += [f"Common {frequency} data: {common_start.date()} to {common_end.date()}",
                 "Available adjusted-price history for the assets required by the selected model.",
                 f"Actual common {frequency} data period: {common_start.date()} through {common_end.date()}."]
    return strategy, prices, monthly, monthly_input, bounds, captions


def options(label):
    from .backtest_presentation import DCA_CAPTION, REFERENCE_CAPTION
    selected = definition(label)
    try:
        prices, metadata, warnings, opens = load_data(selected)
        strategy, prices, monthly, monthly_input, bounds, captions = prepare(selected, prices)
        return clean({"models": [{f.name: getattr(m, f.name) for f in fields(m) if f.name != "model_class"}
                                 for m in MODEL_CATALOG if getattr(m.model_class, "backtest_available", True)],
                      "label": label, "currency": selected.execution_currency, "bounds": bounds,
                      "reference_replay_available": getattr(strategy, "signal_calendar", None) == "XNYS",
                      "dca_caption": DCA_CAPTION, "reference_caption": REFERENCE_CAPTION,
                      "captions": captions, "warnings": warnings + [MINIMUM_NOTE],
                      "data_validation": table(metadata.loc[list(prices.columns)].join(data.date_ranges(prices))),
                      "defaults": Inputs().model_dump(mode="json")})
    except Exception as exc:
        raise HTTPException(400, signals.safe_error(exc)) from None


def preview(frame):
    value = table(frame.head(PREVIEW_ROWS))
    return {**value, "total_rows": len(frame), "shown_rows": min(len(frame), PREVIEW_ROWS), "truncated": len(frame) > PREVIEW_ROWS}


def chart(frame):
    """Display-only sampling/scaling; metrics and exports use unreduced frames."""
    original_rows = len(frame)
    positions = np.unique(np.linspace(0, len(frame)-1, min(len(frame), CHART_ROWS), dtype=int))
    reduced = frame.iloc[positions]
    finite = frame.to_numpy(dtype=float)
    low, high = float(np.nanmin(finite)), float(np.nanmax(finite))
    span = high-low or max(abs(high), 1.)
    start, end = reduced.index[0].value, reduced.index[-1].value
    series = []
    for column in reduced:
        points = []
        for day, value in reduced[column].items():
            if pd.isna(value):
                continue
            x = 55 + 815 * (day.value-start) / (end-start or 1)
            y = 250 - 220 * (float(value)-low)/span
            points.append(f"{x:.3f},{y:.3f}")
        series.append({"label": column, "svg_points": " ".join(points)})
    return {"series": series, "start": reduced.index[0].date().isoformat(), "end": reduced.index[-1].date().isoformat(),
            "minimum": low, "maximum": high, "original_rows": original_rows, "display_rows": len(reduced),
            "reduced": len(reduced) < original_rows,
            "caption": "Chart series are reduced for display only; metrics, tax ledger and CSV downloads use every original row." if len(reduced) < original_rows else "Chart uses every original observation."}


def report(selected, request, strategy, prices, monthly, metadata, decisions, result, timing):
    from .backtest_presentation import audit_view, captions_for, performance_table
    initial = request.initial
    pre = f"{strategy.name} pre-tax"
    after = f"{strategy.name} after-tax"
    benchmark = f"{getattr(strategy, 'benchmark_asset', 'SPY')} buy-and-hold"
    summary = performance_table(strategy, result, initial, request.tax_enabled)
    nav = result.daily if result.daily is not None else result.monthly
    mapping = {pre: "pre_tax_value", **({after: "after_tax_value"} if request.tax_enabled else {}), benchmark: "benchmark_value"}
    curves = pd.DataFrame({label: nav[column] for label, column in mapping.items()})
    units = unit_curves(result, {pre: "pre_tax_value", benchmark: "benchmark_value", **({after: "after_tax_value"} if request.tax_enabled else {})}, initial)
    drawdowns = units.div(units.cummax().clip(lower=initial)).sub(1)
    audit = audit_view(strategy, result, tuple(prices.columns))
    downloads = {
        "audit": {"label": "Download audit CSV", "filename": f"{strategy.name.lower().replace(' ', '_').replace('(', '').replace(')', '')}_monthly_audit.csv", "csv": audit.to_csv()},
        "tax_events": {"label": "Download realized-gain tax events CSV", "filename": "rvol_shifter_tax_events.csv" if result.daily is not None else "modeled_tax_events.csv", "csv": result.tax_events.to_csv(index=False)},
    }
    if result.daily is not None:
        downloads["daily_nav"] = {"label": "Download daily NAV and executions CSV", "filename": "rvol_shifter_daily_nav.csv", "csv": result.daily.to_csv()}
    annual = pd.DataFrame({label: annual_returns(result.monthly[{"pre_tax_value": "pre_tax_monthly_return", "after_tax_value": "after_tax_monthly_return", "benchmark_value": "benchmark_monthly_return"}[column]]) for label, column in mapping.items()})
    monthly_returns = pd.DataFrame({label: result.monthly[{"pre_tax_value": "pre_tax_monthly_return", "after_tax_value": "after_tax_monthly_return", "benchmark_value": "benchmark_monthly_return"}[column]] for label, column in mapping.items()})
    raw_metrics = {"pre_tax": backtest_result_metrics(result, "pre_tax_value", initial), "after_tax": backtest_result_metrics(result, "after_tax_value", initial), "benchmark": backtest_result_metrics(result, "benchmark_value", initial)}
    params = request.model_dump(mode="json")
    passed = {"initial_investment": initial, "transaction_cost": request.fee_value / 100 if request.fee_type == "percentage" else 0.,
              "fixed_fee": request.fee_value if request.fee_type == "fixed" else 0., "tax_enabled": request.tax_enabled,
              "tax_rate": request.tax_rate / 100, "monthly_contribution": request.monthly_contribution}
    public = {"label": selected.label, "currency": selected.execution_currency, "settings": params, "engine_parameters": passed,
              "summary": summary, "metrics": raw_metrics, "value_chart": chart(curves), "drawdown_chart": chart(drawdowns),
              "periods": preview(audit), "tax_events": preview(result.tax_events), "annual": preview(annual), "monthly": preview(monthly_returns),
              "tax_event_count": len(result.tax_events), "report_rows": len(nav), "monthly_rows": len(result.monthly),
              "first_date": nav.index.min().isoformat(), "last_date": nav.index.max().isoformat(),
              "captions": captions_for(strategy, decisions, result, benchmark), "warnings": [MINIMUM_NOTE, TAX_NOTE] + ([strategy.risk_warning] if hasattr(strategy, "risk_warning") else []),
              "data_validation": table(metadata.loc[list(prices.columns)].join(data.date_ranges(prices))),
              "calculated_at": datetime.now(timezone.utc).isoformat(), "calculation_timing": timing,
              "data_origin": "Existing live loaders; no cached/live price splice or proxy substitution."}
    return clean({"kind": "single-backtest-v1", "public": public, "downloads": downloads})


def run(request, code):
    started = perf_counter()
    selected = definition(request.label)
    if request.reference_replay and getattr(selected.model_class, "signal_calendar", None) != "XNYS":
        raise HTTPException(400, "Reference replay is available only for the US-signals / TASE V3 implementations.")
    try:
        all_prices, metadata, warnings, opens = load_data(selected)
        loaded = perf_counter()
        strategy, prices, monthly, monthly_input, bounds, range_captions = prepare(selected, all_prices)
        start = request.start or date.fromisoformat(bounds["start_min"])
        end = request.end or date.fromisoformat(bounds["end_max"])
        if not date.fromisoformat(bounds["start_min"]) <= start <= date.fromisoformat(bounds["start_max"]):
            raise ValueError("Start date is outside the available data range.")
        if not date.fromisoformat(bounds["end_min"]) <= end <= date.fromisoformat(bounds["end_max"]) or start > end:
            raise ValueError("End date is outside the available data range or before start.")
        request = request.model_copy(update={"start": start, "end": end})
        rows = {asset: [{"date": day.isoformat(), "value": clean(value)} for day, value in all_prices[asset].items()] for asset in all_prices}
        if opens is not None:
            rows.update({"open:" + asset: [{"date": day.isoformat(), "value": clean(value)} for day, value in opens[asset].items()] for asset in opens})
        version = data_version(rows)
        params = {**request.model_dump(mode="json"), "code": code, "utc_date": str(datetime.now(timezone.utc).date()),
                  "completed_cutoff": str(strategy.completed_cutoff()) if hasattr(strategy, "completed_cutoff") else None,
                  "source_metadata": digest(table(metadata)), "warnings": warnings}
        def compute():
            signal_start = perf_counter()
            inputs = prices if getattr(strategy, "uses_daily_signals", False) else monthly_input
            decisions = strategy.decisions(inputs, cash_start=start if request.reference_replay else None) if getattr(strategy, "signal_calendar", None) == "XNYS" else strategy.decisions(inputs)
            if decisions.empty:
                raise ValueError(f"Insufficient history for {strategy.name}.")
            signal_done = perf_counter()
            result = run_backtest(decisions, monthly, request.initial,
                request.fee_value / 100 if request.fee_type == "percentage" else 0., request.tax_enabled, request.tax_rate / 100,
                pd.Timestamp(start), pd.Timestamp(end), daily_prices=prices, benchmark_asset=getattr(strategy, "benchmark_asset", "SPY"),
                daily_open_prices=opens, monthly_contribution=request.monthly_contribution,
                fixed_fee=request.fee_value if request.fee_type == "fixed" else 0.)
            engine_done = perf_counter()
            nav = result.daily if result.daily is not None else result.monthly
            if nav.empty or not np.isfinite(nav[["pre_tax_value", "after_tax_value", "benchmark_value"]].to_numpy()).all():
                raise ValueError("The engine returned no finite completed result. Check the settings and data range.")
            if getattr(strategy, "actual_history_only", False):
                provenance = plain_holding_provenance(metadata, strategy.data_assets).loc[strategy.holding_asset]
                for field in ("source", "identifier", "price_field", "history_kind", "automatic_proxy_extension"):
                    result.audit[f"history_{field}"] = provenance[field]
            timing = {"data_seconds": round(loaded-started, 6), "signal_seconds": round(signal_done-signal_start, 6), "engine_seconds": round(engine_done-signal_done, 6)}
            return report(selected, request, strategy, prices, monthly, metadata, decisions, result, timing)
        bundle, info = RESULTS.run(model="backtest:" + selected.label, params=params, start=str(start), end=str(end), version=version, compute=compute)
        public = bundle["public"]
        public["warnings"] += warnings + info["warnings"]
        public["cache"] = info
        public["data_version"] = version
        public["timing"] = {"data_seconds": round(loaded-started, 6), "signal_seconds": 0. if info["hit"] else public["calculation_timing"]["signal_seconds"],
                            "engine_seconds": 0. if info["hit"] else public["calculation_timing"]["engine_seconds"], "total_seconds": round(perf_counter()-started, 6)}
        public["downloads"] = [{"kind": kind, "filename": item["filename"], "label": item["label"], "bytes": len(item["csv"].encode())} for kind, item in bundle["downloads"].items()]
        # Only timings are logged: never amounts, fee values, deposits or request bodies.
        LOG.info("backtest seconds data=%.6f signal=%.6f engine=%.6f", public["timing"]["data_seconds"], public["timing"]["signal_seconds"], public["timing"]["engine_seconds"])
        if len(json.dumps(public, ensure_ascii=False, separators=(",", ":")).encode()) >= 3_000_000:
            raise ValueError("Display response exceeds the size limit; try a shorter date range.")
        return public
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, signals.safe_error(exc)) from None


def download(key, kind):
    if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
        raise HTTPException(400, "Invalid result cache key.")
    from .backtest_multi import deep
    allowed = {"audit", "tax_events", "daily_nav", "portfolio_nav", "sleeve_nav", "executions", "sleeve_tax", "proxy_tax", "proxy_audit", "synthetic_tax", "synthetic_nav", "synthetic_audit", "synthetic_source", "daily_source", "history_sources"}
    allowed |= {f"source_{key}_{segment}" for key, spec in deep.ALL_DEEP_HISTORY_SPECS.items() if spec.actual_etf_ticker for segment in ("actual", "early")}
    if kind not in allowed:
        raise HTTPException(400, "Unknown download type.")
    with RESULTS.lock:
        bundle = RESULTS.warm.get(key)
        if bundle is None:
            try:
                rows = store.cache_client().table("results_cache").select("result").eq("cache_key", key).execute().data
                bundle = rows[0]["result"] if rows else None
            except Exception:
                bundle = None
    if not bundle or bundle.get("kind") not in {"single-backtest-v1", "backtest-portfolio-v1", "backtest-deep-history-v1"} or kind not in bundle["downloads"]:
        raise HTTPException(404, "Full download unavailable. Run the backtest again.")
    return bundle["downloads"][kind]
