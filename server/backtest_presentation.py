"""Presentation-only port from app.py; no Streamlit import or execution."""
import pandas as pd
from haa.backtest_options import result_metrics as backtest_result_metrics
from haa.strategies import (BAAG4Aggressive, CenturyMomentum, CenturyMomentumIsrael, GEM, GGCEMLinkOriginal, GrowthInflationConcentrated, GrowthInflationDiversified, HAA4, HAA4Leveraged2x, HAAClassicLeveragedNoQQQ, HAAClassicNoQQQ, InflationCompassFast, InflationCompassStandard, InflationCompassSteady, OrthogonalAlpha, VAAG4)
from .signals_wire import table

PERCENTAGE_ROWS = ["CAGR", "Total return", "Maximum drawdown", "Annualized volatility", "Best month", "Worst month", "Annual turnover"]
RATIO_ROWS = ["Sharpe", "Sortino", "Calmar"]
NUMERIC_ROWS = ["Final value", "Total contributed", "Investment gain", "Allocation changes", "Average changes/year"]
DCA_CAPTION = "Starts in the month after initial funding. Contributions buy at the next monthly execution boundary, or the first session's open for daily strategies. Synthetic proxies invest at the start of each complete reporting month. CAGR and drawdown exclude deposits; benchmarks receive the same deposits and are shown without trading fees."
REFERENCE_CAPTION = "Keeps prior indicator warm-up. Reference uses a different, unverified December month-end reset and FIFO/spread/final-sale accounting; its taxable CAGR is not a match target."


def performance_table(strategy, result, initial, tax_enabled):
    pre_tax_label = f"{strategy.name} pre-tax"
    after_tax_label = f"{strategy.name} after-tax"
    benchmark_label = f"{getattr(strategy, 'benchmark_asset', 'SPY')} buy-and-hold"
    comparison = {pre_tax_label: backtest_result_metrics(result, "pre_tax_value", initial)}
    if tax_enabled:
        comparison[after_tax_label] = backtest_result_metrics(result, "after_tax_value", initial)
    comparison[benchmark_label] = backtest_result_metrics(result, "benchmark_value", initial)
    summary = pd.DataFrame(comparison)
    changes = int(result.monthly["allocation_change"].sum())
    years = len(result.monthly) / 12
    if result.daily is not None:
        years = max((result.daily.index[-1] - result.daily.index[0]).days, 1) / 365.25
    annual_turnover = result.monthly["turnover"].sum() / years if "turnover" in result.monthly and years else changes / years if years else 0
    summary.loc["Allocation changes", pre_tax_label] = changes
    summary.loc["Average changes/year", pre_tax_label] = changes / years if years else 0
    summary.loc["Annual turnover", pre_tax_label] = annual_turnover
    observed = result.daily if result.daily is not None and not result.daily.empty else result.monthly
    summary.loc["Tested from (first observation)"] = observed.index.min().strftime("%Y-%m-%d")
    summary.loc["Tested through (last observation)"] = observed.index.max().strftime("%Y-%m-%d")
    value = table(summary.rename_axis("metric"))
    formatted = []
    for row in value["rows"]:
        metric = row["metric"]
        fmt = "{:.2%}" if metric in PERCENTAGE_ROWS else "{:.2f}" if metric in RATIO_ROWS + NUMERIC_ROWS else None
        formatted.append({column: fmt.format(item) if fmt and isinstance(item, (int, float)) else item for column, item in row.items()})
    value["display_rows"] = formatted
    return value


def captions_for(strategy, decisions, result, benchmark_label):
    captions = ["These settings configure this backtest only."]
    if result.daily is not None:
        local = decisions.attrs.get("local_daily_execution", False)
        if getattr(strategy, "signal_calendar", None) == "XNYS":
            captions += ["US closing signals execute at the first eligible TASE session's closing/NAV price. The 1x middle holds Harel alone; the blended middle drifts and resets on the first TASE session of each year. App tax uses average cost without spreads or final liquidation; it does not reproduce reference FIFO taxable CAGR.",
                f"US prices/signals through {decisions.attrs['us_completed_through']:%Y-%m-%d}; TASE execution prices through {decisions.attrs['execution_prices_completed_through']:%Y-%m-%d}."]
        else:
            captions.append("Israel execution uses next-session closing/NAV prices, not exchange opens. The two-fund QLD substitute drifts until state changes or its annual reset. Fund expenses are already in NAV. Realized-sale tax and broker fees are additional. Drawdown uses daily closes; no terminal liquidation, FX/indexation or legal tax validation is assumed." if local else "Signals use the completed session's closing prices. Trades execute at the next session's open. Fees apply separately to buys and sells. Drawdown and volatility use daily closing values, not intraday lows; monthly returns include partial boundary months.")
        captions.append("Israel also supports same-currency ILS daily-valued portfolio Backtests. Portfolio Compare, generic monthly Research and synthetic Deep History are not available for this local implementation." if local else "Also available in USD portfolio backtests and portfolio comparisons using initial weights / daily valuation. Model-only monthly Compare remains unsupported. Long synthetic A-RVol supports monthly Deep History blends and modeled CGT; the older import remains standalone only.")
    else:
        captions.append("Signals are evaluated at month-end and execute for the following holding period; no optimization or synthetic history.")
    nav = result.daily if result.daily is not None else result.monthly
    frequency = "daily sessions" if result.daily is not None else "monthly periods"
    captions.append(f"Holding periods: {nav.index.min().date()} through {nav.index.max().date()}. {benchmark_label} uses these same {frequency}.")
    captions.append(f"First valid signal date: **{decisions.index.min().date()}**")
    if getattr(strategy, "actual_history_only", False):
        captions.append("Plain buy-and-hold assets: actual available fund history only; no automatic proxy or pre-fund extension. Fund expenses are already embedded in prices.")
    return captions

