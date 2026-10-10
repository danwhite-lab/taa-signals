"""User-selected TASE implementation of the V3 Cash-Only state machine."""
from __future__ import annotations

import pandas as pd

from .rvol_shifter import RVolShifterCashOnly
from ..market_sessions import scheduled_tase_execution_dates, validate_tase_sessions


def completed_tase_cutoff(as_of=None):
    now = pd.Timestamp.now(tz="Asia/Jerusalem") if as_of is None else pd.Timestamp(as_of)
    now = now.tz_localize("Asia/Jerusalem") if now.tzinfo is None else now.tz_convert("Asia/Jerusalem")
    date = now.tz_localize(None).normalize()
    return date if now.hour >= 20 else date - pd.Timedelta(days=1)


class RVolShifterCashOnlyIsrael(RVolShifterCashOnly):
    name = "A-RVol Shifter V3 Cash-Only Israel"
    signal_assets = ("RVOL_QQQ_IL", "RVOL_SPY_IL", "RVOL_HYG_IL", "RVOL_LQD_IL")
    data_assets = (*signal_assets, "RVOL_3X_IL", "RVOL_CASH_IL")
    market_data_assets = data_assets
    benchmark_asset = "RVOL_SPY_IL"
    execution_currency = "ILS"
    execution_timing = "next-session-close"
    research_unavailable_reason = "This local daily strategy requires actual TASE histories and next-session closing/NAV execution. Use daily Backtest, not generic monthly Research or synthetic US history."
    validate_sessions = staticmethod(validate_tase_sessions)
    completed_cutoff = staticmethod(completed_tase_cutoff)
    schedule_dates = staticmethod(scheduled_tase_execution_dates)
    risk_warning = (
        "EXPERIMENTAL Israel implementation: MTF 1187079 resets its Nasdaq leverage monthly. "
        "The QLD state enters 50% MTF x3 / 50% Harel Nasdaq-100 and allows drift until "
        "the annual reset or a state change. Cash is Ayalon 5117700 in shekels. "
        "Backtests execute at the next TASE session's closing/NAV price, not an opening price."
    )
    state_weights = {
        "TQQQ": {"RVOL_3X_IL": 1.0},
        "QLD": {"RVOL_3X_IL": .5, "RVOL_QQQ_IL": .5},
        "BIL": {"RVOL_CASH_IL": 1.0},
    }
    state_labels = {
        "TQQQ": "MTF Nasdaq-100 x3 (1187079)",
        "QLD": "50% MTF x3 (1187079) / 50% Harel Nasdaq-100 (1149038)",
        "BIL": "Ayalon Kaspit (5117700)",
    }

    def decisions(self, daily_prices, include_current_month=False, as_of=None):
        result = super().decisions(daily_prices, include_current_month, as_of)
        if not result.empty:
            result["model_state"] = result.selected_asset
            result["previous_model_state"] = result.previous_asset
            result["target_weights"] = result.model_state.map(lambda state: self.state_weights[state].copy())
            result["previous_weights"] = result.previous_model_state.map(lambda state: self.state_weights[state].copy())
            result["selected_asset"] = result.model_state.map(self.state_labels)
            result["previous_asset"] = result.previous_model_state.map(self.state_labels)
            result["scheduled_execution_timing"] = self.execution_timing
            annual = (result.scheduled_execution_date.dt.year != result.index.year) & result.model_state.eq("QLD")
            result.loc[annual, "trade"] = True
            result.loc[annual, "transition_reason"] = "Annual 50/50 QLD-substitute reset"
        result.attrs.update(local_daily_execution=True, execution_currency="ILS", execution_timing=self.execution_timing)
        return result
