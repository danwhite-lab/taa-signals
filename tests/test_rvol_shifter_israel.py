import numpy as np
import pandas as pd
import pytest

from haa.engine import run_backtest
from haa.market_sessions import tase_equity_sessions, scheduled_tase_execution_dates
from haa.model_catalog import resolve
from haa.strategies.rvol_shifter_israel import RVolShifterCashOnlyIsrael, completed_tase_cutoff
from haa.tase_data import TASE_ISRAEL_ASSET_IDS
from haa.comparison import ModelInput
from haa.portfolio_backtest import run_portfolio_backtest


def fixture(states, dates=None):
    dates = tase_equity_sessions("2024-12-29", "2025-01-06") if dates is None else dates
    model = RVolShifterCashOnlyIsrael()
    prices = pd.DataFrame(100., index=dates, columns=model.data_assets)
    states = states[:len(dates)-1]
    decisions = pd.DataFrame({"model_state": states,
        "target_weights": [model.state_weights[s] for s in states],
        "selected_asset": [model.state_labels[s] for s in states]}, index=dates[:len(states)])
    decisions.attrs.update(local_daily_execution=True, execution_frequency="daily", completed_through=dates[-1])
    return decisions, prices


def run(decisions, prices, **kw):
    return run_backtest(decisions, pd.DataFrame(), 100., daily_prices=prices,
        benchmark_asset="RVOL_SPY_IL", **kw)


def test_catalog_and_exact_mapping():
    assert resolve("A-RVol Shifter", "V3 Cash-Only", "Israel").model_class is RVolShifterCashOnlyIsrael
    expected = ("1149038", "1144385", "1159078", "1159185", "1187079", "5117700")
    assert tuple(TASE_ISRAEL_ASSET_IDS[a] for a in RVolShifterCashOnlyIsrael.data_assets) == expected
    assert completed_tase_cutoff("2025-01-05 19:59") == pd.Timestamp("2025-01-04")
    assert completed_tase_cutoff("2025-01-05 20:00") == pd.Timestamp("2025-01-05")


def test_tase_session_schedule_not_us_calendar():
    assert scheduled_tase_execution_dates(pd.DatetimeIndex(["2025-01-02"]))[0] == pd.Timestamp("2025-01-05")


def test_indicators_warmup_and_no_future_leak():
    dates = tase_equity_sessions("2022-01-02", "2024-12-31")
    x = np.arange(len(dates))
    model = RVolShifterCashOnlyIsrael()
    prices = pd.DataFrame({a: 100*np.exp(np.cumsum(.001+.005*np.sin(x))) for a in model.data_assets}, index=dates)
    first = model.decisions(prices, as_of="2025-01-01")
    assert first.index[0] == dates[266]
    changed = prices.copy()
    changed.loc[dates[400]:, "RVOL_QQQ_IL"] *= 1.5
    second = model.decisions(changed, as_of="2025-01-01")
    pd.testing.assert_frame_equal(first.loc[:dates[399]], second.loc[:dates[399]])
    assert first.attrs["local_daily_execution"]


def test_next_close_and_actual_sale_tax_not_daily_rebalancing():
    dates = tase_equity_sessions("2025-01-05", "2025-01-09")
    decisions, prices = fixture(["QLD", "QLD", "BIL", "BIL"], dates)
    prices.loc[dates[2]:, "RVOL_3X_IL"] = 150.
    result = run(decisions, prices, tax_enabled=True)
    assert result.daily.index[0] == dates[1]
    assert result.daily.loc[dates[2], "actual_weights"]["RVOL_3X_IL"] == pytest.approx(.6)
    assert not result.daily.loc[dates[2], "security_trades"]
    assert result.daily.iloc[-1].pre_tax_value == pytest.approx(125.)
    assert result.daily.iloc[-1].after_tax_value == pytest.approx(118.75)
    assert result.tax_events.tax_paid.sum() == pytest.approx(6.25)


def test_annual_internal_reset_and_fees():
    decisions, prices = fixture(["QLD"]*10)
    prices.loc[pd.Timestamp("2024-12-31"): , "RVOL_3X_IL"] = 150.
    result = run(decisions, prices, tax_enabled=True)
    assert result.daily.loc["2024-12-31", "actual_weights"]["RVOL_3X_IL"] == pytest.approx(.6)
    assert result.daily.loc["2025-01-01", "annual_reset"]
    assert result.daily.loc["2025-01-01", "actual_weights"]["RVOL_3X_IL"] == pytest.approx(.5)
    assert result.tax_events.tax_paid.sum() == pytest.approx(12.5/3*.25)
    charged = run(decisions, prices, transaction_cost=.0005)
    assert charged.daily.iloc[0].pre_tax_value == pytest.approx(100/1.0005)
    assert charged.daily.iloc[-1].pre_tax_value < result.daily.iloc[-1].pre_tax_value


def test_missing_session_refuses_fabricated_fills():
    decisions, prices = fixture(["QLD"]*10)
    with pytest.raises(ValueError, match="Missing"):
        run(decisions, prices.drop(index=prices.index[2]))


def test_ils_mixed_portfolio_aligns_with_standalone():
    dates = tase_equity_sessions("2025-01-05", "2025-01-09")
    decisions, prices = fixture(["QLD"]*4, dates)
    prices.loc[dates[2]:, "RVOL_3X_IL"] = 150.
    daily = ModelInput("local", decisions, prices, prices, "RVOL_SPY_IL", None, "ILS")
    monthly = pd.DataFrame({"selected_asset": ["RVOL_CASH_IL"]}, index=pd.DatetimeIndex(["2024-12-31"]))
    slow = ModelInput("cash", monthly, prices, prices, "RVOL_SPY_IL", None, "ILS")
    result = run_portfolio_backtest({"rvol": (.5, daily), "cash": (.5, slow)}, 100., tax_enabled=True)
    assert result.daily.iloc[-1].pre_tax_value == pytest.approx(112.5)
    assert result.daily.iloc[-1].after_tax_value == pytest.approx(112.5)
    standalone = run_portfolio_backtest({"rvol": (1., daily)}, 100., tax_enabled=True)
    pd.testing.assert_series_equal(standalone.daily.pre_tax_value, run(decisions, prices, tax_enabled=True).daily.pre_tax_value, check_names=False, check_freq=False)
