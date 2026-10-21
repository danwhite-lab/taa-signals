"""Parity with the original functions; Streamlit is stubbed ONLY in tests."""
import ast
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace
import pandas as pd
import pytest

from test_api import ROOT
from server import rebalance_quotes as port, rebalance_editor as editor
from haa.rebalance_holdings import security, empty_account


def reference(monkeypatch, filename, name):
    def decorator(**kwargs):
        def apply(fn):
            fn.clear = lambda: None
            return fn
        return apply
    monkeypatch.setitem(sys.modules, "streamlit", SimpleNamespace(cache_data=decorator))
    spec = importlib.util.spec_from_file_location(name, ROOT / "src/haa" / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


@pytest.fixture
def original(monkeypatch):
    source = reference(monkeypatch, "rebalance_market.py", "haa._quote_parity_reference")
    for module in (source, port):
        monkeypatch.setattr(module, "utc_now", lambda: "2026-10-16T08:00:00Z")
        module.fetch_unit_quote.clear(); module.fetch_fx_quote.clear(); module.load_portfolio_signals.clear()
    yield source
    port.clear_rebalance_quotes()


def publication(identifier="5117700"):
    metadata = port.MAYA_ILS_UNIT_FUNDS[identifier]
    return {"fundId": int(identifier), "isin": metadata["isin"], "fundTypeId": metadata["fund_type_id"],
        "mutualFundSubType": 1, "deleted": False, "mergingLiquidationStatus": None,
        "features": [{"title": "יחידות הקרן נקובות ב- $", "enabled": False}],
        "redemptionPrice": "125.67", "ratesAsOf": "2026-10-15", "assetValueAsOf": "2026-10-16"}


def test_all_ported_function_bodies_are_identical_to_original_ast():
    for old, new in ((ROOT/"src/haa/rebalance_market.py", ROOT/"server/rebalance_quotes.py"), (ROOT/"src/haa/rebalance_page.py", ROOT/"server/rebalance_editor.py")):
        originals = {n.name: n for n in ast.parse(old.read_text()).body if isinstance(n, ast.FunctionDef)}
        copies = {n.name: n for n in ast.parse(new.read_text()).body if isinstance(n, ast.FunctionDef)}
        for name, node in copies.items():
            node.decorator_list = []; originals[name].decorator_list = []
            assert ast.dump(node) == ast.dump(originals[name]), name


@pytest.mark.parametrize("market,now", [("US", "2026-10-16T12:00:00Z"), ("US", "2026-07-03T22:00:00Z"), ("TASE", "2026-10-17T12:00:00Z")])
def test_completed_session_parity(original, market, now):
    assert port.last_completed_session(market, now) == original.last_completed_session(market, now)


@pytest.mark.parametrize("identifier", list(port.MAYA_ILS_UNIT_FUNDS))
@pytest.mark.parametrize("stamp", ["2026-10-15", "2026-10-12", "2026-10-18"])
def test_allowlist_conversion_and_stale_future_parity(original, identifier, stamp):
    published = publication(identifier); published["ratesAsOf"] = stamp
    item = security(identifier, "TASE")
    actual = port.quote_from_maya_fund(published, item, "2026-10-16T08:00:00Z")
    assert actual == original.quote_from_maya_fund(published, item, "2026-10-16T08:00:00Z")
    assert actual["price"] == "1.2567"
    assert actual["as_of"] == stamp and actual["is_execution_price"] is False


@pytest.mark.parametrize("change", [{"fundId": 0}, {"isin": "BAD"}, {"fundTypeId": 9}, {"mutualFundSubType": 2}, {"deleted": True},
    {"mergingLiquidationStatus": "Merged"}, {"features": []}, {"features": [{"title": "יחידות הקרן נקובות ב- $", "enabled": True}]},
    {"ratesAsOf": None}, {"ratesAsOf": "bad"}, {"redemptionPrice": 0}, {"redemptionPrice": "NaN"}])
def test_identity_change_fails_closed_exactly(original, change):
    for module in (port, original):
        with pytest.raises((ValueError, TypeError)):
            module.quote_from_maya_fund({**publication(), **change}, security("5117700", "TASE"), "2026-10-16T08:00:00Z")


def test_agorot_raw_close_not_adjusted_and_last_bad_row_not_filled(original):
    item = security("1149038", "TASE")
    history = pd.DataFrame({"Close": [12345.6, 99999.], "Adj Close": [1., 2.]}, index=pd.to_datetime(["2026-10-15", "2026-10-16"]))
    for frame in (history, history.iloc[:1]):
        assert port.quote_from_history(frame, item, "test", 100, "2026-10-16T05:00:00Z") == original.quote_from_history(frame, item, "test", 100, "2026-10-16T05:00:00Z")
    for module in (port, original):
        with pytest.raises(ValueError): module.quote_from_history(history.drop(columns="Close"), item, "test", 100, "2026-10-16T05:00:00Z")
        bad = history.copy(); bad.loc[pd.Timestamp("2026-10-15"), "Close"] = float("nan")
        with pytest.raises(ValueError): module.quote_from_history(bad, item, "test", 100, "2026-10-16T05:00:00Z")


@pytest.mark.parametrize("identifier,currency", [("5129999", "ILS"), ("5139076", "USD"), ("5131792", "USD")])
def test_unverified_fund_never_guesses_a_divisor(original, monkeypatch, identifier, currency):
    from tasekit.api import TaseClient
    monkeypatch.setattr(TaseClient, "fetch_maya_fund_info", lambda *a: {"redemptionPrice": 99.5, "ratesAsOf": "2026-10-15"})
    item = security(identifier, "TASE", currency)
    assert port.fetch_unit_quote(item) == original.fetch_unit_quote(item)
    assert "price" not in port.fetch_unit_quote(item)


def test_raw_us_currency_and_manual_override_fx_precedence(original, monkeypatch):
    import yfinance as yf
    fake = SimpleNamespace(history=lambda **kwargs: pd.DataFrame({"Close": [10]}, index=pd.to_datetime(["2026-10-15"])),
                           get_history_metadata=lambda: {"currency": "USD"})
    monkeypatch.setattr(yf, "Ticker", lambda *a: fake)
    for module in (port, original):
        monkeypatch.setattr(module, "last_completed_session", lambda *a: pd.Timestamp("2026-10-15"))
        monkeypatch.setattr(module.data, "download_latest_yahoo_close", lambda *a: (3.5, "2026-10-15"))
    item = security("GLD", "US")
    assert port.unit_quote(item, {}) == original.unit_quote(item, {})
    for stamp in ("2026-10-15", "2020-01-01", "2099-01-01"):
        position = {"manual_price": "12.345", "manual_price_date": stamp}
        assert port.unit_quote(item, position) == original.unit_quote(item, position)
        account = {"manual_fx": "3.6", "manual_fx_date": stamp}
        assert port.fx_quote(account) == original.fx_quote(account)
    port.fetch_unit_quote.clear(); fake.get_history_metadata = lambda: {"currency": "ILS"}
    assert port.unit_quote(item, {}).get("error") == original.unit_quote(item, {}).get("error")


@pytest.mark.parametrize("label", ["Buy and Hold SPY", "HAA-Simple", "HAA-Simple Israel"])
def test_target_loader_matches_original_actionable_signals(original, monkeypatch, label):
    from test_signals import fixtures, AS_OF
    from haa import portfolio_signals
    actionable = portfolio_signals.latest_actionable_signal
    monkeypatch.setattr(portfolio_signals, "latest_actionable_signal", lambda *a: actionable(*a, as_of=AS_OF))
    prices, _, _ = fixtures(label)
    for module in (port, original):
        monkeypatch.setattr(module.data, "download_yahoo_prices", lambda mapping, **k: prices.loc[:, list(mapping)])
        monkeypatch.setattr(module, "download_tase_israel_prices", lambda assets: (prices.loc[:, assets], None))
    actual = port.load_portfolio_signals((label,), (), {})
    assert actual == original.load_portfolio_signals((label,), (), {})
    assert actual[0] and not actual[1], actual


def test_cache_deep_copy_expiry_and_page_only_refresh(monkeypatch):
    from server import rebalance_ttl as ttl
    clock = [0]; calls = []
    monkeypatch.setattr(ttl, "monotonic", lambda: clock[0])
    @ttl.cache_data(ttl=300)
    def quote(key): calls.append(key); return {"price": "10"}
    quote("x")["price"] = "99"
    assert quote("x")["price"] == "10" and calls == ["x"]
    clock[0] = 301; quote("x"); assert calls == ["x", "x"]
    quote.clear(); quote("x"); assert len(calls) == 3
