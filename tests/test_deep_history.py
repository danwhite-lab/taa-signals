import pandas as pd

from haa.deep_history import DEEP_HISTORY_DIR, DEEP_HISTORY_SPECS, US_TOTAL_MARKET_BENCHMARK, _read_monthly_returns, deep_history_model_input, load_deep_history
from haa.engine import run_backtest
from haa.metrics import rolling_annualized_returns
from haa.portfolio_backtest import run_portfolio_backtest


def test_bundled_proxy_histories_align_without_invented_months():
    for spec in DEEP_HISTORY_SPECS.values():
        signals, returns = load_deep_history(spec)
        assert not signals.index.has_duplicates
        assert not returns.index.has_duplicates
        assert (signals.index + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1)).isin(returns.index).all()


def test_deep_history_uses_the_total_market_vti_proxy_only_over_shared_months():
    benchmark_returns = _read_monthly_returns(DEEP_HISTORY_DIR / US_TOTAL_MARKET_BENCHMARK.returns_file)
    assert benchmark_returns.index.min() == pd.Timestamp("1988-01-31")
    assert benchmark_returns.index.max() == pd.Timestamp("2026-10-31")
    model = deep_history_model_input(DEEP_HISTORY_SPECS["century_momentum"])
    assert model.benchmark_asset == US_TOTAL_MARKET_BENCHMARK.asset_id
    assert model.monthly_prices.index.min() == pd.Timestamp("1987-12-31")
    assert model.monthly_prices.index.max() == pd.Timestamp("2026-09-30")
    assert model.monthly_prices[US_TOTAL_MARKET_BENCHMARK.asset_id].notna().all()


def test_rolling_annualized_returns_compound_exact_monthly_periods():
    returns = pd.Series([0.01] * 24, index=pd.date_range("2020-01-31", periods=24, freq="ME"))
    rolling = rolling_annualized_returns(returns, 1)
    assert rolling.iloc[:11].isna().all()
    assert abs(rolling.iloc[11] - ((1.01**12) - 1)) < 1e-12
    assert abs(rolling.iloc[-1] - ((1.01**12) - 1)) < 1e-12


def test_proxy_tax_path_and_cm_ic_blend_run():
    models = {key: deep_history_model_input(spec) for key, spec in DEEP_HISTORY_SPECS.items()}
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


def test_proxy_blend_aligns_last_trading_days_to_every_calendar_month():
    models = {key: deep_history_model_input(spec) for key, spec in DEEP_HISTORY_SPECS.items()}
    blend = run_portfolio_backtest(
        {"CM": (0.7, models["century_momentum"]), "IC": (0.3, models["inflation_compass"])},
        100_000,
    )
    expected = pd.date_range(blend.monthly.index.min(), blend.monthly.index.max(), freq="ME")
    assert blend.monthly.index.equals(expected)
    assert blend.monthly.index.min() == pd.Timestamp("1988-01-31")
    assert blend.monthly.index.max() == pd.Timestamp("2026-09-30")