def audit_view(strategy, result, data_assets):
    audit_momentum_assets = getattr(strategy, 'signal_assets', data_assets)
    audit_columns = [f'{asset}_price' for asset in data_assets]
    if not isinstance(strategy, (BAAG4Aggressive, CenturyMomentum, CenturyMomentumIsrael, GEM, GrowthInflationConcentrated, GrowthInflationDiversified, VAAG4, OrthogonalAlpha)):
        audit_columns += [f'{asset}_13612u' for asset in audit_momentum_assets]
    if isinstance(strategy, (HAAClassicNoQQQ, HAAClassicLeveragedNoQQQ, HAA4, HAA4Leveraged2x)):
        audit_columns += [f'{asset}_rank' for asset in strategy.offensive_assets] + ['selected_assets', 'target_weights', 'previous_weights']
        if isinstance(strategy, (HAA4, HAA4Leveraged2x)):
            audit_columns += ['defensive_winner', 'selected_offensive_assets', 'replaced_offensive_assets']
        if isinstance(strategy, HAA4Leveraged2x):
            audit_columns += ['selected_underlying_assets', 'mapped_holding_assets']
    if isinstance(strategy, (InflationCompassFast, InflationCompassStandard, InflationCompassSteady)):
        audit_columns += ['SPY_200d_sma', 't5yie_lag_date', 't5yie_lagged', 't5yie_momentum_date', 't5yie_momentum_value', 'positive_basket_growth', 'negative_basket_growth', 'inflation_indicator', 'indicator_momentum_slope', 'growth_up', 'inflation_level', 'breakeven_momentum', 'asset_momentum', 'inflation_on', 'target_weights', 'previous_weights']
        if isinstance(strategy, HAAClassicLeveragedNoQQQ):
            audit_columns += ['selected_underlying_assets', 'mapped_holding_assets']
    if isinstance(strategy, (GrowthInflationConcentrated, GrowthInflationDiversified)):
        audit_columns += ['SPY_200d_sma', 'positive_sector_basket', 'negative_sector_basket', 'inflation_ratio', 'inflation_ratio_200d_sma', 'growth_up', 'inflation_on', 'target_weights', 'previous_weights']
    if isinstance(strategy, VAAG4):
        audit_columns += [f'{asset}_13612w' for asset in data_assets] + ['breadth_bad_count', 'breadth_threshold', 'offensive_winner', 'defensive_winner', 'target_weights', 'previous_weights']
    if isinstance(strategy, BAAG4Aggressive):
        audit_columns += [f'{asset}_13612w' for asset in strategy.canary_assets] + [f'{asset}_sma12' for asset in data_assets] + ['breadth_bad_count', 'selected_defensive_assets', 'bil_replacements', 'target_weights', 'previous_weights']
    if isinstance(strategy, GEM):
        audit_columns += [f'{asset}_12m_return' for asset in strategy.signal_assets] + ['signal_selected_asset']
    if isinstance(strategy, GGCEMLinkOriginal):
        audit_columns += [f'{asset}_12m_return' for asset in strategy.signal_assets] + ['oecd_cli_diffusion', 'macro_source', 'risk_on', 'signal_selected_asset']
    if isinstance(strategy, OrthogonalAlpha):
        audit_columns += ['BTAL_13612u', 'BIL_13612u', 'satellite_asset', 'target_weights', 'previous_weights']
    if isinstance(strategy, (CenturyMomentum, CenturyMomentumIsrael)):
        audit_columns += [f'{strategy.equity_asset}_10m_sma', 'trend_up']
    audit_columns += ['regime', 'selected_asset', 'previous_asset', 'trade', 'execution_date', 'holding_end', 'holding_period_return']
    if 'security_trades' in result.audit:
        audit_columns += ['security_trades', 'pre_tax_fee', 'after_tax_fee']
    if getattr(strategy, 'actual_history_only', False):
        audit_columns += [column for column in result.audit if column.startswith('history_')]
    audit = result.audit[[column for column in audit_columns if column in result.audit.columns]]
    return audit
