"""Offline route parity with the unchanged engines; only fake account inputs."""
from copy import deepcopy
import ast
from unittest.mock import Mock
import json
import pandas as pd
import pytest

from test_api import client, ROOT
from test_private_api import signed_in, HEADERS
from test_signals import fixtures
from server import backtest as base, backtest_multi as page, cache, private_api
from server.signals_wire import table, clean
from haa.comparison import ModelInput
from haa.constants import ASSETS
from haa.model_catalog import definition_for_label
from haa.portfolio_signals import monthly_strategy_input
from haa.portfolio_backtest import run_portfolio_backtest
from haa.engine import run_backtest
from haa.backtest_options import result_metrics, unit_curves
from haa.deep_history import ALL_DEEP_HISTORY_SPECS, DEEP_HISTORY_BENCHMARKS, deep_history_model_input
from haa.synthetic_history import monthly_blend_input
from haa.tase_data import plain_holding_provenance


@pytest.fixture(autouse=True)
def storage(monkeypatch):
    monkeypatch.setattr(base, "RESULTS", cache.ResultCache())
    monkeypatch.setattr(cache, "cache_client", Mock(side_effect=RuntimeError("Mock cache unavailable")))


def body(labels=("HAA-Simple", "Buy and Hold SPY"), mode="portfolio", **updates):
    value = {"mode": mode, "initial": 10000., "tax_enabled": True, "tax_rate": 25,
             "sleeves": [{"id": i, "model": label, "weight": 100/len(labels)} for i, label in enumerate(labels, 1)]}
    value.update(updates)
    return value


def live_fixture(monkeypatch, labels):
    columns = {}
    for label in labels:
        for asset, series in fixtures(label)[0].items(): columns.setdefault(asset, series)
    prices = pd.DataFrame(columns)
    metadata = pd.DataFrame({"source": "Mock fixture", "identifier": list(prices), "price_field": "Mock close"}, index=pd.Index(prices.columns, name="asset"))
    opens = prices*.999
    def load(definition, *, daily_bars=False):
        return (prices, metadata, [], opens) if daily_bars else (prices, metadata, [])
    monkeypatch.setattr(page.signals, "load_inputs", load)
    return prices, opens


def independent_live(request, prices, opens):
    inputs = {}
    for sleeve in request["sleeves"]:
        strategy = definition_for_label(sleeve["model"]).model_class()
        key = f"{sleeve['model']} ({len(inputs)+1})"
        assets = tuple(dict.fromkeys((*getattr(strategy, "data_assets", ASSETS), "SPY")))
        daily = prices.loc[:, assets]
        market = tuple(dict.fromkeys((*getattr(strategy, "market_data_assets", assets), "SPY")))
        monthly, decision_prices = monthly_strategy_input(daily, market)
        decisions = strategy.decisions(daily if getattr(strategy, "uses_daily_signals", False) else decision_prices)
        inputs[key] = (sleeve["weight"]/100, ModelInput(key, decisions, monthly, daily, "SPY", opens, "USD"))
    return inputs


@pytest.mark.parametrize('labels', [('HAA-Simple','Buy and Hold SPY'), ('A-RVol Shifter V3 Cash-Only','Buy and Hold SPY')])
def test_portfolio_currency_fees_end_to_end(signed_in, monkeypatch, labels):
    prices, opens = live_fixture(monkeypatch, labels)
    request = body(labels, fees_enabled=True, monthly_contribution=100.)
    response = client.post('/api/backtest',headers=HEADERS,json=request)
    assert response.status_code == 200, response.text
    value = response.json()
    from haa.trading_fees import TradingFees, totals
    direct = run_portfolio_backtest(independent_live(request, prices, opens),10000,
        tax_enabled=True,monthly_contribution=100.,trading_fees=TradingFees('USD'))
    assert value['fees']['pre_tax'] == totals(direct)['pre_tax']
    assert value['fees']['after_tax'] == totals(direct)['after_tax']
    assert value['metrics']['after_tax']['Final value'] == direct.monthly.after_tax_value.iloc[-1]
    assert value['engine_parameters']['trading_fees']['currency']=='USD'


@pytest.mark.parametrize('proxy',['rvol_daily','rvol_synthetic'])
def test_fee_incompatible_history_is_explicit_error_not_silently_free(signed_in,proxy):
    response=client.post('/api/backtest',headers=HEADERS,json=body((proxy,), 'deep',fees_enabled=True))
    assert response.status_code==400
    assert 'fee' in response.json()['detail'].lower()


