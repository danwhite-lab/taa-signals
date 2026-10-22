"""Offline, deterministic price fixtures; no accounts or price downloads."""
import ast
from dataclasses import fields
import inspect
import json
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from test_api import ROOT, client, module
from test_private_api import signed_in, HEADERS
from server import signals as page
from server.cache import ResultCache
from server import cache as caches
from server.signals_wire import clean, table
from haa.constants import ASSETS
from haa.model_catalog import definition_for_label, MODEL_CATALOG
from haa.portfolio_signals import monthly_strategy_input
from haa import signals as engine
from haa.market_sessions import us_equity_sessions, tase_equity_sessions

AS_OF = pd.Timestamp("2024-06-14")
LABELS = ["HAA-Simple", "Inflation Compass Standard", "HAA-Simple Israel",
          "A-RVol Shifter V3 Cash-Only", "Buy and Hold SPY"]


@pytest.fixture(autouse=True)
def mock_result_store(monkeypatch):
    def unavailable():
        raise RuntimeError("Mock shared cache unavailable")
    monkeypatch.setattr(caches, "cache_client", unavailable)


def fixtures(label):
    strategy = definition_for_label(label).model_class()
    assets = tuple(dict.fromkeys((*getattr(strategy, "data_assets", ASSETS), getattr(strategy, "benchmark_asset", "SPY"))))
    dates = us_equity_sessions("2020-01-02", "2024-06-28")
    local_dates = tase_equity_sessions("2020-01-02", "2024-06-28")
    columns = {}
    for number, asset in enumerate(assets):
        index = local_dates if asset in page.tase_data.TASE_ISRAEL_ASSET_IDS else dates
        x = np.arange(len(index))
        values = 100 * np.exp(np.cumsum(.0005 + .005 * np.sin(x / (8 + number))))
        if asset == "T5YIE":
            values = 2 + .0005 * x + .03 * np.sin(x / 50)
        if asset == "OECD_CLI_DIFFUSION":
            values = .6 + .05 * np.sin(x / 50)
        columns[asset] = pd.Series(values, index=index)
    prices = pd.DataFrame(columns)
    metadata = pd.DataFrame({"source": "Mock fixture", "identifier": list(assets), "price_field": "Mock close"}, index=pd.Index(assets, name="asset"))
    return prices, metadata, []


def direct(label, prices):
    strategy = definition_for_label(label).model_class()
    assets = getattr(strategy, "data_assets", ASSETS)
    prices = prices.loc[prices.index <= AS_OF, assets]
    market = getattr(strategy, "market_data_assets", assets)
    completed = prices.loc[prices.index.to_period("M") < AS_OF.to_period("M")]
    monthly, monthly_input = monthly_strategy_input(completed, market)
    daily = getattr(strategy, "execution_frequency", "monthly") == "daily"
    inputs = prices if daily else completed if getattr(strategy, "uses_daily_signals", False) else monthly_input
    kwargs = {"as_of": AS_OF} if "as_of" in inspect.signature(strategy.decisions).parameters else {}
    decisions = strategy.decisions(inputs, **kwargs)
    status = engine.latest_actionable_signal(decisions, prices if daily else monthly, market, as_of=AS_OF)
    return strategy, prices, monthly, decisions, status


