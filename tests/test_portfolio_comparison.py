import ast
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from test_mixed_portfolio import fixture
from haa.comparison import ModelInput
from haa.portfolio_comparison import compare_portfolios
from haa.portfolio_config import deep_history_portfolio_config


def test_daily_and_monthly_portfolios_share_dates_capital_and_benchmark():
    daily, slow, prices = fixture()
    slow = ModelInput(slow.name, slow.decisions, slow.monthly_prices, prices, "SPY", prices.copy())
    prices.loc[prices.index[6]:, "A"] = 120
    daily.daily_open_prices.loc[prices.index[6]:, "A"] = 120
    result = compare_portfolios({"mixed": {"fast": (.7, daily), "slow": (.3, slow)},
                                 "monthly": {"slow": (1., slow)}}, 1000, start="2024-02-01", drift=True)
    first, second = result.results.values()
    assert first.common_index.equals(second.common_index)
    assert first.daily.index[0] == pd.Timestamp("2024-02-01")
    assert first.daily.pre_tax_value.iloc[0] == pytest.approx(1000)
    np.testing.assert_allclose(first.daily.benchmark_value, second.daily.benchmark_value)
    with pytest.raises(ValueError, match="require initial weights"):
        compare_portfolios({"mixed": {"fast": (1., daily)}, "monthly": {"slow": (1., slow)}}, 1000)


def test_load_deep_portfolio_rejects_variant_substitution_and_preserves_payload():
    payload = {"version": 1, "total_ils": 350000, "ils_per_usd": 3.5,
               "sleeves": [{"model": "Century Momentum", "weight": 70}, {"model": "A-RVol Shifter V3 Cash-Only", "weight": 30}]}
    models = {s["model"]: object for s in payload["sleeves"]}
    specs = {"century_momentum": object, "rvol_synthetic": object}
    sleeves, capital = deep_history_portfolio_config(payload, models, specs)
    assert capital == 100000
    assert [s["model"] for s in sleeves] == ["century_momentum", "rvol_synthetic"]
    assert payload["sleeves"][0]["model"] == "Century Momentum"
    payload["sleeves"][0]["model"] = "Century Momentum Israel"
    with pytest.raises(ValueError, match="No compatible"):
        deep_history_portfolio_config(payload, {**models, "Century Momentum Israel": object}, specs)


def test_monthly_comparisons_restart_over_exact_common_periods():
    dates = pd.date_range("2023-12-31", periods=6, freq="ME")
    prices = pd.DataFrame({"A": [100, 110, 120, 100, 110, 125], "B": 100., "SPY": 100.}, index=dates)
    d1 = pd.DataFrame({"selected_asset": ["A", "A", "B", "A", "A"]}, index=dates[:-1])
    d2 = pd.DataFrame({"selected_asset": "B"}, index=dates[1:-1])
    a = ModelInput("A", d1, prices)
    b = ModelInput("B", d2, prices)
    portfolios = {"one": {"A": (1., a)}, "two": {"B": (1., b)}}
    result = compare_portfolios(portfolios, 1000, taxed=True, start=dates[2], end=dates[4])
    assert result.common_index.equals(dates[2:5])
    assert result.results["two"].monthly.pre_tax_value.iloc[0] == 1000
    # Prior January gains must not enter February's cost basis or tax state.
    assert result.results["one"].monthly.after_tax_value.iloc[0] == pytest.approx(1000*120/110)


def test_app_performance_tables_are_not_expanders_and_date_rows_are_present():
    source = Path("app.py").read_text()
    ast.parse(source)
    assert 'st.expander("Full performance table"' not in source
    assert 'st.expander("Performance and tax details"' not in source
    assert source.count("add_test_dates(summary,") == 5
