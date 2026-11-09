"""Parity with the original functions; Streamlit is stubbed ONLY in tests."""
import ast
from copy import deepcopy
import importlib.util
import json
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
        module.LAST_AVAILABLE_QUOTES.clear(); module.LAST_AVAILABLE_FX = None
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
            # The account-fund branches add a separate pricing and precision
            # path. Legacy behavior remains covered by the parity tests below.
            if name in {"unit_quote", "_preview_positions"}:
                continue
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


@pytest.mark.parametrize("identifier", ["5117700", "5139837", "5142476", "5132972"])
@pytest.mark.parametrize("change", [{"fundId": 0}, {"isin": "BAD"}, {"fundTypeId": 9}, {"mutualFundSubType": 2}, {"deleted": True},
    {"mergingLiquidationStatus": "Merged"}, {"features": []}, {"features": [{"title": "יחידות הקרן נקובות ב- $", "enabled": True}]},
    {"ratesAsOf": None}, {"ratesAsOf": "bad"}, {"redemptionPrice": 0}, {"redemptionPrice": "NaN"}])
def test_identity_change_fails_closed_exactly(original, identifier, change):
    for module in (port, original):
        with pytest.raises((ValueError, TypeError)):
            module.quote_from_maya_fund({**publication(identifier), **change}, security(identifier, "TASE"), "2026-11-05T08:00:00Z")


@pytest.mark.parametrize("identifier,expected,stamp", [
    ("5139837", "1.0885", "2026-11-04"),
    ("5142476", "0.9776", "2026-11-03"),
    ("5132972", "2.9494", "2026-11-05"),
])
def test_new_fund_fixture_uses_exact_live_redemption_value_and_date(identifier, expected, stamp):
    published = json.loads((ROOT / "api" / "tests" / "fixtures" / f"maya_fund_{identifier}.json").read_text())
    quote = port.quote_from_maya_fund(published, security(identifier, "TASE"), "2026-11-05T08:00:00Z")
    assert quote["price"] == expected
    assert quote["as_of"] == stamp
    assert quote["raw_published_value"] == str(published["redemptionPrice"])
    assert quote["quote_divisor"] == "100" and quote["valuation_kind"] == "fund_nav"


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


def test_verified_last_quote_remains_usable_when_the_next_fetch_fails(monkeypatch):
    item = security("GLD", "US")
    port.LAST_AVAILABLE_QUOTES.clear()
    monkeypatch.setattr(port, "last_completed_session", lambda *a: pd.Timestamp("2026-10-15"))
    monkeypatch.setattr(port, "fetch_unit_quote", lambda *a: {"price": "10", "as_of": "2026-10-15", "source": "Verified test close"})
    assert port.unit_quote(item, {})["fresh"]
    monkeypatch.setattr(port, "fetch_unit_quote", lambda *a: (_ for _ in ()).throw(RuntimeError("feed unavailable")))
    fallback = port.unit_quote(item, {})
    assert fallback["price"] == "10" and fallback["as_of"] == "2026-10-15"
    assert fallback["fresh"] is False and fallback["fallback"] is True
    assert "last available price dated 2026-10-15" in fallback["status"]


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


@pytest.mark.parametrize('identifier,schedule,stamp,now,expected,fresh',[
    ('5141627','Mon-Thu - 16:00','2026-11-05','2026-11-09T09:00:00Z','2026-11-05',True),
    ('5141627','Mon-Thu - 16:00','2026-11-04','2026-11-09T09:00:00Z','2026-11-05',False),
    ('5117700','Fri - 12:30, Mon-Thu - 16:00','2026-11-05','2026-11-09T09:00:00Z','2026-11-06',False),
    ('5117700','Fri - 12:30, Mon-Thu - 16:00','2026-11-06','2026-11-09T09:00:00Z','2026-11-06',True),
    ('5141627','Mon-Thu - 16:00','2026-11-05','2026-11-09T13:00:00Z','2026-11-05',True),
    ('5141627','Mon-Thu - 16:00','2026-11-05','2026-11-09T13:59:59Z','2026-11-05',True),
    ('5141627','Mon-Thu - 16:00','2026-11-05','2026-11-09T14:00:00Z','2026-11-09',False),
    ('5141627','Mon-Thu - 16:00','2026-11-05','2026-11-09T15:00:00Z','2026-11-09',False),
])
def test_maya_freshness_uses_own_dealing_days_without_publication_grace(original,identifier,schedule,stamp,now,expected,fresh):
    published={**publication(identifier),'designatedHours':schedule,'ratesAsOf':stamp}
    quote=port.quote_from_maya_fund(published,security(identifier,'TASE'),now)
    assert quote==original.quote_from_maya_fund(published,security(identifier,'TASE'),now)
    assert quote['dealing_schedule']==schedule
    assert quote['price']=='1.2567' and quote['raw_published_value']=='125.67'
    assert quote['as_of']==stamp and quote['expected_through']==expected
    assert quote['expected_basis']=='fund_dealing_day' and quote['fresh'] is fresh
    assert 'error' not in quote
    if fresh:
        assert quote['status']=='Current observation' and 'awaiting_dealing_day' not in quote
    else:
        assert quote['status']==f'Awaiting price for dealing day {expected}; latest published {stamp}'
        assert quote['awaiting_dealing_day']==expected


