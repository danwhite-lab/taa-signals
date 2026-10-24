"""Frozen ILS scenarios are isolated from actual funds and existing USD histories."""
import hashlib

import pandas as pd
import pytest

from haa import deep_history as deep
from haa.comparison import compare_models
from haa.engine import run_backtest
from haa.portfolio_backtest import run_portfolio_backtest
from haa.portfolio_config import deep_history_portfolio_config

KEYS = ("research_ta125_x3_ils", "research_nasdaq100_x3_ils")
USD_BASELINE = {
    "buy_and_hold_gld": "eeb8c85d2c0271ec0f26a3356f5eaab120860badf0201e57230dd963a2003b29",
    "buy_and_hold_global": "e8373fb82414120663ab4441f3a8f543f4ebdb002ce94d2214801f9f0394a8da",
    "buy_and_hold_ief": "b9e5061475d8ff23802a8f2a9fc1b7bc4470e44179dd2e73c8620a240e777260",
    "buy_and_hold_sp500": "234f18fde50f27bda46ca7c9293957260bf8186c9b09a1ded4603f2ad8e2fdea",
    "century_momentum": "92359ecefe04cd81079416036ab90b61a6ec295c4d0ed119462f01ca7cc1663b",
    "chimeric": "bb417d63c9ea24657d869bebc8c0b7bc369a997dc112812f15cd52d0bee3de5d",
    "gem": "645125ae6989ab717cfa36f9f0941a33cba7c29bd13c20d67e4069267fed2d5a",
    "haa_simple": "a1366a3c7b4b4cb858e9c54b96d58c3602b27ae5c33a76f77e1683dfe6e1c036",
    "inflation_compass": "08e3fd963c82b1e507a52c7ee43a03d76a8e5ecb7fd695e0364484527d2f6340",
    "rvol_daily": "8f020e4c74202e99dcffb9c9c3e56fef484abd08b68afc96daf781b74d4a8e03",
    "rvol_synthetic": "1e466f1e8158d7ca62be2567d2bf0b69ca96089e9562fd6a88d53cbef6c83309"
}


@pytest.mark.parametrize("key", KEYS)
def test_complete_decimal_ils_history_and_standalone_ledger(key):
    spec = deep.ALL_DEEP_HISTORY_SPECS[key]
    assert spec.currency == "ILS" and "RESEARCH ONLY" in spec.label
    assert spec.caveat == deep.ILS_RESEARCH_BANNER
    assert spec.completed_only and spec.usable_through == "2026-09-30"
    _, returns = deep.load_deep_history(spec)
    assert len(returns) == 273
    assert returns.index.equals(pd.date_range("2004-01-31", "2026-09-30", freq="ME"))
    model = deep.deep_history_model_input(spec)
    assert model.execution_currency == "ILS"
    assert model.benchmark_asset == deep.DEEP_HISTORY_BENCHMARKS[spec.benchmark_key].asset_id
    assert model.decisions.attrs["single_strategy_only"]
    expected_first = .09111650 if key == KEYS[0] else .06596589
    assert returns.iloc[0] == expected_first
    assert model.monthly_prices[spec.holding_asset].iloc[1] / 100 - 1 == pytest.approx(expected_first)
    result = run_backtest(model.decisions, model.monthly_prices, 1000., benchmark_asset=model.benchmark_asset, tax_enabled=True)
    assert len(result.monthly) == 273
    assert result.monthly.pre_tax_value.iloc[-1] == pytest.approx(1000*(1+returns).prod())
    assert result.tax_events.empty  # No sales or fabricated final liquidation.
    with pytest.raises(ValueError, match="single-strategy"):
        run_portfolio_backtest({key: (1., model)}, 1000., monthly_contribution=100.)
    usd = deep.deep_history_model_input(deep.DEEP_HISTORY_SPECS["buy_and_hold_sp500"])
    with pytest.raises(ValueError, match="single-strategy"):
        compare_models({key: model, "USD": usd}, 1000.)
    with pytest.raises(ValueError, match="standalone"):
        deep.validate_deep_history_context([spec, deep.DEEP_HISTORY_SPECS["buy_and_hold_sp500"]])
    for benchmark in (deep.SP500_TOTAL_RETURN_BENCHMARK, deep.DEEP_HISTORY_BENCHMARKS["nasdaq100_ils" if key == KEYS[0] else "ta125_ils"]):
        with pytest.raises(ValueError, match="ILS benchmark"):
            deep.deep_history_model_input(spec, benchmark)
    for kw in ({"fx_conversion": True}, {"inflation_adjustment": True}):
        with pytest.raises(ValueError, match="FX conversion"):
            deep.deep_history_model_input(spec, **kw)
    saved = {"version": 1, "sleeves": [{"model": key, "weight": 100}], "total_ils": 3500, "ils_per_usd": 3.5}
    with pytest.raises(ValueError, match="saved-FX"):
        deep_history_portfolio_config(saved, {}, deep.ALL_DEEP_HISTORY_SPECS)
    assert key in deep.deep_history_options(1) and key not in deep.deep_history_options(2)


