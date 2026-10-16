"""The shared, unchanged actionable portfolio signal calculation."""
from .constants import ASSETS
from .data import to_month_end
from .signals import latest_actionable_signal


def monthly_strategy_input(daily_prices, market_assets):
    monthly_market = to_month_end(daily_prices.loc[:, list(market_assets)])
    auxiliary = daily_prices.drop(columns=list(market_assets), errors="ignore")
    if auxiliary.empty:
        return monthly_market, monthly_market
    values = auxiliary.reindex(monthly_market.index, method="ffill")
    return monthly_market, monthly_market.join(values)


def portfolio_signal(model_class, all_prices):
    strategy = model_class()
    assets = getattr(strategy, "data_assets", ASSETS)
    prices = all_prices.loc[:, assets]
    market_assets = getattr(strategy, "market_data_assets", assets)
    monthly, monthly_input = monthly_strategy_input(prices, market_assets)
    decision_prices = prices if getattr(strategy, "uses_daily_signals", False) else monthly_input
    status_prices = prices if getattr(strategy, "execution_frequency", "monthly") == "daily" else monthly
    try:
        decisions = strategy.decisions(decision_prices)
    except ValueError as exc:
        return None, str(exc)
    status = latest_actionable_signal(decisions, status_prices, market_assets)
    if status.decision is None:
        return None, status.reason
    decision = status.decision
    weights = decision.get("target_weights", {decision["selected_asset"]: 1.0})
    return {"decision": decision, "weights": dict(weights), "strategy": strategy}, None
