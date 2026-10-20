"""Vercel ASGI entrypoint; the existing engine remains authoritative."""
from dataclasses import fields
import ast
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import logging
import math
from pathlib import Path
import sys
from threading import Lock
from time import perf_counter
import traceback
import warnings

from fastapi import FastAPI, HTTPException, Response, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from haa.model_catalog import MODEL_CATALOG  # noqa: E402
from haa import data as engine_data, tase_data as engine_tase  # noqa: E402
from haa.engine import run_backtest  # noqa: E402
from haa.strategies.rvol_shifter import RVolShifterCashOnly  # noqa: E402
from server import private_api, cron, market_cache, signals as signals_page, backtest as backtest_page  # noqa: E402
from server.cache import ResultCache, data_version, digest  # noqa: E402
from server.signals_wire import SignalsCompression  # noqa: E402
from server import rebalance  # noqa: E402
from server import today as today_page  # noqa: E402
from server import backtest_multi  # noqa: E402


app = FastAPI(
    title="TAA Signals API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(SignalsCompression)


@app.middleware("http")
async def private_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith(("/api/me", "/api/workspace", "/api/portfolios", "/api/cron", "/api/signals", "/api/backtest", "/api/rebalance", "/api/today")):
        response.headers["Cache-Control"] = "no-store, private"
    return response


@app.exception_handler(RequestValidationError)
async def invalid_input(request, exc):
    # FastAPI's default validation output includes the submitted private values.
    return JSONResponse(status_code=400 if request.url.path.startswith(("/api/backtest", "/api/rebalance")) else 422, content={"detail": "Check the request fields and try again."})


@app.get("/api/strategies")
def strategies() -> list[dict]:
    """Expose catalogue metadata, not executable Python class objects."""
    return [
        {
            field.name: getattr(model, field.name)
            for field in fields(model)
            if field.name != "model_class"
        }
        for model in MODEL_CATALOG
    ]


@lru_cache(maxsize=1)
def _shared_rules():
    """Read trusted repository rule declarations, never import/run Streamlit.

    app.py remains the one text source. Only assignments to MODEL_RULES and
    its existing catalogue-derived augmentation are evaluated. Imports, UI,
    authentication, market-data calls and all other app statements are omitted.
    """
    source = Path(__file__).resolve().parents[1] / "app.py"
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))

    def writes_rules(node):
        return isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "MODEL_RULES"
            or isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
            and target.value.id == "MODEL_RULES"
            for target in node.targets
        )

    declarations = [node for node in tree.body if writes_rules(node) or (
        isinstance(node, ast.For) and isinstance(node.iter, ast.Name)
        and node.iter.id == "MODEL_CATALOG"
        and any(writes_rules(child) for child in ast.walk(node))
    )]
    block = ast.Module(body=declarations, type_ignores=[])
    # Fail closed if future edits put function calls other than the existing
    # metadata getattr in this block. No source or code comes from a request.
    if any(isinstance(node, ast.Call) and not (
        isinstance(node.func, ast.Name) and node.func.id == "getattr"
    ) for node in ast.walk(block)):
        raise ValueError("The shared rule declarations contain an unsupported function call.")
    namespace = {"__builtins__": {}, "getattr": getattr, "MODEL_CATALOG": MODEL_CATALOG}
    exec(compile(block, str(source) + ":rule-definitions", "exec"), namespace)
    rules = namespace.get("MODEL_RULES")
    if not isinstance(rules, dict) or not rules or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in rules.items()
    ):
        raise ValueError("No valid shared rule descriptions were found in app.py.")
    notes = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        if not any(isinstance(item.context_expr, ast.Call)
                   and isinstance(item.context_expr.func, ast.Attribute)
                   and item.context_expr.func.attr == "expander"
                   and item.context_expr.args
                   and isinstance(item.context_expr.args[0], ast.Constant)
                   and item.context_expr.args[0].value == "Implementation and data notes"
                   for item in node.items):
            continue
        for child in ast.walk(node):
            if (isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "markdown" and child.args
                    and isinstance(child.args[0], ast.Constant)
                    and isinstance(child.args[0].value, str)):
                notes.append(child.args[0].value)
    return rules, "\n\n".join(notes)


@app.get("/api/rules")
def rules(response: Response) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        descriptions, notes = _shared_rules()
        return {"source": "app.py:MODEL_RULES", "implementation_notes": notes,
                "models": [{"label": item.label, "strategy": item.strategy,
                            "variant": item.variant, "implementation": item.implementation,
                            "execution_currency": item.execution_currency,
                            "markdown": descriptions.get(item.label),
                            "description_missing": item.label not in descriptions,
                            "risk_warning": getattr(item.model_class, "risk_warning", None)}
                           for item in MODEL_CATALOG]}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc


