import pytest

from haa.model_catalog import MODEL_CATALOG, definition_for_label, implementations, resolve, strategies, variants
from haa.strategies import HAASimpleIsrael, InflationCompassFast, InflationCompassFastIsrael, InflationCompassStandard, InflationCompassStandardIsrael, InflationCompassSteadyIsrael


def test_catalog_exposes_every_stable_model_once():
    labels = [item.label for item in MODEL_CATALOG]
    assert len(labels) == len(set(labels))
    assert definition_for_label("HAA-Simple Israel").model_class is HAASimpleIsrael
    assert definition_for_label("HAA-Simple Israel").execution_currency == "ILS"
    assert definition_for_label("HAA-Simple").execution_currency == "USD"


def test_israel_implementations_are_available_for_simple_haa_and_inflation_compass():
    assert implementations("HAA", "Simple") == ("Original", "Israel")
    assert implementations("HAA", "HAA 4") == ("Original",)
    assert implementations("Inflation Compass", "Steady (80-day)") == ("Original", "Israel")
    assert implementations("Inflation Compass", "Standard") == ("Original", "Israel")
    assert implementations("Inflation Compass", "Fast (40-day)") == ("Original", "Israel")


def test_catalog_selection_resolves_existing_stable_model_class():
    assert strategies() == ("HAA", "Inflation Compass")
    assert "HAA 4" in variants("HAA")
    assert resolve("Inflation Compass", "Standard", "Original").model_class is InflationCompassStandard
    assert resolve("Inflation Compass", "Fast (40-day)", "Original").model_class is InflationCompassFast
    assert resolve("Inflation Compass", "Steady (80-day)", "Israel").model_class is InflationCompassSteadyIsrael
    assert resolve("Inflation Compass", "Standard", "Israel").model_class is InflationCompassStandardIsrael
    assert resolve("Inflation Compass", "Fast (40-day)", "Israel").model_class is InflationCompassFastIsrael
    assert resolve("Inflation Compass", "Standard", "Israel").execution_currency == "ILS"
    assert not resolve("Inflation Compass", "Standard", "Israel").model_class.backtest_available
    assert resolve("HAA", "Simple", "Israel").model_class is HAASimpleIsrael
    with pytest.raises(ValueError, match="Unknown model selection"):
        resolve("HAA", "HAA 4", "Israel")
