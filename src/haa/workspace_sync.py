"""Small, explicitly selected workspace preferences; never results or tokens."""
from __future__ import annotations

import json
from datetime import date, datetime

FIELDS = {
    'page', 'model_name', 'signals_model_name', 'research_model_name',
    'ticker_text', 'initial', 'cost_pct', 'tax_enabled', 'tax_rate',
    'compare_initial', 'compare_cost_pct', 'compare_tax_enabled', 'compare_tax_rate',
    'portfolio_sleeves', 'portfolio_next_id', 'portfolio_base_currency',
    'portfolio_name', 'portfolio_total_ils', 'portfolio_capital_text', 'portfolio_fx_rate',
    'browser_default_portfolio', 'browser_portfolio_library',
    'backtest_mode', 'backtest_sleeves', 'backtest_next_id',
    'deep_proxy_sleeves', 'deep_proxy_next_id', 'settings_cost_pct', 'settings_tax_rate',
    'backtest_dca_amount', 'backtest_dca_enabled', 'backtest_fee_mode', 'backtest_fixed_fee',
    'compare_models', 'compare_start', 'compare_end', 'deep_proxy_start', 'deep_proxy_end',
    'comparison_mode', 'comparison_portfolio_method', 'deep_history_benchmark',
    'comparison_initial', 'comparison_cost_pct', 'comparison_tax_enabled', 'comparison_tax_rate',
    'comparison_saved_portfolios', 'portfolio_compare_initial', 'portfolio_compare_fee',
    'portfolio_compare_tax', 'portfolio_compare_tax_rate',
    'mixed_rebalance_cap', 'mixed_rebalance_rule', 'mixed_rebalance_sleeve', 'mixed_rebalance_target',
    'substitution_mode',
}


def _encode(value):
    if isinstance(value, (date, datetime)):
        return {'__date__': value.date().isoformat() if isinstance(value, datetime) else value.isoformat()}
    raise TypeError('Unsupported preference')


def snapshot(state):
    result = {}
    for key in FIELDS:
        if key in state:
            try:
                result[key] = json.loads(json.dumps(state[key], default=_encode, allow_nan=False))
            except (ValueError, TypeError):
                continue
    return result


def restore(payload):
    if not isinstance(payload, dict):
        return {}
    def decode(value):
        if isinstance(value, dict):
            if set(value) == {'__date__'}:
                return date.fromisoformat(value['__date__'])
            return {key: decode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [decode(item) for item in value]
        return value
    result = {}
    for key, value in payload.items():
        if key in FIELDS:
            try:
                result[key] = decode(value)
            except (ValueError, TypeError):
                continue
    return result
