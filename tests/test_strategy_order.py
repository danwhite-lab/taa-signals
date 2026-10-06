import unittest

from haa.model_catalog import MODEL_CATALOG, implementations, resolve, strategies, variants


class StrategyOrderTests(unittest.TestCase):
    def test_names_are_alphabetical_without_removing_models(self):
        expected = tuple(sorted({item.strategy for item in MODEL_CATALOG}, key=str.casefold))
        self.assertEqual(strategies(), expected)
        self.assertEqual(strategies()[0], "A-RVol Shifter")

    def test_existing_variants_and_implementations_are_unchanged(self):
        self.assertEqual(variants("Inflation Compass"), ("Standard", "Fast (40-day)", "Steady (80-day)"))
        self.assertEqual(implementations("HAA", "Simple"), ("Original", "Israel"))
        for item in MODEL_CATALOG:
            self.assertEqual(resolve(item.strategy, item.variant, item.implementation), item)
