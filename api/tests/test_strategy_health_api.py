"""Health API and orchestration reuse real engines with fixed prices only."""
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from test_api import client, module
from test_private_api import signed_in, HEADERS
from server import strategy_health as health
from haa.comparison import ModelInput
from haa.engine import run_backtest
from haa.portfolio_backtest import run_portfolio_backtest
from haa.strategy_health import analyze


@pytest.fixture
def histories(monkeypatch):
    dates = pd.date_range('2000-01-31', periods=145, freq='ME')
    prices = pd.DataFrame({'SPY': 100 * 1.005 ** np.arange(len(dates)),
                           'SPMO': 100 * np.cumprod(1 + np.tile([.01, -.02, .03, .01], 37)[:len(dates)]),
                           'IEF': 100 * 1.002 ** np.arange(len(dates))}, index=dates)
    def load(definition, clock):
        asset = 'SPMO' if definition.strategy == 'Century Momentum' else 'IEF'
        decisions = pd.DataFrame({'selected_asset': asset, 'regime': 'risk-on', 'trade': False}, index=dates[:-1])
        model = ModelInput(definition.label, decisions, prices, benchmark_asset='SPY')
        result = run_backtest(decisions, prices, 1., benchmark_asset='SPY')
        return model, result, []
    monkeypatch.setattr(health, 'model_history', load)
    monkeypatch.setattr(health.signals, 'load_inputs', lambda definition: (prices, pd.DataFrame(), []))
    # The US-only fixtures do not access any local or remote data source.
    return load


def selected(cm=75, ic=25):
    return [health.Sleeve(model='Century Momentum', weight=cm), health.Sleeve(model='Inflation Compass Standard', weight=ic)]


def test_combined_uses_saved_weights_and_the_existing_portfolio_engine(histories):
    body = health.Inputs(end='2012-01-31')
    sleeves = selected()
    report = health.run(body, sleeves, clock='2012-02-20')
    assert len(report['reports']) == 3
    models = {}
    for i, sleeve in enumerate(sleeves):
        definition = health.definition_for_label(sleeve.model)
        model, result, _ = histories(definition, pd.Timestamp('2012-02-20'))
        models[str(i)] = (sleeve.weight / 100, model)
    expected = run_portfolio_backtest(models, 1.)
    expected_report = analyze(expected.monthly, pd.Timestamp('2000-01-31'), {'review': 80, 'structural': 95}, health.WORDS['minimumSamples'])
    assert report['reports'][2]['metrics'] == expected_report['metrics']
    changed = health.run(body, selected(25, 75), clock='2012-02-20')
    assert report['reports'][2]['metrics']['relative']['current'] != changed['reports'][2]['metrics']['relative']['current']
    assert report['reports'][0]['metrics'] == changed['reports'][0]['metrics']


def test_a_failed_sleeve_does_not_hide_the_other_strategy(histories, monkeypatch):
    def load(definition, clock):
        if definition.strategy == 'Inflation Compass':
            raise RuntimeError('Private provider failure')
        return histories(definition, clock)
    monkeypatch.setattr(health, 'model_history', load)
    result = health.run(health.Inputs(end='2012-01-31'), selected(), clock='2012-02-20')
    assert result['reports'][0]['metrics']
    assert result['reports'][1]['status'] == result['reports'][2]['status'] == 'insufficient'
    assert 'Private provider' not in str(result)


def test_thresholds_enforce_cautious_ic_policy():
    for values in ({'review': 99, 'structural': 95}, {'ic_review': 95}, {'review': float('nan')}):
        with pytest.raises(ValidationError):
            health.Thresholds(**values)