_diagnostic_lock = Lock()
_results = ResultCache()
TASE_CHECKS = (("CSPX_IL", "1159250"), ("RVOL_3X_IL", "1187079"),
               ("TA125_SMART_MOMENTUM", "5134713"))


@lru_cache(maxsize=1)
def _engine_code_version():
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / "src" / "haa").rglob("*.py"))
    files += sorted((root / "server").rglob("*.py")) + [Path(__file__).resolve()]
    return digest({str(path.relative_to(root)): path.read_text() for path in files})


@contextmanager
def _provider_messages():
    """Retain provider log errors even when a loader wraps the exception."""
    messages = []

    class Collector(logging.Handler):
        def emit(self, record):
            messages.append(self.format(record))

    handler = Collector()
    handler.setFormatter(logging.Formatter("%(name)s %(levelname)s: %(message)s"))
    loggers = [logging.getLogger(name) for name in ("yfinance", "tasekit")]
    for logger in loggers:
        logger.addHandler(handler)
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            yield messages
            messages.extend(f"{type(item.message).__name__}: {item.message}" for item in caught)
    finally:
        for logger in loggers:
            logger.removeHandler(handler)


def _timed_check(identifier, operation):
    result = {"identifier": identifier, "success": False, "price": None,
              "price_date": None, "error": None, "error_type": None,
              "traceback": None, "provider_messages": []}
    started = perf_counter()
    with _provider_messages() as messages:
        try:
            operation(result)
            result["success"] = True
        except Exception as exc:
            result.update(error=str(exc), error_type=type(exc).__name__,
                          traceback=traceback.format_exc())
    result["provider_messages"] = messages
    result["seconds"] = round(perf_counter() - started, 6)
    return result


def _latest(series, result):
    available = series.dropna().sort_index()
    if available.empty:
        raise ValueError("The existing loader returned no usable price observations.")
    price = float(available.iloc[-1])
    if not math.isfinite(price) or price <= 0:
        raise ValueError("The latest provider price is not finite and positive.")
    result.update(price=price, price_date=available.index[-1].isoformat(),
                  observations=len(available))


def _us_price(ticker, result):
    result.update(source="haa.data.download_yahoo_prices → yfinance",
                  price_field="Existing history loader: Adj Close preferred, Close fallback",
                  price_units="USD history series; not an executable spot quote")
    prices = engine_data.download_yahoo_prices({ticker: ticker})
    _latest(prices[ticker], result)


def _tase_price(asset, result):
    # In particular, RVOL_3X_IL follows the app's published-EOD route, not
    # an invented alternative tasekit endpoint or a US proxy.
    result.update(source="haa.tase_data.TasePriceSource → existing TASE/Maya route", asset=asset)
    item = engine_tase.TasePriceSource().fetch_asset(asset)
    result.update(source=item.source, price_field=item.field,
                  price_units="Unmodified provider history units; not a broker per-unit conversion")
    _latest(item.prices, result)


def _arvol_backtest(result):
    strategy = RVolShifterCashOnly()
    result.update(strategy=strategy.name, implementation="Original USD daily V3",
                  data_assets=list(strategy.data_assets),
                  window="Full real Yahoo history; engine uses completed sessions only",
                  parameters={"initial_investment": 10000, "transaction_cost": 0,
                              "tax_enabled": True, "tax_rate": .25,
                              "monthly_contribution": 0, "fixed_fee": 0},
                  data_seconds=None, signal_seconds=None, engine_seconds=None,
                  phase="download adjusted closes and opens")
    started = perf_counter()
    try:
        closes, opens, origin, data_warnings = market_cache.arvol_inputs(strategy.data_assets)
    finally:
        result["data_seconds"] = round(perf_counter() - started, 6)
    result.update(data_source=origin, data_warnings=data_warnings)
    rows = {asset: cron.bars_rows(closes, opens, asset) for asset in strategy.data_assets}
    # Code identity and completed-session cutoff also invalidate stale decisions
    # when prices are unchanged but a deployment/session boundary has changed.
    params = {**result["parameters"], "engine_code": _engine_code_version(),
              "completed_cutoff": str(strategy.completed_cutoff())}
    result["phase"] = "calculate or read the data-versioned backtest"
    computed, cache_info = _results.run(
        model="Original USD A-RVol V3 diagnostic", params=params,
        start=min(row["date"] for series in rows.values() for row in series),
        end=max(row["date"] for series in rows.values() for row in series),
        version=data_version(rows),
        compute=lambda: _calculate_arvol(strategy, closes, opens, result["parameters"]),
    )
    result.update(computed, cache=cache_info,
                  timing_note="Signal/engine timings describe the original calculation, not cache lookup time.")


