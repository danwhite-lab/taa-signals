import pandas as pd

from haa.deep_history import DEEP_HISTORY_DIR, DEEP_HISTORY_SPECS, SP500_TOTAL_RETURN_BENCHMARK, GLOBAL_TOTAL_RETURN_BENCHMARK, _read_benchmark_returns, _read_monthly_returns, deep_history_model_input, load_deep_history
from haa.engine import run_backtest
from haa.metrics import rolling_annualized_returns, worst_rolling_annualized_return
from haa.portfolio_backtest import run_portfolio_backtest


def test_bundled_proxy_histories_align_without_invented_months():
    for spec in DEEP_HISTORY_SPECS.values():
        if spec.buy_and_hold:
            continue
        signals, returns = load_deep_history(spec)
        assert not signals.index.has_duplicates
        assert not returns.index.has_duplicates
        assert (signals.index + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1)).isin(returns.index).all()


def test_deep_history_uses_the_long_sp500_total_return_proxy():
    benchmark_returns = _read_benchmark_returns(SP500_TOTAL_RETURN_BENCHMARK)
    assert benchmark_returns.index.min() == pd.Timestamp("1871-02-28")
    assert benchmark_returns.index.max() == pd.Timestamp("2026-09-30")
    model = deep_history_model_input(DEEP_HISTORY_SPECS["century_momentum"])
    assert model.benchmark_asset == SP500_TOTAL_RETURN_BENCHMARK.asset_id
    assert model.monthly_prices.index.min() == pd.Timestamp("1928-03-31")
    assert model.monthly_prices.index.max() == pd.Timestamp("2026-09-30")
    assert model.monthly_prices[SP500_TOTAL_RETURN_BENCHMARK.asset_id].notna().all()


def test_buy_and_hold_sp500_is_available_as_a_deep_history_sleeve():
    model = deep_history_model_input(DEEP_HISTORY_SPECS["buy_and_hold_sp500"])
    result = run_backtest(model.decisions, model.monthly_prices, 100_000, benchmark_asset=model.benchmark_asset)
    assert result.monthly.index.min() == pd.Timestamp("1871-02-28")
    assert result.monthly["pre_tax_value"].equals(result.monthly["benchmark_value"])


def test_global_usd_source_is_complete_and_preserves_exported_values():
    returns = _read_benchmark_returns(GLOBAL_TOTAL_RETURN_BENCHMARK)
    assert len(returns) == 681
    assert returns.index.equals(pd.date_range("1970-01-31", "2026-09-30", freq="ME"))
    assert abs(returns.iloc[0] - (-0.0787)) < 1e-12
    assert abs(returns.iloc[-1] - (-0.0119)) < 1e-12
    frame = pd.read_csv(DEEP_HISTORY_DIR / GLOBAL_TOTAL_RETURN_BENCHMARK.returns_file)
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    differences = ((1 + frame[months] / 100).prod(axis=1) - 1) * 100 - frame["Return"]
    assert differences.abs().max() < 0.02


def test_buy_and_hold_sleeves_keep_independent_benchmark_returns():
    for key, benchmark in [("buy_and_hold_global", SP500_TOTAL_RETURN_BENCHMARK), ("buy_and_hold_sp500", GLOBAL_TOTAL_RETURN_BENCHMARK), ("buy_and_hold_global", GLOBAL_TOTAL_RETURN_BENCHMARK)]:
        spec = DEEP_HISTORY_SPECS[key]
        model = deep_history_model_input(spec, benchmark)
        assert model.decisions.iloc[0]["target_weights"] == {spec.holding_asset: 1.0}
        assert model.monthly_prices.index.min() == pd.Timestamp("1969-12-31")
        result = run_backtest(model.decisions, model.monthly_prices, 100_000, benchmark_asset=model.benchmark_asset, tax_enabled=True)
        assert len(result.monthly) == 681
        expected_benchmark = _read_benchmark_returns(benchmark).loc["1970-01-31":"2026-09-30"]
        expected_value = 100_000 * (1 + expected_benchmark).prod()
        assert abs(result.monthly["benchmark_value"].iloc[-1] / expected_value - 1) < 1e-10
        if spec.holding_asset == benchmark.asset_id:
            assert result.monthly["pre_tax_value"].equals(result.monthly["benchmark_value"])
        else:
            assert not result.monthly["pre_tax_value"].equals(result.monthly["benchmark_value"])
        assert result.tax_events.empty


def test_return_reader_rejects_duplicate_months(tmp_path):
    path = tmp_path / "duplicate.csv"
    path.write_text("Year,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec\n1970,1,,,,,,,,,,,\n1970,2,,,,,,,,,,,\n")
    try:
        _read_monthly_returns(path)
    except ValueError as error:
        assert "duplicate" in str(error)
    else:
        raise AssertionError("Duplicate source months must not be silently discarded")


