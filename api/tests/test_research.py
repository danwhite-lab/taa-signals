"""Offline synthetic observations and mocked storage; direct original-engine parity."""
import ast
from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import Mock

import numpy as np
import pandas as pd
import pytest

from test_api import client, ROOT, module
from test_private_api import signed_in, HEADERS
from server import research as page, research_presentation as presentation, cache
from server.signals_wire import clean, table
from haa.validation import ValidationInput, ValidationReport, profile_for, research_unavailable_reason, run_deterministic_validation
from haa.portfolio_signals import monthly_strategy_input


def fixture(label):
    selected = page.definition(label)
    strategy = selected.model_class()
    profile = profile_for(strategy)
    assets = tuple(dict.fromkeys((*getattr(strategy, "data_assets", page.base.ASSETS), getattr(strategy, "benchmark_asset", "SPY"), *(p.proxy_asset for p in profile.proxy_substitutions))))
    dates = pd.bdate_range("2004-01-01", "2024-06-28")
    x = np.arange(len(dates))
    prices = pd.DataFrame({asset: (2+.00004*x+.03*np.sin(x/50) if asset == "T5YIE" else 100*np.exp(.0002*x+.03*np.sin(x/(10+i)))) for i, asset in enumerate(assets)}, index=dates)
    metadata = pd.DataFrame({"source": "Mock source", "identifier": list(assets), "price_field": "Mock adjusted close"}, index=pd.Index(assets, name="asset"))
    return prices, metadata, []


def direct_input(label, prices):
    selected = page.definition(label); strategy = selected.model_class(); profile = profile_for(strategy)
    assets = tuple(dict.fromkeys((*getattr(strategy, "data_assets", page.base.ASSETS), getattr(strategy, "benchmark_asset", "SPY"))))
    raw = prices.loc[:, assets]
    market = tuple(dict.fromkeys((*getattr(strategy, "market_data_assets", assets), getattr(strategy, "benchmark_asset", "SPY"))))
    monthly, monthly_input = monthly_strategy_input(raw, market)
    decision_prices = raw if getattr(strategy, "uses_daily_signals", False) else monthly_input
    decisions = strategy.decisions(decision_prices)
    proxy_monthly = {p.proxy_asset: page.base.data.to_month_end(prices[[p.proxy_asset]])[p.proxy_asset] for p in profile.proxy_substitutions}
    proxy_daily = {p.proxy_asset: prices[p.proxy_asset] for p in profile.proxy_substitutions}
    return ValidationInput(label, decisions, monthly, raw, getattr(strategy, "benchmark_asset", "SPY"), profile,
                           proxy_monthly, proxy_daily, strategy, decision_prices)


@pytest.fixture(autouse=True)
def storage(monkeypatch):
    monkeypatch.setattr(page, "RESULTS", cache.ResultCache())
    monkeypatch.setattr(cache, "cache_client", Mock(side_effect=RuntimeError("Mock shared cache unavailable")))


@pytest.mark.parametrize("label", ["HAA-Simple", "Inflation Compass Standard", "BAA-G4 (Aggressive)", "BAA-G4 (Aggressive) Israel"])
def test_exact_frames_csv_profiles_and_no_validation_in_options(signed_in, monkeypatch, label):
    prices, metadata, warnings = fixture(label)
    calls = []
    def loader(descriptor):
        calls.append(descriptor.model_class().data_assets)
        return prices, metadata, warnings
    monkeypatch.setattr(page.signals, "load_inputs", loader)
    validation = Mock(wraps=page.run_deterministic_validation); monkeypatch.setattr(page, "run_deterministic_validation", validation)
    options = client.get("/api/research/options", params={"label": label}, headers=HEADERS)
    assert options.status_code == 200, options.text
    assert validation.call_count == 0 and "prices" not in options.json()
    source = direct_input(label, prices)
    original = source.decisions.copy(deep=True)
    direct = run_deterministic_validation(source, 10000)
    response = client.post("/api/research", headers=HEADERS, json={"label": label, "initial": 10000})
    assert response.status_code == 200, response.text
    value = response.json()
    assert validation.call_count == 1
    assert response.headers["cache-control"] == "no-store, private" and len(response.content) < 3_000_000
    for kind, frame in {"scenarios": direct.scenarios, "rolling": direct.rolling_periods, "subperiods": direct.subperiods,
                        "data_quality": direct.data_quality, "scorecard": direct.scorecard, "monte_carlo": direct.monte_carlo}.items():
        assert value["tables"][kind] == clean(presentation.preview(frame))
        if kind in page.WORDS["downloads"]:
            download = client.get("/api/research/download", params={"key": value["cache"]["key"], "kind": kind}, headers=HEADERS)
            assert download.status_code == 200 and download.content == frame.to_csv(index=False).encode()
    pd.testing.assert_frame_equal(source.decisions, original)
    pd.testing.assert_frame_equal(validation.call_args.args[0].decisions, source.decisions)
    assert all(p.proxy_asset in calls[0] for p in source.profile.proxy_substitutions)
    proxies = value["tables"]["proxies"]["rows"]
    # BAA Israel declares three proxies but inherits a profile that does not
    # enable the proxy_substitution test. Preserve this original limitation.
    assert len(proxies) == (1 if label == "HAA-Simple" else 0)
    if label.endswith("Israel"):
        assert len(source.profile.proxy_substitutions) == 3
        assert "proxy_substitution" not in source.profile.applicable_tests
    if label == "Inflation Compass Standard": assert any(row["test"] == "parameter_sweep" for row in value["tables"]["execution"]["rows"])
    assert value["history"] == options.json()["history"]
    expected_grade = direct.scorecard.loc[direct.scorecard.Category == "Overall robustness", "Grade"].iloc[0]
    assert value["grade"] == expected_grade
    assert value["verdict"] == page.WORDS["verdicts"].get(expected_grade, "Mixed")


