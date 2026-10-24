from copy import deepcopy
from dataclasses import replace
from datetime import date
import hashlib

import pandas as pd
import pytest

import haa.deep_history as deep
import haa.supabase_sync as sync
from haa.engine import run_backtest
from haa.portfolio_backtest import run_portfolio_backtest
from haa.portfolio_config import deep_history_portfolio_config
from haa.model_catalog import MODEL_CATALOG
from haa.synthetic_history import monthly_blend_input
from test_saved_portfolio_ui import account, open_app


@pytest.mark.parametrize("key,ticker,first,count,digest", [
    ("buy_and_hold_gld", "GLD", "2004-12-31", 262, "3736bbc3c6d16c2752d85fef1e9124dd39e33a75d3c6ddb59ce5096774355a9f"),
    ("buy_and_hold_ief", "IEF", "2002-08-31", 290, "290df83c3c93dd25d319b7236f4c0e63fcad5631e78deea6723eaa27edb6a804"),
])
def test_actual_etf_months_reconcile_without_pre_history(key, ticker, first, count, digest):
    spec = replace(deep.ALL_DEEP_HISTORY_SPECS[key], pre_etf_returns_file=None, pre_etf_source=None)
    assert hashlib.sha256((deep.DEEP_HISTORY_DIR / spec.returns_file).read_bytes()).hexdigest() == digest
    _, returns = deep.load_deep_history(spec)
    assert returns.index.equals(pd.date_range(first, "2026-09-30", freq="ME"))
    assert len(returns) == count
    assert key in deep.deep_history_options(2)
    for benchmark in deep.DEEP_HISTORY_BENCHMARKS.values():
        if benchmark.currency != spec.currency:
            with pytest.raises(ValueError, match="currencies"):
                deep.deep_history_model_input(spec, benchmark)
            continue
        model = deep.deep_history_model_input(spec, benchmark)
        assert model.decisions.attrs["actual_etf_ticker"] == ticker
        assert model.decisions.attrs["pre_etf_extension"] is False
        result = run_backtest(model.decisions, model.monthly_prices, 1000., benchmark_asset=benchmark.asset_id, tax_enabled=True)
        assert result.monthly.index.equals(returns.index)
        assert result.monthly.pre_tax_value.iloc[-1] == pytest.approx(1000 * (1+returns).prod())
        assert result.tax_events.empty


@pytest.mark.parametrize("problem", ["gap", "wrong_source", "bad_return", "bad_anchor"])
def test_actual_etf_source_rejects_missing_or_fabricated_data(tmp_path, monkeypatch, problem):
    spec = deep.ALL_DEEP_HISTORY_SPECS["buy_and_hold_gld"]
    frame = pd.read_csv(deep.DEEP_HISTORY_DIR / spec.returns_file)
    if problem == "gap": frame = frame.drop(index=3)
    elif problem == "wrong_source": frame.loc[3, "ticker"] = "FUTURES_PROXY"
    elif problem == "bad_return": frame.loc[3, "nominalReturn"] = .99
    elif problem == "bad_anchor": frame.loc[3, "observationDate"] = "2005-03-30"
    frame.to_csv(tmp_path / spec.returns_file, index=False)
    monkeypatch.setattr(deep, "DEEP_HISTORY_DIR", tmp_path)
    with pytest.raises(ValueError): deep.load_deep_history(spec)


def test_saved_five_sleeve_portfolio_loads_and_starts_january_1999():
    names = ["Century Momentum", "Inflation Compass Standard", "Buy and Hold Gold GLD", "Buy and Hold IEF", "A-RVol Shifter V3 Cash-Only"]
    payload = {"version": 1, "total_ils": 3500, "ils_per_usd": 3.5,
               "sleeves": [{"model": name, "weight": 20.} for name in names]}
    original = deepcopy(payload)
    models = {definition.label: definition.model_class for definition in MODEL_CATALOG}
    sleeves, capital = deep_history_portfolio_config(payload, models, deep.ALL_DEEP_HISTORY_SPECS)
    assert payload == original
    assert [s["model"] for s in sleeves][2:4] == ["buy_and_hold_gld", "buy_and_hold_ief"]
    inputs = {s["model"]: (.2, monthly_blend_input(deep.deep_history_model_input(deep.ALL_DEEP_HISTORY_SPECS[s["model"]]))) for s in sleeves}
    result = run_portfolio_backtest(inputs, capital, tax_enabled=True)
    assert result.monthly.index.min() == pd.Timestamp("1999-01-31")
    assert result.monthly.index.max() == pd.Timestamp("2026-09-30")
    assert result.monthly.after_tax_value.iloc[-1] <= result.monthly.pre_tax_value.iloc[-1]


