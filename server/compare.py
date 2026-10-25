"""Read-only Compare orchestration. Financial calculations remain in haa."""
from dataclasses import replace
from datetime import date, datetime, timezone
import json
import logging
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from haa.comparison import ModelInput, compare_models
from .compare_execution import compare_portfolios
from .performance import decisions as cached_decisions, span, measure
from haa.portfolio_config import backtest_portfolio_config
from . import backtest as base, backtest_multi as multi, signals, cache as store
from .cache import ResultCache, digest, data_version
from .signals_wire import clean, table

WORDS = json.loads((Path(__file__).resolve().parents[1]/"web/content/compare.json").read_text())
RESULTS = ResultCache()
LOG = logging.getLogger("taa.compare.timing")


class Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["models", "portfolios"] = "models"
    models: list[str] = Field(default_factory=list, max_length=100)
    portfolio_ids: list[str] = Field(default_factory=list, max_length=100)
    method: Literal["monthly", "daily"] = "monthly"
    initial: float = Field(default=100000., ge=1)
    monthly_contribution: float = Field(default=0., ge=0)
    fee_pct: float = Field(default=0., ge=0, le=10)
    tax_enabled: bool = False
    tax_rate: float = Field(default=25., ge=0, le=100)
    start: date | None = None
    end: date | None = None


def error(key):
    raise HTTPException(400, WORDS[key])


def definition(label):
    try: return base.definition(label)
    except HTTPException: error("unknown")


def options(records):
    models = [{**{f.name: getattr(m, f.name) for f in base.fields(m) if f.name != "model_class"},
               "benchmark": getattr(m.model_class, "benchmark_asset", "SPY")}
              for m in sorted(base.MODEL_CATALOG, key=lambda m: m.label.casefold())
              if getattr(m.model_class, "backtest_available", True)]
    # Only this private no-store selector response carries record identifiers/names.
    summaries = [{"id": str(r["id"]), "name": r.get("payload", {}).get("name", "")} for r in records]
    return {"models": models, "portfolios": summaries, "modes": WORDS["modes"],
            "defaults": Inputs(models=[m["label"] for m in models[:2]]).model_dump(mode="json")}


def selection(request, records):
    if request.mode == "models":
        labels = sorted(set(request.models), key=str.casefold)
        for label in labels: definition(label)
        return labels
    if len(set(request.portfolio_ids)) != len(request.portfolio_ids): error("unknownPortfolio")
    result = []
    for identifier in request.portfolio_ids:
        row = next((r for r in records if str(r.get("id")) == identifier), None)
        if row is None: error("unknownPortfolio")
        try: sleeves, _ = backtest_portfolio_config(row.get("payload"), multi.MODELS, require_capital_fx=False)
        except (ValueError, TypeError, OverflowError, KeyError): error("invalidSaved")
        result.append(sleeves)
    currencies = {definition(s["model"]).execution_currency for sleeves in result for s in sleeves}
    if len(currencies) > 1 or not currencies.issubset({"USD", "ILS"}):
        error("portfolioCurrency")
    return result