@pytest.mark.parametrize('schedule',[None,42,'','Mon-Thu 16h'])
def test_missing_or_unparsable_maya_schedule_keeps_exchange_freshness_exactly(original,schedule):
    published={**publication('5141627'),'ratesAsOf':'2026-11-05'}
    now='2026-11-09T09:00:00Z'
    baseline=port.quote_from_maya_fund(published,security('5141627','TASE'),now)
    if schedule is not None:published['designatedHours']=schedule
    quote=port.quote_from_maya_fund(published,security('5141627','TASE'),now)
    assert quote==original.quote_from_maya_fund(published,security('5141627','TASE'),now)
    if isinstance(schedule,str):assert quote.pop('dealing_schedule')==schedule
    else:assert 'dealing_schedule' not in quote
    assert quote==baseline
    assert quote['expected_through']=='2026-11-06' and quote['fresh'] is False
    assert quote['status']=='Stale: latest completed session is 2026-11-06'
    assert 'expected_basis' not in quote and 'awaiting_dealing_day' not in quote


@pytest.mark.parametrize('schedule',[
    None,'','  ',[], 'Mon-Thu 16h','Mon-Thu - 24:00','Mon-Thu - 16:60','mon-thu - 16:00',
    'Fri-Mon - 16:00','Sat-Sun - 16:00','Mon - 9:00','Mon - 16:00:00','Mon - 16:00 UTC',
    'Mon - 16:00,','Mon - 16:00, Mon - 17:00','Mon-Wed - 16:00, Wed-Thu - 15:00',
])
def test_dealing_schedule_parser_fails_closed(original,schedule):
    assert port.parse_dealing_schedule(schedule) is None
    assert original.parse_dealing_schedule(schedule) is None


@pytest.mark.parametrize('schedule,expected',[
    ('Mon-Thu - 16:00',{0:(16,0),1:(16,0),2:(16,0),3:(16,0)}),
    ('Fri - 12:30, Mon-Thu - 16:00',{4:(12,30),0:(16,0),1:(16,0),2:(16,0),3:(16,0)}),
    ('Sun-Sat - 00:00',{i:(0,0) for i in range(7)}),
])
def test_dealing_schedule_parser_accepts_only_explicit_days_and_cutoffs(original,schedule,expected):
    parsed=port.parse_dealing_schedule(schedule)
    assert parsed==original.parse_dealing_schedule(schedule)
    assert {day:(cutoff.hour,cutoff.minute) for day,cutoff in parsed.items()}==expected


def test_fund_dealing_day_skips_real_tase_closures_and_honors_jerusalem_dst(original):
    # The postponed election on 27 February 2024 was a verified TASE closure.
    schedule=port.parse_dealing_schedule('Tue - 16:00')
    assert port.last_fund_dealing_day(schedule,'2024-02-27T17:00:00Z')==pd.Timestamp('2024-02-20')
    summer=port.parse_dealing_schedule('Mon-Thu - 16:00')
    # Jerusalem is UTC+3 in July: 13:00 UTC is exactly the 16:00 cutoff.
    assert port.last_fund_dealing_day(summer,'2026-07-06T12:59:59Z')==pd.Timestamp('2026-07-02')
    assert port.last_fund_dealing_day(summer,'2026-07-06T13:00:00Z')==pd.Timestamp('2026-07-06')
    assert original.last_fund_dealing_day(summer,'2026-07-06T13:00:00Z')==pd.Timestamp('2026-07-06')


def test_manual_price_precedence_ignores_dealing_schedule(original):
    quote={'price':'2.50','as_of':'2026-11-04','field':'Manual per-unit price',
           'dealing_schedule':'Mon-Thu - 16:00','awaiting_dealing_day':'2026-11-09','expected_basis':'fund_dealing_day'}
    value=port.assess_quote(quote,'TASE','2026-11-09T15:00:00Z')
    assert value==original.assess_quote(quote,'TASE','2026-11-09T15:00:00Z')
    assert value['fresh'] is True and value['price']=='2.50'
    assert 'expected_basis' not in value and 'awaiting_dealing_day' not in value


def test_reassessment_removes_awaiting_marker_when_new_fund_price_is_current(original):
    raw={**publication('5141627'),'ratesAsOf':'2026-11-05','designatedHours':'Mon-Thu - 16:00'}
    before=port.quote_from_maya_fund(raw,security('5141627','TASE'),'2026-11-09T13:00:00Z')
    assert before['fresh'] and 'awaiting_dealing_day' not in before
    after=port.assess_quote(before,'TASE','2026-11-09T15:00:00Z')
    assert not after['fresh'] and after['awaiting_dealing_day']=='2026-11-09'
    current=port.assess_quote({**after,'as_of':'2026-11-09'},'TASE','2026-11-09T15:00:00Z')
    assert current['fresh'] and 'awaiting_dealing_day' not in current
    assert current['price']==before['price']
    # Receiving malformed metadata later must not leave a misleading fund basis.
    fallback=port.assess_quote({**after,'dealing_schedule':'invalid'},'TASE','2026-11-09T09:00:00Z')
    assert 'awaiting_dealing_day' not in fallback and 'expected_basis' not in fallback
