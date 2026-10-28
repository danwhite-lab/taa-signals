import pandas as pd
import pytest

import haa.rebalance_market as market
from haa.rebalance_holdings import security, empty_account, compare_holdings, make_buy_plan


@pytest.fixture(autouse=True)
def clear_quote_cache():
    cached = market.fetch_unit_quote
    cached.clear()
    yield
    cached.clear()


def fund_publication(identifier='5117700'):
    # Synthetic prices; public identifiers/ISINs are not account holdings.
    identities = {'5117700': ('IL0051177009', 1), '5131792': ('IL0051317928', 4),
                  '5140850': ('IL0051408503', 4)}
    isin, fund_type = identities[identifier]
    return {'fundId': int(identifier), 'isin': isin, 'fundTypeId': fund_type,
            'mutualFundSubType': 1, 'deleted': False, 'mergingLiquidationStatus': None,
            'features': [{'title': 'יחידות הקרן נקובות ב- $', 'enabled': False}],
            'redemptionPrice': '125.67', 'purchasePrice': '125.67', 'ratesAsOf': '2026-10-15',
            'assetValueAsOf': '2026-10-16'}


@pytest.mark.parametrize('market_name,now,expected', [
    ('US', '2026-10-16T12:00:00Z', '2026-10-15'),  # Before Friday US close.
    ('US', '2026-10-17T12:00:00Z', '2026-10-16'),
    ('US', '2026-07-03T22:00:00Z', '2026-07-02'),  # Observed Independence Day.
    ('TASE', '2026-10-17T12:00:00Z', '2026-10-16'),
])
def test_freshness_uses_real_completed_exchange_sessions(market_name, now, expected):
    assert market.last_completed_session(market_name, now) == pd.Timestamp(expected)


def test_agorot_conversion_uses_raw_close_not_adjusted_or_partial_today():
    instrument = security('1149038', 'TASE')
    history = pd.DataFrame({'Close': [12345.6, 99999.], 'Adj Close': [1., 2.]}, index=pd.to_datetime(['2026-10-15', '2026-10-16']))
    quote = market.quote_from_history(history, instrument, 'Actual TASE', 100, '2026-10-16T05:00:00Z')
    assert quote['price'] == '123.456'
    assert quote['as_of'] == '2026-10-15'
    assert quote['fresh']


def test_stale_fund_quote_is_not_forward_filled_and_missing_raw_close_is_rejected():
    instrument = security('1149038', 'TASE')
    history = pd.DataFrame({'Close': [100.]}, index=pd.to_datetime(['2026-10-12']))
    quote = market.quote_from_history(history, instrument, 'TASE', 100, '2026-10-16T22:00:00Z')
    assert not quote['fresh'] and quote['as_of'] == '2026-10-12'
    with pytest.raises(ValueError, match='unadjusted'):
        market.quote_from_history(history.rename(columns={'Close': 'Adj Close'}), instrument, 'TASE', 100, '2026-10-16T22:00:00Z')


def test_unknown_mutual_fund_quote_units_or_currency_never_guessed(monkeypatch):
    from tasekit.api import TaseClient
    monkeypatch.setattr(TaseClient, 'fetch_maya_fund_info', lambda *a: {'redemptionPrice': 103.07, 'ratesAsOf': '2026-10-15'})
    for identifier, currency in [('5129999', 'ILS'), ('5139076', 'USD'), ('5131792', 'USD')]:
        market.fetch_unit_quote.clear()
        quote = market.fetch_unit_quote(security(identifier, 'TASE', currency))
        assert 'not verified' in quote['error']
        assert quote['raw_published_value'] == 103.07
        assert quote['as_of'] == '2026-10-15'
        assert not quote['fresh'] and 'price' not in quote


def test_missing_feed_manual_price_and_future_manual_price_are_explicit(monkeypatch):
    instrument = security('TQQQ', 'US')
    monkeypatch.setattr(market, 'fetch_unit_quote', lambda *a: (_ for _ in ()).throw(RuntimeError('feed unavailable')))
    quote = market.unit_quote(instrument, {})
    assert quote['error'] == 'feed unavailable' and not quote['fresh']
    quote = market.assess_quote({'price': '10', 'as_of': '2026-10-16', 'field': 'Manual per-unit price'}, 'US', '2026-10-16T12:00:00Z')
    assert quote['fresh'] and quote['field'] == 'Manual per-unit price'
    quote = market.assess_quote({'price': '10', 'as_of': '2026-10-17', 'field': 'Manual per-unit price'}, 'US', '2026-10-16T12:00:00Z')
    assert not quote['fresh'] and 'future' in quote['error']


def test_fx_is_dated_and_direction_is_ils_per_usd(monkeypatch):
    monkeypatch.setattr(market, 'last_completed_session', lambda name: pd.Timestamp('2026-10-15'))
    monkeypatch.setattr(market, 'fetch_fx_quote', lambda: {'price': '3.5', 'as_of': '2026-10-15', 'source': 'ILS=X'})
    quote = market.fx_quote({})
    assert quote['fresh'] and quote['price'] == '3.5'
    quote = market.fx_quote({'manual_fx': '3.6', 'manual_fx_date': '2026-10-01'})
    assert not quote['fresh'] and quote['source'] == 'Manual ILS per USD'