def assert_report(response, direct, initial=10000., proxy=False):
    assert response.status_code == 200, response.text
    value = response.json()
    for name, column in (("pre_tax", "pre_tax_value"), ("after_tax", "after_tax_value"), ("benchmark", "benchmark_value")):
        expected = clean(result_metrics(direct, column, initial))
        assert value["metrics"][name] == expected
    nav = direct.monthly if proxy else direct.daily if direct.daily is not None else direct.monthly
    labels = [s["label"] for s in value["value_chart"]["series"]]
    columns = ["pre_tax_value", "after_tax_value", "benchmark_value"] if len(labels) == 3 else ["pre_tax_value", "benchmark_value"]
    curves = pd.DataFrame({label: nav[column] for label, column in zip(labels, columns)})
    assert value["value_chart"] == clean(base.chart(curves))
    units = unit_curves(direct, dict(zip(labels, columns)), initial)
    assert value["drawdown_chart"] == clean(base.chart(units.div(units.cummax().clip(lower=initial)).sub(1)))
    audit = direct.audit if direct.audit is not None else direct.monthly
    assert value["periods"] == clean(base.preview(audit))
    assert value["tax_events"] == clean(base.preview(direct.tax_events))
    assert (base.MINIMUM_NOTE in value['warnings']) == bool(value['settings']['fee_value'])
    assert response.headers["cache-control"] == "no-store, private"
    assert len(response.content) < 3_000_000
    return value


@pytest.mark.parametrize("labels,rule", [
    (("HAA-Simple", "Buy and Hold SPY"), "none"),
    (("HAA-Simple", "Buy and Hold SPY", "Buy and Hold IEF"), "none"),
    (("A-RVol Shifter V3 Cash-Only", "Buy and Hold SPY"), "none"),
    (("A-RVol Shifter V3 Cash-Only", "Buy and Hold SPY"), "rvol_cap"),
    (("A-RVol Shifter V3 Cash-Only", "Buy and Hold SPY"), "annual_target"),
])
@pytest.mark.parametrize("fee_type,fee_value,deposit", [("percentage", .05, 0), ("fixed", 2, 100)])
def test_portfolio_route_matches_direct_engine(signed_in, monkeypatch, labels, rule, fee_type, fee_value, deposit):
    if rule != "none": deposit = 0  # Existing engine rejects transfers + deposits.
    prices, opens = live_fixture(monkeypatch, labels)
    request = body(labels, sleeve_rebalance_mode=rule, rebalance_sleeve=1 if rule == "rvol_cap" else None,
                   fee_type=fee_type, fee_value=fee_value, monthly_contribution=deposit)
    inputs = independent_live(request, prices, opens)
    direct = run_portfolio_backtest(inputs, 10000, transaction_cost=.0005 if fee_type == "percentage" else 0.,
        fixed_fee=fee_value if fee_type == "fixed" else 0., tax_enabled=True, tax_rate=.25, monthly_contribution=deposit,
        sleeve_rebalance_mode=rule, rebalance_sleeve="A-RVol Shifter V3 Cash-Only (1)" if rule == "rvol_cap" else None,
        rebalance_cap=.15, rebalance_target=.10)
    actual = assert_report(client.post("/api/backtest", headers=HEADERS, json=request), direct)
    for item in actual["downloads"]:
        if item["kind"] == "history_sources":
            assets = tuple(a for label in labels if getattr(definition_for_label(label).model_class, "actual_history_only", False) for a in definition_for_label(label).model_class.data_assets)
            metadata = pd.DataFrame({"source": "Mock fixture", "identifier": list(prices), "price_field": "Mock close"}, index=pd.Index(prices.columns, name="asset"))
            expected = (plain_holding_provenance(metadata, assets), True)
        else:
            expected = {"portfolio_nav": (direct.daily, True), "sleeve_nav": (direct.sleeve_nav, True), "executions": (direct.audit, False), "sleeve_tax": (direct.tax_events, False)}[item["kind"]]
        response = client.get("/api/backtest/download", params={"key": actual["cache"]["key"], "kind": item["kind"]}, headers=HEADERS)
        assert response.content == expected[0].to_csv(index=expected[1]).encode()


