import numpy as np
import pandas as pd
import pytest

from haa.momentum import momentum_13612w
from haa.strategies import VAAG4


ASSETS = ("SPY", "EFA", "EEM", "AGG", "LQD", "IEF", "SHY")


def monthly_prices(steps=None):
    steps = steps or {asset: 0.01 for asset in ASSETS}
    index = pd.date_range("2023-01-31", periods=15, freq="ME")
    return pd.DataFrame({asset: 100 * (1 + steps[asset]) ** np.arange(len(index)) for asset in ASSETS}, index=index)


def test_13612w_uses_published_weighted_annualized_returns():
    values = pd.Series([100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112], dtype=float)
    expected = (12 * (112 / 111 - 1) + 4 * (112 / 109 - 1) + 2 * (112 / 106 - 1) + (112 / 100 - 1)) / 4
    assert momentum_13612w(values).iloc[-1] == pytest.approx(expected)


def test_requires_twelve_prior_completed_month_end_observations():
    assert VAAG4().decisions(monthly_prices().iloc[:12]).empty
    assert len(VAAG4().decisions(monthly_prices())) == 3


def test_risk_on_selects_highest_offensive_asset_when_all_are_positive():
    decision = VAAG4().decisions(monthly_prices({"SPY": .03, "EFA": .02, "EEM": .01, "AGG": .005, "LQD": .01, "IEF": .01, "SHY": .01})).iloc[-1]
    assert decision["breadth_bad_count"] == 0
    assert decision["regime"] == "risk-on"
    assert decision["target_weights"] == {"SPY": 1.0}


def test_one_non_positive_offensive_asset_triggers_best_defensive_asset():
    decision = VAAG4().decisions(monthly_prices({"SPY": .02, "EFA": .01, "EEM": -.01, "AGG": .005, "LQD": .01, "IEF": .03, "SHY": .005})).iloc[-1]
    assert decision["breadth_bad_count"] >= 1
    assert decision["regime"] == "risk-off"
    assert decision["target_weights"] == {"IEF": 1.0}


def test_zero_momentum_counts_as_bad_and_asset_list_order_breaks_ties():
    decision = VAAG4().decisions(monthly_prices({"SPY": .01, "EFA": .01, "EEM": .01, "AGG": 0, "LQD": .01, "IEF": .01, "SHY": .01})).iloc[-1]
    assert decision["breadth_bad_count"] == 1
    assert decision["target_weights"] == {"LQD": 1.0}