def test_global_sleeve_blends_with_all_other_sleeves_and_tax():
    models = {key: (1 / len(DEEP_HISTORY_SPECS), deep_history_model_input(spec, GLOBAL_TOTAL_RETURN_BENCHMARK)) for key, spec in DEEP_HISTORY_SPECS.items()}
    blend = run_portfolio_backtest(models, 100_000, tax_enabled=True)
    assert len(blend.sleeve_returns.columns) == len(DEEP_HISTORY_SPECS)
    assert blend.monthly.index.min() == pd.Timestamp("1986-03-31")
    assert blend.monthly.index.max() == pd.Timestamp("2026-09-30")
    assert blend.monthly["after_tax_value"].iloc[-1] <= blend.monthly["pre_tax_value"].iloc[-1]
    assert not blend.tax_events.empty


def test_gem_returns_signals_tax_and_both_benchmarks():
    spec = DEEP_HISTORY_SPECS["gem"]
    signals, returns = load_deep_history(spec)
    assert len(signals) == len(returns) == 488
    assert returns.index.equals(pd.date_range("1986-03-31", "2026-10-31", freq="ME"))
    assert (signals.index + pd.offsets.MonthEnd(0)).equals(pd.date_range("1986-02-28", "2026-09-30", freq="ME"))
    assert {asset for weights in signals.target_weights for asset in weights} == {"SPY", "VEU", "AGG"}
    assert abs(returns.iloc[0] - 0.108) < 1e-12
    for benchmark in (SP500_TOTAL_RETURN_BENCHMARK, GLOBAL_TOTAL_RETURN_BENCHMARK):
        model = deep_history_model_input(spec, benchmark)
        result = run_backtest(model.decisions, model.monthly_prices, 100_000, benchmark_asset=model.benchmark_asset, tax_enabled=True)
        assert result.monthly.index.equals(pd.date_range("1986-03-31", "2026-09-30", freq="ME"))
        expected = 100_000 * (1 + returns.loc[:"2026-09-30"]).prod()
        assert abs(result.monthly["pre_tax_value"].iloc[-1] / expected - 1) < 1e-10
        assert result.monthly["after_tax_value"].iloc[-1] <= result.monthly["pre_tax_value"].iloc[-1]
        assert not result.tax_events.empty
        cm = deep_history_model_input(DEEP_HISTORY_SPECS["century_momentum"], benchmark)
        blend = run_portfolio_backtest({"GEM": (0.3, model), "CM": (0.7, cm)}, 100_000, tax_enabled=True)
        assert len(blend.sleeve_returns.columns) == 2
        assert blend.monthly.index.equals(result.monthly.index)


def test_rolling_annualized_returns_compound_exact_monthly_periods():
    returns = pd.Series([0.01] * 24, index=pd.date_range("2020-01-31", periods=24, freq="ME"))
    rolling = rolling_annualized_returns(returns, 1)
    assert rolling.iloc[:11].isna().all()
    assert abs(rolling.iloc[11] - ((1.01**12) - 1)) < 1e-12
    assert abs(rolling.iloc[-1] - ((1.01**12) - 1)) < 1e-12
    assert abs(worst_rolling_annualized_return(returns, 1) - ((1.01**12) - 1)) < 1e-12


def test_proxy_tax_path_and_cm_ic_blend_run():
    models = {key: deep_history_model_input(spec) for key, spec in DEEP_HISTORY_SPECS.items() if not spec.buy_and_hold}
    century = run_backtest(models["century_momentum"].decisions, models["century_momentum"].monthly_prices, 100_000, tax_enabled=True)
    assert century.monthly["after_tax_value"].iloc[-1] <= century.monthly["pre_tax_value"].iloc[-1]
    blend = run_portfolio_backtest(
        {"CM": (0.7, models["century_momentum"]), "IC": (0.3, models["inflation_compass"])},
        100_000,
        tax_enabled=True,
    )
    assert blend.monthly["after_tax_value"].iloc[-1] <= blend.monthly["pre_tax_value"].iloc[-1]
    assert not blend.tax_events.empty
    three_sleeves = run_portfolio_backtest(
        {"CM": (0.4, models["century_momentum"]), "HAA": (0.3, models["haa_simple"]), "IC": (0.3, models["inflation_compass"])},
        100_000,
        tax_enabled=True,
    )
    assert len(three_sleeves.sleeve_returns.columns) == 3
    assert three_sleeves.monthly["after_tax_value"].iloc[-1] <= three_sleeves.monthly["pre_tax_value"].iloc[-1]
    four_sleeves = run_portfolio_backtest(
        {"CM": (0.25, models["century_momentum"]), "HAA": (0.25, models["haa_simple"]), "IC": (0.25, models["inflation_compass"]), "S&P 500": (0.25, deep_history_model_input(DEEP_HISTORY_SPECS["buy_and_hold_sp500"]))},
        100_000,
    )
    assert len(four_sleeves.sleeve_returns.columns) == 4


def test_proxy_blend_aligns_last_trading_days_to_every_calendar_month():
    models = {key: deep_history_model_input(spec) for key, spec in DEEP_HISTORY_SPECS.items()}
    blend = run_portfolio_backtest(
        {"CM": (0.7, models["century_momentum"]), "IC": (0.3, models["inflation_compass"])},
        100_000,
    )
    expected = pd.date_range(blend.monthly.index.min(), blend.monthly.index.max(), freq="ME")
    assert blend.monthly.index.equals(expected)
    assert blend.monthly.index.min() == pd.Timestamp("1951-03-31")
    assert blend.monthly.index.max() == pd.Timestamp("2026-09-30")
