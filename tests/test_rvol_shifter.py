import unittest

import numpy as np
import pandas as pd

from haa.comparison import ModelInput, compare_models
from haa.daily_engine import daily_performance_metrics
from haa.engine import run_backtest
from haa.model_catalog import resolve
from haa.portfolio_backtest import run_portfolio_backtest
from haa.signals import latest_actionable_signal
from haa.strategies.rvol_shifter import RVolShifterCashOnly, completed_daily_cutoff


class RVolShifterTests(unittest.TestCase):
    def transition(self, state="QLD", **changes):
        inputs = dict(rvol=0.16, vr=1.0, trend=0.0, credit=0.0, donchian=False,
                      recovery=0.0, defensive_age=0, donchian_lock=False)
        inputs.update(changes)
        return RVolShifterCashOnly.transition(state, **inputs)

    def test_all_transitions_and_strict_boundaries(self):
        for changes in ({"rvol": .181}, {"vr": 1.251}, {"trend": -.031}):
            self.assertEqual(self.transition("TQQQ", **changes)[0], "QLD")
        self.assertEqual(self.transition("TQQQ", rvol=.18, vr=1.25, trend=-.03)[0], "TQQQ")
        for changes in ({"rvol": .361}, {"vr": 1.401}, {"credit": -.041}, {"trend": -.031}):
            self.assertEqual(self.transition(**changes)[:2], ("BIL", False))
        self.assertEqual(self.transition(rvol=.139, vr=.899, trend=.031)[0], "TQQQ")
        self.assertEqual(self.transition(rvol=.14, vr=.90, trend=.03)[0], "QLD")
        self.assertEqual(self.transition("BIL", rvol=.249, vr=1.099, trend=-.014)[0], "QLD")
        self.assertEqual(self.transition("BIL", rvol=.25, vr=1.10, trend=-.015)[0], "BIL")
        # Severe stress may downshift only once per closing observation.
        self.assertEqual(self.transition("TQQQ", rvol=.50)[0], "QLD")

    def test_donchian_exit_lock_recovery_timeout_and_priority(self):
        self.assertEqual(self.transition(donchian=True, rvol=.20)[:2], ("BIL", True))
        self.assertEqual(self.transition(donchian=True, rvol=.199)[0], "QLD")
        self.assertEqual(self.transition(donchian=True, rvol=.20, credit=-.05)[:2], ("BIL", False))
        self.assertEqual(self.transition("BIL", donchian_lock=True, defensive_age=19)[0], "BIL")
        self.assertEqual(self.transition("BIL", donchian_lock=True, defensive_age=20, rvol=.60)[0], "QLD")
        self.assertEqual(self.transition("BIL", donchian_lock=True, recovery=.03)[:2], ("QLD", False))

    def prices(self):
        dates = pd.bdate_range("2020-01-01", periods=650)
        x = np.arange(len(dates))
        qqq = 100 * np.exp(np.cumsum(.0007 + .006 * np.sin(x)))
        return pd.DataFrame({"QQQ": qqq, "SPY": qqq, "HYG": 100 + x / 100,
            "LQD": 100 + x / 100, "TQQQ": qqq * 2, "QLD": qqq * 1.5,
            "BIL": 100 + x / 1000}, index=dates)

    def test_indicators_and_warmup_use_only_past_data(self):
        model = RVolShifterCashOnly()
        prices = self.prices()
        indicators = model.indicators(prices)
        logs = np.log(prices.QQQ / prices.QQQ.shift(1))
        expected = logs.iloc[286:301].std(ddof=1) * np.sqrt(252)
        self.assertAlmostEqual(indicators.rvol.iloc[300], expected)
        self.assertAlmostEqual(indicators.vr.iloc[300], expected / indicators.rvol.iloc[49:301].mean())
        as_of = pd.Timestamp("2025-01-01", tz="UTC")
        decisions = model.decisions(prices, as_of=as_of)
        self.assertEqual(decisions.index.min(), prices.index[266])
        self.assertEqual(decisions.attrs["execution_frequency"], "daily")
        changed = prices.copy()
        changed.loc[prices.index[500]:, "QQQ"] *= 1.5
        other = model.decisions(changed, as_of=as_of)
        pd.testing.assert_frame_equal(decisions.iloc[:234], other.iloc[:234])
        self.assertEqual(resolve("A-RVol Shifter", "V3 Cash-Only", "Documented interpretation").model_class, RVolShifterCashOnly)

    def test_missing_session_is_not_silently_skipped(self):
        prices = self.prices()
        prices.iloc[400, prices.columns.get_loc("HYG")] = np.nan
        with self.assertRaisesRegex(ValueError, "Missing/invalid daily data"):
            RVolShifterCashOnly().decisions(prices, as_of=pd.Timestamp("2025-01-01", tz="UTC"))

    def test_live_cutoff_and_daily_status(self):
        self.assertEqual(completed_daily_cutoff(pd.Timestamp("2024-01-05 16:30", tz="America/New_York")), pd.Timestamp("2024-01-04"))
        self.assertEqual(completed_daily_cutoff(pd.Timestamp("2024-01-05 17:00", tz="America/New_York")), pd.Timestamp("2024-01-05"))
        prices = self.prices()
        as_of = prices.index[-1].tz_localize("America/New_York") + pd.Timedelta(hours=17)
        decisions = RVolShifterCashOnly().decisions(prices, as_of=as_of)
        status = latest_actionable_signal(decisions, prices, RVolShifterCashOnly.data_assets, as_of=as_of)
        self.assertEqual(status.decision.name, prices.index[-1])
        stale = latest_actionable_signal(decisions, prices, RVolShifterCashOnly.data_assets, as_of=as_of + pd.Timedelta(days=10))
        self.assertIsNone(stale.decision)