@pytest.mark.parametrize("labels", [("haa_simple",), ("buy_and_hold_gld",), ("buy_and_hold_ief",), ("century_momentum", "inflation_compass"), ("century_momentum", "rvol_synthetic"), ("rvol_daily",), ("rvol_synthetic",)])
@pytest.mark.parametrize("benchmark", ["sp500", "global"])
def test_proxy_route_exact_original_helpers_and_sources(signed_in, labels, benchmark):
    request = body(labels, "deep", benchmark=benchmark, start="2020-01-31", end="2023-12-31")
    inputs = {}
    for i, label in enumerate(labels, 1):
        spec = ALL_DEEP_HISTORY_SPECS[label]
        model = deep_history_model_input(spec, DEEP_HISTORY_BENCHMARKS[benchmark])
        inputs[f"{spec.label} ({i})"] = (1/len(labels), monthly_blend_input(model) if len(labels) > 1 else model)
    if len(labels) == 1:
        model = next(iter(inputs.values()))[1]
        direct = run_backtest(model.decisions, model.monthly_prices, 10000, daily_prices=model.daily_prices,
            benchmark_asset=model.benchmark_asset, tax_enabled=labels[0] != "rvol_daily", start=pd.Timestamp(request["start"]), end=pd.Timestamp(request["end"]))
    else:
        direct = run_portfolio_backtest(inputs, 10000, tax_enabled=True, start=pd.Timestamp(request["start"]), end=pd.Timestamp(request["end"]))
    actual = assert_report(client.post("/api/backtest", headers=HEADERS, json=request), direct, proxy=True)
    assert actual["engine_parameters"]["tax_enabled"] == (labels != ("rvol_daily",))
    for item in actual["downloads"]:
        if not item["kind"].startswith("source_"): continue
        response = client.get("/api/backtest/download", params={"key": actual["cache"]["key"], "kind": item["kind"]}, headers=HEADERS)
        assert response.content == (page.deep.DEEP_HISTORY_DIR/item["filename"]).read_bytes()
    for label in labels:
        caveat = ALL_DEEP_HISTORY_SPECS[label].caveat
        if caveat: assert caveat in actual["warnings"]


@pytest.mark.parametrize("patch", [
    {"sleeves": [{"id": 1, "model": "HAA-Simple", "weight": 99}]},
    {"sleeves": [{"id": 1, "model": "HAA-Simple", "weight": 0}, {"id": 2, "model": "Buy and Hold SPY", "weight": 100}]},
    {"sleeves": [{"id": 1, "model": "unknown", "weight": 100}]}, {"fee_value": -1}, {"monthly_contribution": -1},
    {"start": "bad"}, {"start": "2024-02-01", "end": "2020-01-01"},
    {"sleeves": [{"id": i, "model": "HAA-Simple", "weight": 1} for i in range(1, 102)]},
    {"mode": "deep", "sleeves": [{"id": 1, "model": "haa_simple", "weight": 50}, {"id": 2, "model": "haa_simple", "weight": 50}]},
    {"mode": "deep", "sleeves": [{"id": 1, "model": "rvol_daily", "weight": 50}, {"id": 2, "model": "haa_simple", "weight": 50}]},
    {"sleeve_rebalance_mode": "rvol_cap"}, {"reference_replay": True}, {"label": "FAKE PRIVATE NAME"},
])
def test_invalid_requests_fail_4xx_before_data_not_cached(signed_in, monkeypatch, patch):
    monkeypatch.setattr(page, "live_inputs", Mock(side_effect=AssertionError("Must not load data")))
    request = body(); request.update(patch)
    for path in ("/api/backtest", "/api/backtest/validate"):
        response = client.post(path, headers=HEADERS, json=request)
        assert 400 <= response.status_code < 500, response.text
    assert not base.RESULTS.warm


def test_no_auth_or_bad_token_never_reads_private_data(monkeypatch, signed_in):
    for headers in ({}, HEADERS):
        if headers: monkeypatch.setattr(private_api.sync, "verified_session", Mock(side_effect=ValueError("Mock expired")))
        assert client.post("/api/backtest", headers=headers, json=body()).status_code == 401
        assert client.get("/api/backtest/config?mode=deep", headers=headers).status_code == 401
        assert client.post("/api/backtest/load", headers=headers, json={"mode": "portfolio", "portfolio_id": "fake"}).status_code == 401


