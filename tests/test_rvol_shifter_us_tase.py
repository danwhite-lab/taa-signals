import numpy as np
import pandas as pd
import pytest

from haa.comparison import ModelInput
from haa.cross_market_daily import tase_execution_schedule
from haa.data import _normalise_frame
from haa.engine import run_backtest
from haa.market_sessions import (us_equity_sessions, tase_equity_sessions,
    scheduled_us_tase_execution_dates, market_session_times)
from haa.model_catalog import definition_for_label
from haa.portfolio_backtest import run_portfolio_backtest
from haa.signals import latest_actionable_signal
from haa.strategies.rvol_shifter import RVolShifterCashOnly
from haa.strategies.rvol_shifter_us_tase import RVolShifterUSTase1x, RVolShifterUSTaseBlend


def history(model):
    us_dates = us_equity_sessions("2021-01-04", "2024-12-31")
    local_dates = tase_equity_sessions("2022-11-15", "2024-12-31")
    x = np.arange(len(us_dates))
    qqq = 100 * np.exp(np.cumsum(.0007 + .006*np.sin(x)))
    us = pd.DataFrame({asset: qqq if asset in ("QQQ", "SPY", "QLD", "TQQQ") else 100+x/1000
                       for asset in model.us_data_assets}, index=us_dates)
    local = pd.DataFrame(100., index=local_dates, columns=model.execution_assets)
    return us, local, us.join(local, how="outer")


@pytest.mark.parametrize("model", [RVolShifterUSTase1x(), RVolShifterUSTaseBlend()])
def test_original_us_v3_decisions_reproduced_exactly(model):
    us, local, combined = history(model)
    expected = RVolShifterCashOnly().decisions(us, as_of="2025-01-01")
    actual = model.us_decisions(combined, as_of="2025-01-01")
    pd.testing.assert_frame_equal(actual, expected)
    mapped = model.decisions(combined, as_of="2025-01-01")
    pd.testing.assert_series_equal(mapped.model_state, expected.selected_asset, check_names=False)
    for field in ("rvol", "vr", "trend", "credit", "donchian", "recovery", "trade",
                  "transition_reason", "donchian_lock", "defensive_age"):
        pd.testing.assert_series_equal(mapped[field], expected[field])
    for state in ("TQQQ", "QLD", "BIL"):
        for weights in mapped.loc[mapped.model_state == state, "target_weights"]:
            assert weights == model.state_weights[state]
    changed = combined.copy()
    changed.loc[local.index, list(model.execution_assets)] *= 2
    pd.testing.assert_frame_equal(model.us_decisions(changed, as_of="2025-01-01"), actual)


def test_mapping_catalog_and_no_proxy_cash():
    assert RVolShifterUSTase1x.state_weights["QLD"] == {"RVOL_QQQ_IL": 1.}
    assert RVolShifterUSTaseBlend.state_weights["QLD"] == {"RVOL_QQQ_IL": .5, "RVOL_3X_IL": .5}
    assert RVolShifterUSTaseBlend.state_weights["BIL"] == {"RVOL_CASH_IL": 1.}
    for model in (RVolShifterUSTase1x, RVolShifterUSTaseBlend):
        assert definition_for_label(model.name).execution_currency == "ILS"
    assert not RVolShifterUSTase1x.annual_reset_states
    assert RVolShifterUSTaseBlend.annual_reset_states == ("QLD",)


def decisions(states, dates, model=RVolShifterUSTaseBlend()):
    frame = pd.DataFrame({"model_state": states,
        "target_weights": [model.state_weights[state] for state in states],
        "selected_asset": [model.state_labels[state] for state in states]}, index=pd.to_datetime(dates))
    frame.attrs.update(execution_frequency="daily", local_daily_execution=True, signal_calendar="XNYS",
                       annual_reset_states=model.annual_reset_states)
    return frame


def test_us_holiday_holds_last_state_and_defensive_age_is_not_recalculated():
    frame = decisions(["QLD", "TQQQ"], ["2025-05-23", "2025-05-27"])
    sessions = tase_equity_sessions("2025-05-25", "2025-05-28")
    schedule = tase_execution_schedule(frame, sessions)
    assert schedule[pd.Timestamp("2025-05-25")][0] == pd.Timestamp("2025-05-23")
    assert schedule[pd.Timestamp("2025-05-26")][1].model_state == "QLD"
    assert schedule[pd.Timestamp("2025-05-27")][1].model_state == "QLD"
    assert schedule[pd.Timestamp("2025-05-28")][1].model_state == "TQQQ"