@pytest.mark.parametrize("keys", [
    ["buy_and_hold_gld", "buy_and_hold_ief"],
    ["century_momentum", "inflation_compass", "buy_and_hold_gld", "buy_and_hold_ief", "rvol_synthetic"],
])
def test_actual_etfs_are_selectable_in_deep_history_ui(account, monkeypatch, keys):
    payload = {"backtest_mode": "Deep History / Proxy", "deep_proxy_sleeves": [
        {"id": i+1, "model": key, "weight": 100./len(keys)} for i,key in enumerate(keys)], "deep_proxy_next_id": len(keys)+1}
    monkeypatch.setattr(sync, "load_workspace", lambda *a: {"revision": 1, "payload": payload})
    app = open_app()
    app.radio(key="page").set_value("Backtest").run()
    assert not app.exception
    assert not app.error, [e.value for e in app.error]
    assert app.date_input(key="deep_proxy_start").value == date(1999,1,31)
    assert not any("Actual GLD" in warning.value or "Actual IEF" in warning.value for warning in app.warning)


@pytest.mark.parametrize("key,last_early,digest", [
    ("buy_and_hold_gld", "2004-11-30", "e31fc801bc1384e0c57f26d9f97eaf645b083a107958c4930c54e8457d9da7e9"),
    ("buy_and_hold_ief", "2002-07-31", "8394a85828c6a68ae7c83107e9ecf806b4e9751cf3d289c1c0b4059d22673bca"),
])
def test_extended_history_joins_returns_without_price_jump(key, last_early, digest):
    spec = deep.ALL_DEEP_HISTORY_SPECS[key]
    assert hashlib.sha256((deep.DEEP_HISTORY_DIR / spec.pre_etf_returns_file).read_bytes()).hexdigest() == digest
    early = deep._read_actual_etf_returns(spec, pre_etf=True)
    actual = deep._read_actual_etf_returns(spec)
    _, returns = deep.load_deep_history(spec)
    assert returns.index.equals(pd.date_range("1999-01-31", "2026-09-30", freq="ME"))
    assert len(returns) == 333
    assert early.index.max() == pd.Timestamp(last_early)
    pd.testing.assert_series_equal(returns.loc[actual.index], actual)
    pd.testing.assert_series_equal(returns.loc[early.index], early)
    frame = pd.read_csv(deep.DEEP_HISTORY_DIR / spec.pre_etf_returns_file)
    assert early.iloc[0] == pytest.approx(frame.adjustedClose.iloc[0] / frame.previousAdjustedClose.iloc[0] - 1)
    for benchmark in deep.DEEP_HISTORY_BENCHMARKS.values():
        if benchmark.currency != spec.currency:
            with pytest.raises(ValueError, match="currencies"):
                deep.deep_history_model_input(spec, benchmark)
            continue
        model = deep.deep_history_model_input(spec, benchmark)
        assert model.decisions.attrs["pre_etf_extension"] is True
        assert model.decisions.attrs["pre_etf_source"] == spec.pre_etf_source
        result = run_backtest(model.decisions, model.monthly_prices, 1000., benchmark_asset=benchmark.asset_id, tax_enabled=True)
        assert result.monthly.pre_tax_value.iloc[-1] == pytest.approx(1000 * (1+returns).prod())
        assert result.tax_events.empty  # Source change is not an investor sale.


@pytest.mark.parametrize("problem", ["gap", "overlap", "wrong_source", "bad_return", "bad_anchor", "unsorted"])
def test_pre_history_rejects_bad_sources_and_splices(tmp_path, monkeypatch, problem):
    spec = deep.ALL_DEEP_HISTORY_SPECS["buy_and_hold_gld"]
    actual = (deep.DEEP_HISTORY_DIR / spec.returns_file).read_text()
    frame = pd.read_csv(deep.DEEP_HISTORY_DIR / spec.pre_etf_returns_file)
    if problem == "gap": frame = frame.iloc[:-1]
    elif problem == "overlap":
        # Valid early rows from the same source, but crossing into actual GLD.
        extra = frame.iloc[[-1]].copy()
        extra.loc[:, "year"] = 2004
        extra.loc[:, "month"] = 12
        extra.loc[:, "previousObservationDate"] = "2004-11-30"
        extra.loc[:, "observationDate"] = "2004-12-31"
        extra.loc[:, "previousAdjustedClose"] = frame.adjustedClose.iloc[-1]
        extra.loc[:, "adjustedClose"] = frame.adjustedClose.iloc[-1]
        extra.loc[:, "nominalReturn"] = 0.
        frame = pd.concat([frame, extra], ignore_index=True)
    elif problem == "wrong_source": frame.loc[3, "ticker"] = "OTHER"
    elif problem == "bad_return": frame.loc[3, "nominalReturn"] = .99
    elif problem == "bad_anchor": frame.loc[3, "observationDate"] = "1999-04-29"
    elif problem == "unsorted": frame = frame.iloc[::-1]
    (tmp_path / spec.returns_file).write_text(actual)
    frame.to_csv(tmp_path / spec.pre_etf_returns_file, index=False)
    monkeypatch.setattr(deep, "DEEP_HISTORY_DIR", tmp_path)
    with pytest.raises(ValueError): deep.load_deep_history(spec)