def test_saved_and_file_loading_use_saved_fx_without_writes(signed_in, monkeypatch):
    payload = {"version": 1, "name": "FAKE PRIVATE NAME", "total_ils": 12000, "ils_per_usd": 4,
               "sleeves": [{"model": "Century Momentum", "weight": 100}]}
    monkeypatch.setattr(private_api.sync, "list_portfolios", lambda *a: [{"id": "FAKE-PRIVATE-ID", "payload": payload}])
    for name in ("save_portfolio", "delete_portfolio", "save_workspace"):
        monkeypatch.setattr(private_api.sync, name, Mock(side_effect=AssertionError("No writes")))
    for mode in ("portfolio", "deep"):
        for source in ({"payload": payload}, {"portfolio_id": "FAKE-PRIVATE-ID"}):
            response = client.post("/api/backtest/load", headers=HEADERS, json={"mode": mode, **source})
            assert response.status_code == 200, response.text
            assert response.json()["initial"] == 3000
            assert response.json()['sleeve_rebalance_mode']=='none'
            assert response.json()['rebalance_sleeve'] is None
            assert response.json()["sleeves"][0]["model"] == ("century_momentum" if mode == "deep" else "Century Momentum")
    assert not base.RESULTS.warm


@pytest.mark.parametrize('null_fields',[False,True])
def test_weights_only_saved_backtest_still_requires_capital_fx(signed_in,monkeypatch,null_fields):
    payload={'version':1,'name':'Fake weights only','sleeves':[{'model':'Buy and Hold SPY','weight':100}]}
    if null_fields:payload.update(total_ils=None,ils_per_usd=None)
    monkeypatch.setattr(private_api.sync,'list_portfolios',lambda *a:[{'id':'FAKE-ID','payload':payload}])
    for source in ({'portfolio_id':'FAKE-ID'},{'payload':payload}):
        response=client.post('/api/backtest/load',headers=HEADERS,json={'mode':'portfolio',**source})
        assert response.status_code==400
        assert response.json()['detail']=='Saved capital and FX rate must be positive and finite.'


@pytest.mark.parametrize('mode',['none','annual_target','rvol_cap'])
def test_saved_transfer_rule_roundtrip_save_to_load_and_engine_parameters(signed_in,monkeypatch,mode):
    from copy import deepcopy
    rvol='A-RVol Shifter V3 Cash-Only'
    payload={'version':1,'name':'Fake transfer portfolio','total_ils':12000,'ils_per_usd':4,
        'sleeves':[{'id':99,'model':'Buy and Hold SPY','weight':80},{'id':1001,'model':rvol,'weight':20}],
        'transfer_rule':{'mode':mode,**({'sleeve_model':rvol,'cap_percent':17.5,'target_percent':9.25} if mode=='rvol_cap' else {})}}
    original=deepcopy(payload); rows=[]
    def save(url,key,session,value,**kwargs):
        assert session['user_id']=='mock-user'
        assert kwargs=={'is_default':True,'existing_id':None,'expected_updated_at':None}
        row={'id':'fake-saved','payload':deepcopy(value),'name':value['name'],'updated_at':'mock-date','is_default':True}
        rows.append(row);return row
    monkeypatch.setattr(private_api.sync,'save_portfolio',save)
    monkeypatch.setattr(private_api.sync,'list_portfolios',lambda *args:rows)
    response=client.post('/api/portfolios',headers=HEADERS,json={'payload':payload,'is_default':True})
    assert response.status_code==200,response.text
    assert rows[0]['payload']==original
    for source in ({'portfolio_id':'fake-saved'},{'payload':payload}):
        response=client.post('/api/backtest/load',headers=HEADERS,json={'mode':'portfolio',**source})
        assert response.status_code==200,response.text
        value=response.json()
        assert value['initial']==3000
        assert value['sleeve_rebalance_mode']==mode
        request=page.validated(page.Inputs(mode='portfolio',sleeves=value['sleeves'],initial=value['initial'],
            **{key:value[key] for key in ('sleeve_rebalance_mode','rebalance_sleeve','rebalance_cap','rebalance_target')}))
        passed=page.engine_parameters(request)
        assert passed['sleeve_rebalance_mode']==mode
        if mode=='rvol_cap':
            assert value['rebalance_sleeve']==2
            assert passed['rebalance_sleeve']==rvol+' (2)'
            assert passed['rebalance_cap']==.175 and passed['rebalance_target']==.0925
    assert payload==original and len(rows)==1