def test_tase_holiday_and_week_transition_latest_eligible_signal_wins():
    # Several US sessions can precede the same TASE opening at New Year.
    frame = decisions(["QLD", "BIL"], ["2026-01-01", "2026-01-02"])
    # Jan 1 is not a US session: timestamp scheduling must reject it.
    with pytest.raises(ValueError, match="timestamps"):
        tase_execution_schedule(frame, pd.to_datetime(["2026-01-05"]))
    frame = decisions(["QLD", "BIL"], ["2025-12-31", "2026-01-02"])
    schedule = tase_execution_schedule(frame, pd.to_datetime(["2026-01-01", "2026-01-05"]))
    assert schedule[pd.Timestamp("2026-01-01")][1].model_state == "QLD"
    assert schedule[pd.Timestamp("2026-01-05")][1].model_state == "BIL"
    dates = pd.to_datetime(["2024-11-29", "2025-03-10", "2025-10-27", "2026-01-09"])
    executions = scheduled_us_tase_execution_dates(dates)
    assert (market_session_times("XTAE", executions, "open") > market_session_times("XNYS", dates, "close")).all()
    assert executions[-1] == pd.Timestamp("2026-01-12")


def test_zero_cost_pre_tax_path_matches_independent_holdings_book():
    model = RVolShifterUSTaseBlend()
    frame = decisions(["QLD", "QLD", "BIL"], ["2025-05-23", "2025-05-27", "2025-05-28"])
    dates = tase_equity_sessions("2025-05-25", "2025-05-29")
    prices = pd.DataFrame(100., index=dates, columns=model.execution_assets)
    prices["RVOL_3X_IL"] = [100., 120., 150., 140., 130.]
    prices["RVOL_QQQ_IL"] = [100., 105., 110., 108., 106.]
    frame.attrs["completed_through"] = dates[-1]
    result = run_backtest(frame, pd.DataFrame(), 100., daily_prices=prices, benchmark_asset=model.benchmark_asset)
    # Enter .5 unit of each security; drift without daily rebalancing, then sell.
    expected = [.5*prices.loc[d, "RVOL_3X_IL"] + .5*prices.loc[d, "RVOL_QQQ_IL"] for d in dates]
    np.testing.assert_allclose(result.daily.pre_tax_value, expected)
    assert not result.daily.iloc[1].security_trades
    assert result.daily.iloc[-1].model_state == "BIL"
    assert result.daily.iloc[-1].actual_weights["RVOL_CASH_IL"] == pytest.approx(1.)
    assert not result.daily.iloc[1].new_us_observation
    assert result.tax_events.empty


def test_annual_reset_is_first_tase_session_not_december_decision():
    model = RVolShifterUSTaseBlend()
    frame = decisions(["QLD"]*4, ["2025-12-29", "2025-12-30", "2025-12-31", "2026-01-02"])
    dates = tase_equity_sessions("2025-12-30", "2026-01-05")
    prices = pd.DataFrame(100., index=dates, columns=model.execution_assets)
    prices.loc["2025-12-31":, "RVOL_3X_IL"] = 150.
    frame.attrs["completed_through"] = dates[-1]
    result = run_backtest(frame, pd.DataFrame(), 100., daily_prices=prices, benchmark_asset=model.benchmark_asset)
    assert not result.daily.loc["2025-12-31", "annual_reset"]
    assert result.daily.loc["2026-01-01", "annual_reset"]
    assert result.daily.loc["2026-01-01", "actual_weights"]["RVOL_3X_IL"] == pytest.approx(.5)
    single = decisions(["QLD"]*4, ["2025-12-29", "2025-12-30", "2025-12-31", "2026-01-02"], RVolShifterUSTase1x())
    single.attrs["completed_through"] = dates[-1]
    result_a = run_backtest(single, pd.DataFrame(), 100., daily_prices=prices, benchmark_asset=model.benchmark_asset)
    assert not result_a.daily.annual_reset.any()


