"""Keep the extracted shared helper identical to the old dashboard path."""
import numpy as np
import pandas as pd
import pytest

from haa.constants import ASSETS
from haa.data import to_month_end
from haa.market_sessions import us_equity_sessions, tase_equity_sessions
from haa.model_catalog import MODEL_CATALOG
from haa.portfolio_signals import portfolio_signal
from haa.signals import latest_actionable_signal
from haa.tase_data import TASE_ISRAEL_ASSET_IDS


def legacy_dashboard_signal(model_class, all_prices):
    # Reference: original app.py current_portfolio_signal before extraction.
    strategy = model_class()
    assets = getattr(strategy, 'data_assets', ASSETS)
    prices = all_prices.loc[:, assets]
    market_assets = getattr(strategy, 'market_data_assets', assets)
    monthly = to_month_end(prices.loc[:, list(market_assets)])
    auxiliary = prices.drop(columns=list(market_assets), errors='ignore')
    monthly_input = monthly if auxiliary.empty else monthly.join(auxiliary.reindex(monthly.index, method='ffill'))
    decision_prices = prices if getattr(strategy, 'uses_daily_signals', False) else monthly_input
    status_prices = prices if getattr(strategy, 'execution_frequency', 'monthly') == 'daily' else monthly
    try:
        decisions = strategy.decisions(decision_prices)
    except ValueError as exc:
        return None, str(exc)
    status = latest_actionable_signal(decisions, status_prices, market_assets)
    if status.decision is None:
        return None, status.reason
    decision = status.decision
    weights = decision.get('target_weights', {decision['selected_asset']: 1.0})
    return {'decision': decision, 'weights': dict(weights), 'strategy': strategy}, None


@pytest.mark.parametrize('label', [
    'Century Momentum', 'Inflation Compass Standard', 'Buy and Hold Gold GLD',
    'A-RVol Shifter V3 Cash-Only', 'A-RVol Shifter V3 Cash-Only Israel',
    'A-RVol V3 US Signals / TASE — 1x Middle',
])
def test_shared_helper_reproduces_legacy_actionable_targets_exactly(label):
    model = next(row.model_class for row in MODEL_CATALOG if row.label == label)
    end = pd.Timestamp.now(tz='UTC').date().isoformat()
    us = us_equity_sessions('2023-01-01', end)
    local = tase_equity_sessions('2023-01-01', end)
    frames = []
    for i, asset in enumerate(model.data_assets):
        dates = local if asset in TASE_ISRAEL_ASSET_IDS else us
        x = np.arange(len(dates))
        values = 100 * np.exp(np.cumsum(.0001*(i+1) + .004*np.sin(x)))
        frames.append(pd.Series(values, index=dates, name=asset))
    prices = pd.concat(frames, axis=1, sort=True)
    old, old_error = legacy_dashboard_signal(model, prices)
    new, new_error = portfolio_signal(model, prices)
    assert new_error == old_error
    assert old is not None, old_error
    assert new['weights'] == old['weights']
    pd.testing.assert_series_equal(new['decision'], old['decision'])
