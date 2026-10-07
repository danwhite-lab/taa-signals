import unittest

import numpy as np
import pandas as pd

from haa.metrics import performance_metrics


class SortinoTests(unittest.TestCase):
    def metrics(self, returns, frequency=12):
        values = pd.Series(100 * np.cumprod(1 + np.asarray(returns)))
        return performance_metrics(values, 100, periods_per_year=frequency)

    def test_zero_target_uses_all_observations(self):
        returns = [.10, -.05, 0., -.02]
        expected = np.mean(returns) * 12 / np.sqrt((.05**2 + .02**2) / 4 * 12)
        self.assertAlmostEqual(self.metrics(returns)['Sortino'], expected)

    def test_one_negative_observation_is_sufficient(self):
        returns = [.10, -.05, .02]
        expected = np.mean(returns) * 252 / np.sqrt(.05**2 / 3 * 252)
        self.assertAlmostEqual(self.metrics(returns, 252)['Sortino'], expected)

    def test_identical_negative_returns_have_nonzero_downside(self):
        self.assertAlmostEqual(self.metrics([-.05, -.05])['Sortino'], -np.sqrt(12))

    def test_no_negative_returns_is_unavailable(self):
        for returns in ([.10, .02], [0., 0.]):
            self.assertTrue(np.isnan(self.metrics(returns)['Sortino']))

    def test_empty_history(self):
        self.assertEqual(performance_metrics(pd.Series(dtype=float), 100), {})


if __name__ == '__main__':
    unittest.main()
