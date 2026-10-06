import unittest

import pandas as pd

from haa.deep_history import ALL_DEEP_HISTORY_SPECS, DEEP_HISTORY_SPECS, GLOBAL_TOTAL_RETURN_BENCHMARK, SP500_TOTAL_RETURN_BENCHMARK, deep_history_model_input, deep_history_options, load_deep_history
from haa.comparison import compare_models
from haa.engine import run_backtest
from haa.metrics import worst_rolling_annualized_return
from haa.portfolio_backtest import run_portfolio_backtest


class RVolDeepHistoryTests(unittest.TestCase):
    spec = ALL_DEEP_HISTORY_SPECS["rvol_daily"]

    def test_import_preserves_daily_changes_and_completed_returns(self):
        signals, returns = load_deep_history(self.spec)
        self.assertEqual(len(signals), 231)
        self.assertEqual(signals.index.min(), pd.Timestamp("2003-01-02"))
        self.assertEqual(signals.index.max(), pd.Timestamp("2026-08-28"))
        self.assertFalse(signals.index.has_duplicates)
        self.assertEqual(sum(signals.groupby(signals.index.to_period("M")).size() > 1), 61)
        self.assertEqual(len(returns), 285)
        self.assertTrue(returns.index.equals(pd.date_range("2003-01-31", "2026-09-30", freq="ME")))
        self.assertAlmostEqual(returns.iloc[0], -.035)
        self.assertAlmostEqual(returns.iloc[-1], .113)

    def test_both_benchmarks_exact_monthly_returns_and_rolling_results(self):
        _, returns = load_deep_history(self.spec)
        for benchmark in (SP500_TOTAL_RETURN_BENCHMARK, GLOBAL_TOTAL_RETURN_BENCHMARK):
            model = deep_history_model_input(self.spec, benchmark)
            result = run_backtest(model.decisions, model.monthly_prices, 100000, benchmark_asset=model.benchmark_asset)
            self.assertTrue(result.monthly.index.equals(returns.index))
            self.assertAlmostEqual(result.monthly.pre_tax_value.iloc[-1] / (100000 * (1 + returns).prod()), 1.0)
            pd.testing.assert_series_equal(result.monthly.pre_tax_monthly_return, returns, check_names=False, atol=1e-12, rtol=1e-12)
            self.assertTrue(result.tax_events.empty)
            self.assertFalse(pd.isna(worst_rolling_annualized_return(result.monthly.pre_tax_monthly_return, 5)))
            self.assertEqual(set(model.monthly_prices), {"ARVOL_STRATEGY_NAV_PROXY", benchmark.asset_id})

    def test_tax_and_additional_fees_fail_closed(self):
        model = deep_history_model_input(self.spec)
        for options, message in (({"tax_enabled": True}, "daily realized gains"), ({"transaction_cost": .001}, "trade-fee")):
            with self.assertRaisesRegex(ValueError, message):
                run_backtest(model.decisions, model.monthly_prices, 100000, benchmark_asset=model.benchmark_asset, **options)

    def test_single_only_in_ui_and_portfolio_engine(self):
        self.assertIn("rvol_daily", deep_history_options(1))
        self.assertNotIn("rvol_daily", deep_history_options(2))
        self.assertNotIn("rvol_daily", DEEP_HISTORY_SPECS)
        model = deep_history_model_input(self.spec)
        with self.assertRaisesRegex(ValueError, "single-strategy only"):
            run_portfolio_backtest({"daily": (1.0, model)}, 100000)
        other = deep_history_model_input(DEEP_HISTORY_SPECS["century_momentum"])
        with self.assertRaisesRegex(ValueError, "single-strategy only"):
            compare_models({"daily": model, "CM": other}, 100000)

    def test_subrange_uses_monthly_returns_without_daily_trade_invention(self):
        model = deep_history_model_input(self.spec)
        _, returns = load_deep_history(self.spec)
        result = run_backtest(model.decisions, model.monthly_prices, 100000,
                              start=pd.Timestamp("2025-01-31"), end=pd.Timestamp("2025-12-31"), benchmark_asset=model.benchmark_asset)
        self.assertEqual(len(result.monthly), 12)
        self.assertAlmostEqual(result.monthly.pre_tax_value.iloc[-1] / (100000 * (1 + returns.loc["2025"]).prod()), 1.0)


if __name__ == "__main__":
    unittest.main()
