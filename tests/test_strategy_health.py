"""Deterministic health diagnostics, with no market-data access."""
import numpy as np
import pandas as pd
import pytest

from haa.strategy_health import analyze, historical_metric

POLICY = {'review': 90, 'structural': 97.5}
MINIMUM = {'drawdown': 36, 'underwater': 3, 'relative': 36}


def history(returns):
    return pd.DataFrame({'pre_tax_monthly_return': returns, 'benchmark_monthly_return': .005},
                        index=pd.date_range('2000-02-01', periods=len(returns), freq='MS'))


def test_initial_capital_is_a_peak_and_calendar_months_measure_underwater():
    result = analyze(history([-.1, .05, -.1]), '2000-01-01', POLICY, MINIMUM)
    assert result['metrics']['drawdown']['current'] == pytest.approx(1 - .9 * 1.05 * .9)
    assert result['metrics']['underwater']['current'] == 3
    assert result['peak'] == '2000-01-01'
    assert result['status'] == 'insufficient'


def test_recovered_episode_excludes_ongoing_episode_from_references():
    result = analyze(history([-.1, .2, -.2, -.1]), '2000-01-01', POLICY, MINIMUM)
    assert result['metrics']['underwater']['samples'] == 1
    assert result['metrics']['underwater']['current'] == 2
    assert result['metrics']['drawdown']['samples'] == 2
    assert result['peak'] == '2000-03-01'


def test_relative_uses_difference_of_annualized_compound_returns_and_excludes_overlap():
    result = analyze(history([.01] * 108), '2000-01-01', POLICY, MINIMUM)
    relative = result['metrics']['relative']
    assert relative['current'] == pytest.approx(-((1.01 ** 12 - 1) - (1.005 ** 12 - 1)))
    assert relative['samples'] == 37
    assert len(result['rolling']) == 73


@pytest.mark.parametrize('damage', ['gap', 'duplicate', 'nan', 'infinity', 'bankrupt'])
def test_missing_and_invalid_periods_withhold_rating(damage):
    frame = history([.01] * 120)
    if damage == 'gap':
        frame = frame.drop(frame.index[40])
    elif damage == 'duplicate':
        frame = pd.concat([frame, frame.iloc[[40]]])
    else:
        frame.iloc[40, 0] = {'nan': np.nan, 'infinity': np.inf, 'bankrupt': -1}[damage]
    result = analyze(frame, '2000-01-01', POLICY, MINIMUM)
    assert result == {'status': 'insufficient', 'reason': 'gap', 'metrics': {}}


def test_equal_histories_are_normal_and_sparse_tails_limit_structural_label():
    assert historical_metric(0, [0] * 100, 36, **POLICY)['status'] == 'normal'
    sparse = historical_metric(100, list(range(5)), 3, **POLICY)
    assert sparse['status'] == 'review'
    assert historical_metric(100, list(range(100)), 36, **POLICY)['status'] == 'structural'


def test_ic_review_is_earlier_for_same_observed_stress():
    reference = list(range(101))
    assert historical_metric(85, reference, 36, **POLICY)['status'] == 'normal'
    assert historical_metric(85, reference, 36, review=80, structural=95)['status'] == 'review'


def test_no_future_data_enters_earlier_snapshot():
    before = history([.01, -.005, .02, .01] * 36)
    after = pd.concat([before, pd.DataFrame({'pre_tax_monthly_return': [-.9], 'benchmark_monthly_return': [.2]}, index=[pd.Timestamp('2012-02-01')])])
    cutoff = before.index[-1]
    assert analyze(before, '2000-01-01', POLICY, MINIMUM) == analyze(after.loc[:cutoff], '2000-01-01', POLICY, MINIMUM)