@pytest.mark.parametrize("label", LABELS)
def test_api_matches_direct_engine_exactly_including_preview_history_and_csv(signed_in, monkeypatch, label):
    bundle = fixtures(label)
    monkeypatch.setattr(page, "load_inputs", lambda definition: bundle)
    monkeypatch.setattr(page, "RESULTS", ResultCache())
    response = client.get("/api/signals", params={"label": label, "as_of": str(AS_OF.date())}, headers=HEADERS)
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store, private"
    payload = response.json()
    strategy, prices, monthly, decisions, status = direct(label, bundle[0])
    assert status.decision is not None, status.reason
    signal = status.decision
    assert payload["current"]["available"], payload
    actual = payload["current"]["decision"]
    assert actual["selected_asset"] == signal.selected_asset
    assert actual["regime"] == signal.regime
    assert actual["target_weights"] == signal.get("target_weights", {signal.selected_asset: 1.})
    assert actual["signal_date"] == signal.name.isoformat()
    assert payload["data"]["completed_through"] == status.completed_through.isoformat()
    assert payload["history"]["count"] == len(decisions)
    daily = payload["mode"] == "daily"
    if daily:
        assert payload["history"]["csv"] == decisions.to_csv()
        date_columns = [c for c in ("decision_date", "scheduled_execution_date") if c in decisions]
        expected_history = table(decisions[date_columns + [c for c in decisions if c not in date_columns]].sort_index(ascending=False))
        assert payload["history"]["table"] == expected_history
        assert payload["heading"] == engine.daily_signal_heading(signal)
        assert payload["current"]["table"]["rows"][0]["Execution date (scheduled open)"] == signal.scheduled_execution_date.date().isoformat()
    else:
        columns = ["regime", "selected_asset", "previous_asset", "trade"]
        if "target_weights" in decisions:
            columns.insert(2, "target_weights")
        history = decisions[columns].copy()
        history["effective_start"] = [engine.first_trading_day_after(prices, d, engine.execution_assets(history.loc[d])) for d in history.index]
        if "target_weights" in history:
            history["target_weights"] = history["target_weights"].map(lambda weights: ", ".join(f"{a} {w:.0%}" for a, w in weights.items()))
        history.index = pd.to_datetime(history.index).strftime("%Y-%m-%d")
        history = history.rename_axis("signal_date")
        assert payload["history"]["csv"] == history.to_csv()
        assert payload["history"]["table"] == table(history.sort_index(ascending=False))
    if payload["mode"] == "monthly":
        effective = engine.first_trading_day_after(prices, signal.name, engine.execution_assets(signal))
        assert payload["current"]["effective_start"] == clean(effective)
        market = getattr(strategy, "market_data_assets", getattr(strategy, "data_assets", ASSETS))
        snapshot, date, reason = engine.month_to_date_snapshot(monthly, prices, market, as_of=AS_OF)
        assert reason is None
        if getattr(strategy, "uses_daily_signals", False):
            projected = strategy.decisions(prices.loc[:date], include_current_month=True)
        else:
            aux = prices.drop(columns=list(market), errors="ignore").reindex(snapshot.index, method="ffill")
            projected = strategy.decisions(snapshot.join(aux))
        preview = engine.latest_preview_signal(projected, date)
        assert payload["preview"]["decision"] == page.decision_record(preview.decision)
        assert payload["preview"]["price_as_of"] == clean(preview.price_as_of)
        assert payload["preview"]["decision"]["target_weights"] == preview.decision.get("target_weights", {preview.decision.selected_asset: 1.})
    else:
        assert payload["preview"] is None
    assert payload["disclaimer"] == page.DISCLAIMER
    json.dumps(payload, allow_nan=False)


def test_auth_required_unknown_label_and_bad_date(signed_in, monkeypatch):
    monkeypatch.setattr(page, "load_inputs", lambda definition: pytest.fail("No download for invalid request"))
    assert client.get("/api/signals").status_code == 401
    assert client.get("/api/signals?label=unknown", headers=HEADERS).status_code == 400
    assert client.get("/api/signals?as_of=2024-02-31", headers=HEADERS).status_code == 400


def test_unavailable_reason_verbatim_no_older_signal_and_not_cached(signed_in, monkeypatch):
    prices, metadata, warnings = fixtures("HAA-Simple")
    missing_month = prices.loc[prices.index < "2024-05-01"]
    monkeypatch.setattr(page, "load_inputs", lambda definition: (missing_month, metadata, warnings))
    memo = ResultCache()
    monkeypatch.setattr(page, "RESULTS", memo)
    for _ in range(2):
        result = client.get("/api/signals?as_of=2024-06-14", headers=HEADERS).json()
        assert result["current"]["reason"] == "No complete monthly price row is available for 2024-05-31."
        assert result["current"]["decision"] is None
    assert not memo.warm