@pytest.mark.parametrize("label,expected", [("A-RVol Shifter V3 Cash-Only", "no_profile"), ("Inflation Compass Standard Israel", "no_backtest")])
def test_exact_gate_order_and_no_price_or_engine_access(signed_in, monkeypatch, label, expected):
    monkeypatch.setattr(page, "load", Mock(side_effect=AssertionError("Gated models must not load")))
    selected = page.definition(label)
    for response in (client.get("/api/research/options", params={"label": label}, headers=HEADERS), client.post("/api/research", headers=HEADERS, json={"label":label})):
        assert response.status_code == 200
        assert response.json()["gate"] == expected
        assert response.json()["reason"] == (research_unavailable_reason(selected.model_class) if expected == "no_profile" else page.WORDS["noBacktest"].format(name=selected.model_class().name))


def test_no_bootstrap_profile_and_fixed_seed_determinism(signed_in, monkeypatch):
    label = "HAA-Simple"; prices, metadata, warnings = fixture(label)
    monkeypatch.setattr(page.signals, "load_inputs", lambda *a: (prices, metadata, warnings))
    loaded = page.load(page.definition(label))
    one = run_deterministic_validation(loaded["input"], 10000)
    two = run_deterministic_validation(loaded["input"], 10000)
    pd.testing.assert_frame_equal(one.monte_carlo, two.monte_carlo)
    klass = page.definition(label).model_class
    profile = profile_for(klass)
    monkeypatch.setattr(klass, "validation_profile", replace(profile, applicable_tests=profile.applicable_tests-{"block_bootstrap"}))
    response = client.post("/api/research", headers=HEADERS, json={"label":label})
    assert response.status_code == 200 and response.json()["has_bootstrap"] is False
    assert response.json()["charts"]["monte_carlo"] is None


def test_cache_hit_revisions_settings_code_and_privacy(signed_in, monkeypatch):
    label = "HAA-Simple"; prices, metadata, warnings = fixture(label)
    monkeypatch.setattr(page.signals, "load_inputs", lambda *a: (prices, metadata, warnings))
    validation = Mock(wraps=page.run_deterministic_validation); monkeypatch.setattr(page, "run_deterministic_validation", validation)
    kwargs = dict(headers=HEADERS, json={"label":label, "initial":10000})
    one = client.post("/api/research", **kwargs).json(); two = client.post("/api/research", **kwargs).json()
    assert validation.call_count == 1 and two["cache"]["hit"] == "memory" and two["timing"]["validation_seconds"] == 0
    # Declared proxy revision, not just a production asset, must invalidate.
    proxy = profile_for(page.definition(label).model_class).proxy_substitutions[0].proxy_asset
    prices.loc[prices.index[-20],proxy] *= 1.00001
    three = client.post("/api/research", **kwargs).json()
    assert validation.call_count == 2 and three["data_version"] != one["data_version"]
    four = client.post("/api/research", headers=HEADERS, json={"label":label, "initial":20000}).json()
    assert four["cache"]["key"] != three["cache"]["key"]
    monkeypatch.setattr(module, "_engine_code_version", lambda: "fake-code-change")
    five = client.post("/api/research", **kwargs).json()
    assert five["cache"]["key"] != three["cache"]["key"]
    spy = Mock(wraps=page.RESULTS.run); monkeypatch.setattr(page.RESULTS, "run", spy)
    client.post("/api/research", **kwargs)
    content = json.dumps({k:v for k,v in spy.call_args.kwargs.items() if k != "compute"}) + json.dumps(list(page.RESULTS.warm.values()))
    for marker in ("mock-token", "mock-user", "test@example.invalid", "portfolio_id", "FAKE-PRIVATE-NAME"):
        assert marker not in content
    bad = client.post("/api/research", headers=HEADERS, json={"label": label, "user_id":"FAKE-PRIVATE-NAME"})
    assert bad.status_code == 400 and "FAKE-PRIVATE-NAME" not in bad.text


