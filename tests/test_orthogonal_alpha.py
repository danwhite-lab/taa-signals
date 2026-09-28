import numpy as np
import pandas as pd
import pytest

from haa.engine import run_backtest
from haa.momentum import momentum_13612u
from haa.strategies import OrthogonalAlpha


ASSETS = ("QLD", "BTAL", "BIL", "SPY")


def prices(steps=None, periods=15):
    steps = steps or {"QLD": .02, "BTAL": .01, "BIL": .001, "SPY": .01}
    index = pd.date_range("2023-01-31", periods=periods, freq="ME")
    return pd.DataFrame({asset: 100 * (1 + steps[asset]) ** np.arange(periods) for asset in ASSETS}, index=index)


def test_blended_momentum_is_equal_weighted_13612u():
    values = pd.Series([100 + value for value in range(13)], dtype=float)
    expected = ((112 / 111 - 1) + (112 / 109 - 1) + (112 / 106 - 1) + (112 / 100 - 1)) / 4
    assert momentum_13612u(values).iloc[-1] == pytest.approx(expected)


def test_btal_satellite_produces_25_qld_75_btal():
    decision = OrthogonalAlpha().decisions(prices({"QLD": .02, "BTAL": .03, "BIL": .001, "SPY": .01})).iloc[-1]
    assert decision["satellite_asset"] == "BTAL"
    assert decision["regime"] == "risk-off"
    assert decision["target_weights"] == {"QLD": .25, "BTAL": .75}


def test_bil_beating_btal_or_a_tie_selects_qld_satellite():
    for btal_step, bil_step in ((.001, .02), (.01, .01)):
        decision = OrthogonalAlpha().decisions(prices({"QLD": .02, "BTAL": btal_step, "BIL": bil_step, "SPY": .01})).iloc[-1]
        assert decision["satellite_asset"] == "QLD"
        assert decision["target_weights"] == {"QLD": .75, "BTAL": .25}


def test_requires_twelve_completed_month_ends_and_executes_after_signal_month():
    strategy = OrthogonalAlpha()
    data = prices(periods=15)
    assert strategy.decisions(data.iloc[:12]).empty
    decisions = strategy.decisions(data)
    daily = data.reindex(pd.date_range(data.index.min(), data.index.max() + pd.Timedelta(days=2), freq="B")).ffill()
    result = run_backtest(decisions, data, 1000, daily_prices=daily)
    first = result.monthly.iloc[0]
    assert first["signal_date"] < first["execution_date"]
    assert first["execution_date"] == pd.Timestamp("2024-02-01")
    assert all(sum(weights.values()) == pytest.approx(1.0) for weights in decisions["target_weights"])