def test_cache_reuses_payload_but_same_date_history_revision_invalidates(signed_in, monkeypatch):
    bundle = fixtures("HAA-Simple")
    monkeypatch.setattr(page, "load_inputs", lambda definition: bundle)
    monkeypatch.setattr(page, "RESULTS", ResultCache())
    build = page.build_payload
    calls = []
    def counted(*args):
        calls.append(1)
        return build(*args)
    monkeypatch.setattr(page, "build_payload", counted)
    url = "/api/signals?as_of=2024-06-14"
    one = client.get(url, headers=HEADERS).json()
    two = client.get(url, headers=HEADERS).json()
    assert two["cache"]["hit"] == "memory" and one["current"] == two["current"] and len(calls) == 1
    bundle[0].iloc[10, 0] *= 1.001
    three = client.get(url, headers=HEADERS).json()
    assert three["data_version"] != one["data_version"] and len(calls) == 2
    client.get("/api/signals?as_of=2024-06-13", headers=HEADERS)
    assert len(calls) == 3


def test_future_prices_cannot_change_frozen_signal_or_preview(signed_in, monkeypatch):
    bundle = fixtures("Inflation Compass Standard")
    monkeypatch.setattr(page, "load_inputs", lambda definition: bundle)
    monkeypatch.setattr(page, "RESULTS", ResultCache())
    url = "/api/signals?label=Inflation%20Compass%20Standard&as_of=2024-06-14"
    one = client.get(url, headers=HEADERS).json()
    bundle[0].loc[bundle[0].index > AS_OF] *= 100
    two = client.get(url, headers=HEADERS).json()
    assert one["current"] == two["current"] and one["preview"] == two["preview"] and one["data_version"] == two["data_version"]


def test_existing_loaders_scope_sources_and_fred_oecd_failures_are_visible(monkeypatch):
    calls = []
    frame, _, _ = fixtures("Inflation Compass Standard")
    def yahoo(mapping, **kwargs):
        calls.append((mapping, kwargs))
        return frame.reindex(columns=mapping)
    monkeypatch.setattr(page.data, "download_yahoo_prices", yahoo)
    monkeypatch.setattr(page.data, "download_fred_series", lambda assets: (_ for _ in ()).throw(RuntimeError("Mock FRED outage")))
    prices, metadata, warnings = page.load_inputs(definition_for_label("Inflation Compass Standard"))
    assert warnings[0] == "FRED retrieval issue: Mock FRED outage" and prices.T5YIE.isna().all()
    assert "complete existing live loader" in warnings[-1]
    assert "T5YIE" not in calls[0][0] and len(calls[0][0]) == 10
    monkeypatch.setattr(page.data, "download_oecd_cli_diffusion", lambda: (_ for _ in ()).throw(RuntimeError("Mock OECD outage")))
    _, _, warnings = page.load_inputs(definition_for_label("GGCEM Link Original"))
    assert warnings[0] == "OECD CLI retrieval issue: Mock OECD outage. This signal is using the disclosed SPY/BIL failsafe."
    assert "complete existing live loader" in warnings[-1]


def test_us_tase_requires_original_adjusted_us_and_tase_adapter(monkeypatch):
    calls = []
    monkeypatch.setattr(page.data, "download_yahoo_prices", lambda mapping, **kwargs: (calls.append((mapping, kwargs)) or pd.DataFrame(columns=mapping)))
    def tase(assets):
        calls.append(tuple(assets))
        return pd.DataFrame(columns=assets), pd.DataFrame(index=assets, columns=["source", "identifier", "price_field"])
    monkeypatch.setattr(page.tase_data, "download_tase_israel_prices", tase)
    definition = next(m for m in MODEL_CATALOG if getattr(m.model_class, "signal_calendar", None) == "XNYS")
    page.load_inputs(definition)
    assert calls[0][1]["require_adjusted_assets"] == definition.model_class.us_data_assets
    assert all(asset == ticker for asset, ticker in calls[0][0].items())
    assert set(calls[1]) == set(definition.model_class.execution_assets)


