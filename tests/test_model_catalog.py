import pytest

from haa.model_catalog import MODEL_CATALOG, definition_for_label, implementations, resolve, strategies, variants
from haa.strategies import BAAG4Aggressive, BAAG4AggressiveIsrael, CenturyMomentum, CenturyMomentumIsrael, GrowthInflationConcentrated, GrowthInflationConcentratedIsrael, GrowthInflationDiversified, HAA4Israel, HAASimpleIsrael, InflationCompassFast, InflationCompassFastIsrael, InflationCompassStandard, InflationCompassStandardIsrael, InflationCompassSteadyIsrael, OrthogonalAlpha, TA125SmartMomentum, VAAG4


def test_catalog_exposes_every_stable_model_once():
    labels = [item.label for item in MODEL_CATALOG]
    assert len(labels) == len(set(labels))
    assert definition_for_label("HAA-Simple Israel").model_class is HAASimpleIsrael
    assert definition_for_label("HAA-Simple Israel").execution_currency == "ILS"
    assert definition_for_label("HAA-Simple").execution_currency == "USD"


def test_israel_implementations_are_available_for_simple_haa_and_inflation_compass():
    assert implementations("HAA", "Simple") == ("Original", "Israel")
    assert implementations("HAA", "HAA 4") == ("Original", "Israel")
    assert implementations("Inflation Compass", "Steady (80-day)") == ("Original", "Israel")
    assert implementations("Inflation Compass", "Standard") == ("Original", "Israel")
    assert implementations("Inflation Compass", "Fast (40-day)") == ("Original", "Israel")


def test_catalog_selection_resolves_existing_stable_model_class():
    assert strategies() == ("HAA", "Inflation Compass", "Buy and Hold", "Century Momentum", "Growth-Inflation Sector Timing", "VAA", "BAA", "Orthogonal Alpha")
    assert "HAA 4" in variants("HAA")
    assert resolve("Inflation Compass", "Standard", "Original").model_class is InflationCompassStandard
    assert resolve("Inflation Compass", "Fast (40-day)", "Original").model_class is InflationCompassFast
    assert resolve("Inflation Compass", "Steady (80-day)", "Israel").model_class is InflationCompassSteadyIsrael
    assert resolve("Inflation Compass", "Standard", "Israel").model_class is InflationCompassStandardIsrael
    assert resolve("Inflation Compass", "Fast (40-day)", "Israel").model_class is InflationCompassFastIsrael
    assert resolve("Inflation Compass", "Standard", "Israel").execution_currency == "ILS"
    assert not resolve("Inflation Compass", "Standard", "Israel").model_class.backtest_available
    assert resolve("HAA", "Simple", "Israel").model_class is HAASimpleIsrael
    assert resolve("HAA", "HAA 4", "Israel").model_class is HAA4Israel
    assert resolve("HAA", "HAA 4", "Israel").execution_currency == "ILS"
    momentum = resolve("Buy and Hold", "TA-125 Smart Momentum", "Migdal MTF TA-125 Smart Momentum")
    assert momentum.model_class is TA125SmartMomentum
    assert momentum.execution_currency == "ILS"
    assert momentum.strategy_mode == "buy_and_hold"
    assert momentum.signal_mode == "internal"
    assert momentum.suggested_max_weight == 0.20
    assert variants("Century Momentum") == ("Standard",)
    assert implementations("Century Momentum", "Standard") == ("Original", "Israel")
    assert resolve("Century Momentum", "Standard", "Original").model_class is CenturyMomentum
    assert resolve("Century Momentum", "Standard", "Israel").model_class is CenturyMomentumIsrael
    assert resolve("Growth-Inflation Sector Timing", "Concentrated", "Original").model_class is GrowthInflationConcentrated
    assert resolve("Growth-Inflation Sector Timing", "Concentrated", "Israel").model_class is GrowthInflationConcentratedIsrael
    assert resolve("Growth-Inflation Sector Timing", "Diversified", "Original").model_class is GrowthInflationDiversified
    assert resolve("VAA", "G4 (T1/B1)", "Original").model_class is VAAG4
    assert resolve("BAA", "G4 (Aggressive)", "Original").model_class is BAAG4Aggressive
    assert resolve("BAA", "G4 (Aggressive)", "Israel").model_class is BAAG4AggressiveIsrael
    assert resolve("BAA", "G4 (Aggressive)", "Israel").execution_currency == "ILS"
    assert resolve("BAA", "G4 (Aggressive)", "Israel").model_class.backtest_available
    assert variants("Orthogonal Alpha") == (None,)
    assert implementations("Orthogonal Alpha", None) == ("Standard",)
    assert resolve("Orthogonal Alpha", None, "Standard").model_class is OrthogonalAlpha
    with pytest.raises(ValueError, match="Unknown model selection"):
        resolve("HAA", "HAA 4", "Israel")



def test_inflation_compass_variants_use_standard_fast_steady_order():
    assert variants("Inflation Compass") == ("Standard", "Fast (40-day)", "Steady (80-day)")