def test_implementation_problems_stay_separate_and_do_not_change_history(histories):
    body = health.Inputs(end='2012-01-31')
    first = health.run(body, selected(), clock='2012-02-20')
    context = {'signals': [{'status_code': 'check_data'}], 'comparison': [
        {'id': 'TASE:1', 'Fund': 'Test fund', 'Actual %': .5, 'Target %': .6, 'Status': 'Underweight', 'price_fresh': False, 'price_as_of': '2011-01-01'}]}
    second = health.run(body, selected(), current=context, clock='2012-02-20')
    assert first['reports'] == second['reports']
    assert second['checks']['findings'][0]['kind'] == 'data'
    assert any(row['kind'] == 'holdings' and row['status'] == 'review' for row in second['checks']['findings'])


def test_route_auth_default_portfolio_and_private_read_only(histories, signed_in, monkeypatch):
    portfolio = {'is_default': True, 'payload': {'sleeves': [dict(s.model_dump(), id=i) for i, s in enumerate(selected())]}}
    monkeypatch.setattr(module.private_api, 'portfolios', lambda session: [deepcopy(portfolio)])
    monkeypatch.setattr(module.private_api, 'workspace', lambda session: {'payload': {}})
    monkeypatch.setattr(module.today_page, 'compose', lambda *a, **k: {'comparison': None, 'signals': []})
    response = client.post('/api/strategy-health', headers=HEADERS, json={'end': '2012-01-31'})
    assert response.status_code == 200
    payload = response.json()
    assert payload['weights'][0]['weight'] == 75
    assert len(payload['reports']) == 3
    assert 'private' in response.headers['cache-control'] and 'no-store' in response.headers['cache-control']
    assert client.post('/api/strategy-health', json={}).status_code == 401


def test_no_default_does_not_guess_a_portfolio(signed_in, monkeypatch):
    monkeypatch.setattr(module.private_api, 'portfolios', lambda session: [])
    response = client.post('/api/strategy-health', headers=HEADERS, json={})
    assert response.status_code == 200
    assert response.json()['reason'] == 'noDefault'


def test_checks_do_not_run_historical_engines(monkeypatch):
    monkeypatch.setattr(health.signals, 'load_inputs', lambda definition: (pd.DataFrame(), pd.DataFrame(), []))
    monkeypatch.setattr(health, 'model_history', lambda *a: pytest.fail('Checks must not load backtest history'))
    result = health.run(health.Inputs(checks_only=True), selected())
    assert not result['reports']
    assert result['checks']['findings']


def test_local_funds_are_not_claimed_to_track_without_comparable_data(monkeypatch):
    dates = pd.date_range('2026-01-01', periods=8, freq='B')
    prices = pd.DataFrame({'SPMO_IL': np.arange(100., 108.), 'IEF_IL': 100.}, index=dates)
    metadata = pd.DataFrame({'identifier': ['5140850', '1159268']}, index=['SPMO_IL', 'IEF_IL'])
    monkeypatch.setattr(health.signals, 'load_inputs', lambda definition: (prices, metadata, []))
    checks = health.implementation_checks(['Century Momentum Israel'])
    assert len(checks['proxies']) == 2
    assert all(row['tracking_status'] == 'insufficient' for row in checks['proxies'])
    assert all(row['last_price_date'] == '2026-01-12' for row in checks['proxies'])
    metadata.loc['SPMO_IL', 'identifier'] = '9999999'
    checks = health.implementation_checks(['Century Momentum Israel'])
    assert any(row['kind'] == 'mapping' and row['status'] == 'review' for row in checks['findings'])


