"""Health-only cash reconstruction, using fixed bundled observations."""
import numpy as np
import pandas as pd
import pytest

from haa.deep_history import DEEP_HISTORY_SPECS, load_deep_history
from haa.health_reference import replace_defensive_returns, replacement_returns
from server.strategy_health import WORDS, reference_history


def source_fixture():
    # Signal from 29 January controls February, not January.
    signals = pd.DataFrame({'target_weights': [{'SPMO': 1.}, {'IEF': 1.}, {'SPMO': 1.}]},
                           index=pd.to_datetime(['2015-12-31', '2016-01-29', '2016-02-29']))
    dates = pd.date_range('2016-01-31', periods=3, freq='ME')
    return signals, pd.Series([.1, -.2, .3], index=dates), pd.Series([.001, .002, .003], index=dates)


def test_reuses_signals_with_one_month_lag_and_changes_only_defensive_returns():
    signals, original, cash = source_fixture()
    saved = signals.copy(deep=True), original.copy(deep=True), cash.copy(deep=True)
    result = replace_defensive_returns(signals, original, cash, risk_asset='SPMO', defensive_asset='IEF')
    assert result.tolist() == [.1, .002, .3]
    pd.testing.assert_frame_equal(signals, saved[0])
    pd.testing.assert_series_equal(original, saved[1])
    pd.testing.assert_series_equal(cash, saved[2])


@pytest.mark.parametrize('damage', ['missing-cash', 'nan-cash', 'duplicate-cash', 'missing-signal', 'duplicate-signal', 'mixed-allocation'])
def test_missing_or_ambiguous_inputs_never_fall_back_to_bonds(damage):
    signals, original, cash = source_fixture()
    if damage == 'missing-cash':
        cash = cash.drop(cash.index[1])
    elif damage == 'nan-cash':
        cash.iloc[1] = np.nan
    elif damage == 'duplicate-cash':
        cash = pd.concat([cash, cash.iloc[[1]]])
    elif damage == 'missing-signal':
        signals = signals.drop(signals.index[1])
    elif damage == 'duplicate-signal':
        signals = pd.concat([signals, signals.iloc[[1]]])
    else:
        signals.at[signals.index[1], 'target_weights'] = {'IEF': .5, 'SPMO': .5}
    with pytest.raises(ValueError, match='Health reference'):
        replace_defensive_returns(signals, original, cash, risk_asset='SPMO', defensive_asset='IEF')


def test_bundled_cash_reference_has_no_bond_defensive_months():
    signals, bond = load_deep_history(DEEP_HISTORY_SPECS['century_momentum'])
    cash, config = reference_history('Century Momentum Move to Cash', '2016-08-01')
    assert cash.index.equals(pd.date_range('1928-04-30', '2016-07-31', freq='ME'))
    assert len(cash) == 1060
    assert config['replacement']['actual_ticker'] == 'BIL'
    defensive = pd.Series(signals.target_weights.apply(lambda w: w == {'IEF': 1.}).to_numpy(),
                          index=signals.index.to_period('M') + 1).reindex(cash.index.to_period('M')).to_numpy()
    replacements = replacement_returns(config['replacement']).reindex(cash.index)
    pd.testing.assert_series_equal(cash.loc[~defensive], bond.reindex(cash.index).loc[~defensive])
    pd.testing.assert_series_equal(cash.loc[defensive], replacements.loc[defensive])
    assert (cash.loc[defensive] != bond.reindex(cash.index).loc[defensive]).any()
    assert replacements.loc['1928-04-30'] == pytest.approx(.0022)
    assert 'proxy' in config['note']
