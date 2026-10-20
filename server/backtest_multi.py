"""Portfolio/proxy orchestration for the existing Backtest API, never an engine."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from typing import Literal

from fastapi import HTTPException
import numpy as np
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from haa.comparison import ModelInput
from haa import deep_history as deep
from haa.portfolio import total_weight
from haa.portfolio_backtest import run_portfolio_backtest
from haa.portfolio_config import backtest_portfolio_config, deep_history_portfolio_config
from haa.portfolio_signals import monthly_strategy_input
from haa.synthetic_history import monthly_blend_input
from . import backtest as base, signals
from .cache import data_version, digest
from .signals_wire import clean, table
from .performance import decisions as cached_decisions

WORDS = json.loads((Path(__file__).resolve().parents[1]/"web/content/backtest-multi.json").read_text())
MODELS = {m.label: m.model_class for m in base.MODEL_CATALOG}


class Sleeve(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: int = Field(ge=1)
    model: str
    weight: float = Field(ge=0, le=100)


class Inputs(base.Inputs):
    label: Literal["HAA-Simple"] = "HAA-Simple"  # Inherited field is unused here, never private free text.
    mode: Literal["portfolio", "deep"]
    sleeves: list[Sleeve] = Field(min_length=1, max_length=100)
    benchmark: Literal["sp500", "global"] = "sp500"
    sleeve_rebalance_mode: Literal["none", "rvol_cap", "annual_target"] = "none"
    rebalance_sleeve: int | None = None
    rebalance_cap: float = Field(default=15., ge=1, le=99)
    rebalance_target: float = Field(default=10., ge=1, le=98)


class Load(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: Literal["portfolio", "deep"]
    portfolio_id: str | None = None
    payload: dict | None = None


def error(key):
    raise HTTPException(400, WORDS[key])


def validated(request):
    if len({s.id for s in request.sleeves}) != len(request.sleeves):
        error("duplicateIds")
    total = total_weight([s.model_dump() for s in request.sleeves])
    if abs(total-100.) > 1e-9:
        raise HTTPException(400, WORDS["deepWeightWarning" if request.mode == "deep" else "weightWarning"].format(total=total))
    if any(s.weight <= 0 for s in request.sleeves):
        error("positiveDeep" if request.mode == "deep" else "positivePortfolio")
    if request.reference_replay:
        error("noReplay")
    if request.mode == "deep":
        if any(s.model not in deep.ALL_DEEP_HISTORY_SPECS for s in request.sleeves):
            error("unknownProxy")
        if len({s.model for s in request.sleeves}) != len(request.sleeves):
            error("duplicateProxy")
        if len(request.sleeves) > len(deep.deep_history_options(len(request.sleeves))):
            error("tooManyProxy")
        if any(s.model == "rvol_daily" for s in request.sleeves) and (len(request.sleeves) != 1 or request.sleeves[0].weight != 100):
            error("dailySingle")
    else:
        for sleeve in request.sleeves:
            base.definition(sleeve.model)
        if request.sleeve_rebalance_mode != "none" and request.monthly_contribution and any(getattr(MODELS[s.model], "execution_frequency", "monthly") == "daily" for s in request.sleeves):
            error("transferDeposits")
        if request.sleeve_rebalance_mode == "rvol_cap":
            chosen = next((s for s in request.sleeves if s.id == request.rebalance_sleeve), None)
            if chosen is None or "RVol" not in chosen.model:
                error("needsRvol")
            if request.rebalance_target >= request.rebalance_cap:
                error("capOrder")
    # Preserve the app's execution/ledger ordering. Only row identifiers become
    # canonical; never assume sale/loss accounting commutes across sleeves.
    ordered = request.sleeves
    cap = next((i for i, s in enumerate(ordered, 1) if s.id == request.rebalance_sleeve), None)
    return request.model_copy(update={"sleeves": [s.model_copy(update={"id": i}) for i, s in enumerate(ordered, 1)], "rebalance_sleeve": cap})


def config(mode):
    from .backtest_presentation import DCA_CAPTION
    if mode not in {"portfolio", "deep"}: error("unknownMode")
    return {"dca_caption": DCA_CAPTION, "models": [{f.name: getattr(m, f.name) for f in base.fields(m) if f.name != "model_class"}
                       for m in base.MODEL_CATALOG if getattr(m.model_class, "backtest_available", True)],
            "proxies": [{"key": key, "label": spec.label, "caveat": spec.caveat,
                          "daily_signal_history": spec.daily_signal_history} for key, spec in deep.ALL_DEEP_HISTORY_SPECS.items()],
            "single_options": deep.deep_history_options(1), "blend_options": deep.deep_history_options(2),
            "benchmarks": [{"key": k, "label": s.label, "caveat": s.caveat} for k, s in deep.DEEP_HISTORY_BENCHMARKS.items()]}


def load_saved(body, portfolios):
    if (body.portfolio_id is None) == (body.payload is None): error("chooseSaved")
    payload = body.payload
    if body.portfolio_id is not None:
        row = next((r for r in portfolios if str(r.get("id")) == body.portfolio_id), None)
        if row is None: error("missingSaved")
        payload = row.get("payload")
    if len(json.dumps(payload).encode()) > 100000: error("fileSize")
    try:
        sleeves, initial = (deep_history_portfolio_config(payload, MODELS, deep.ALL_DEEP_HISTORY_SPECS)
                            if body.mode == "deep" else backtest_portfolio_config(payload, MODELS))
        warnings = [WORDS["unavailable"].format(model=s["model"]) for s in sleeves
                    if body.mode == "portfolio" and not getattr(MODELS[s["model"]], "backtest_available", True)]
        return {"sleeves": sleeves, "initial": initial, "warnings": warnings}
    except (ValueError, TypeError, OverflowError) as exc:
        # Do not echo untrusted portfolio contents or numeric inputs.
        if str(exc) in WORDS["savedErrors"] or str(exc).startswith("No compatible bundled Deep History for "):
            raise HTTPException(400, str(exc)) from None
        error("invalidSavedDeep" if body.mode == "deep" else "invalidSaved")


def live_inputs(request):
    definitions = [base.definition(s.model) for s in request.sleeves]
    mixed = any(getattr(d.model_class, "execution_frequency", "monthly") == "daily" for d in definitions)
    local = all(d.execution_currency == "ILS" for d in definitions)
    benchmark = "RVOL_SPY_IL" if mixed and local else "SPY"
    assets = tuple(dict.fromkeys(a for d in definitions for a in (*getattr(d.model_class, "data_assets", base.ASSETS), getattr(d.model_class, "benchmark_asset", "SPY"), benchmark)))
    strict = tuple(dict.fromkeys(a for d in definitions if getattr(d.model_class, "signal_calendar", None) == "XNYS" for a in d.model_class.us_data_assets))
    # Loader-only union descriptor. All decisions still use the original class.
    context = SimpleNamespace(model_class=lambda: SimpleNamespace(data_assets=assets, benchmark_asset=benchmark,
        us_data_assets=strict, signal_calendar="XNYS" if strict else None))
    bars = mixed and not local
    loaded = signals.load_inputs(context, daily_bars=bars)
    prices, metadata, warnings = loaded[:3]
    opens = loaded[3] if bars else None
    models = {}
    for sleeve, definition in zip(request.sleeves, definitions):
        strategy = definition.model_class()
        sleeve_assets = tuple(dict.fromkeys((*getattr(strategy, "data_assets", base.ASSETS), benchmark)))
        daily = prices.loc[:, sleeve_assets]
        market = tuple(dict.fromkeys((*getattr(strategy, "market_data_assets", sleeve_assets), benchmark)))
        monthly, decision_monthly = monthly_strategy_input(daily, market)
        decisions = cached_decisions(strategy, daily if getattr(strategy, "uses_daily_signals", False) else decision_monthly)
        key = f"{sleeve.model} ({sleeve.id})"
        models[key] = (sleeve.weight/100, ModelInput(key, decisions, monthly, daily, benchmark, opens, definition.execution_currency))
    observations = {str(a): [{"date": day.isoformat(), "value": clean(v)} for day, v in prices[a].items()] for a in prices}
    if opens is not None:
        observations.update({"open:"+str(a): [{"date": day.isoformat(), "value": clean(v)} for day, v in opens[a].items()] for a in opens})
    cutoff = {d.label: str(d.model_class().completed_cutoff()) for d in definitions if hasattr(d.model_class, "completed_cutoff")}
    return models, data_version(observations), metadata, warnings, benchmark, cutoff


def proxy_inputs(request):
    benchmark = deep.DEEP_HISTORY_BENCHMARKS[request.benchmark]
    models = {}
    for sleeve in request.sleeves:
        spec = deep.ALL_DEEP_HISTORY_SPECS[sleeve.model]
        model = deep.deep_history_model_input(spec, benchmark=benchmark)
        if len(request.sleeves) > 1: model = monthly_blend_input(model)
        models[f"{spec.label} ({sleeve.id})"] = (sleeve.weight/100, model)
    # Include all frozen dependencies, including synthetic tax reconstruction.
    hashes = {str(p.relative_to(deep.DEEP_HISTORY_DIR)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in sorted(deep.DEEP_HISTORY_DIR.rglob("*")) if p.is_file()}
    return models, digest(hashes), pd.DataFrame(), [], benchmark.asset_id, {}


def engine_parameters(request):
    daily_proxy = request.mode == "deep" and any(deep.ALL_DEEP_HISTORY_SPECS[s.model].daily_signal_history for s in request.sleeves)
    passed = {"transaction_cost": 0. if daily_proxy or request.fee_type == "fixed" else request.fee_value/100,
              "fixed_fee": 0. if daily_proxy or request.fee_type == "percentage" else request.fee_value,
              "tax_enabled": request.tax_enabled and not (request.mode == "deep" and request.sleeves[0].model == "rvol_daily"),
              "tax_rate": request.tax_rate/100, "monthly_contribution": request.monthly_contribution}
    if request.mode == "portfolio":
        sleeve = next((s for s in request.sleeves if s.id == request.rebalance_sleeve), None)
        passed.update(sleeve_rebalance_mode=request.sleeve_rebalance_mode,
                      rebalance_sleeve=f"{sleeve.model} ({sleeve.id})" if sleeve else None,
                      rebalance_cap=request.rebalance_cap/100, rebalance_target=request.rebalance_target/100)
    return passed


def calculate(request, models, passed, *, start=None, end=None):
    if request.mode == "deep" and len(models) == 1:
        model = next(iter(models.values()))[1]
        return base.run_backtest(model.decisions, model.monthly_prices, request.initial,
            daily_prices=model.daily_prices, benchmark_asset=model.benchmark_asset, start=start, end=end, **passed)
    return run_portfolio_backtest(models, request.initial, start=start, end=end, **passed)


def run(request, code):
    from .backtest_multi_presentation import report
    started = perf_counter()
    request = validated(request)
    try:
        models, version, metadata, warnings, benchmark, cutoff = (proxy_inputs(request) if request.mode == "deep" else live_inputs(request))
        loaded = perf_counter()
        passed = engine_parameters(request)
        params = {k: v for k, v in request.model_dump(mode="json").items() if k not in {"label", "start", "end", "reference_replay"}}
        order = [{"model": s.model, "weight": s.weight} for s in request.sleeves]
        params["sleeves"] = sorted(order, key=lambda s: (s["model"], s["weight"]))
        params["execution_order"] = order
        params.update(code=code, utc_date=str(datetime.now(timezone.utc).date()), completed_cutoff=cutoff,
                      source_metadata=digest(table(metadata)), content_version=digest(WORDS), presentation=f"backtest-{'portfolio' if request.mode == 'portfolio' else 'deep-history'}-v1")
        def compute():
            began = perf_counter()
            preliminary = calculate(request, models, passed)
            common = preliminary.common_index if hasattr(preliminary, "common_index") else preliminary.monthly.index
            lower, upper = common.min().date(), common.max().date()
            start, end = request.start or lower, request.end or upper
            if not lower <= start <= end <= upper: error("dateRange")
            result = preliminary if start == lower and end == upper else calculate(request, models, passed, start=pd.Timestamp(start), end=pd.Timestamp(end))
            nav = result.daily if result.daily is not None else result.monthly
            # Synthetic daily NAV intentionally has no invented daily benchmark.
            if nav.empty or not np.isfinite(nav[[c for c in ("pre_tax_value", "after_tax_value", "benchmark_value") if c in nav]].to_numpy()).all() or not np.isfinite(result.monthly[["pre_tax_value", "after_tax_value", "benchmark_value"]].to_numpy()).all(): error("invalidResult")
            timing = {"input_and_signal_seconds": round(loaded-started, 6), "engine_seconds": round(perf_counter()-began, 6)}
            bundle = report(request, result, models, passed, benchmark, metadata, (lower, upper), (start, end), timing)
            # Guard before ResultCache can persist a failed/oversized result.
            probe = {**bundle["public"], "warnings": bundle["public"]["warnings"] + warnings,
                     "downloads": [{"kind": k, "label": v["label"], "filename": v["filename"], "bytes": len(v["csv"].encode())} for k, v in bundle["downloads"].items()]}
            if len(json.dumps(probe, ensure_ascii=False).encode()) >= 2_900_000: error("sizeError")
            return bundle
        bundle, info = base.RESULTS.run(model="backtest:"+request.mode, params=params,
            start=str(request.start), end=str(request.end), version=version, compute=compute)
        public = bundle["public"]
        public.update(cache=info, data_version=version)
        public["warnings"] += warnings + info["warnings"]
        public["timing"] = {"input_and_signal_seconds": round(loaded-started, 6),
            "engine_seconds": 0. if info["hit"] else public["calculation_timing"]["engine_seconds"], "total_seconds": round(perf_counter()-started, 6)}
        public["downloads"] = [{"kind": k, "filename": v["filename"], "label": v["label"], "bytes": len(v["csv"].encode())} for k, v in bundle["downloads"].items()]
        if len(json.dumps(public, ensure_ascii=False).encode()) >= 3_000_000: error("sizeError")
        return clean(public)
    except HTTPException: raise
    except Exception as exc:
        raise HTTPException(400, signals.safe_error(exc)) from None
