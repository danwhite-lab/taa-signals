"""Traffic-light comparisons from deterministic completed monthly returns."""
import numpy as np
import pandas as pd
import pytest

from haa.strategy_health import analyze, band_metric, overall_status

POLICY = {'minimum_falls': 8, 'warning_fraction': 2 / 3, 'gap_tail_percent': 10, 'minimum_years': 0}


def history(returns):
    return pd.DataFrame({'pre_tax_monthly_return': returns, 'benchmark_monthly_return': .005},
                        index=pd.date_range('2000-02-01', periods=len(returns), freq='MS'))


def test_initial_capital_is_a_peak_and_calendar_months_measure_underwater():
    result = analyze(history([-.1, .05, -.1]), '2000-01-01', POLICY)
    assert result['metrics']['drawdown']['current'] == pytest.approx(1 - .9 * 1.05 * .9)
    assert result['metrics']['underwater']['current'] == 3
    assert result['peak'] == '2000-01-01'
    assert result['status'] == 'insufficient'


def test_completed_episode_retains_deepest_loss_and_full_recovery_time():
    result = analyze(history([-.1, .2, -.2, -.1]), '2000-01-01', POLICY)
    assert result['metrics']['drawdown']['samples'] == 1
    assert result['metrics']['underwater']['samples'] == 1
    assert result['metrics']['underwater']['current'] == 2
    assert result['episodes'][0]['depth'] == pytest.approx(.1)
    assert result['episodes'][0]['months'] == 2
    assert result['peak'] == '2000-03-01'


def test_three_year_gaps_use_disjoint_windows_and_the_same_return_convention():
    result = analyze(history([.01] * 108), '2000-01-01', POLICY)
    relative = result['metrics']['relative']
    assert relative['current'] == pytest.approx(-((1.01 ** 12 - 1) - (1.005 ** 12 - 1)))
    assert relative['samples'] == 2
    assert len(result['rolling']) == 73
    windows = result['reference_windows']
    assert windows[0]['last_period'] < windows[1]['first_period']
    assert windows[1]['last_period'] < '2006-02-01'  # current window starts here
    assert windows[0]['gap'] == pytest.approx(-relative['current'])


@pytest.mark.parametrize('length,windows', [(35, 0), (36, 0), (71, 0), (72, 1), (107, 1), (108, 2), (123, 2)])
def test_only_complete_prior_non_overlapping_windows_are_counted(length, windows):
    result = analyze(history([.01] * length), '2000-01-01', POLICY)
    assert result['metrics']['relative']['samples'] == windows
    assert len(result['reference_windows']) == windows


@pytest.mark.parametrize('current,status', [(19.9, 'green'), (20, 'yellow'), (30, 'yellow'), (30.01, 'red')])
def test_depth_and_duration_bands_include_two_thirds_and_worst_boundaries(current, status):
    metric = band_metric(current, [10, 15, 30], 1, warning_fraction=2 / 3)
    assert metric['status'] == status
    assert metric['review_value'] == 20
    assert metric['structural_value'] == 30


def test_relative_tail_is_configurable_and_red_requires_worse_than_all_past_windows():
    sample = [0., .01, .02, .03, .04, .05, .06, .07, .08, .09]
    assert band_metric(.075, sample, 1, tail_percent=10)['status'] == 'green'
    assert band_metric(.075, sample, 1, tail_percent=25)['status'] == 'yellow'
    assert band_metric(.09, sample, 1, tail_percent=10)['status'] == 'yellow'
    assert band_metric(.091, sample, 1, tail_percent=10)['status'] == 'red'


@pytest.mark.parametrize('statuses,expected', [
    (['green', 'green', 'green'], 'green'),
    (['yellow', 'green', 'green'], 'yellow'),
    (['red', 'green', 'green'], 'red'),
    (['red', 'yellow', 'green'], 'red'),
    (['red', 'yellow', 'insufficient'], 'insufficient'),
])
def test_overall_light_uses_the_worst_measure(statuses, expected):
    assert overall_status(statuses) == expected


def test_minimum_defaults_to_eight_and_changing_the_setting_changes_only_availability():
    returns = [-.1, 1 / .9 - 1 + .001] * 8 + [.01] * 60
    frame = history(returns)
    default = analyze(frame, '2000-01-01', POLICY)
    assert len(default['episodes']) == 8
    assert default['status'] != 'insufficient'
    higher = analyze(frame, '2000-01-01', {**POLICY, 'minimum_falls': 9})
    assert higher['status'] == 'insufficient'
    for key in default['metrics']:
        assert default['metrics'][key]['current'] == higher['metrics'][key]['current']


def test_entire_falls_set_limits_once_and_the_open_fall_does_not_raise_its_own_limit():
    depths = [.05 + index * .01 for index in range(10)]
    returns = []
    for depth in depths:
        returns += [-depth, 1 / (1 - depth) - 1 + .001]
    returns += [.01] * 60 + [-.2, 0., 0., 0.]
    result = analyze(history(returns), '2000-01-01', POLICY)
    assert result['metrics']['drawdown']['distribution'] == pytest.approx(sorted(depths))
    assert result['metrics']['drawdown']['structural_value'] == pytest.approx(max(depths))
    assert result['metrics']['drawdown']['status'] == 'red'
    assert result['status'] == 'red'