@pytest.mark.parametrize('label', ['Century Momentum', 'Inflation Compass Standard'])
def test_history_uses_real_strategy_and_engine_without_network(label, monkeypatch):
    from haa.market_sessions import us_equity_sessions
    definition = health.definition_for_label(label)
    dates = us_equity_sessions('2015-01-02', '2026-11-19')
    trend = np.arange(len(dates))
    columns = {asset: 100 * np.exp(.00015 * trend + .05 * np.sin(trend / (25 + i)))
               for i, asset in enumerate(definition.model_class.data_assets) if asset != 'T5YIE'}
    if 'T5YIE' in definition.model_class.data_assets:
        columns['T5YIE'] = 2 + .1 * np.sin(trend / 60)
    prices = pd.DataFrame(columns, index=dates)
    monkeypatch.setattr(health.signals, 'load_inputs', lambda d: (prices, pd.DataFrame(), []))
    model, actual, _ = health.model_history(definition, pd.Timestamp('2026-11-20'))
    expected = run_backtest(model.decisions, model.monthly_prices, 1., daily_prices=model.daily_prices, benchmark_asset='SPY')
    pd.testing.assert_frame_equal(actual.monthly, expected.monthly)
    assert len(actual.monthly) > 100
    broken = prices.drop(dates[1000])
    monkeypatch.setattr(health.signals, 'load_inputs', lambda d: (broken, pd.DataFrame(), []))
    with pytest.raises(ValueError, match='Missing US equity trading sessions'):
        health.model_history(definition, pd.Timestamp('2026-11-20'))


def test_truncated_local_feed_cannot_change_underlying_performance(histories, monkeypatch):
    from haa.market_sessions import tase_equity_sessions
    dates = tase_equity_sessions('2010-01-01', '2012-01-31')
    local = pd.DataFrame({'SPMO_IL': np.linspace(100, 130, len(dates)), 'IEF_IL': 100.}, index=dates)
    metadata = pd.DataFrame({'identifier': ['5140850', '1159268']}, index=['SPMO_IL', 'IEF_IL'])
    monkeypatch.setattr(health.signals, 'load_inputs', lambda d: (local, metadata, []))
    sleeves = [health.Sleeve(model='Century Momentum Israel', weight=100)]
    body = health.Inputs(end='2012-01-31')
    original = health.run(body, sleeves, clock='2012-02-20')
    monkeypatch.setattr(health.signals, 'load_inputs', lambda d: (local.iloc[:10], metadata, []))
    truncated = health.run(body, sleeves, clock='2012-02-20')
    assert original['reports'] == truncated['reports']
    assert original['checks']['proxies'][0]['last_price_date'] != truncated['checks']['proxies'][0]['last_price_date']


def test_stale_signal_and_macro_observations_are_actionable(monkeypatch):
    from haa.market_sessions import us_equity_sessions
    definition = health.definition_for_label('Inflation Compass Standard')
    dates = us_equity_sessions('2026-08-03', '2026-11-19')
    prices = pd.DataFrame(100., index=dates, columns=definition.model_class.data_assets)
    prices.loc[prices.index >= '2026-09-01', 'T5YIE'] = np.nan
    prices.loc[prices.index >= '2026-11-18', 'SPY'] = np.nan
    monkeypatch.setattr(health.signals, 'load_inputs', lambda d: (prices, pd.DataFrame(), []))
    checks = health.implementation_checks([definition.label], clock='2026-11-20')
    assert any(health.WORDS['staleInput'] in f['message'] for f in checks['findings'])
    assert any(health.WORDS['staleMacro'] in f['message'] for f in checks['findings'])
    assert next(row for row in checks['observations'] if row['asset'] == 'SPY')['last_date'] == '2026-11-17'


def test_missing_comparison_prevents_overall_normal_even_when_other_metrics_exist():
    from haa.strategy_health import analyze
    dates = pd.date_range('2000-02-01', periods=108, freq='MS')
    monthly = pd.DataFrame({'pre_tax_monthly_return': .01, 'benchmark_monthly_return': .005}, index=dates)
    report = analyze(monthly, '2000-01-01', {'review': 90, 'structural': 97.5}, health.WORDS['minimumSamples'])
    assert report['metrics']['drawdown']['status'] == 'insufficient'
    assert report['metrics']['relative']['status'] == 'normal'
    assert report['metrics']['underwater']['status'] == 'insufficient'
    assert report['status'] == 'insufficient'


