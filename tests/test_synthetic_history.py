import unittest
import numpy as np
import pandas as pd

from haa.deep_history import ALL_DEEP_HISTORY_SPECS, DEEP_HISTORY_BENCHMARKS, deep_history_model_input, deep_history_options, load_deep_history
from haa.engine import run_backtest
from haa.portfolio_backtest import run_portfolio_backtest
from haa.strategies.rvol_shifter import RVolShifterCashOnly


class SyntheticHistoryTests(unittest.TestCase):
    spec = ALL_DEEP_HISTORY_SPECS["rvol_synthetic"]

    def test_source_and_complete_months(self):
        daily, returns = load_deep_history(self.spec)
        self.assertEqual(len(daily), 10059)
        self.assertEqual(daily.index.min(), pd.Timestamp("1986-11-03"))
        self.assertEqual(daily.index.max(), pd.Timestamp("2026-10-08"))
        self.assertEqual(returns.index.min(), pd.Timestamp("1986-12-31"))
        self.assertEqual(returns.index.max(), pd.Timestamp("2026-09-30"))
        self.assertEqual((daily.exec == "NEXT_OPEN_TRADE_TODAY").sum(), 226)

    def test_actual_app_transition_function_matches_every_source_decision(self):
        from haa.deep_history import DEEP_HISTORY_DIR
        root = DEEP_HISTORY_DIR / "arvol_synthetic_v5" / "inputs"
        read = lambda name: pd.read_csv(root / f"{name}.csv", index_col=0, parse_dates=True)
        gs = read("GSPC")
        cal = gs.index[gs.index >= "1985-10-01"]
        nc = read("NDX").close.reindex(cal)
        sp = read("SP500TR").close.reindex(cal)
        spr = sp.pct_change().where(sp.notna().cumsum() > 1, gs.close.reindex(cal).pct_change()).fillna(0)
        trend_prices = (1 + spr - .0007 / 252).cumprod()
        rv = np.log(nc / nc.shift(1)).rolling(15).std(ddof=1) * np.sqrt(252)
        vr = rv / rv.rolling(252).mean()
        trend = trend_prices / trend_prices.rolling(200).mean() - 1
        credit_ratio = read("HYG").adj.reindex(cal) / read("LQD").adj.reindex(cal)
        credit = credit_ratio / credit_ratio.shift(20) - 1
        low40, low5 = nc.rolling(40).min(), nc.rolling(5).min()
        daily, _ = load_deep_history(self.spec)
        state, lock, age = "BIL", False, 0
        targets = []
        for date in daily.index:
            previous = state
            if state == "BIL" and lock:
                age += 1
            state, lock, _ = RVolShifterCashOnly.transition(state, rv[date], vr[date], trend[date],
                credit[date] if np.isfinite(credit[date]) else 0., nc[date] <= low40[date],
                nc[date] / low5[date] - 1, age, lock)
            if state != "BIL" or previous != "BIL":
                age = 0
            targets.append("DEF(cash:synthetic T-bill)" if state == "BIL" else state)
        # Target decided at yesterday's close executes today, not yesterday.
        self.assertEqual(targets[:-1], daily.position_end_of_day.iloc[1:].tolist())

    def test_daily_nav_is_preserved_for_both_benchmarks(self):
        for benchmark in DEEP_HISTORY_BENCHMARKS.values():
            model = deep_history_model_input(self.spec, benchmark)
            result = run_backtest(model.decisions, model.monthly_prices, 100000,
                                  daily_prices=model.daily_prices, benchmark_asset=model.benchmark_asset)
            source = model.daily_prices
            anchor = source.loc[:"1986-11-30", "nav"].iloc[-1]
            expected = 100000 * source.loc["1986-12-01":"2026-09-30", "nav"] / anchor
            pd.testing.assert_series_equal(result.daily.pre_tax_value, expected, check_names=False)
            self.assertNotIn("benchmark_value", result.daily)
            self.assertTrue(result.tax_events.empty)
            self.assertAlmostEqual(result.monthly.pre_tax_value.iloc[-1], expected.iloc[-1])
            ends = result.daily.pre_tax_value.groupby(result.daily.index.to_period("M")).last()
            pd.testing.assert_series_equal(result.monthly.pre_tax_value.reset_index(drop=True), ends.reset_index(drop=True), check_names=False)

    def test_subrange_restarts_capital_and_compounds_daily(self):
        model = deep_history_model_input(self.spec)
        result = run_backtest(model.decisions, model.monthly_prices, 100000,
            daily_prices=model.daily_prices, benchmark_asset=model.benchmark_asset,
            start=pd.Timestamp("2025-01-31"), end=pd.Timestamp("2025-12-31"))
        self.assertEqual(len(result.monthly), 12)
        source = model.daily_prices
        self.assertAlmostEqual(result.monthly.pre_tax_value.iloc[-1], 100000 * source.loc["2025-12-31", "nav"] / source.loc["2024-12-31", "nav"])
        self.assertAlmostEqual((1 + result.daily.pre_tax_daily_return).prod(), result.monthly.pre_tax_value.iloc[-1] / 100000)

    def test_tax_fees_and_blends_fail_closed(self):
        model = deep_history_model_input(self.spec)
        for options in ({"tax_enabled": True}, {"transaction_cost": .001}):
            with self.assertRaises(ValueError):
                run_backtest(model.decisions, model.monthly_prices, 100000, daily_prices=model.daily_prices, **options)
        with self.assertRaisesRegex(ValueError, "single-strategy only"):
            run_portfolio_backtest({"synthetic": (1., model)}, 100000)
        self.assertIn("rvol_synthetic", deep_history_options(1))
        self.assertNotIn("rvol_synthetic", deep_history_options(2))


if __name__ == "__main__":
    unittest.main()
