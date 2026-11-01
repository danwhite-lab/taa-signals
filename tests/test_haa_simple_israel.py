import pandas as pd

from haa.engine import run_backtest
from haa.strategies import HAASimpleIsrael


ASSETS = ("SPY", "TIP", "IEF", "BIL", "CSPX_IL", "IEF_IL", "AYALON_KASPIT")


def prices_with_terminal_scores(scores: dict[str, float]) -> pd.DataFrame:
    index = pd.date_range("2020-01-31", periods=15, freq="ME")
    prices = pd.DataFrame({asset: [100.0] * len(index) for asset in ASSETS}, index=index)
    for asset, score in scores.items():
        prices.loc[index[-2], asset] = 100 * (1 + score)
    return prices


def test_tip_and_spy_positive_select_cspx():
    decision = HAASimpleIsrael().decisions(prices_with_terminal_scores({"TIP": .1, "SPY": .2})).iloc[-2]
    assert decision["regime"] == "risk-on"
    assert decision["signal_selected_asset"] == "SPY"
    assert decision["selected_asset"] == "CSPX_IL"


def test_nonpositive_tip_or_spy_selects_mapped_us_defensive_asset():
    tip_off = HAASimpleIsrael().decisions(prices_with_terminal_scores({"TIP": 0, "IEF": .2, "BIL": .1})).iloc[-2]
    spy_off = HAASimpleIsrael().decisions(prices_with_terminal_scores({"TIP": .1, "SPY": 0, "IEF": .1, "BIL": .2})).iloc[-2]
    assert tip_off["selected_asset"] == "IEF_IL"
    assert spy_off["selected_asset"] == "AYALON_KASPIT"


def test_us_defensive_tie_selects_ief_il():
    decision = HAASimpleIsrael().decisions(prices_with_terminal_scores({"TIP": 0, "IEF": .1, "BIL": .1})).iloc[-2]
    assert decision["selected_asset"] == "IEF_IL"


def test_stale_tase_prices_do_not_change_underlying_signal_or_selection():
    prices = prices_with_terminal_scores({"TIP": .1, "SPY": .1})
    baseline = HAASimpleIsrael().decisions(prices)
    prices.loc[prices.index[-4]:, ["CSPX_IL", "IEF_IL", "AYALON_KASPIT"]] = float("nan")
    actual = HAASimpleIsrael().decisions(prices)
    pd.testing.assert_frame_equal(actual, baseline, check_exact=True)


def test_israel_execution_uses_cspx_benchmark_on_same_dates():
    index = pd.to_datetime(["2021-01-29", "2021-02-26"])
    monthly = pd.DataFrame({asset: [100.0, 110.0] for asset in ASSETS}, index=index)
    daily = pd.DataFrame({asset: [100.0, 105.0, 110.0, 120.0] for asset in ASSETS}, index=pd.to_datetime(["2021-01-29", "2021-02-01", "2021-02-26", "2021-03-01"]))
    decisions = pd.DataFrame({"selected_asset": ["CSPX_IL", "CSPX_IL"]}, index=index)
    result = run_backtest(decisions, monthly, 100, daily_prices=daily, benchmark_asset="CSPX_IL")
    assert result.audit.iloc[0]["execution_date"] == pd.Timestamp("2021-02-01")
    assert result.monthly.index.equals(result.monthly["benchmark_value"].index)
    assert result.monthly.iloc[0]["holding_period_return"] == result.monthly.iloc[0]["spy_return"]
