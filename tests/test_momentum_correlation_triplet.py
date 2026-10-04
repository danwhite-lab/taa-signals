import numpy as np
import pandas as pd

from haa.strategies import MomentumCorrelationTriplet


def prices(candidate_return=0.0008, bil_return=0.0001):
    strategy = MomentumCorrelationTriplet()
    index = pd.bdate_range("2023-01-02", periods=600)
    frame = pd.DataFrame(index=index)
    for position, asset in enumerate(strategy.candidate_assets):
        # Different cycles make correlations deterministic but non-identical.
        returns = candidate_return + 0.0003 * np.sin(np.arange(len(index)) / (5 + position))
        frame[asset] = 100 * np.cumprod(1 + returns)
    frame["BIL"] = 100 * np.cumprod(np.full(len(index), 1 + bil_return))
    return frame


def test_selects_three_equal_weight_low_correlation_assets():
    decision = MomentumCorrelationTriplet().decisions(prices()).iloc[-1]
    assert len(decision["target_weights"]) == 3
    assert sum(decision["target_weights"].values()) == 1
    assert all(weight == 1 / 3 for weight in decision["target_weights"].values())
    assert decision["average_pairwise_correlation"] is not None


def test_unqualified_slots_are_filled_with_bil():
    decision = MomentumCorrelationTriplet().decisions(prices(candidate_return=-0.0002)).iloc[-1]
    assert decision["target_weights"] == {"BIL": 1.0}


def test_correlation_requires_actual_aligned_returns_not_calendar_fills():
    frame = prices()
    # Simulate TASE Sundays/holidays: these missing sessions must reduce the
    # aligned return count, not be silently forward-filled.
    frame.loc[frame.index[::3], "BWX"] = np.nan
    decision = MomentumCorrelationTriplet().decisions(frame).iloc[-1]
    assert "BWX" not in decision["target_weights"]
