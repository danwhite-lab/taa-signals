"""Read-only Research orchestration; all financial tests live in haa.validation."""
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace

from fastapi import HTTPException
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field

from haa.validation import ValidationInput, profile_for, research_unavailable_reason, run_deterministic_validation
from . import backtest as base, cache as store, signals
from .cache import ResultCache, data_version, digest
from .signals_wire import clean, table

WORDS = json.loads((Path(__file__).resolve().parents[1]/"web/content/research.json").read_text())
RESULTS = ResultCache()
LOG = logging.getLogger("taa.research.timing")


class Inputs(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    label: str = "HAA-Simple"
    initial: float = Field(default=100000., ge=1)


def definition(label):
    try: return base.definition_for_label(label)
    except ValueError: raise HTTPException(400, WORDS["unknown"]) from None


def gate(selected):
    strategy = selected.model_class()
    profile = profile_for(strategy)
    if profile is None:
        return "no_profile", research_unavailable_reason(strategy) or WORDS["noProfile"].format(name=strategy.name)
    if not getattr(strategy, "backtest_available", True):
        return "no_backtest", WORDS["noBacktest"].format(name=strategy.name)
    return "available", None


def catalogue():
    return [{**{f.name: getattr(m, f.name) for f in base.fields(m) if f.name != "model_class"},
             "gate": gate(m)[0], "reason": gate(m)[1]} for m in base.MODEL_CATALOG]


def profile_summary(profile):
    rows = [{WORDS["parameterColumns"][0]: item.key, WORDS["parameterColumns"][1]: item.published_value,
             WORDS["parameterColumns"][2]: ", ".join(map(str, item.candidate_values)) or WORDS["immutable"],
             WORDS["parameterColumns"][3]: item.description} for item in profile.published_parameters]
    return {"id": profile.profile_id, "data_confidence": profile.data_confidence,
            "caption": WORDS["profileCaption"].format(id=profile.profile_id, confidence=profile.data_confidence.title()),
            "parameters": table(pd.DataFrame(rows, columns=WORDS["parameterColumns"]), index=False),
            "notes": profile.notes or WORDS["profileNotes"]}


def load(selected):
    strategy = selected.model_class()
    profile = profile_for(strategy)
    assets = tuple(dict.fromkeys((*getattr(strategy, "data_assets", base.ASSETS), getattr(strategy, "benchmark_asset", "SPY"),
                                 *(proxy.proxy_asset for proxy in profile.proxy_substitutions))))
    # Existing loader, augmented only with the profile's declared proxy assets.
    context = SimpleNamespace(model_class=lambda: SimpleNamespace(data_assets=assets,
        benchmark_asset=getattr(strategy, "benchmark_asset", "SPY"), us_data_assets=getattr(strategy, "us_data_assets", ()),
        signal_calendar=getattr(strategy, "signal_calendar", None)))
    all_prices, metadata, warnings = signals.load_inputs(context)
    strategy, prices, monthly, monthly_input, bounds, _ = base.prepare(selected, all_prices)
    decision_prices = prices if getattr(strategy, "uses_daily_signals", False) else monthly_input
    decisions = strategy.decisions(decision_prices)
    proxies_monthly, proxies_daily = {}, {}
    for proxy in profile.proxy_substitutions:
        if proxy.proxy_asset in all_prices:
            proxies_monthly[proxy.proxy_asset] = base.data.to_month_end(all_prices.loc[:, [proxy.proxy_asset]])[proxy.proxy_asset]
            proxies_daily[proxy.proxy_asset] = all_prices[proxy.proxy_asset]
    validation_input = ValidationInput(selected.label, decisions, monthly, prices, getattr(strategy, "benchmark_asset", "SPY"),
        profile, proxies_monthly, proxies_daily, strategy, decision_prices)
    start, end = base.data.common_monthly_period(monthly)
    years = len(monthly.loc[start:end])/12
    history = {"start": start.isoformat(), "end": end.isoformat(), "years": years,
        "caption": WORDS["historyCaption"].format(start=start.strftime("%B %Y"), end=end.strftime("%B %Y"), years=years)}
    rows = {str(a): [{"date": day.isoformat(), "value": clean(v)} for day, v in all_prices[a].items()] for a in all_prices}
    return {"input": validation_input, "history": history, "bounds": bounds,
            "metadata": table(metadata.join(base.data.date_ranges(all_prices))), "warnings": warnings,
            "version": data_version(rows), "cutoff": str(strategy.completed_cutoff()) if hasattr(strategy, "completed_cutoff") else None}


def options(label):
    selected = definition(label)
    state, reason = gate(selected)
    result = {"models": catalogue(), "label": label, "gate": state, "reason": reason, "currency": selected.execution_currency,
              "default_initial": 100000., "profile": None, "history": None, "warnings": []}
    if state != "available": return result
    try:
        loaded = load(selected)
        result.update(profile=profile_summary(loaded["input"].profile), history=loaded["history"], bounds=loaded["bounds"],
                      data_validation=loaded["metadata"], warnings=loaded["warnings"])
        return clean(result)
    except Exception as exc: raise HTTPException(400, signals.safe_error(exc)) from None


def run_loaded(request, selected, loaded, code, *, started=None, input_seconds=0.):
    """Production cache path; also permits timing identical retained real frames."""
    from .research_presentation import present
    started = perf_counter() if started is None else started
    profile = loaded["input"].profile
    profile_contract = asdict(profile)
    profile_contract["applicable_tests"] = sorted(profile.applicable_tests)
    params = {"profile_id": profile.profile_id, "profile": clean(profile_contract), "code": code,
              "content": digest(WORDS), "utc_date": str(datetime.now(timezone.utc).date()), "completed_cutoff": loaded["cutoff"],
              "initial": request.initial, "sources": digest(loaded["metadata"]), "presentation": "research-v1"}
    def compute():
        began = perf_counter()
        report = run_deterministic_validation(loaded["input"], request.initial)
        elapsed = perf_counter()-began
        bundle = present(report, request, selected, profile, loaded)
        bundle["public"]["calculation_timing"] = {"input_seconds": input_seconds, "validation_seconds": round(elapsed, 6)}
        probe = {**bundle["public"], "warnings": bundle["public"].get("warnings",[])+loaded["warnings"], "downloads": manifest(bundle)}
        if len(json.dumps(probe, ensure_ascii=False).encode()) >= 2_900_000: raise HTTPException(400, WORDS["sizeError"])
        return bundle
    bundle, info = RESULTS.run(model="research:"+selected.label, params=params,
        start=loaded["history"]["start"], end=loaded["history"]["end"], version=loaded["version"], compute=compute)
    result = bundle["public"]
    result.update(cache=info, data_version=loaded["version"], warnings=result.get("warnings",[])+loaded["warnings"]+info["warnings"], downloads=manifest(bundle),
        timing={"input_seconds": round(input_seconds, 6), "validation_seconds": 0. if info["hit"] else result["calculation_timing"]["validation_seconds"],
                "total_seconds": round(perf_counter()-started, 6)})
    if len(json.dumps(result, ensure_ascii=False).encode()) >= 3_000_000: raise HTTPException(400, WORDS["sizeError"])
    LOG.info("research seconds input=%.6f validation=%.6f", result["timing"]["input_seconds"], result["timing"]["validation_seconds"])
    return clean(result)


def manifest(bundle):
    return [{"kind": k, "label": v["label"], "filename": v["filename"], "bytes": len(v["csv"].encode())} for k, v in bundle["downloads"].items()]


def run(request, code):
    selected = definition(request.label)
    state, reason = gate(selected)
    if state != "available": return {"gate": state, "reason": reason, "label": selected.label}
    started = perf_counter()
    try:
        loaded = load(selected)
        return run_loaded(request, selected, loaded, code, started=started, input_seconds=perf_counter()-started)
    except HTTPException: raise
    except Exception as exc: raise HTTPException(400, signals.safe_error(exc)) from None


def download(key, kind):
    if len(key) != 64 or any(c not in "0123456789abcdef" for c in key) or kind not in {*WORDS["downloads"], "price-warnings"}:
        raise HTTPException(400, WORDS["downloadError"])
    with RESULTS.lock:
        bundle = RESULTS.warm.get(key)
        if bundle is None:
            try:
                rows = store.cache_client().table("results_cache").select("result").eq("cache_key", key).execute().data
                bundle = rows[0]["result"] if rows else None
            except Exception: bundle = None
    if not bundle or bundle.get("kind") != "research-v1" or kind not in bundle["downloads"]:
        raise HTTPException(404, WORDS["downloadError"])
    return bundle["downloads"][kind]