def load(request, chosen):
    if request.mode == "portfolios":
        # The Step 7 union loader supplies shared SPY and adjusted opens whenever
        # a daily sleeve needs them. Canonical IDs, never saved identifiers.
        labels = list(dict.fromkeys(s["model"] for sleeves in chosen for s in sleeves))
        descriptor = SimpleNamespace(sleeves=[multi.Sleeve(id=i, model=label, weight=100/len(labels)) for i, label in enumerate(labels, 1)],
                                     daily_valuation=request.method == "daily")
        templates, version, metadata, warnings, _, cutoff = multi.live_inputs(descriptor)
        templates = {label: templates[f"{label} ({i})"][1] for i, label in enumerate(labels, 1)}
        portfolios = {}
        for number, sleeves in enumerate(chosen, 1):
            name = WORDS["portfolioLabel"].format(number=number)
            portfolios[name] = {}
            for sleeve in sleeves:
                key = f"{sleeve['model']} ({sleeve['id']})"
                portfolios[name][key] = (sleeve["weight"]/100, replace(templates[sleeve["model"]], name=key))
        return {"inputs": portfolios, "version": version, "metadata": table(metadata), "warnings": warnings,
                "cutoff": cutoff, "bounds": None}
    definitions = [definition(label) for label in chosen]
    assets = tuple(dict.fromkeys(a for d in definitions for a in (*getattr(d.model_class, "data_assets", base.ASSETS), getattr(d.model_class, "benchmark_asset", "SPY"))))
    strict = tuple(dict.fromkeys(a for d in definitions if getattr(d.model_class, "signal_calendar", None) == "XNYS" for a in d.model_class.us_data_assets))
    descriptor = SimpleNamespace(model_class=lambda: SimpleNamespace(data_assets=assets, us_data_assets=strict,
        benchmark_asset=getattr(definitions[0].model_class, "benchmark_asset", "SPY"), signal_calendar="XNYS" if strict else None))
    prices, metadata, warnings = signals.load_inputs(descriptor)
    inputs, bounds, cutoffs = {}, [], {}
    for d in definitions:
        strategy = d.model_class()
        own = tuple(dict.fromkeys((*getattr(strategy, "data_assets", base.ASSETS), getattr(strategy, "benchmark_asset", "SPY"))))
        daily = prices.loc[:, own]
        market = getattr(strategy, "market_data_assets", own)
        monthly = base.data.to_month_end(daily.loc[:, list(market)])
        decisions = cached_decisions(strategy, daily if getattr(strategy, "uses_daily_signals", False) else monthly)
        inputs[d.label] = ModelInput(d.label, decisions, monthly, daily, getattr(strategy, "benchmark_asset", "SPY"), execution_currency=d.execution_currency)
        first, last = base.data.common_monthly_period(monthly)
        if first is None or last is None: raise ValueError(WORDS["noMonthly"].format(name=d.label))
        bounds.append((first.date(), last.date()))
        if hasattr(strategy, "completed_cutoff"): cutoffs[d.label] = str(strategy.completed_cutoff())
    if len({m.execution_currency for m in inputs.values()}) != 1: error("mismatch")
    observations = {str(a): [{"date": day.isoformat(), "value": clean(v)} for day, v in prices[a].items()] for a in prices}
    return {"inputs": inputs, "version": data_version(observations), "metadata": table(metadata), "warnings": warnings,
            "cutoff": cutoffs, "bounds": (max(a for a, _ in bounds), min(b for _, b in bounds))}


def calculate(request, loaded):
    args = (loaded["inputs"], request.initial, request.fee_pct/100, request.tax_enabled, request.tax_rate/100)
    if request.start and request.end and request.start > request.end:
        error("dateOrder" if request.mode == "models" else "portfolioDateOrder")
    if request.mode == "models":
        lower, upper = loaded["bounds"]
        if lower > upper: raise ValueError("The selected models have no common executable holding periods.")
        start, end = request.start or lower, request.end or upper
        if not lower <= start <= end <= upper: error("dateRange")
        return compare_models(*args, pd.Timestamp(start), pd.Timestamp(end),
                              monthly_contribution=request.monthly_contribution), (lower, upper)
    preliminary = compare_portfolios(*args, drift=request.method == "daily", monthly_contribution=request.monthly_contribution)
    lower, upper = preliminary.common_index[0].date(), preliminary.common_index[-1].date()
    start, end = request.start or lower, request.end or upper
    if not lower <= start <= end <= upper: error("dateRange")
    if start == lower and end == upper:
        return preliminary, (lower, upper)
    return compare_portfolios(*args, pd.Timestamp(start), pd.Timestamp(end), drift=request.method == "daily",
                              monthly_contribution=request.monthly_contribution), (lower, upper)


