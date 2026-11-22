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
    monkeypatch.setattr(health, 'reference_history', lambda *args: (None, None))
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
    expected_report = analyze(expected.monthly, pd.Timestamp('2000-01-31'), health.Thresholds().model_dump())
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


def test_traffic_light_settings_validate_fraction_tail_and_episode_minimum():
    for values in ({'minimum_falls': 0}, {'minimum_falls': 2.5}, {'warning_fraction': 0}, {'warning_fraction': 1.1}, {'gap_tail_percent': 101}, {'gap_tail_percent': float('nan')}, {'minimum_years': -1}, {'minimum_years': 2.5}):
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
    report = analyze(monthly, '2000-01-01', health.Thresholds().model_dump())
    assert report['metrics']['drawdown']['status'] == 'insufficient'
    assert report['metrics']['relative']['status'] == 'yellow'
    assert report['metrics']['underwater']['status'] == 'insufficient'
    assert report['status'] == 'short_history'


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


def test_combined_names_every_missing_mapping_and_keeps_all_saved_weights(histories, monkeypatch):
    resolve = health.usd_equivalents.resolve
    def missing_mapping(label):
        if label in {'Buy and Hold Russell 2000 Israel', 'Gold Cross-Asset Israel'}:
            raise ValueError('No configured USD mapping')
        return resolve(label)
    monkeypatch.setattr(health.usd_equivalents, 'resolve', missing_mapping)
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


def test_acwi_health_loader_requests_spy_without_changing_the_strategy(monkeypatch):
    from haa.market_sessions import us_equity_sessions
    definition = health.definition_for_label('Buy and Hold ACWI')
    dates = us_equity_sessions('2015-01-02', '2026-11-19')
    prices = pd.DataFrame({'ACWI': 100 * np.exp(np.arange(len(dates)) * .0001),
                           'SPY': 100 * np.exp(np.arange(len(dates)) * .0002)}, index=dates)
    def load(selected):
        strategy = selected.model_class()
        assert strategy.data_assets == ('ACWI', 'SPY')
        assert strategy.benchmark_asset == 'SPY'
        assert set(strategy.require_adjusted_assets) == {'ACWI', 'SPY'}
        return prices, pd.DataFrame(), []
    monkeypatch.setattr(health.signals, 'load_inputs', load)
    model, result, warnings = health.model_history(definition, pd.Timestamp('2026-11-20'))
    assert model.benchmark_asset == 'SPY'
    assert len(result.monthly) > 100
    first = result.monthly.iloc[0]
    expected = prices.loc[result.monthly.index[0], 'SPY'] / prices.loc[first.execution_date, 'SPY'] - 1
    assert first.benchmark_monthly_return == pytest.approx(expected)
    assert definition.model_class.benchmark_asset == 'ACWI'
    assert definition.model_class.data_assets == ('ACWI',)
    assert not warnings


