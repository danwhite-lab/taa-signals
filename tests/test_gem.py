import numpy as np
import pandas as pd

from haa.strategies import GEM, GEMIsrael


ASSETS = ("SPY", "VEU", "AGG", "BIL")


def monthly_prices(steps):
    index = pd.date_range("2023-01-31", periods=15, freq="ME")
    return pd.DataFrame({asset: 100 * (1 + steps[asset]) ** np.arange(len(index)) for asset in ASSETS}, index=index)


def test_gem_selects_spy_when_absolute_and_relative_momentum_both_win():
    decision = GEM().decisions(monthly_prices({"SPY": .03, "VEU": .02, "AGG": .01, "BIL": .005})).iloc[-1]
    assert decision["regime"] == "risk-on-us"
    assert decision["selected_asset"] == "SPY"


def test_gem_selects_veu_when_it_beats_spy_after_the_absolute_gate():
    decision = GEM().decisions(monthly_prices({"SPY": .02, "VEU": .03, "AGG": .01, "BIL": .005})).iloc[-1]
    assert decision["regime"] == "risk-on-international"
    assert decision["selected_asset"] == "VEU"


def test_gem_selects_agg_when_spy_is_not_strictly_above_bil():
    decision = GEM().decisions(monthly_prices({"SPY": .005, "VEU": .03, "AGG": .01, "BIL": .005})).iloc[-1]
    assert decision["regime"] == "risk-off"
    assert decision["selected_asset"] == "AGG"


def test_gem_israel_maps_veu_and_agg_to_the_declared_us_execution_proxies():
    prices = monthly_prices({"SPY": .02, "VEU": .03, "AGG": .01, "BIL": .005})
    prices["ACWX"] = 100 * 1.01 ** np.arange(len(prices))
    prices["BNDW"] = 100 * 1.01 ** np.arange(len(prices))
    decision = GEMIsrael().decisions(prices).iloc[-1]
    assert decision["signal_selected_asset"] == "VEU"
    assert decision["selected_asset"] == "ACWX"
