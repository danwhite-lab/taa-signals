import numpy as np
import pandas as pd
import pytest

from haa.momentum import momentum_sma12
from haa.strategies import BAAG4Aggressive


ASSETS = ("SPY", "VEA", "VWO", "BND", "QQQ", "TIP", "DBC", "BIL", "IEF", "TLT", "LQD")


def monthly_prices(steps=None):
    steps = steps or {asset: 0.01 for asset in ASSETS}
    index = pd.date_range("2023-01-31", periods=15, freq="ME")
    return pd.DataFrame({asset: 100 * (1 + steps[asset]) ** np.arange(len(index)) for asset in ASSETS}, index=index)


def test_sma12_uses_current_and_previous_twelve_month_ends():
    values = pd.Series(range(100, 113), dtype=float)
    assert momentum_sma12(values).iloc[-1] == pytest.approx(112 / values.mean() - 1)


def test_requires_twelve_prior_completed_month_end_observations():
    assert BAAG4Aggressive().decisions(monthly_prices().iloc[:12]).empty
    assert len(BAAG4Aggressive().decisions(monthly_prices())) == 3


def test_risk_on_selects_the_top_one_offensive_asset_by_sma_score():
    decision = BAAG4Aggressive().decisions(monthly_prices({
        "SPY": .02, "VEA": .01, "VWO": .015, "BND": .005, "QQQ": .04,
        "TIP": .01, "DBC": .01, "BIL": .01, "IEF": .01, "TLT": .01, "LQD": .01,
    })).iloc[-1]
    assert decision["breadth_bad_count"] == 0
    assert decision["regime"] == "risk-on"
    assert decision["target_weights"] == {"QQQ": 1.0}


def test_risk_off_selects_top_three_and_combines_bil_replacements():
    decision = BAAG4Aggressive().decisions(monthly_prices({
        "SPY": .02, "VEA": .01, "VWO": .015, "BND": -.005, "QQQ": .04,
        "TIP": .005, "DBC": .004, "BIL": .02, "IEF": .03, "TLT": .01, "LQD": .008,
    })).iloc[-1]
    assert decision["regime"] == "risk-off"
    assert decision["selected_defensive_assets"] == "IEF, BIL, TLT"
    assert decision["bil_replacements"] == "TLT"
    assert decision["target_weights"] == pytest.approx({"IEF": 1 / 3, "BIL": 2 / 3})
