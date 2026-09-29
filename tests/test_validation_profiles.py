import pytest

from haa.model_catalog import MODEL_CATALOG
from haa.strategies import HAASimple, InflationCompassStandard, OrthogonalAlpha, VAAG4
from haa.validation import ValidationProfile, profile_for


@pytest.mark.parametrize("strategy_class, profile_id", [
    (HAASimple, "haa-simple"),
    (InflationCompassStandard, "inflation-compass-standard"),
    (OrthogonalAlpha, "orthogonal-alpha"),
    (VAAG4, "vaa-g4-t1-b1"),
])
def test_research_profiles_are_discoverable_from_strategy_classes_and_instances(strategy_class, profile_id):
    assert profile_for(strategy_class).profile_id == profile_id
    assert profile_for(strategy_class()).profile_id == profile_id


def test_profile_keeps_published_baseline_and_research_candidates_separate():
    profile = profile_for(InflationCompassStandard)
    window = next(item for item in profile.published_parameters if item.key == "momentum_window")
    assert window.published_value == 60
    assert window.candidate_values == (40, 50, 60, 70, 80)
    assert "parameter_sweep" in profile.applicable_tests
    assert "signal_perturbation" in profile.applicable_tests
    assert "block_bootstrap" in profile.applicable_tests


def test_historical_formula_without_declared_variants_cannot_be_swept():
    profile = profile_for(HAASimple)
    formula = profile.published_parameters[0]
    assert formula.key == "momentum_formula"
    assert formula.candidate_values == ()
    assert "parameter_sweep" not in profile.applicable_tests


def test_profile_is_immutable_and_unprofiled_strategies_are_explicit():
    profile = profile_for(VAAG4)
    with pytest.raises(Exception):
        profile.data_confidence = "high"

    class Unprofiled:
        pass

    assert profile_for(Unprofiled) is None


def test_every_catalogued_strategy_declares_a_validation_profile():
    missing = [definition.label for definition in MODEL_CATALOG if profile_for(definition.model_class) is None]
    assert missing == []
