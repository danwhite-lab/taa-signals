"""Vercel ASGI entrypoint; the existing engine remains authoritative."""
from dataclasses import fields
import ast
from functools import lru_cache
from pathlib import Path
import sys
from time import perf_counter

from fastapi import FastAPI, HTTPException, Response, Request, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


SRC = str(Path(__file__).resolve().parents[1] / "src")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from haa.model_catalog import MODEL_CATALOG  # noqa: E402
from server import private_api, cron, signals as signals_page, backtest as backtest_page  # noqa: E402
from server.cache import digest  # noqa: E402
from server.signals_wire import SignalsCompression  # noqa: E402
from server import rebalance  # noqa: E402
from server import today as today_page  # noqa: E402
from server import backtest_multi  # noqa: E402
from server import research  # noqa: E402
from server import compare as compare_page  # noqa: E402
from server import test_login  # noqa: E402


app = FastAPI(
    title="TAA Signals API",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(SignalsCompression)
app.include_router(test_login.router)


@app.middleware("http")
async def private_headers(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/test-login") and response.status_code >= 400:
        response = JSONResponse({"detail": test_login.WORDS["failure"]}, status_code=response.status_code)
    if request.url.path.startswith(("/api/me", "/api/workspace", "/api/portfolios", "/api/cron", "/api/signals", "/api/backtest", "/api/rebalance", "/api/today", "/api/research", "/api/compare", "/api/test-login")):
        response.headers["Cache-Control"] = "no-store, private"
    if request.url.path.startswith("/api/test-login"):
        response.headers["Pragma"] = "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def invalid_input(request, exc):
    # FastAPI's default validation output includes the submitted private values.
    return JSONResponse(status_code=400 if request.url.path.startswith(("/api/backtest", "/api/rebalance", "/api/research", "/api/compare")) else 422, content={"detail": "Check the request fields and try again."})


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


@lru_cache(maxsize=1)
def _engine_code_version():
    root = Path(__file__).resolve().parents[1]
    files = sorted((root / "src" / "haa").rglob("*.py"))
    files += sorted((root / "server").rglob("*.py")) + [Path(__file__).resolve()]
    return digest({str(path.relative_to(root)): path.read_text() for path in files})


app.include_router(private_api.router)
app.include_router(cron.router)
app.include_router(rebalance.router)


@app.get("/api/today")
def today(request: Request, session=Depends(private_api.authenticated)):
    # Vercel forwards the rewrite capture as ?path=today even when the
    # browser requested /api/today with no query. It is routing, not input.
    params = request.query_params.multi_items()
    if any(key not in {"path", "preview", "live"} or (key=="path" and value!="today") or (key in {"preview", "live"} and value not in {"true", "false"}) for key,value in params) or len({key for key,_ in params}) != len(params):
        raise HTTPException(400, "Today reads your saved default portfolio; query parameters are not supported.")
    started = perf_counter()
    portfolios = private_api.portfolios(session)
    with signals_page.input_policy(force_live=request.query_params.get("live", "false")=="true"):
        result = today_page.compose(portfolios, _engine_code_version(), include_preview=request.query_params.get("preview", "true")=="true")
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


@app.get("/api/research/options")
def research_options(label: str = "HAA-Simple", session=Depends(private_api.authenticated)):
    return research.options(label)


@app.get("/api/compare/options")
def compare_options(session=Depends(private_api.authenticated)):
    return compare_page.options(private_api.portfolios(session))


@app.post("/api/compare")
def compare_run(body: compare_page.Inputs, session=Depends(private_api.authenticated)):
    records = private_api.portfolios(session) if body.mode == "portfolios" else []
    return compare_page.run(body, records, _engine_code_version())


@app.get("/api/compare/download")
def compare_download(key: str, kind: str, session=Depends(private_api.authenticated)):
    item = compare_page.download(key, kind)
    return Response(content=item["csv"].encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{item["filename"]}"'})


@app.post("/api/research")
def research_run(body: research.Inputs, session=Depends(private_api.authenticated)):
    return research.run(body, _engine_code_version())


@app.get("/api/research/download")
def research_download(key: str, kind: str, session=Depends(private_api.authenticated)):
    item = research.download(key, kind)
    return Response(content=item["csv"].encode("utf-8"), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{item["filename"]}"'})


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
