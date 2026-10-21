"""All data/SDK access is mocked; reference computations use the unchanged engine."""
from io import StringIO
import json
from unittest.mock import MagicMock

import pandas as pd
import pytest

from test_api import ROOT, client
from test_private_api import signed_in, HEADERS
from test_signals import fixtures, LABELS
from server import backtest as page, cache
from haa.engine import run_backtest
from haa.backtest_options import result_metrics
from haa.model_catalog import definition_for_label
from haa.portfolio_signals import monthly_strategy_input
from haa.tase_data import plain_holding_provenance


@pytest.fixture(autouse=True)
def mocked_storage(monkeypatch):
    monkeypatch.setattr(cache, "cache_client", lambda: (_ for _ in ()).throw(RuntimeError("Mock cache unavailable")))
    monkeypatch.setattr(page, "RESULTS", cache.ResultCache())


def bundle(label):
    prices, metadata, warnings = fixtures(label)
    return prices, metadata, warnings, prices * .999 if label == "A-RVol Shifter V3 Cash-Only" else None


@pytest.mark.parametrize("label", LABELS)
@pytest.mark.parametrize("tax_enabled", [False, True])
@pytest.mark.parametrize("deposit", [0., 100.])
def test_exact_engine_parity_tax_deposits_whole_ledger_and_rows(signed_in, monkeypatch, label, tax_enabled, deposit):
    prices, metadata, warnings, opens = bundle(label)
    monkeypatch.setattr(page, "load_data", lambda selected: (prices, metadata, warnings, opens))
    selected = definition_for_label(label)
    # Direct app.py path: shared monthly input, original decisions, original engine.
    strategy = selected.model_class()
    benchmark = getattr(strategy, "benchmark_asset", "SPY")
    assets = tuple(dict.fromkeys((*getattr(strategy, "data_assets", ("SPY", "TIP", "IEF", "BIL")), benchmark)))
    raw = prices.loc[:, assets]
    market = tuple(dict.fromkeys((*getattr(strategy, "market_data_assets", assets), benchmark)))
    monthly, monthly_input = monthly_strategy_input(raw, market)
    decisions = strategy.decisions(raw if getattr(strategy, "uses_daily_signals", False) else monthly_input)
    options = client.get("/api/backtest/options", params={"label": label}, headers=HEADERS)
    assert options.status_code == 200, options.text
    bounds = options.json()["bounds"]
    start, end = bounds["start_min"], bounds["end_max"]
    direct = run_backtest(decisions, monthly, 10000., .0005, tax_enabled, .25,
                          pd.Timestamp(start), pd.Timestamp(end), daily_prices=raw, benchmark_asset=benchmark,
                          daily_open_prices=opens, monthly_contribution=deposit, fixed_fee=0.)
    body = {"label": label, "initial": 10000., "start": start, "end": end,
            "fee_type": "percentage", "fee_value": .05, "tax_enabled": tax_enabled, "tax_rate": 25., "monthly_contribution": deposit}
    response = client.post("/api/backtest", headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    actual = response.json()
    for key, column in [("pre_tax", "pre_tax_value"), ("after_tax", "after_tax_value"), ("benchmark", "benchmark_value")]:
        metrics = result_metrics(direct, column, 10000.)
        for metric in ["Final value", "CAGR", "Maximum drawdown"]:
            assert actual["metrics"][key][metric] == pytest.approx(metrics[metric], abs=1e-9, rel=0)
    nav = direct.daily if direct.daily is not None else direct.monthly
    assert actual["report_rows"] == len(nav)
    assert actual["monthly_rows"] == len(direct.monthly)
    assert actual["first_date"] == nav.index.min().isoformat() and actual["last_date"] == nav.index.max().isoformat()
    assert actual["tax_event_count"] == len(direct.tax_events)
    key = actual["cache"]["key"]
    ledger = client.get("/api/backtest/download", params={"key": key, "kind": "tax_events"}, headers=HEADERS)
    assert ledger.status_code == 200 and ledger.content == direct.tax_events.to_csv(index=False).encode("utf-8")
    if direct.daily is not None:
        daily = client.get("/api/backtest/download", params={"key": key, "kind": "daily_nav"}, headers=HEADERS)
        assert daily.content == direct.daily.to_csv().encode("utf-8")
    assert actual["engine_parameters"]["transaction_cost"] == .0005
    assert actual["engine_parameters"]["monthly_contribution"] == deposit
    assert actual["engine_parameters"]["tax_rate"] == .25
    assert any(page.MINIMUM_NOTE == text for text in actual["warnings"])
    assert len(actual["summary"]["columns"]) == (4 if tax_enabled else 3)
    assert len(response.content) < 3_000_000


@pytest.mark.parametrize("patch", [
    {"label": "unknown"}, {"initial": -1}, {"initial": None}, {"fee_value": -1}, {"tax_rate": 101},
    {"fee_type": "minimum"}, {"fee_value": 11}, {"monthly_contribution": -1},
    {"start": "2024-05-01", "end": "2024-01-01"}, {"start": "bad-date"}, {"reference_replay": True},
])
def test_input_validation_is_400_not_cached(signed_in, monkeypatch, patch):
    data = bundle("HAA-Simple")
    monkeypatch.setattr(page, "load_data", lambda selected: data)
    result = client.post("/api/backtest", headers=HEADERS, json=patch)
    assert result.status_code == 400
    assert not page.RESULTS.warm


def test_auth_required_options_run_download():
    assert client.get("/api/backtest/options").status_code == 401
    assert client.post("/api/backtest", json={}).status_code == 401
    assert client.get("/api/backtest/download?key=mock&kind=audit").status_code == 401


def test_cache_hit_and_data_open_parameter_misses(signed_in, monkeypatch):
    prices, metadata, warnings, opens = bundle("A-RVol Shifter V3 Cash-Only")
    monkeypatch.setattr(page, "load_data", lambda selected: (prices, metadata, warnings, opens))
    engine = page.run_backtest
    calls = MagicMock(side_effect=engine)
    monkeypatch.setattr(page, "run_backtest", calls)
    body = {"label": "A-RVol Shifter V3 Cash-Only", "initial": 10000.}
    one = client.post("/api/backtest", headers=HEADERS, json=body).json()
    two = client.post("/api/backtest", headers=HEADERS, json=body).json()
    assert calls.call_count == 1 and two["cache"]["hit"] == "memory" and one["calculated_at"] == two["calculated_at"]
    assert two["timing"]["engine_seconds"] == 0.
    opens.iloc[-10, 0] *= 1.00001
    three = client.post("/api/backtest", headers=HEADERS, json=body).json()
    assert calls.call_count == 2 and one["data_version"] != three["data_version"]
    client.post("/api/backtest", headers=HEADERS, json={**body, "monthly_contribution": 100})
    assert calls.call_count == 3


def test_failed_engine_does_not_cache_and_fixed_fee_is_passed_unchanged(signed_in, monkeypatch):
    monkeypatch.setattr(page, "load_data", lambda selected: bundle("HAA-Simple"))
    fake = MagicMock(side_effect=ValueError("Mock engine refused order"))
    monkeypatch.setattr(page, "run_backtest", fake)
    body = {"fee_type": "fixed", "fee_value": 2., "tax_enabled": True, "tax_rate": 25.}
    for _ in range(2):
        assert client.post("/api/backtest", headers=HEADERS, json=body).status_code == 400
    assert fake.call_count == 2 and not page.RESULTS.warm
    assert fake.call_args.args[3:6] == (0., True, .25)
    assert fake.call_args.kwargs["fixed_fee"] == 2.


def test_bad_dates_beyond_common_range(signed_in, monkeypatch):
    monkeypatch.setattr(page, "load_data", lambda selected: bundle("HAA-Simple"))
    for body in ({"start": "1900-01-01"}, {"end": "2100-01-01"}):
        assert client.post("/api/backtest", headers=HEADERS, json=body).status_code == 400


def test_full_download_cannot_reveal_other_cache_types_or_unknown_names(signed_in):
    assert client.get("/api/backtest/download?key=not-a-key&kind=audit", headers=HEADERS).status_code == 400
    assert client.get("/api/backtest/download", params={"key": "a"*64, "kind": "tax_events"}, headers=HEADERS).status_code == 404


def test_live_loader_requires_same_source_opens_only_for_us_daily(monkeypatch):
    calls = []
    def loader(selected, daily_bars=False):
        calls.append((selected.label, daily_bars))
        return ("closes", "metadata", [], "opens") if daily_bars else ("closes", "metadata", [])
    monkeypatch.setattr(page.signals, "load_inputs", loader)
    assert page.load_data(definition_for_label("A-RVol Shifter V3 Cash-Only"))[-1] == "opens"
    assert page.load_data(definition_for_label("A-RVol Shifter V3 Cash-Only Israel"))[-1] is None
    assert calls[0][1] is True and calls[1][1] is False


@pytest.mark.parametrize("reference", [False, True])
def test_us_signals_tase_replay_keeps_original_cash_start_and_ledger(signed_in, monkeypatch, reference):
    from haa.model_catalog import MODEL_CATALOG
    selected = next(m for m in MODEL_CATALOG if m.implementation == "US signals / TASE — 50:50 middle")
    prices, metadata, warnings = fixtures(selected.label)
    monkeypatch.setattr(page, "load_data", lambda definition: (prices, metadata, warnings, None))
    options = page.options(selected.label)
    start, end = options["bounds"]["start_min"], options["bounds"]["end_max"]
    response = client.post("/api/backtest", headers=HEADERS, json={"label": selected.label, "reference_replay": reference, "initial": 10000, "start": start, "end": end})
    assert response.status_code == 200, response.text
    strategy = selected.model_class()
    market = tuple(dict.fromkeys((*strategy.market_data_assets, strategy.benchmark_asset)))
    monthly, _ = monthly_strategy_input(prices, market)
    decisions = strategy.decisions(prices, cash_start=pd.Timestamp(start).date() if reference else None)
    direct = run_backtest(decisions, monthly, 10000, 0, True, .25, pd.Timestamp(start), pd.Timestamp(end),
                          daily_prices=prices, benchmark_asset=strategy.benchmark_asset,
                          daily_open_prices=None, monthly_contribution=0, fixed_fee=0)
    assert response.json()["metrics"]["after_tax"]["Final value"] == pytest.approx(result_metrics(direct, "after_tax_value", 10000)["Final value"], abs=1e-9, rel=0)
    csv = client.get("/api/backtest/download", params={"key": response.json()["cache"]["key"], "kind": "tax_events"}, headers=HEADERS)
    assert csv.content == direct.tax_events.to_csv(index=False).encode()


def test_real_fallback_warning_visible_and_main_payload_is_small(signed_in, monkeypatch):
    prices, metadata, _, opens = bundle("A-RVol Shifter V3 Cash-Only")
    monkeypatch.setattr(page, "load_data", lambda selected: (prices, metadata, ["Mock disclosed source failure/failsafe"], opens))
    result = client.post("/api/backtest", headers=HEADERS, json={"label": "A-RVol Shifter V3 Cash-Only"})
    assert result.status_code == 200
    assert "Mock disclosed source failure/failsafe" in result.json()["warnings"]
    assert any("Result cache unavailable" in text for text in result.json()["warnings"])
    assert result.json()["value_chart"]["display_rows"] <= 700
    assert result.json()["periods"]["shown_rows"] <= 150
    assert result.json()["report_rows"] > result.json()["periods"]["shown_rows"]
    assert len(result.content) < 3_000_000


def test_bad_token_is_401(signed_in):
    assert client.post("/api/backtest", headers={"Authorization": "Bearer invalid-mock-token"}, json={}).status_code == 401