@pytest.mark.parametrize('damage', ['gap', 'duplicate', 'nan', 'infinity', 'bankrupt'])
def test_missing_and_invalid_periods_withhold_light(damage):
    frame = history([.01] * 120)
    if damage == 'gap':
        frame = frame.drop(frame.index[40])
    elif damage == 'duplicate':
        frame = pd.concat([frame, frame.iloc[[40]]])
    else:
        frame.iloc[40, 0] = {'nan': np.nan, 'infinity': np.inf, 'bankrupt': -1}[damage]
    assert analyze(frame, '2000-01-01', POLICY) == {'status': 'insufficient', 'reason': 'gap', 'metrics': {}}


def test_future_observations_never_enter_an_earlier_snapshot():
    before = history([.01, -.005, .02, .01] * 36)
    after = pd.concat([before, pd.DataFrame({'pre_tax_monthly_return': [-.9], 'benchmark_monthly_return': [.2]}, index=[pd.Timestamp('2012-02-01')])])
    assert analyze(before, '2000-01-01', POLICY) == analyze(after.loc[:before.index[-1]], '2000-01-01', POLICY)


def test_short_real_history_is_grey_with_configurable_twenty_year_default():
    frame = history([-.05, .07, .01] * 40)
    report = analyze(frame, '2000-01-01', {**POLICY, 'minimum_years': 20})
    assert report['status'] == 'short_history'
    assert report['proxy_before'] is None
    lower = analyze(frame, '2000-01-01', {**POLICY, 'minimum_years': 5})
    assert lower['status'] in {'green', 'yellow', 'red'}


def test_proxy_only_changes_past_fall_references_not_current_or_relative_results():
    frame = history([-.03, .05, .01] * 40)
    real_before = frame.copy(deep=True)
    policy = {**POLICY, 'minimum_years': 20}
    before = analyze(frame, '2000-01-01', policy)
    proxy = pd.Series([-.2, .3] * 240, index=pd.date_range('1960-01-31', periods=480, freq='ME'))
    proxy_before = proxy.copy(deep=True)
    after = analyze(frame, '2000-01-01', policy, proxy)
    assert before['status'] == 'short_history'
    assert after['status'] in {'green', 'yellow', 'red'}
    assert after['reference_start'] == '1960-01-31'
    assert after['proxy_before'] == '2000-01-01'
    assert after['metrics']['drawdown']['structural_value'] == pytest.approx(.2)
    assert after['metrics']['relative'] == before['metrics']['relative']
    assert after['peak'] == before['peak']
    assert after['episodes'] == before['episodes']
    for metric in before['metrics']:
        assert before['metrics'][metric]['current'] == after['metrics'][metric]['current']
    pd.testing.assert_frame_equal(frame, real_before)
    pd.testing.assert_series_equal(proxy, proxy_before)


def test_proxy_overlap_and_future_observations_never_enter_the_reference():
    frame = history([-.03, .05, .01] * 40)
    proxy = pd.Series([-.2, .3] * 240, index=pd.date_range('1960-01-31', periods=480, freq='ME'))
    future = pd.concat([proxy, pd.Series([-.99], index=[pd.Timestamp('2000-01-31')])])
    assert analyze(frame, '2000-01-01', POLICY, proxy) == analyze(frame, '2000-01-01', POLICY, future)


@pytest.mark.parametrize('damage', ['gap', 'duplicate', 'nan', 'bankrupt'])
def test_invalid_proxy_reference_is_rejected_without_filling(damage):
    proxy = pd.Series([-.2, .3] * 12, index=pd.date_range('1998-01-31', periods=24, freq='ME'))
    if damage == 'gap':
        proxy = proxy.drop(proxy.index[10])
    elif damage == 'duplicate':
        proxy = pd.concat([proxy, proxy.iloc[[10]]])
    else:
        proxy.iloc[10] = np.nan if damage == 'nan' else -1
    with pytest.raises(ValueError, match='health reference'):
        analyze(history([.01] * 120), '2000-01-01', POLICY, proxy)


def test_proxy_does_not_remove_short_history_gate_when_total_reference_is_under_twenty_years():
    early = pd.Series([-.05, .07] * 12, index=pd.date_range('1998-01-31', periods=24, freq='ME'))
    frame = history([-.05, .07, .01] * 40)
    result = analyze(frame, '2000-01-01', {**POLICY, 'minimum_years': 20}, early)
    assert result['reference_start'] == '1998-01-31'
    assert result['proxy_before'] == '2000-01-01'
    assert result['status'] == 'short_history'
    assert analyze(frame, '2000-01-01', {**POLICY, 'minimum_years': 10}, early)['status'] != 'short_history'
