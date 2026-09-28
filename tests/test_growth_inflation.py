import numpy as np
import pandas as pd
import pytest

from haa.strategies import GrowthInflationConcentrated, GrowthInflationDiversified


ASSETS = ("SPY", "XLE", "XLB", "XLI", "XLF", "XLU", "XLV", "XLP", "XLY", "XLK")


def prices(growth_step=0.001, positive_step=0.002, negative_step=0.001):
    index = pd.bdate_range("2023-01-02", periods=300)
    values = {}
    for asset in ASSETS:
        step = growth_step if asset == "SPY" else positive_step if asset in {"XLE", "XLB", "XLI", "XLF"} else negative_step
        values[asset] = 100 * (1 + step) ** np.arange(len(index))
    return pd.DataFrame(values, index=index)


@pytest.mark.parametrize(("growth_step", "positive_step", "negative_step", "expected"), [
    (0.001, 0.002, 0.001, {"XLE": 1.0}),
    (0.001, 0.001, 0.002, {"XLK": 1.0}),
    (-0.001, 0.002, 0.001, {"XLV": 1.0}),
    (-0.001, 0.001, 0.002, {"XLP": 1.0}),
])
def test_concentrated_selects_each_growth_inflation_quadrant(growth_step, positive_step, negative_step, expected):
    decision = GrowthInflationConcentrated().decisions(prices(growth_step, positive_step, negative_step)).iloc[-1]
    assert decision["target_weights"] == expected


@pytest.mark.parametrize(("growth_step", "positive_step", "negative_step", "expected"), [
    (0.001, 0.002, 0.001, {"XLE": 0.5, "XLI": 0.5}),
    (0.001, 0.001, 0.002, {"XLK": 0.5, "XLY": 0.5}),
    (-0.001, 0.002, 0.001, {"XLE": 0.5, "XLB": 0.5}),
    (-0.001, 0.001, 0.002, {"XLV": 0.5, "XLP": 0.5}),
])
def test_diversified_uses_fixed_equal_pairs(growth_step, positive_step, negative_step, expected):
    decision = GrowthInflationDiversified().decisions(prices(growth_step, positive_step, negative_step)).iloc[-1]
    assert decision["target_weights"] == expected
    assert sum(decision["target_weights"].values()) == 1.0


def test_requires_both_200_day_indicators_before_first_signal():
    assert GrowthInflationConcentrated().decisions(prices().iloc[:199]).empty
    assert not GrowthInflationConcentrated().decisions(prices().iloc[:200]).empty