def test_full_five_sleeve_health_uses_us_history_and_discloses_iwm(monkeypatch):
    from haa.constants import INFLATION_COMPASS_DATA_ASSETS
    from haa.market_sessions import us_equity_sessions
    dates = us_equity_sessions('2000-01-03', '2026-11-19')
    t = np.arange(len(dates))
    assets = tuple(dict.fromkeys((*INFLATION_COMPASS_DATA_ASSETS, 'SPMO', 'BIL', 'GLD', 'ACWI', 'IWM')))
    source = pd.DataFrame({asset: (2 + .1 * np.sin(t / 60) if asset == 'T5YIE'
                                  else 100 * np.exp(.00015 * t + .06 * np.sin(t / (25 + i))))
                           for i, asset in enumerate(assets)}, index=dates)
    calls = []
    def load(definition):
        strategy = definition.model_class()
        required = tuple(dict.fromkeys((*strategy.data_assets, strategy.benchmark_asset)))
        calls.append(required)
        assert 'SPY' in required
        assert not any(asset.endswith('_IL') for asset in required)
        return source.loc[:, required].copy(), pd.DataFrame(), []
    monkeypatch.setattr(health.signals, 'load_inputs', load)
    monkeypatch.setattr(health, 'implementation_checks', lambda *a: {'findings': [], 'proxies': []})
    sleeves = [health.Sleeve(model=label, weight=weight) for label, weight in [
        ('Century Momentum Move to Cash Israel', 45), ('Inflation Compass Standard Israel', 20),
        ('Buy and Hold Global Israel', 20), ('Buy and Hold Russell 2000 Israel', 5), ('Gold Cross-Asset Israel', 10)]]
    result = health.run(health.Inputs(), sleeves, clock='2026-11-20T14:00:00')
    combined = result['reports'][2]
    assert set(combined['metrics']) == {'drawdown', 'underwater', 'relative'}
    assert combined['as_of'] == '2026-11-02'
    assert not combined.get('failures')
    assert combined['composition'] == 'all_sleeves'
    assert len(combined['models']) == 5
    assert result['weights'] == [s.model_dump() for s in sleeves]
    assert any('IWM proxy' in caveat['warning'] for caveat in combined['caveats'])
    assert any('IWM' in assets for assets in calls)
    assert any({'GLD', 'IEF', 'BIL'}.issubset(assets) for assets in calls)
    # Independently invoke the existing portfolio engine on those same five
    # inputs to guard against dropping a sleeve or changing saved weights.
    models = {}
    for index, sleeve in enumerate(sleeves):
        original = health.usd_equivalents.resolve(sleeve.model)
        model, _, _ = health.model_history(original, pd.Timestamp('2026-11-20T14:00:00'))
        models[str(index)] = (sleeve.weight / 100, model)
    portfolio = run_portfolio_backtest(models, 1.)
    # The selected weighted monthly return stream must have the same compound
    # drawdown as the public report, regardless of its health sample size.
    values = pd.concat([pd.Series([1.]), (1 + portfolio.monthly.pre_tax_monthly_return).cumprod().reset_index(drop=True)], ignore_index=True)
    assert combined['metrics']['drawdown']['current'] == pytest.approx(float(1 - values.iloc[-1] / values.max()))


def test_data_warning_does_not_change_a_green_light(histories, monkeypatch):
    valid = {'status': 'green', 'reason': None, 'as_of': '2012-01-31',
             'metrics': {key: {'status': 'green'} for key in ('drawdown', 'underwater', 'relative')}}
    monkeypatch.setattr(health, 'analyze', lambda *args: deepcopy(valid))
    def warned(definition, clock):
        model, result, _ = histories(definition, clock)
        return model, result, ['T5YIE source fallback notice']
    monkeypatch.setattr(health, 'model_history', warned)
    result = health.run(health.Inputs(end='2012-01-31'), selected(), clock='2012-02-20')
    assert all(report['status'] == 'green' for report in result['reports'])
    assert all('T5YIE' in report['caveats'][0]['warning'] for report in result['reports'])


def test_bundled_reference_is_opt_in_for_bond_cm_and_respects_configured_start(monkeypatch):
    before = pd.Timestamp('2016-07-01')
    returns, config = health.reference_history('Century Momentum', before)
    assert config['series'] == 'century_momentum'
    assert returns.index.min() == pd.Timestamp('1928-04-30')
    assert returns.index.max() == pd.Timestamp('2016-06-30')
    cash, cash_config = health.reference_history('Century Momentum Move to Cash', before)
    assert cash.index.equals(returns.index)
    assert cash_config['replacement']['actual_ticker'] == 'BIL'
    assert not cash.equals(returns)
    monkeypatch.setitem(health.WORDS, 'referenceProxies', {'Another Strategy': {**config, 'start': '1980-01-31'}})
    selected, _ = health.reference_history('Another Strategy', before)
    assert selected.index.min() == pd.Timestamp('1980-01-31')
    assert health.reference_history('Century Momentum', before) == (None, None)