def test_compass_israel_requests_extended_local_history_only_and_avoids_short_snapshot(monkeypatch):
    from server import market_cache
    definition = definition_for_label("Inflation Compass Standard Israel")
    prices, metadata, _ = fixtures(definition.label)
    calls = []
    monkeypatch.setattr(page.data, "download_yahoo_prices", lambda mapping, **kw: prices.reindex(columns=mapping))
    monkeypatch.setattr(page.data, "download_fred_series", lambda assets: prices.reindex(columns=assets))
    def tase(assets, **kwargs):
        calls.append((tuple(assets), kwargs))
        return prices.reindex(columns=assets), metadata.reindex(assets)
    monkeypatch.setattr(page.tase_data, "download_tase_israel_prices", tase)
    monkeypatch.setattr(market_cache, "model_inputs", lambda *a, **kw: pytest.fail("Do not silently use a five-year snapshot"))
    page.load_inputs(definition)
    assert calls[0][1] == {"history_years": 8}
    assert set(calls[0][0]) == {"XLE_IL", "XLK_IL", "XLU_IL", "XLP_IL", "IEF_IL"}
    page.live_inputs(definition_for_label("HAA-Simple Israel"))
    assert calls[-1][1] == {}


def test_verbatim_presentation_port_ast_parity_and_no_streamlit_import():
    original = ast.parse((ROOT / "app.py").read_text())
    block = next(node for node in ast.walk(original) if isinstance(node, ast.With) and
                 any(isinstance(i.context_expr, ast.Name) and i.context_expr.id == "signal_inputs" for i in node.items))
    ported = ast.parse((ROOT / "server/signals_presentation.py").read_text())
    rationale = next(n for n in ported.body if isinstance(n, ast.FunctionDef) and n.name == "rationale")
    # Exact literal and f-string chunks, expressions and table field labels.
    strings = lambda node: sorted(n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str))
    assert strings(block) == strings(rationale)
    allocation = next(n for n in original.body if isinstance(n, ast.FunctionDef) and n.name == "display_allocation")
    copied = next(n for n in ported.body if isinstance(n, ast.FunctionDef) and n.name == "display_allocation")
    assert ast.dump(allocation, include_attributes=False) == ast.dump(copied, include_attributes=False)
    for path in (ROOT / "server").glob("signals*.py"):
        source = path.read_text()
        assert "import streamlit" not in source and "import app" not in source and "exec(" not in source


@pytest.mark.parametrize("label", ["A-RVol Shifter V3 Cash-Only Israel", next(m.label for m in MODEL_CATALOG if m.implementation == "US signals / TASE — 1x middle"), "TA-125 Smart Momentum", "GGCEM Link Original"])
def test_additional_daily_and_fund_modes_do_not_invent_monthly_instructions(signed_in, monkeypatch, label):
    bundle = fixtures(label)
    monkeypatch.setattr(page, "load_inputs", lambda definition: bundle)
    monkeypatch.setattr(page, "RESULTS", ResultCache())
    result = client.get("/api/signals", params={"label": label, "as_of": "2024-06-14"}, headers=HEADERS).json()
    assert result["current"]["available"], result
    if result["mode"] in {"daily", "buy_and_hold"}:
        assert result["preview"] is None and "instruction" not in result["current"]
    if getattr(definition_for_label(label).model_class, "signal_calendar", None) == "XNYS":
        assert any("US signals through" in c for c in result["captions"])
    if label == "TA-125 Smart Momentum":
        assert result["current"]["table"]["rows"][0]["External signal"] == "None — Buy & Hold"


def test_full_history_transport_is_compressed_without_changing_csv(signed_in, monkeypatch):
    bundle = fixtures("A-RVol Shifter V3 Cash-Only")
    monkeypatch.setattr(page, "load_inputs", lambda definition: bundle)
    monkeypatch.setattr(page, "RESULTS", ResultCache())
    response = client.get("/api/signals?label=A-RVol%20Shifter%20V3%20Cash-Only&as_of=2024-06-14", headers={**HEADERS, "Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in response.headers["vary"].lower()
    assert "display_rows" not in response.json()["history"]["table"]
    assert len(response.json()["history"]["table"]["rows"]) == response.json()["history"]["count"]
    assert "content-encoding" not in client.get("/api/strategies").headers