def test_missing_latest_eligible_us_session_is_not_treated_as_holiday():
    frame = decisions(["BIL"], ["2025-05-23"])
    with pytest.raises(ValueError, match="Missing completed US decision"):
        tase_execution_schedule(frame, pd.to_datetime(["2025-05-28"]))


def test_missing_sessions_pending_nav_and_no_future_leak():
    model = RVolShifterUSTaseBlend()
    us, local, combined = history(model)
    baseline = model.decisions(combined, as_of="2025-01-01")
    bad = combined.copy()
    bad.loc[us.index[400], "HYG"] = np.nan
    with pytest.raises(ValueError, match="Missing/invalid"):
        model.decisions(bad, as_of="2025-01-01")
    bad = combined.copy()
    bad.loc[local.index[100], "RVOL_CASH_IL"] = np.nan
    short_gap = model.decisions(bad, as_of="2025-01-01")
    pd.testing.assert_frame_equal(short_gap, baseline, check_exact=True)
    pending = combined.copy()
    pending.loc[local.index[-1], "RVOL_CASH_IL"] = np.nan
    trimmed = model.decisions(pending, as_of="2025-01-01")
    assert trimmed.attrs["execution_prices_completed_through"] == local.index[-2]
    assert trimmed.attrs["pending_price_dates"] == [str(local.index[-1].date())]
    future = combined.copy()
    future.loc[us.index[700]:, "QQQ"] *= 1.2
    changed = model.decisions(future, as_of="2025-01-01")
    pd.testing.assert_frame_equal(baseline.loc[:us.index[699]], changed.loc[:us.index[699]])
    with pytest.raises(ValueError, match="adjusted close required"):
        _normalise_frame(pd.DataFrame({"Close": [100.]}), "HYG", require_adjusted=True)


def test_reference_cash_restart_retains_prior_indicator_warmup():
    model = RVolShifterUSTaseBlend()
    us, local, combined = history(model)
    replay = model.decisions(combined, as_of="2025-01-01", cash_start="2022-11-15")
    assert replay.index.min() == pd.Timestamp("2022-11-15")
    assert replay.iloc[0].previous_model_state == "BIL"
    expected = RVolShifterCashOnly().indicators(us).loc["2022-11-15"]
    assert replay.iloc[0].rvol == expected.rvol
    schedule = tase_execution_schedule(replay, pd.to_datetime(["2022-11-15", "2022-11-16"]))
    assert pd.isna(schedule[pd.Timestamp("2022-11-15")][0])
    assert schedule[pd.Timestamp("2022-11-15")][1].model_state == "BIL"
    assert schedule[pd.Timestamp("2022-11-16")][0] == pd.Timestamp("2022-11-15")


def test_standalone_matches_100_percent_ils_sleeve_and_us_freshness():
    model = RVolShifterUSTaseBlend()
    us, local, combined = history(model)
    frame = model.decisions(combined, as_of="2025-01-01")
    standalone = run_backtest(frame, pd.DataFrame(), 100., daily_prices=combined, benchmark_asset=model.benchmark_asset)
    sleeve = ModelInput("US signals TASE", frame, pd.DataFrame(), combined, model.benchmark_asset, None, "ILS")
    portfolio = run_portfolio_backtest({"test": (1., sleeve)}, 100.)
    pd.testing.assert_series_equal(standalone.daily.pre_tax_value, portfolio.daily.pre_tax_value, check_names=False, check_freq=False)
    status = latest_actionable_signal(frame, combined, model.data_assets, as_of="2024-12-31 17:00")
    assert status.decision.name == pd.Timestamp("2024-12-31")
    stale = latest_actionable_signal(frame, combined, model.data_assets, as_of="2025-01-03 17:00")
    assert stale.decision is None


def test_direct_engine_starts_at_actual_common_fund_availability():
    model = RVolShifterUSTaseBlend()
    us, local, combined = history(model)
    combined.loc[local.index[:50], "RVOL_CASH_IL"] = np.nan
    frame = model.decisions(combined, as_of="2025-01-01")
    result = run_backtest(frame, pd.DataFrame(), 100., daily_prices=combined,
                          benchmark_asset=model.benchmark_asset)
    assert result.daily.index.min() == local.index[50]