def test_health_reference_leaves_backtest_outputs_unchanged(histories, monkeypatch):
    definition = health.definition_for_label('Century Momentum')
    model, trading, warnings = histories(definition, pd.Timestamp('2012-02-20'))
    original_monthly = trading.monthly.copy(deep=True)
    original_decisions = model.decisions.copy(deep=True)
    sleeves = [health.Sleeve(model='Century Momentum', weight=100)]
    body = health.Inputs(end='2012-01-31')
    original = health.run(body, sleeves, clock='2012-02-20')['reports'][0]
    early = pd.Series([-.2, .3] * 240, index=pd.date_range('1960-01-31', periods=480, freq='ME'))
    monkeypatch.setattr(health, 'reference_history', lambda *args: (early, {'series': 'test-proxy', 'note': 'Reference only.'}))
    monkeypatch.setattr(health, 'model_history', lambda *args: (model, trading, warnings))
    extended = health.run(body, sleeves, clock='2012-02-20')['reports'][0]
    assert extended['reference_proxy'] == 'test-proxy'
    assert extended['proxy_before'] == '2000-01-31'
    assert extended['metrics']['relative'] == original['metrics']['relative']
    assert extended['metrics']['drawdown']['current'] == original['metrics']['drawdown']['current']
    pd.testing.assert_frame_equal(trading.monthly, original_monthly)
    pd.testing.assert_frame_equal(model.decisions, original_decisions)


def test_unavailable_proxy_keeps_real_metrics_and_reports_short_history(histories, monkeypatch):
    monkeypatch.setattr(health, 'reference_history', lambda *args: (_ for _ in ()).throw(ValueError('Unavailable proxy')))
    result = health.run(health.Inputs(end='2012-01-31'), [health.Sleeve(model='Century Momentum', weight=100)], clock='2012-02-20')
    report = result['reports'][0]
    assert report['status'] == 'short_history'
    assert report['metrics']['drawdown']['current'] is not None
    assert not report.get('proxy_before')
    assert any(c['warning'] == health.WORDS['proxyLoadFailed'] for c in report['caveats'])


def test_composite_never_uses_just_one_sleeves_reference(histories, monkeypatch):
    early = pd.Series([-.2, .3] * 240, index=pd.date_range('1960-01-31', periods=480, freq='ME'))
    monkeypatch.setattr(health, 'reference_history', lambda label, before: (early, {'series': 'test-proxy', 'note': 'Reference only.'}) if label == 'Century Momentum' else (None, None))
    result = health.run(health.Inputs(end='2012-01-31'), selected(), clock='2012-02-20')
    assert result['reports'][0]['proxy_before']
    assert result['reports'][2]['status'] == 'short_history'
    assert not result['reports'][2].get('proxy_before')
    assert result['weights'] == [s.model_dump() for s in selected()]


def test_cash_health_reference_uses_cash_history_and_keeps_live_metrics():
    dates = pd.date_range('2016-09-01', '2026-11-01', freq='MS')
    monthly = pd.DataFrame({'pre_tax_monthly_return': np.resize([-.03, .05, .01], len(dates)),
                            'benchmark_monthly_return': .005}, index=dates)
    before = analyze(monthly, '2016-08-01', health.Thresholds().model_dump())
    early, _ = health.reference_history('Century Momentum Move to Cash', '2016-08-01')
    after = analyze(monthly, '2016-08-01', health.Thresholds().model_dump(), early)
    assert before['status'] == 'short_history'
    assert after['status'] in {'green', 'yellow', 'red'}
    assert after['reference_start'] == '1928-04-30'
    assert after['metrics']['relative'] == before['metrics']['relative']
    for key in before['metrics']:
        assert after['metrics'][key]['current'] == before['metrics'][key]['current']


