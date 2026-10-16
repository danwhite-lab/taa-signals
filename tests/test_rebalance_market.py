import pandas as pd
import pytest

import haa.rebalance_market as market
from haa.rebalance_holdings import security


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
    for identifier, currency in [('5131792', 'ILS'), ('5139076', 'USD')]:
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