def test_loader_caveat_is_named_and_does_not_erase_a_valid_rating(histories, monkeypatch):
    def degraded(definition, clock):
        model, result, _ = histories(definition, clock)
        return model, result, ['T5YIE provider returned a dated warning']
    monkeypatch.setattr(health, 'model_history', degraded)
    result = health.run(health.Inputs(end='2012-01-31'), selected(), clock='2012-02-20')
    for report in result['reports']:
        assert report['reason'] != 'sourceWarning'
        assert report['caveats'][0]['warning'] == 'T5YIE provider returned a dated warning'
        assert report['caveats'][0]['model']
    monkeypatch.setattr(health, 'model_history', histories)
    clean = health.run(health.Inputs(end='2012-01-31'), selected(), clock='2012-02-20')
    assert [r['status'] for r in result['reports']] == [r['status'] for r in clean['reports']]


def test_combined_names_every_missing_mapping_and_keeps_all_saved_weights(histories):
    sleeves = [health.Sleeve(model='Century Momentum Move to Cash Israel', weight=45),
               health.Sleeve(model='Inflation Compass Standard Israel', weight=20),
               health.Sleeve(model='Buy and Hold Global Israel', weight=20),
               health.Sleeve(model='Buy and Hold Russell 2000 Israel', weight=5),
               health.Sleeve(model='Gold Cross-Asset Israel', weight=10)]
    result = health.run(health.Inputs(end='2012-01-31'), sleeves, clock='2012-02-20')
    combined = result['reports'][2]
    assert combined['composition'] == 'all_sleeves'
    assert combined['status'] == 'insufficient'
    assert {f['model'] for f in combined['failures']} == {'Buy and Hold Russell 2000 Israel', 'Gold Cross-Asset Israel'}
    assert all('USD mapping' in f['message'] for f in combined['failures'])
    assert result['weights'] == [s.model_dump() for s in sleeves]


@pytest.mark.parametrize('stamp,age,status', [('2026-11-18', 1, 'normal'), ('2026-11-17', 2, 'review'), ('2026-11-13', 4, 'review')])
def test_local_quote_age_uses_tase_sessions_and_does_not_change_signals(stamp, age, status):
    finding = health.price_age_finding('TASE:5141627', stamp, pd.Timestamp('2026-11-20T11:00:00'))
    assert finding['trading_days_old'] == age
    assert finding['status'] == status
    assert 'Signals are not affected' in finding['message']
    assert 'holding period' not in finding['message']


def test_account_quote_uses_same_one_day_age_rule_as_local_proxy_quote():
    current = {'signals': [], 'comparison': [{'id': 'TASE:5141627', 'Actual %': .1, 'Target %': .1, 'Status': 'On target', 'price_fresh': False, 'price_as_of': '2026-11-18'}]}
    checks = health.implementation_checks([], current, clock='2026-11-20T11:00:00')
    quote = next(row for row in checks['findings'] if 'trading_days_old' in row)
    assert quote['status'] == 'normal'
    assert not any(row['status'] == 'review' for row in checks['findings'])


def test_acwi_missing_health_benchmark_is_named_without_changing_the_mapping(histories, monkeypatch):
    def history(definition, clock):
        if definition.label == 'Buy and Hold ACWI':
            raise KeyError("['SPY'] not in index")
        return histories(definition, clock)
    monkeypatch.setattr(health, 'model_history', history)
    sleeves = [health.Sleeve(model='Century Momentum', weight=50), health.Sleeve(model='Buy and Hold Global Israel', weight=50)]
    result = health.run(health.Inputs(end='2012-01-31'), sleeves, clock='2012-02-20')
    failure = result['reports'][2]['failures'][0]
    assert failure['model'] == 'Buy and Hold Global Israel'
    assert 'SPY benchmark series' in failure['message']
    assert result['weights'] == [s.model_dump() for s in sleeves]
