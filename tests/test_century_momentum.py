import numpy as np
import pandas as pd

from haa.strategies import CenturyMomentum, CenturyMomentumIsrael, CenturyMomentumMoveToCash, CenturyMomentumMoveToCashIsrael


def prices(spmo_values):
    index = pd.date_range("2023-01-31", periods=len(spmo_values), freq="ME")
    return pd.DataFrame({
        "SPMO": spmo_values,
        "IEF": 100 * 1.001 ** np.arange(len(index)),
        "SPY": 100 * 1.002 ** np.arange(len(index)),
    }, index=index)


def test_requires_ten_completed_month_ends_for_the_sma():
    assert CenturyMomentum().decisions(prices(np.arange(100, 109))).empty
    assert len(CenturyMomentum().decisions(prices(np.arange(100, 110)))) == 1


def test_holds_spmo_above_its_ten_month_sma():
    decision = CenturyMomentum().decisions(prices([100] * 9 + [120])).iloc[-1]
    assert decision["SPMO_10m_sma"] == 102
    assert decision["trend_up"]
    assert decision["selected_asset"] == "SPMO"


def test_equal_or_below_sma_selects_ief():
    equal = CenturyMomentum().decisions(prices([100] * 10)).iloc[-1]
    below = CenturyMomentum().decisions(prices([100] * 9 + [80])).iloc[-1]
    assert equal["selected_asset"] == "IEF"
    assert below["selected_asset"] == "IEF"


def test_israel_variant_uses_us_spmo_for_signal_and_tase_funds_for_execution():
    source = prices([100] * 9 + [120]).assign(SPMO_IL=80., IEF_IL=90.)
    decision = CenturyMomentumIsrael().decisions(source).iloc[-1]
    assert decision["selected_asset"] == "SPMO_IL"
    assert decision["signal_selected_asset"] == "SPMO"
    assert decision["regime"] == "risk-on"
    assert decision["SPMO_10m_sma"] == 102
    assert CenturyMomentumIsrael.benchmark_asset == "SPMO_IL"


def test_move_to_cash_uses_reusable_bil_defensive_setting_and_maps_to_kaspit():
    source = prices([100] * 10).assign(BIL=101., SPMO_IL=90., RVOL_CASH_IL=70.)
    original = CenturyMomentumMoveToCash().decisions(source).iloc[-1]
    israel = CenturyMomentumMoveToCashIsrael().decisions(source).iloc[-1]
    assert original.selected_asset == "BIL"
    assert israel.signal_selected_asset == "BIL"
    assert israel.selected_asset == "RVOL_CASH_IL"


def test_stale_tase_prices_do_not_change_century_israel_signal():
    source = prices([100] * 9 + [120]).assign(SPMO_IL=80., IEF_IL=90.)
    baseline = CenturyMomentumIsrael().decisions(source)
    stale = source.copy()
    stale.loc[stale.index[-4]:, ["SPMO_IL", "IEF_IL"]] = float("nan")
    actual = CenturyMomentumIsrael().decisions(stale)
    pd.testing.assert_frame_equal(actual, baseline, check_exact=True)