def test_combined_cash_reference_aligns_holding_months_and_preserves_all_weights(monkeypatch):
    from types import SimpleNamespace

    # Exit dates are in the following month: align by execution_date instead.
    early_months = pd.date_range('1990-01-31', '2016-07-31', freq='ME')
    cash = pd.Series(np.resize([-.02, .03], len(early_months)), index=early_months)
    dates = pd.date_range('2003-06-01', '2016-08-01', freq='MS')
    ic_returns = pd.Series(np.resize([.01, -.04, .05], len(dates)), index=dates)
    cash_frame = pd.DataFrame({'execution_date': [pd.Timestamp('2016-08-01')],
                              'pre_tax_monthly_return': [.8]}, index=[pd.Timestamp('2016-09-01')])
    ic_frame = pd.DataFrame({'execution_date': dates, 'pre_tax_monthly_return': ic_returns.to_numpy()},
                            index=dates + pd.offsets.MonthBegin(1))
    calls = []
    def reference(label, before):
        calls.append(label)
        return (cash, {'note': 'Cash-only reconstruction'}) if label == 'Century Momentum Move to Cash' else (None, None)
    monkeypatch.setattr(health, 'reference_history', reference)
    components = [(SimpleNamespace(name='Century Momentum Move to Cash'), SimpleNamespace(monthly=cash_frame)),
                  (SimpleNamespace(name='Inflation Compass Standard'), SimpleNamespace(monthly=ic_frame))]
    earlier, config = health.combined_reference(components, [.75, .25], '2016-08-01')
    assert earlier.index[0] == pd.Timestamp('2003-06-30')
    assert earlier.index[-1] == pd.Timestamp('2016-07-31')
    assert len(earlier) == 158
    assert earlier.iloc[0] == pytest.approx(.75 * cash.loc['2003-06-30'] + .25 * ic_returns.iloc[0])
    assert config['series'] == 'combined_health_reference'
    assert calls == ['Century Momentum Move to Cash', 'Inflation Compass Standard']
    # A gap cannot become a portfolio made from just its available sleeves.
    broken = ic_frame.drop(ic_frame.index[20])
    with pytest.raises(ValueError, match='every configured sleeve'):
        health.combined_reference([components[0], (components[1][0], SimpleNamespace(monthly=broken))], [.75,.25], '2016-08-01')
    # A third, younger sleeve limits the common reference, never gets dropped.
    younger = pd.DataFrame({'execution_date': [pd.Timestamp('2016-08-01')], 'pre_tax_monthly_return': [.01]})
    assert health.combined_reference([*components,(SimpleNamespace(name='Another sleeve'), SimpleNamespace(monthly=younger))], [.6,.2,.2], '2016-08-01') == (None,None)
    # Bond-defense CM must not be used as a cash reference.
    assert health.combined_reference([(SimpleNamespace(name='Century Momentum'), components[0][1]), components[1]], [.75,.25], '2016-08-01') == (None,None)


def test_combined_cash_card_loses_short_history_without_changing_current_metrics(monkeypatch):
    dates = pd.date_range('1985-01-31', '2012-01-31', freq='ME')
    prices = pd.DataFrame({'SPY': 100 * 1.004 ** np.arange(len(dates)),
                           'BIL': 100 * np.cumprod(1 + np.resize([-.02,.03,.01],len(dates)))},index=dates)
    def history(definition, clock):
        frame = prices.loc['2000':] if definition.label == 'Century Momentum Move to Cash' else prices
        decisions = pd.DataFrame({'selected_asset':'BIL','trade':False},index=frame.index[:-1])
        return ModelInput(definition.label,decisions,frame,benchmark_asset='SPY'), run_backtest(decisions,frame,1.,benchmark_asset='SPY'), []
    earlier = pd.Series(np.resize([-.02,.03,.01],240),index=pd.date_range('1980-01-31',periods=240,freq='ME'))
    monkeypatch.setattr(health,'model_history',history)
    monkeypatch.setattr(health,'implementation_checks',lambda *a: {'findings':[],'proxies':[]})
    monkeypatch.setattr(health,'reference_history',lambda label,before:(earlier,{'series':'cash-only','note':'Cash only'}) if label=='Century Momentum Move to Cash' else (None,None))
    sleeves=[health.Sleeve(model='Century Momentum Move to Cash',weight=75),health.Sleeve(model='Inflation Compass Standard',weight=25)]
    extended=health.run(health.Inputs(end='2012-01-31'),sleeves,clock='2012-02-20')
    monkeypatch.setattr(health,'combined_reference',lambda *args:(None,None))
    original=health.run(health.Inputs(end='2012-01-31'),sleeves,clock='2012-02-20')
    assert original['reports'][2]['status']=='short_history'
    assert extended['reports'][2]['status'] in {'green','yellow','red'}
    assert extended['reports'][2]['reference_start']=='1985-01-31'
    assert extended['reports'][2]['reference_proxy']=='combined_health_reference'
    assert extended['reports'][:2]==original['reports'][:2]
    for metric in original['reports'][2]['metrics']:
        assert extended['reports'][2]['metrics'][metric]['current']==original['reports'][2]['metrics'][metric]['current']
    assert extended['reports'][2]['metrics']['relative']==original['reports'][2]['metrics']['relative']
    assert extended['weights']==original['weights']