@pytest.mark.parametrize("body", [{"label":"unknown"}, {"initial":-1}, {"initial":None}, {"initial":"private amount"}, {"fee":1}, {"start":"2020-01-01"}])
def test_validation_and_no_error_body_echo(signed_in, body):
    response = client.post("/api/research", headers=HEADERS, json=body)
    assert response.status_code == 400 and "private amount" not in response.text


def test_auth_methods_download_missing_and_failed_run_not_cached(signed_in, monkeypatch):
    for name in ("load_workspace","list_portfolios","save_workspace","save_portfolio","delete_portfolio"):
        monkeypatch.setattr(module.private_api.sync,name,Mock(side_effect=AssertionError("Research never accesses private saved data")))
    assert client.get("/api/research/options").status_code == 401
    assert client.post("/api/research", json={}).status_code == 401
    assert client.get("/api/research/download?key=bad&kind=scenarios").status_code == 401
    assert client.get("/api/research", headers=HEADERS).status_code == 405
    assert client.post("/api/research/options", headers=HEADERS, json={}).status_code == 405
    assert client.get("/api/research/download", params={"key":"0"*64,"kind":"scenarios"}, headers=HEADERS).status_code == 404
    prices, metadata, warnings = fixture("HAA-Simple")
    monkeypatch.setattr(page.signals, "load_inputs", lambda *a: (prices, metadata, warnings))
    monkeypatch.setattr(page, "run_deterministic_validation", Mock(side_effect=RuntimeError("Mock failed validation")))
    response = client.post("/api/research", headers=HEADERS, json={})
    assert response.status_code == 400 and not page.RESULTS.warm
    monkeypatch.setattr(module.private_api.sync, "verified_session", Mock(side_effect=ValueError("Mock expired")))
    assert client.post("/api/research", headers=HEADERS, json={}).status_code == 401


def test_original_research_words_and_no_runtime_app_reader():
    literals = {node.value for node in ast.walk(ast.parse((ROOT/"app.py").read_text())) if isinstance(node,ast.Constant) and isinstance(node.value,str)}
    for key in ("caption", "readMarkdown", "scoreMarkdown", "info", "before", "completed", "executionCaption", "proxyCaption", "qualityCaption", "bootstrapCaption", "noBootstrap", "scoreCaption", "limits"):
        assert page.WORDS[key] in literals, key
    source = (ROOT/"server/research.py").read_text()+(ROOT/"server/research_presentation.py").read_text()
    assert "app.py" not in source
    assert "MINIMUM_NOTE" not in source


@pytest.mark.parametrize("grade,expected", [("A","Reasonably robust"),("B+","Reasonably robust"),("B","Reasonably robust"),("C","Mixed"),("D","Fragile"),("Not assessed","Not enough evidence yet"),("unknown","Mixed")])
def test_verdict_and_three_check_fallback_are_exact(grade, expected):
    selected = page.definition("HAA-Simple")
    scenarios = pd.DataFrame([{"test":"baseline","scenario":"published","status":"unavailable"}])
    scorecard = pd.DataFrame([{"Category":"Overall robustness","Grade":grade,"Evidence":"Mock overall evidence"}])
    report = ValidationReport(scenarios, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), scorecard, pd.DataFrame())
    public = presentation.present(report, page.Inputs(), selected, profile_for(selected.model_class), {"history":{},"metadata":{}})["public"]
    assert public["verdict"] == expected
    assert public["meaning"] == page.WORDS["meanings"][expected]
    assert public["cards"][1]["value"] == "Unavailable" and public["cards"][2]["value"] == "Unavailable"
    assert all(row["Result"] == "Not assessed" for row in public["checks"]["rows"])


def test_initial_scaling_and_oversize_failure_not_cached(signed_in, monkeypatch):
    prices, metadata, warnings = fixture("HAA-Simple")
    monkeypatch.setattr(page.signals,"load_inputs",lambda *a:(prices,metadata,warnings))
    loaded = page.load(page.definition("HAA-Simple"))
    one = run_deterministic_validation(loaded["input"],10000)
    two = run_deterministic_validation(loaded["input"],20000)
    complete = (one.scenarios.status=="complete") & (two.scenarios.status=="complete")
    np.testing.assert_allclose(one.scenarios.loc[complete,"CAGR"],two.scenarios.loc[complete,"CAGR"],atol=1e-9,rtol=0)
    assert one.scorecard.Grade.tolist() == two.scorecard.Grade.tolist()
    # Display errors must be raised before ResultCache can remember the bundle.
    original = presentation.present
    def oversized(*args,**kwargs):
        bundle=original(*args,**kwargs); bundle["public"]["meaning"]="X"*3_000_000; return bundle
    monkeypatch.setattr(presentation,"present",oversized)
    response=client.post("/api/research",headers=HEADERS,json={"initial":10000})
    assert response.status_code==400 and not page.RESULTS.warm