def test_saved_transfer_rule_load_rejects_missing_sleeve_and_active_deep_rule(signed_in):
    payload={'version':1,'name':'Fake','total_ils':1000,'ils_per_usd':4,'sleeves':[{'model':'Buy and Hold SPY','weight':100}],
        'transfer_rule':{'mode':'rvol_cap','sleeve_model':'A-RVol Shifter V3 Cash-Only','cap_percent':15,'target_percent':10}}
    response=client.post('/api/backtest/load',headers=HEADERS,json={'mode':'portfolio','payload':payload})
    assert response.status_code==400
    assert response.json()['detail']=='Saved transfer rule is invalid or its RVol sleeve is unavailable.'
    payload['transfer_rule']={'mode':'annual_target'}
    response=client.post('/api/backtest/load',headers=HEADERS,json={'mode':'deep','payload':payload})
    assert response.status_code==400 and response.json()['detail']==page.WORDS['savedTransferDeep']


def test_cache_sorted_sleeves_revision_settings_and_failure(signed_in, monkeypatch):
    labels = ("HAA-Simple", "Buy and Hold SPY")
    prices, _ = live_fixture(monkeypatch, labels)
    engine = Mock(wraps=page.calculate); monkeypatch.setattr(page, "calculate", engine)
    request = body(labels)
    one = client.post("/api/backtest", headers=HEADERS, json=request).json()
    two = client.post("/api/backtest", headers=HEADERS, json=request).json()
    assert two["cache"]["hit"] == "memory" and engine.call_count == 1
    request["sleeves"].reverse()
    reordered = client.post("/api/backtest", headers=HEADERS, json=request).json()
    assert reordered["cache"]["key"] != one["cache"]["key"] and engine.call_count == 2
    prices.iloc[-20, 0] *= 1.000001
    three = client.post("/api/backtest", headers=HEADERS, json=request).json()
    assert three["cache"]["key"] != reordered["cache"]["key"] and engine.call_count == 3
    request["monthly_contribution"] = 100
    four = client.post("/api/backtest", headers=HEADERS, json=request).json()
    assert four["cache"]["key"] != three["cache"]["key"]
    content = json.dumps(list(base.RESULTS.warm.values()))
    assert "FAKE PRIVATE NAME" not in content and "FAKE-PRIVATE-ID" not in content and "mock-token" not in content
    base.RESULTS.warm.clear()
    monkeypatch.setattr(page, "calculate", Mock(side_effect=ValueError("Mock engine failed")))
    assert client.post("/api/backtest", headers=HEADERS, json=request).status_code == 400
    assert not base.RESULTS.warm


def test_daily_proxy_fee_requests_are_not_applied(signed_in):
    response = client.post("/api/backtest", headers=HEADERS, json=body(("rvol_daily",), "deep", fee_type="fixed", fee_value=5))
    assert response.status_code == 200, response.text
    assert response.json()["engine_parameters"]["fixed_fee"] == 0
    assert response.json()["engine_parameters"]["transaction_cost"] == 0
    assert page.WORDS["unsupportedFees"] in response.json()["warnings"]


def test_deep_cache_hit_file_revision_and_code_invalidation(signed_in, monkeypatch, tmp_path):
    original = deep_history_model_input(ALL_DEEP_HISTORY_SPECS["haa_simple"])
    monkeypatch.setattr(page.deep, "deep_history_model_input", lambda *a, **k: deepcopy(original))
    monkeypatch.setattr(page.deep, "DEEP_HISTORY_DIR", tmp_path)
    data_file = tmp_path/"fake_source.csv"
    data_file.write_text("fake bundled version one")
    request = page.Inputs(**body(("haa_simple",), "deep"))
    one = page.run(request, "fake-code-one")
    two = page.run(request, "fake-code-one")
    assert two["cache"]["hit"] == "memory"
    data_file.write_text("fake bundled version two")
    three = page.run(request, "fake-code-one")
    assert three["cache"]["hit"] is None and three["data_version"] != one["data_version"]
    four = page.run(request, "fake-code-two")
    assert four["cache"]["key"] != three["cache"]["key"]