@pytest.mark.parametrize('identifier', ['5117700', '5131792', '5140850'])
def test_verified_fund_conversion_is_native_per_unit_and_dated(identifier):
    quote = market.quote_from_maya_fund(fund_publication(identifier), security(identifier, 'TASE'), '2026-10-16T08:00:00Z')
    assert quote['price'] == '1.2567'
    assert quote['currency'] == 'ILS'
    assert quote['as_of'] == '2026-10-15'  # Never use the newer asset-value date.
    assert quote['fresh']
    assert quote['raw_published_value'] == '125.67'
    assert quote['quote_divisor'] == '100'
    assert quote['valuation_kind'] == 'fund_nav'
    assert quote['is_execution_price'] is False
    assert 'not a live execution price' in quote['source']


@pytest.mark.parametrize('identifier', ['5117700', '5131792', '5140850'])
def test_funds_route_to_maya_not_exchange_csv_or_a_proxy(monkeypatch, identifier):
    from tasekit.api import TaseClient
    calls = []
    def fetch(self, fund_id):
        calls.append(fund_id)
        return fund_publication(fund_id)
    monkeypatch.setattr(TaseClient, 'fetch_maya_fund_info', fetch)
    monkeypatch.setattr(market, 'last_completed_session', lambda *a: pd.Timestamp('2026-10-15'))
    monkeypatch.setattr(market, 'download_published_eod_closes', lambda *a: pytest.fail('Mutual fund must not use the exchange CSV path'))
    quote = market.unit_quote(security(identifier, 'TASE'), {})
    assert quote['price'] == '1.2567' and quote['fresh']
    assert calls == [identifier]


@pytest.mark.parametrize('change', [
    {'fundId': 1234567}, {'isin': 'WRONG'}, {'fundTypeId': 9}, {'deleted': True},
    {'mutualFundSubType': 2}, {'mergingLiquidationStatus': 'Merged'},
    {'features': []}, {'features': [{'title': 'יחידות הקרן נקובות ב- $', 'enabled': True}]},
    {'ratesAsOf': None}, {'ratesAsOf': 'not-a-date'}, {'redemptionPrice': None},
    {'redemptionPrice': 0}, {'redemptionPrice': -1}, {'redemptionPrice': 'NaN'},
])
def test_maya_normalization_fails_closed_when_metadata_or_prices_are_unverified(change):
    published = {**fund_publication(), **change}
    with pytest.raises((ValueError, TypeError)):
        market.quote_from_maya_fund(published, security('5117700', 'TASE'), '2026-10-17T12:00:00Z')


def test_published_fund_dates_never_relabelled_current_or_forward_filled():
    instrument = security('5117700', 'TASE')
    quote = market.quote_from_maya_fund(fund_publication(), instrument, '2026-10-17T12:00:00Z')
    assert quote['price'] == '1.2567' and not quote['fresh']
    assert quote['as_of'] == '2026-10-15'
    assert quote['expected_through'] == '2026-10-16'
    future = market.quote_from_maya_fund({**fund_publication(), 'ratesAsOf': '2026-10-18'}, instrument, '2026-10-17T12:00:00Z')
    assert not future['fresh'] and 'future' in future['error']


def test_fund_transport_failure_does_not_fallback_and_manual_override_still_wins(monkeypatch):
    from tasekit.api import TaseClient
    monkeypatch.setattr(TaseClient, 'fetch_maya_fund_info', lambda *a: (_ for _ in ()).throw(RuntimeError('Public feed unavailable')))
    instrument = security('5117700', 'TASE')
    quote = market.unit_quote(instrument, {})
    assert not quote['fresh'] and 'price' not in quote
    monkeypatch.setattr(market, 'last_completed_session', lambda *a: pd.Timestamp('2026-10-15'))
    quote = market.unit_quote(instrument, {'manual_price': '1.75', 'manual_price_date': '2026-10-15'})
    assert quote['price'] == '1.75' and quote['fresh']
    assert quote['field'] == 'Manual per-unit price'


@pytest.mark.parametrize('identifier', ['5117700', '5131792', '5140850'])
def test_maya_quotes_value_units_and_size_buys_without_altering_freshness_rules(identifier):
    instrument = security(identifier, 'TASE')
    key = instrument['id']
    account = empty_account()
    account['positions'][key] = {**instrument, 'units': '10'}
    quote = market.quote_from_maya_fund(fund_publication(identifier), instrument, '2026-10-16T08:00:00Z')
    _, _, total = compare_holdings(account, {key: instrument}, {key: 1.}, {key: quote}, '1')
    assert float(total) == 12.567
    plan = make_buy_plan(account, {key: instrument}, {key: 1.}, {key: quote}, '1', '5', {}, allocation_mode="biggest_gap_first")
    assert plan['orders'][0]['units'] == 3
    stale = market.quote_from_maya_fund(fund_publication(identifier), instrument, '2026-10-17T12:00:00Z')
    assert make_buy_plan(account, {key: instrument}, {key: 1.}, {key: stale}, '1', '5', {}, allocation_mode="biggest_gap_first")["orders"]
