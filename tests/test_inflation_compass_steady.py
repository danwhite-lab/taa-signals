import numpy as np
import pandas as pd
import pytest

from haa.strategies import InflationCompassFast, InflationCompassFastIsrael, InflationCompassStandard, InflationCompassStandardIsrael, InflationCompassSteady, InflationCompassSteadyIsrael
from haa.validation import ValidationInput, profile_for, run_deterministic_validation


ASSETS = ("SPY", "XLE", "XLK", "XLU", "XLP", "IEF", "XLI", "XLF", "XLB", "XLV", "T5YIE")


def daily_prices(t5yie_start=2.1, t5yie_step=.002, positive_step=.002, negative_step=.001, spy_step=.001):
    index = pd.bdate_range("2020-01-02", periods=280)
    values = {}
    for asset in ASSETS:
        step = positive_step if asset in {"XLE", "XLI", "XLF", "XLB"} else negative_step if asset in {"XLU", "XLV", "XLP"} else spy_step
        values[asset] = 100 * (1 + step) ** np.arange(len(index))
    values["T5YIE"] = t5yie_start + t5yie_step * np.arange(len(index))
    return pd.DataFrame(values, index=index)


def test_growth_and_inflation_on_selects_xle():
    decision = InflationCompassSteady().decisions(daily_prices()).iloc[-1]
    assert decision["growth_up"]
    assert decision["inflation_on"]
    assert decision["target_weights"] == {"XLE": 1.0}


def test_growth_up_inflation_off_selects_xlk():
    decision = InflationCompassSteady().decisions(daily_prices(t5yie_start=1.9, t5yie_step=0)).iloc[-1]
    assert decision["growth_up"]
    assert not decision["inflation_on"]
    assert decision["target_weights"] == {"XLK": 1.0}


def test_growth_down_inflation_on_selects_xlu():
    prices = daily_prices()
    prices.loc[prices.index[-1], "SPY"] *= .7
    decision = InflationCompassSteady().decisions(prices).iloc[-1]
    assert not decision["growth_up"]
    assert decision["target_weights"] == {"XLU": 1.0}


def test_growth_down_inflation_off_selects_xlp_and_ief():
    prices = daily_prices(t5yie_start=1.9, t5yie_step=0)
    prices.loc[prices.index[-1], "SPY"] *= .7
    decision = InflationCompassSteady().decisions(prices).iloc[-1]
    assert decision["target_weights"] == {"XLP": .5, "IEF": .5}


def test_month_end_t5yie_uses_prior_observation_not_same_day_value():
    prices = daily_prices(t5yie_start=1.9, t5yie_step=0)
    last_month_end = prices.index.to_series().groupby(prices.index.to_period("M")).tail(1).iloc[-1]
    prices.loc[last_month_end, "T5YIE"] = 9.0
    decision = InflationCompassSteady().decisions(prices).iloc[-1]
    assert decision["t5yie_lagged"] == 1.9
    assert decision["t5yie_lag_date"] < decision.name


def test_requires_80_trading_day_breakeven_lookback_and_200_day_spy_sma():
    assert InflationCompassSteady().decisions(daily_prices().iloc[:199]).empty


def test_indicator_uses_daily_rebalanced_returns_not_raw_prices():
    decision = InflationCompassSteady().decisions(daily_prices()).iloc[-1]
    assert decision["positive_basket_growth"] > decision["negative_basket_growth"]
    assert decision["indicator_80d_slope"] > 0


def test_standard_uses_60_valid_trading_observations_for_both_confirmations():
    prices = daily_prices()
    prices.loc[prices.index[:-62], "T5YIE"] = np.nan
    assert InflationCompassSteady().decisions(prices).empty
    decision = InflationCompassStandard().decisions(prices).iloc[-1]
    assert decision["t5yie_60d_date"] == prices["T5YIE"].dropna().index[0]
    assert decision["indicator_60d_slope"] > 0


def test_standard_and_steady_agree_when_both_windows_confirm_the_same_regime():
    prices = daily_prices()
    standard = InflationCompassStandard().decisions(prices).iloc[-1]
    steady = InflationCompassSteady().decisions(prices).iloc[-1]
    assert standard["target_weights"] == steady["target_weights"] == {"XLE": 1.0}


def test_fast_uses_40_valid_trading_observations_for_both_confirmations():
    prices = daily_prices()
    prices.loc[prices.index[:-42], "T5YIE"] = np.nan
    assert InflationCompassStandard().decisions(prices).empty
    decision = InflationCompassFast().decisions(prices).iloc[-1]
    assert decision["t5yie_40d_date"] == prices["T5YIE"].dropna().index[0]
    assert decision["indicator_40d_slope"] > 0


def test_fast_standard_and_steady_agree_when_all_windows_confirm_the_same_regime():
    prices = daily_prices()
    decisions = [model().decisions(prices).iloc[-1] for model in (InflationCompassFast, InflationCompassStandard, InflationCompassSteady)]
    assert [decision["target_weights"] for decision in decisions] == [{"XLE": 1.0}] * 3