class DailyEngineTests(unittest.TestCase):
    def fixture(self):
        dates = pd.bdate_range("2020-01-02", periods=5)
        prices = pd.DataFrame({"SPY": [100, 100, 101, 102, 103],
            "TQQQ": [90, 100, 110, 121, 999], "QLD": [80, 90, 95, 100, 120]}, index=dates)
        decisions = pd.DataFrame({"target_weights": [{a: 1.0} for a in ("TQQQ", "TQQQ", "QLD", "QLD", "QLD")],
            "selected_asset": ["TQQQ", "TQQQ", "QLD", "QLD", "QLD"], "regime": "risk-on"}, index=dates)
        decisions.attrs["execution_frequency"] = "daily"
        return decisions, prices

    def run_model(self, **kwargs):
        decisions, prices = self.fixture()
        return run_backtest(decisions, prices, 1000, daily_prices=prices, **kwargs)

    def test_next_close_execution_daily_carry_and_no_final_sale(self):
        result = self.run_model(tax_enabled=True)
        self.assertEqual(len(result.daily), 4)
        self.assertTrue((result.audit.execution_date > result.audit.index).all())
        self.assertEqual(result.daily.iloc[0].pre_tax_value, 1000)
        self.assertAlmostEqual(result.daily.iloc[-1].pre_tax_value, 1452)
        self.assertAlmostEqual(result.daily.iloc[-1].after_tax_value, (1210 - 210 * .25) * 1.2)
        self.assertEqual(len(result.tax_events), 1)
        self.assertAlmostEqual(result.daily.iloc[-1].benchmark_value, 1030)

    def test_buy_sell_fees_and_net_gain_tax_reconcile(self):
        result = self.run_model(transaction_cost=.01, tax_enabled=True)
        self.assertAlmostEqual(result.daily.iloc[0].pre_tax_value, 990)
        self.assertAlmostEqual(result.daily.iloc[-1].pre_tax_value, 990 * 1.21 * .99 * .99 * 1.2)
        net_proceeds = 990 * 1.21 * .99
        tax = (net_proceeds - 1000) * .25
        self.assertAlmostEqual(result.tax_events.tax_paid.iloc[0], tax)
        self.assertAlmostEqual(result.daily.iloc[-1].after_tax_value, (net_proceeds - tax) * .99 * 1.2)
        self.assertAlmostEqual((1 + result.monthly.pre_tax_monthly_return).prod(), result.daily.pre_tax_value.iloc[-1] / 1000)

    def test_subrange_restart_and_extra_delay(self):
        _, prices = self.fixture()
        result = self.run_model(start=prices.index[3], tax_enabled=True)
        self.assertEqual(len(result.daily), 2)
        self.assertEqual(result.daily.pre_tax_value.iloc[0], 1000)
        self.assertAlmostEqual(result.daily.pre_tax_value.iloc[-1], 1200)
        self.assertTrue(result.tax_events.empty)
        delayed = self.run_model(execution_delay_business_days=1)
        self.assertEqual(delayed.daily.index.min(), prices.index[2])

    def test_daily_drawdown_is_not_hidden_by_monthly_aggregation(self):
        decisions, prices = self.fixture()
        decisions.target_weights = [{"TQQQ": 1.0} for _ in decisions.index]
        prices.TQQQ = [100, 100, 50, 100, 100]
        result = run_backtest(decisions, prices, 1000, daily_prices=prices)
        self.assertEqual(daily_performance_metrics(result, "pre_tax_value", 1000)["Maximum drawdown"], -.5)
        self.assertAlmostEqual(result.monthly.pre_tax_monthly_return.iloc[0], 0)

    def test_missing_prices_and_unsupported_monthly_blends_fail_explicitly(self):
        decisions, prices = self.fixture()
        model = ModelInput("Daily", decisions, prices, prices)
        with self.assertRaisesRegex(ValueError, "single-strategy"):
            run_portfolio_backtest({"Daily": (1.0, model)}, 1000)
        with self.assertRaisesRegex(ValueError, "single-strategy"):
            compare_models({"Daily": model, "Other": model}, 1000)
        prices.iloc[3, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "Missing or invalid"):
            run_backtest(decisions, prices, 1000, daily_prices=prices)


if __name__ == "__main__":
    unittest.main()