def manifest(bundle):
    return [{"kind": k, "label": v["label"], "filename": v["filename"], "bytes": len(v["csv"].encode())} for k, v in bundle["downloads"].items()]


def run_loaded(request, chosen, loaded, code, *, started=None, input_seconds=0.):
    from .compare_presentation import present
    started = perf_counter() if started is None else started
    params = {k:v for k,v in request.model_dump(mode="json").items() if k not in {"models", "portfolio_ids"}}
    if request.mode == "models": params["models"] = sorted(chosen, key=str.casefold)
    else:
        order = [[{"model": s["model"], "weight": s["weight"]} for s in sleeves] for sleeves in chosen]
        params.update(portfolios=[sorted(sleeves, key=lambda s:(s["model"], s["weight"])) for sleeves in order], execution_order=order)
    params.update(code=code, content=digest(WORDS), utc_date=str(datetime.now(timezone.utc).date()),
        completed_cutoff=loaded["cutoff"], sources=digest(loaded["metadata"]), presentation=f"compare-{request.mode}-v1")
    def compute():
        began = perf_counter()
        result, bounds = calculate(request, loaded)
        elapsed = perf_counter()-began
        for r in result.results.values():
            nav = r.daily if r.daily is not None else r.monthly
            if nav.empty or not np.isfinite(nav[["pre_tax_value", "after_tax_value", "benchmark_value"]].to_numpy()).all(): error("invalidResult")
        with span("result_seconds"): bundle = present(request, result, loaded, bounds)
        bundle["public"]["calculation_timing"] = {"input_seconds": input_seconds, "engine_seconds": round(elapsed, 6)}
        if len(json.dumps({**bundle["public"], "warnings": loaded["warnings"], "downloads": manifest(bundle)}, ensure_ascii=False).encode()) >= 2_900_000: error("sizeError")
        return bundle
    bundle, info = RESULTS.run(model="compare:"+request.mode, params=params, start=str(request.start), end=str(request.end), version=loaded["version"], compute=compute)
    public = bundle["public"]
    public.update(cache=info, warnings=loaded["warnings"]+info["warnings"], data_version=loaded["version"], downloads=manifest(bundle),
        timing={"input_seconds": round(input_seconds, 6), "engine_seconds": 0. if info["hit"] else public["calculation_timing"]["engine_seconds"], "total_seconds": round(perf_counter()-started, 6)})
    if len(json.dumps(public, ensure_ascii=False).encode()) >= 3_000_000: error("sizeError")
    LOG.info("compare seconds input=%.6f engine=%.6f", public["timing"]["input_seconds"], public["timing"]["engine_seconds"])
    return clean(public)


def run(request, records, code):
    chosen = selection(request, records)
    if len(chosen) < 2: return {"gate": "selection", "reason": WORDS["modelsGate" if request.mode == "models" else "portfoliosGate"]}
    started = perf_counter()
    try:
        with measure() as phases:
            with span("load_seconds"): loaded = load(request, chosen)
            result = run_loaded(request, chosen, loaded, code, started=started, input_seconds=perf_counter()-started)
            result["timing"]["phases"] = {k:round(v,6) for k,v in phases.items()}
            LOG.info("compare phases %s", result["timing"]["phases"])
            return result
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400, signals.safe_error(exc)) from None


def download(key, kind):
    if len(key) != 64 or any(c not in "0123456789abcdef" for c in key): error("downloadError")
    with RESULTS.lock:
        bundle = RESULTS.warm.get(key)
        if bundle is None:
            try:
                rows = store.cache_client().table("results_cache").select("result").eq("cache_key", key).execute().data
                bundle = rows[0]["result"] if rows else None
            except Exception: bundle = None
    if not bundle or bundle.get("kind") not in {"compare-models-v1", "compare-portfolios-v1"} or kind not in bundle["downloads"]:
        raise HTTPException(404, WORDS["downloadError"])
    return bundle["downloads"][kind]