def test_standard_recomputes_full_daily_indicators_on_shifted_research_dates():
    prices = daily_prices()
    strategy = InflationCompassStandard()
    production = strategy.decisions(prices)
    shifted_dates = production.index - pd.offsets.BDay(1)
    shifted = strategy.decisions_at_dates(prices, shifted_dates)
    assert shifted.index.equals(shifted_dates)
    assert shifted["SPY_200d_sma"].notna().all()

    validation_input = ValidationInput(
        strategy.name, production, prices.resample("ME").last(), prices, "SPY", profile_for(strategy),
        strategy=strategy, signal_prices=prices,
    )
    report = run_deterministic_validation(validation_input, 10_000)
    shifts = report.scenarios.loc[report.scenarios["test"] == "rebalance_shift"]
    assert set(shifts["status"]) == {"complete"}


def test_israel_execution_variants_use_the_identical_usd_compass_calculations():
    prices = daily_prices()
    pairs = (
        (InflationCompassFast, InflationCompassFastIsrael),
        (InflationCompassStandard, InflationCompassStandardIsrael),
        (InflationCompassSteady, InflationCompassSteadyIsrael),
    )
    for original, israel in pairs:
        original_rows, local_rows = original().decisions(prices), israel().decisions(prices)
        signal_columns = original_rows.columns.difference(["target_weights", "previous_weights", "selected_asset", "selected_assets", "previous_asset"])
        pd.testing.assert_frame_equal(original_rows[signal_columns], local_rows[signal_columns], check_exact=True)


@pytest.mark.parametrize("model", [InflationCompassFastIsrael, InflationCompassStandardIsrael, InflationCompassSteadyIsrael])
@pytest.mark.parametrize("growth,inflation,expected", [(True, True, {"XLE_IL": 1.}), (True, False, {"XLK_IL": 1.}),
    (False, True, {"XLU_IL": 1.}), (False, False, {"XLP_IL": .5, "IEF_IL": .5})])
def test_israel_regimes_map_only_execution_holdings(model, growth, inflation, expected):
    prices = daily_prices(t5yie_start=2.1 if inflation else 1.9, t5yie_step=.002 if inflation else 0, spy_step=.001 if growth else -.001)
    result = model().decisions(prices)
    assert result.iloc[-1].target_weights == expected
    assert result.attrs["ic_israel_actual_execution"] is True


def local_prices():
    from haa.market_sessions import tase_equity_sessions
    from haa.constants import INFLATION_COMPASS_ISRAEL_EXECUTION_ASSETS
    prices = daily_prices()
    dates = tase_equity_sessions(str(prices.index.min().date()), str(prices.index.max().date()))
    local = pd.DataFrame({a: 100*1.001**np.arange(len(dates)) for a in INFLATION_COMPASS_ISRAEL_EXECUTION_ASSETS}, index=dates)
    return prices.join(local, how="outer")


@pytest.mark.parametrize("model", [InflationCompassFastIsrael, InflationCompassStandardIsrael, InflationCompassSteadyIsrael])
def test_israel_runs_real_monthly_engine_on_synthetic_us_and_tase_prices(model):
    from haa.engine import run_backtest
    prices = local_prices()
    strategy = model()
    result = run_backtest(strategy.decisions(prices), prices.resample("ME").last(), 1000., daily_prices=prices)
    assert not result.monthly.empty
    assert result.audit.execution_date.gt(result.audit.index).all()
    assert result.audit.target_weights.map(lambda w: set(w) <= {"XLE_IL", "XLK_IL", "XLU_IL", "XLP_IL", "IEF_IL"}).all()


def test_execution_skips_pre_inception_periods_without_changing_signal_dates():
    from haa.ic_israel_execution import execution_schedule
    prices = local_prices()
    decisions = InflationCompassStandardIsrael().decisions(prices)
    original_dates = decisions.index.copy()
    prices.loc[prices.index < "2020-12-01", "XLE_IL"] = np.nan
    schedule = execution_schedule(decisions, prices, "SPY")
    assert min(v[0] for v in schedule.values()) >= pd.Timestamp("2020-12-01")
    assert decisions.index.equals(original_dates)
    # Unused utilities can start later; they must not force an all-five start.
    prices["XLU_IL"] = np.nan
    assert execution_schedule(decisions, prices, "SPY") == schedule


def test_internal_missing_fund_price_stops_with_id_and_date_not_forward_fill():
    from haa.ic_israel_execution import execution_schedule
    prices = local_prices()
    decisions = InflationCompassStandardIsrael().decisions(prices)
    schedule = execution_schedule(decisions, prices, "SPY")
    entry = min(v[0] for v in schedule.values())
    prices.loc[entry, "XLE_IL"] = np.nan
    with pytest.raises(ValueError, match=f"1145903.*{entry:%Y-%m-%d}"):
        execution_schedule(decisions, prices, "SPY")


def test_slowdown_waits_for_both_real_funds_and_names_missing_bond():
    from haa.ic_israel_execution import execution_schedule
    prices = local_prices()
    decisions = InflationCompassStandardIsrael().decisions(prices)
    decisions["target_weights"] = [{"XLP_IL": .5, "IEF_IL": .5} for _ in range(len(decisions))]
    prices.loc[prices.index < "2020-12-01", "IEF_IL"] = np.nan
    schedule = execution_schedule(decisions, prices, "SPY")
    assert min(v[0] for v in schedule.values()) >= pd.Timestamp("2020-12-01")
    prices["IEF_IL"] = np.nan
    with pytest.raises(ValueError, match="IEF_IL.*1159268.*no actual fund price"):
        execution_schedule(decisions, prices, "SPY")
