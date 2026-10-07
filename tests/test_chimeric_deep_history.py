import unittest
from unittest.mock import patch

import pandas as pd

from haa.deep_history import DEEP_HISTORY_DIR, DEEP_HISTORY_SPECS, GLOBAL_TOTAL_RETURN_BENCHMARK, SP500_TOTAL_RETURN_BENCHMARK, _read_signals, _read_monthly_returns, deep_history_model_input, load_deep_history
from haa.engine import run_backtest
from haa.portfolio_backtest import run_portfolio_backtest


class ChimericDeepHistoryTests(unittest.TestCase):
    spec = DEEP_HISTORY_SPECS["chimeric"]

    def test_raw_rows_preserved_including_markerless_first_row(self):
        signals = _read_signals(DEEP_HISTORY_DIR / self.spec.signal_file)
        self.assertEqual(len(signals), 538)
        self.assertEqual(signals.iloc[-1].target_weights, {"BIL": 1.0})
        self.assertEqual(signals.index[-1], pd.Timestamp("2026-09-09"))
        returns = _read_monthly_returns(DEEP_HISTORY_DIR / self.spec.returns_file)
        self.assertEqual(len(returns), 536)
        self.assertAlmostEqual(returns.iloc[-1], .008)

    def test_usable_months_unique_complete_and_pinned(self):
        signals, returns = load_deep_history(self.spec)
        self.assertEqual(len(signals), 535)
        self.assertEqual(len(returns), 535)
        self.assertEqual(self.spec.usable_through, "2026-09-30")
        self.assertTrue(returns.index.equals(pd.date_range("1982-03-31", "2026-09-30", freq="ME")))
        self.assertFalse(signals.index.to_period("M").has_duplicates)
        self.assertAlmostEqual(returns.iloc[0], .041)
        self.assertAlmostEqual(returns.iloc[-1], .026)

    def test_august_correction_preserves_raw_export_and_returns(self):
        raw = _read_signals(DEEP_HISTORY_DIR / self.spec.signal_file)
        signals, returns = load_deep_history(self.spec)
        date = pd.Timestamp("2026-08-31")
        self.assertEqual(raw.loc[date, "target_weights"], {"BIL": 1.0})
        self.assertEqual(signals.loc[date, "target_weights"], {"UPRO": .25, "ERX": .25, "PDBC": .25, "BIL": .25})
        self.assertEqual(signals.loc[date, "regime"], "Risk-Off")
        pd.testing.assert_frame_equal(signals.drop(date), raw.loc[signals.index].drop(date))
        raw_returns = _read_monthly_returns(DEEP_HISTORY_DIR / self.spec.returns_file).loc[returns.index]
        pd.testing.assert_series_equal(returns, raw_returns)

    def test_correction_changes_tax_path_not_pre_tax_returns(self):
        signals, returns = load_deep_history(self.spec)
        old_signals = signals.copy(deep=True)
        old_signals.at[pd.Timestamp("2026-08-31"), "target_weights"] = {"BIL": 1.0}
        corrected_model = deep_history_model_input(self.spec)
        with patch("haa.deep_history.load_deep_history", return_value=(old_signals, returns)):
            old_model = deep_history_model_input(self.spec)
        results = [run_backtest(m.decisions, m.monthly_prices, 100000, tax_enabled=True, benchmark_asset=m.benchmark_asset)
                   for m in (corrected_model, old_model)]
        corrected, old = results
        pd.testing.assert_series_equal(corrected.monthly.pre_tax_value, old.monthly.pre_tax_value)
        self.assertFalse(corrected.tax_events.equals(old.tax_events))
        self.assertEqual(corrected.audit.loc[pd.Timestamp("2026-08-31"), "target_weights"],
                         {"UPRO": .25, "ERX": .25, "PDBC": .25, "BIL": .25})

    def test_supplied_return_reconciliation_tax_and_both_benchmarks(self):
        _, returns = load_deep_history(self.spec)
        for benchmark in (SP500_TOTAL_RETURN_BENCHMARK, GLOBAL_TOTAL_RETURN_BENCHMARK):
            model = deep_history_model_input(self.spec, benchmark)
            result = run_backtest(model.decisions, model.monthly_prices, 100000, tax_enabled=True, benchmark_asset=model.benchmark_asset)
            self.assertTrue(result.monthly.index.equals(returns.index))
            self.assertAlmostEqual(result.monthly.pre_tax_value.iloc[-1] / (100000 * (1 + returns).prod()), 1.0)
            self.assertFalse(result.tax_events.empty)
            self.assertLessEqual(result.monthly.after_tax_value.iloc[-1], result.monthly.pre_tax_value.iloc[-1])

    def test_blend_runs_with_existing_sleeve(self):
        models = {key: (weight, deep_history_model_input(DEEP_HISTORY_SPECS[key]))
                  for key, weight in (("chimeric", .3), ("century_momentum", .7))}
        result = run_portfolio_backtest(models, 100000, tax_enabled=True)
        self.assertEqual(len(result.monthly), 535)
        self.assertEqual(len(result.sleeve_returns.columns), 2)

    def test_usable_intramonth_signals_rejected_not_deduplicated(self):
        signals, returns = load_deep_history(self.spec)
        extra = signals.iloc[[0]].copy()
        extra.index = pd.DatetimeIndex(["1982-02-25"])
        multiple = pd.concat([signals, extra]).sort_index()
        with patch("haa.deep_history.load_deep_history", return_value=(multiple, returns)):
            with self.assertRaisesRegex(ValueError, "duplicate calendar-month signals"):
                deep_history_model_input(self.spec)

    def test_missing_month_rejected_not_bridged(self):
        signals, returns = load_deep_history(self.spec)
        with patch("haa.deep_history.load_deep_history", return_value=(signals.drop(signals.index[10]), returns)):
            with self.assertRaisesRegex(ValueError, "gaps"):
                deep_history_model_input(self.spec)


if __name__ == "__main__":
    unittest.main()