def _calculate_arvol(strategy, closes, opens, parameters):
    result = {"phase": "generate original daily signals"}
    started = perf_counter()
    try:
        decisions = strategy.decisions(closes)
        monthly = engine_data.to_month_end(closes)
    finally:
        result["signal_seconds"] = round(perf_counter() - started, 6)
    result["phase"] = "run existing backtest engine"
    started = perf_counter()
    try:
        backtest = run_backtest(decisions, monthly, daily_prices=closes,
                               daily_open_prices=opens, benchmark_asset=strategy.benchmark_asset,
                               **parameters)
    finally:
        result["engine_seconds"] = round(perf_counter() - started, 6)
    result.update(phase="completed", signals=len(decisions), daily_rows=len(backtest.daily),
                  first_date=backtest.daily.index.min().isoformat(),
                  last_date=backtest.daily.index.max().isoformat())
    return result


@app.get("/api/price-check")
def price_check(response: Response) -> dict:
    """Live price diagnostics plus data-versioned fixed backtest; errors stay visible."""
    response.headers["Cache-Control"] = "no-store"
    started = perf_counter()
    # Serialise diagnostics per worker to keep provider log/warning capture
    # attributable to its check. Price checks remain uncached and unsubstituted.
    with _diagnostic_lock:
        checks = [_timed_check(ticker, lambda row, t=ticker: _us_price(t, row))
                  for ticker in ("SPY", "QQQ", "VXUS")]
        checks.extend(_timed_check(identifier, lambda row, a=asset: _tase_price(a, row))
                      for asset, identifier in TASE_CHECKS)
        backtest = _timed_check("A-RVol", _arvol_backtest)
    return {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
            "note": "Actual existing app history loaders, not guaranteed live execution prices. "
                    "Provider errors, warnings and tracebacks are returned verbatim. "
                    "Outer timing measures this request; cached engine timings describe the original calculation.",
            "prices": checks, "backtest": backtest,
            "total_seconds": round(perf_counter() - started, 6)}


app.include_router(private_api.router)
app.include_router(cron.router)
app.include_router(rebalance.router)


@app.get("/api/today")
def today(request: Request, session=Depends(private_api.authenticated)):
    # Vercel forwards the rewrite capture as ?path=today even when the
    # browser requested /api/today with no query. It is routing, not input.
    if request.query_params and request.query_params.multi_items() != [("path", "today")]:
        raise HTTPException(400, "Today reads your saved default portfolio; query parameters are not supported.")
    started = perf_counter()
    portfolios = private_api.portfolios(session)
    result = today_page.compose(portfolios, _engine_code_version())
    result["timing"]["request_seconds"] = round(perf_counter()-started, 6)
    return result


@app.get("/api/signals")
def signals(label: str = "HAA-Simple", as_of: str | None = None,
            session=Depends(private_api.authenticated)):
    from datetime import date
    if label not in {model.label for model in MODEL_CATALOG}:
        raise HTTPException(400, "Unknown strategy catalogue label.")
    if as_of is not None:
        try:
            if date.fromisoformat(as_of).isoformat() != as_of:
                raise ValueError()
        except ValueError:
            raise HTTPException(400, "as_of must be YYYY-MM-DD.") from None
    return signals_page.signals_payload(label, as_of, _engine_code_version())


@app.get("/api/backtest/options")
def backtest_options(label: str = "HAA-Simple", session=Depends(private_api.authenticated)):
    return backtest_page.options(label)


@app.post("/api/backtest")
def backtest(body: backtest_multi.Inputs | backtest_page.Inputs, session=Depends(private_api.authenticated)):
    return (backtest_multi.run(body, _engine_code_version()) if isinstance(body, backtest_multi.Inputs)
            else backtest_page.run(body, _engine_code_version()))


@app.get("/api/backtest/config")
def backtest_config(mode: str, session=Depends(private_api.authenticated)):
    return backtest_multi.config(mode)


@app.post("/api/backtest/validate")
def backtest_validate(body: backtest_multi.Inputs, session=Depends(private_api.authenticated)):
    backtest_multi.validated(body)
    return {"valid": True, "message": backtest_multi.WORDS["weightSuccess"]}


@app.post("/api/backtest/load")
def backtest_load(body: backtest_multi.Load, session=Depends(private_api.authenticated)):
    rows = private_api.portfolios(session) if body.portfolio_id is not None else []
    return backtest_multi.load_saved(body, rows)


@app.get("/api/backtest/download")
def backtest_download(key: str, kind: str, session=Depends(private_api.authenticated)):
    item = backtest_page.download(key, kind)
    return Response(content=item["csv"].encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{item["filename"]}"'})
