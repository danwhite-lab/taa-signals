import pandas as pd

from haa.deep_history import DEEP_HISTORY_SPECS, deep_history_model_input, load_deep_history
from haa.engine import run_backtest
from haa.portfolio_backtest import run_portfolio_backtest


def test_bundled_proxy_histories_align_without_invented_months():
    for spec in DEEP_HISTORY_SPECS.values():
        signals, returns = load_deep_history(spec)
        assert not signals.index.has_duplicates
        assert not returns.index.has_duplicates
        assert (signals.index + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1)).isin(returns.index).all()


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
