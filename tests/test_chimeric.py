import unittest

import numpy as np
import pandas as pd

from haa.data import to_month_end
from haa.engine import run_backtest
from haa.market_sessions import us_equity_sessions
from haa.model_catalog import resolve, strategies
from haa.strategies import ChimericAssetAllocation


def fixture():
    dates = us_equity_sessions("2021-01-04", "2024-12-31")
    t = np.arange(len(dates))
    return pd.DataFrame({
        asset: 100 * np.exp(np.cumsum(0.0002 + j * 0.00002 + 0.009 * np.sin(t / (7 + j)) + 0.003 * np.cos(t / 19)))
        for j, asset in enumerate((*ChimericAssetAllocation.data_assets, "SPY"))
    }, index=dates)


class TestChimeric(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.prices = fixture()
        cls.model = ChimericAssetAllocation()
        cls.decisions = cls.model.decisions(cls.prices)

    def allocation(self, order, tip=1, bad=(), defense="IEF"):
        scores = pd.Series({a: 10 - i for i, a in enumerate(order)})
        momentum = pd.Series(1.0, index=self.model.data_assets)
        momentum["TIP"] = tip
        momentum.loc[list(bad)] = 0
        momentum[defense] = 2
        return self.model.allocate(scores, momentum)

    def test_top_four_without_refilling(self):
        order = self.model.offensive_assets
        self.assertEqual(self.allocation(order, bad=("TQQQ",)), {"UPRO": .25, "IEF": .25, "EURL": .25, "EDC": .25})

    def test_partial_retains_best_equity_and_top_three_diversifiers(self):
        order = ("PDBC", "UPRO", "UGL", "ERX", "TQQQ", "EURL", "EDC", "TNA", "EDV", "TMF")
        self.assertEqual(self.allocation(order, tip=-1, defense="SGOV"), {"PDBC": .25, "UPRO": .25, "UGL": .25, "SGOV": .25})

    def test_partial_does_not_promote_best_equity_outside_top_four(self):
        order = (*self.model.diversifier_assets, *self.model.equity_assets)
        self.assertEqual(self.allocation(order, tip=-1), {"PDBC": .25, "ERX": .25, "UGL": .25, "IEF": .25})

    def test_zero_tip_is_normal_and_nonpositive_own_momentum_replaced(self):
        self.assertEqual(self.allocation(self.model.offensive_assets, tip=0, bad=("UPRO", "TQQQ", "EURL", "EDC")), {"IEF": 1.0})

    def test_full_warmup_actual_history_monthly_weights(self):
        self.assertGreaterEqual(len(to_month_end(self.prices.loc[:self.decisions.index[0]])), 13)
        self.assertLess(len(self.decisions), 50)
        for weights in self.decisions.target_weights:
            self.assertEqual(sum(weights.values()), 1)
            self.assertTrue(all(w % .25 == 0 for w in weights.values()))
        self.assertNotIn("BIL", self.model.data_assets)

    def test_independent_nine_signal_calculation(self):
        row = self.decisions.iloc[-1]
        date = row.name
        daily = self.prices.loc[:date, self.model.offensive_assets]
        returns = daily.pct_change(fill_method=None).iloc[-252:]
        rho = returns.corrwith(returns.mean(axis=1))
        monthly = to_month_end(self.prices.loc[:date])
        raw = pd.DataFrame(index=self.model.offensive_assets)
        for n in (63, 126, 252):
            raw[f"tr_{n}"] = daily.iloc[-1] / daily.iloc[-1-n] - 1
            changes = np.log(daily.iloc[-n-1:]).diff().iloc[1:]
            raw[f"pe_{n}"] = changes.sum() / changes.abs().sum()
        for w in (3, 6, 12):
            raw[f"pma_{w}"] = monthly.iloc[-1] / monthly.iloc[-w:].mean() - 1
        scores = raw.div(1 + rho, axis=0).rank(method="average", pct=True).mean(axis=1)
        for asset in self.model.offensive_assets:
            self.assertAlmostEqual(row[f"{asset}_score"], scores[asset])
            self.assertAlmostEqual(row[f"{asset}_correlation"], rho[asset])
            for key in raw:
                self.assertAlmostEqual(row[f"{asset}_{key}"], raw.loc[asset, key])

    def test_no_future_prices(self):
        cut = self.decisions.index[8]
        changed = self.prices.copy()
        changed.loc[changed.index > cut] *= 4
        pd.testing.assert_frame_equal(self.decisions.loc[:cut], self.model.decisions(changed).loc[:cut])

    def test_missing_session_or_quote_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing US equity"):
            self.model.decisions(self.prices.drop(self.prices.index[400]))
        changed = self.prices.copy()
        changed.loc[changed.index[400], "ERX"] = np.nan
        with self.assertRaisesRegex(ValueError, "complete, finite"):
            self.model.decisions(changed)

    def test_later_inception_delays_signals(self):
        changed = self.prices.copy()
        changed.loc[changed.index < "2022-01-03", "SGOV"] = np.nan
        later = self.model.decisions(changed)
        self.assertGreater(later.index[0], self.decisions.index[0])
        self.assertGreaterEqual(later.index[0], pd.Timestamp("2023-01-01"))

    def test_flat_path_rejected_not_invented(self):
        changed = self.prices.copy()
        changed["UPRO"] = 100.0
        with self.assertRaisesRegex(ValueError, "Undefined Chimeric"):
            self.model.decisions(changed)

    def test_preview_and_completed_month(self):
        today = pd.Timestamp.now(tz="UTC").tz_localize(None)
        self.assertTrue(all(self.decisions.index.to_period("M") < today.to_period("M")))
        preview = self.model.decisions(self.prices.loc[:"2024-08-15"], include_current_month=True)
        self.assertEqual(preview.index[-1], pd.Timestamp("2024-08-15"))

    def test_monthly_engine_and_tax_integration(self):
        result = run_backtest(self.decisions, to_month_end(self.prices), 100000,
                              transaction_cost=.001, tax_enabled=True, daily_prices=self.prices)
        self.assertFalse(result.monthly.empty)
        self.assertTrue((result.audit.execution_date > result.audit.index).all())
        self.assertTrue((result.monthly.after_tax_value <= result.monthly.pre_tax_value + 1e-6).all())
        self.assertFalse(result.tax_events.empty)

    def test_catalog_and_tie_convention(self):
        self.assertIs(resolve("Chimeric Asset Allocation", "Standard", "Published rules (experimental)").model_class, ChimericAssetAllocation)
        self.assertEqual(strategies(), tuple(sorted(strategies(), key=str.casefold)))
        tied = pd.Series(1.0, index=self.model.offensive_assets)
        momenta = pd.Series(1.0, index=self.model.data_assets)
        momenta.loc[list(self.model.offensive_assets)] = 0
        self.assertEqual(self.model.allocate(tied, momenta), {"IEF": 1.0})


if __name__ == "__main__":
    unittest.main()
