import pytest

from haa.model_catalog import MODEL_CATALOG
from haa.strategies import BAAG4Aggressive, HAASimple, InflationCompassStandard, OrthogonalAlpha, VAAG4
from haa.validation import ValidationProfile, profile_for, research_unavailable_reason


@pytest.mark.parametrize("strategy_class, profile_id", [
    (HAASimple, "haa-simple"),
    (InflationCompassStandard, "inflation-compass-standard"),
    (OrthogonalAlpha, "orthogonal-alpha"),
    (VAAG4, "vaa-g4-t1-b1"),
    (BAAG4Aggressive, "baa-g4-aggressive"),
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


def test_every_catalogued_strategy_declares_research_support_or_explicit_limitation():
    for definition in MODEL_CATALOG:
        profile = profile_for(definition.model_class)
        reason = research_unavailable_reason(definition.model_class)
        assert (profile is not None) != (reason is not None), definition.label
    unsupported = {d.label for d in MODEL_CATALOG if research_unavailable_reason(d.model_class)}
    assert unsupported == {"A-RVol Shifter V3 Cash-Only", "A-RVol Shifter V3 Cash-Only Israel"}


def test_new_monthly_profiles_do_not_enable_tuning_or_change_variants():
    from haa.strategies import ChimericAssetAllocation, ChimericFullRetreat, MomentumCorrelationTriplet, RVolShifterCashOnly
    for model in (ChimericAssetAllocation, ChimericFullRetreat, MomentumCorrelationTriplet):
        profile = profile_for(model)
        assert profile.execution.rebalance_frequency == "monthly"
        assert "parameter_sweep" not in profile.applicable_tests
        assert all(not p.candidate_values for p in profile.published_parameters)
    assert profile_for(ChimericAssetAllocation).profile_id != profile_for(ChimericFullRetreat).profile_id
    assert profile_for(RVolShifterCashOnly) is None
    assert "opening prices" in research_unavailable_reason(RVolShifterCashOnly())


@pytest.mark.parametrize("model_name", ["ChimericAssetAllocation", "ChimericFullRetreat", "MomentumCorrelationTriplet"])
def test_new_profiles_run_research_with_benchmark_and_preserve_signals(model_name):
    from dataclasses import replace
    import numpy as np
    import pandas as pd
    from haa import strategies
    from haa.data import to_month_end
    from haa.market_sessions import us_equity_sessions
    from haa.validation import ValidationInput, run_deterministic_validation

    strategy = getattr(strategies, model_name)()
    dates = us_equity_sessions("2021-01-04", "2024-12-31")
    t = np.arange(len(dates))
    # Match app preparation: retain the benchmark even when it is not a signal asset.
    assets = tuple(dict.fromkeys((*strategy.data_assets, strategy.benchmark_asset)))
    daily = pd.DataFrame({
        asset: 100 * np.exp(np.cumsum(0.0002 + j * 0.00002 + 0.009 * np.sin(t / (7 + j)) + 0.003 * np.cos(t / 19)))
        for j, asset in enumerate(assets)
    }, index=dates)
    decisions = strategy.decisions(daily)
    original = decisions.copy(deep=True)
    profile = profile_for(strategy)
    profile = replace(profile, bootstrap=replace(profile.bootstrap, simulations=20))
    inputs = ValidationInput(strategy.name, decisions, to_month_end(daily), daily,
                             strategy.benchmark_asset, profile, strategy=strategy, signal_prices=daily)
    report = run_deterministic_validation(inputs, 10_000)
    for test, count in (("baseline", 1), ("execution_delay", 3), ("transaction_cost", 3), ("israeli_tax", 1)):
        rows = report.scenarios.loc[report.scenarios.test == test]
        assert len(rows) == count
        assert set(rows.status) == {"complete"}
    assert not set(report.scenarios.test) & {"parameter_sweep", "rebalance_shift", "signal_perturbation"}
    pd.testing.assert_frame_equal(decisions, original)