def test_loaded_private_markers_never_enter_cache(signed_in, monkeypatch):
    live_fixture(monkeypatch, ("Buy and Hold SPY",))
    payload = {"version": 1, "name": "FAKE PRIVATE NAME", "total_ils": 12000, "ils_per_usd": 4,
               "sleeves": [{"id": 991111, "model": "Buy and Hold SPY", "weight": 100}]}
    monkeypatch.setattr(private_api.sync, "list_portfolios", lambda *a: [{"id": "FAKE-PRIVATE-ID", "payload": payload}])
    loaded = client.post("/api/backtest/load", headers=HEADERS, json={"mode": "portfolio", "portfolio_id": "FAKE-PRIVATE-ID"}).json()
    spy = Mock(wraps=base.RESULTS.run); monkeypatch.setattr(base.RESULTS, "run", spy)
    response = client.post("/api/backtest", headers=HEADERS, json={"mode": "portfolio", "sleeves": loaded["sleeves"], "initial": loaded["initial"]})
    assert response.status_code == 200
    captured = json.dumps({k:v for k,v in spy.call_args.kwargs.items() if k != "compute"}) + json.dumps(list(base.RESULTS.warm.values()))
    for forbidden in ("FAKE PRIVATE NAME", "FAKE-PRIVATE-ID", "991111", "mock-token", "ils_per_usd", "total_ils", "portfolio_id"):
        assert forbidden not in captured
    assert spy.call_args.kwargs["params"]["initial"] == 3000  # Explicit numeric setting is permitted.


def test_existing_transfer_deposit_restriction_and_saved_unavailable_flag(signed_in, monkeypatch):
    request = body(("A-RVol Shifter V3 Cash-Only", "Buy and Hold SPY"), monthly_contribution=100, sleeve_rebalance_mode="annual_target")
    response = client.post("/api/backtest/validate", headers=HEADERS, json=request)
    assert response.status_code == 400 and response.json()["detail"] == page.WORDS["transferDeposits"]
    klass = page.MODELS["Buy and Hold SPY"]
    monkeypatch.setattr(klass, "backtest_available", False, raising=False)
    payload = {"version": 1, "total_ils": 1000, "ils_per_usd": 4, "sleeves": [{"model": "Buy and Hold SPY", "weight": 100}]}
    response = client.post("/api/backtest/load", headers=HEADERS, json={"mode": "portfolio", "payload": payload})
    assert response.status_code == 200
    assert response.json()["warnings"] == ["Buy and Hold SPY is not available for backtesting."]
    assert client.post("/api/backtest/validate", headers=HEADERS, json={"mode": "portfolio", "initial": 250, "sleeves": response.json()["sleeves"]}).status_code == 400


def test_oversized_failed_response_and_bad_bounds_never_cache(signed_in, monkeypatch):
    live_fixture(monkeypatch, ("Buy and Hold SPY",))
    request = body(("Buy and Hold SPY",), start="1900-01-01")
    response = client.post("/api/backtest", headers=HEADERS, json=request)
    assert response.status_code == 400 and not base.RESULTS.warm
    from server import backtest_multi_presentation as presentation
    original = presentation.report
    def oversized(*args, **kwargs):
        bundle = original(*args, **kwargs)
        bundle["public"]["captions"].append("X"*3_000_000)
        return bundle
    monkeypatch.setattr(presentation, "report", oversized)
    response = client.post("/api/backtest", headers=HEADERS, json=body(("Buy and Hold SPY",)))
    assert response.status_code == 400 and response.json()["detail"] == page.WORDS["sizeError"]
    assert not base.RESULTS.warm


def test_original_static_words_stay_verbatim_except_transfer_loading_caption():
    literals = {node.value for node in ast.walk(ast.parse((ROOT/"app.py").read_text())) if isinstance(node, ast.Constant) and isinstance(node.value, str)}
    for key in ("sleeveCaption", "deepLoadCaption", "proxyCaption", "benchmarkHelp", "weightSuccess", "duplicateProxy", "dailySingle", "mixedCaption", "taxCaption", "dailyCaption", "syntheticTax", "unsupportedFees", "monthlyReset", "mixedNone", "mixedCap", "mixedAnnual", "mixedTax", "proxyWarning", "blendWarning", "dailyMetrics", "sourceCaption", "sleeveFeeCaption", "plainCaption", "rollingCaption"):
        assert page.WORDS[key] in literals, key
    assert 'saved transfer rule with its parameters' in page.WORDS['loadCaption']