@pytest.mark.parametrize("problem", ["gap", "duplicate", "nan"])
def test_ils_import_fails_closed_on_bad_source(tmp_path, monkeypatch, problem):
    spec = deep.ALL_DEEP_HISTORY_SPECS[KEYS[0]]
    frame = pd.read_csv(deep.DEEP_HISTORY_DIR / spec.returns_file)
    if problem == "gap": frame = frame.drop(index=2)
    elif problem == "duplicate": frame = pd.concat([frame, frame.iloc[[0]]])
    else: frame.loc[2, "nominalReturn"] = float("nan")
    frame.to_csv(tmp_path / spec.returns_file, index=False)
    monkeypatch.setattr(deep, "DEEP_HISTORY_DIR", tmp_path)
    with pytest.raises(ValueError): deep.load_deep_history(spec)


def test_tidy_return_units_are_decimals_not_percentage_points(tmp_path):
    path = tmp_path / "decimal.csv"
    path.write_text("year,month,nominalReturn\n2004,1,0.0123\n")
    returns = deep._read_long_monthly_returns(path)
    assert returns.iloc[0] == .0123
    assert 1000 * (1 + returns.iloc[0]) == pytest.approx(1012.3)


@pytest.mark.parametrize("label", ["Buy and Hold TA-125 x3 Israel", "Buy and Hold Nasdaq-100 x3 Monthly Israel"])
def test_actual_only_funds_are_never_automatically_extended(label):
    from haa.model_catalog import definition_for_label
    model = definition_for_label(label).model_class
    assert model.actual_history_only
    assert not any(spec.holding_asset in model.data_assets for spec in deep.DEEP_HISTORY_SINGLE_SPECS.values())
    payload = {"version": 1, "total_ils": 3500, "ils_per_usd": 3.5, "sleeves": [{"model": label, "weight": 100}]}
    with pytest.raises(ValueError, match="No compatible bundled Deep History"):
        deep_history_portfolio_config(payload, {label: model}, deep.ALL_DEEP_HISTORY_SPECS)


@pytest.mark.parametrize("key", USD_BASELINE)
def test_existing_usd_frames_and_engine_outputs_are_byte_identical(key):
    model = deep.deep_history_model_input(deep.ALL_DEEP_HISTORY_SPECS[key])
    result = run_backtest(model.decisions, model.monthly_prices, 10000., benchmark_asset=model.benchmark_asset,
        daily_prices=model.daily_prices, start=model.monthly_prices.index[-25], tax_enabled=key != "rvol_daily", monthly_contribution=100.)
    serialized = model.decisions.to_csv() + model.monthly_prices.to_csv()
    for name in ("monthly", "daily", "audit", "tax_events"):
        value = getattr(result, name, None)
        if value is not None: serialized += name + value.to_csv()
    assert hashlib.sha256(serialized.encode()).hexdigest() == USD_BASELINE[key]
