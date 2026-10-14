"""Unchanged US V3 signals, separately scheduled actual TASE execution."""
from __future__ import annotations

import pandas as pd

from .rvol_shifter import RVolShifterCashOnly
from .rvol_shifter_israel import completed_tase_cutoff
from ..cross_market_daily import market_frame, complete_tase_prices
from ..market_sessions import market_session_times, scheduled_us_tase_execution_dates


class RVolShifterUSTase1x:
    name = "A-RVol V3 US Signals / TASE — 1x Middle"
    us_data_assets = RVolShifterCashOnly.data_assets
    signal_assets = RVolShifterCashOnly.signal_assets
    execution_assets = ("RVOL_QQQ_IL", "RVOL_3X_IL", "RVOL_CASH_IL", "RVOL_SPY_IL")
    data_assets = (*us_data_assets, *execution_assets)
    market_data_assets = execution_assets
    benchmark_asset = "RVOL_SPY_IL"
    execution_currency = "ILS"
    execution_frequency = "daily"
    execution_timing = "next-session-close"
    signal_calendar = "XNYS"
    uses_daily_signals = True
    is_multi_asset = True
    backtest_available = True
    annual_reset_states = ()
    state_weights = {"TQQQ": {"RVOL_3X_IL": 1.}, "QLD": {"RVOL_QQQ_IL": 1.}, "BIL": {"RVOL_CASH_IL": 1.}}
    state_labels = {"TQQQ": "MTF Nasdaq-100 monthly x3 (1187079)", "QLD": "Harel Nasdaq-100 x1 (1149038)", "BIL": "Ayalon Kaspit (5117700)"}
    research_unavailable_reason = "US daily signals and actual TASE closing/NAV execution require daily Backtest; monthly Research and synthetic Deep History are not supported."
    risk_warning = "EXPERIMENTAL: unchanged US V3 signals; actual ILS TASE funds. Middle state is 100% Harel 1149038, not QLD. MTF 1187079 resets leverage monthly. Execute at the first TASE session after the completed US close, modeled at closing/NAV prices; broker dealing deadlines may differ. No claim of reproducing the reported taxable CAGR."

    def us_decisions(self, prices, as_of=None, cash_start=None):
        us = market_frame(prices, self.us_data_assets, "US")
        original = RVolShifterCashOnly()
        if cash_start is None:
            return original.decisions(us, as_of=as_of)
        # Retain full historical indicators but restart the identical transition
        # loop in cash for a reference replay. The normal parity path is untouched.
        indicators = original.indicators(us)
        class CashReplay(RVolShifterCashOnly):
            def indicators(self, replay_prices):
                return indicators.reindex(replay_prices.index)
        return CashReplay().decisions(us.loc[pd.Timestamp(cash_start):], as_of=as_of)

    def decisions(self, daily_prices, include_current_month=False, as_of=None, *, cash_start=None):
        result = self.us_decisions(daily_prices, as_of, cash_start).copy()
        if result.empty:
            return result
        local, pending = complete_tase_prices(daily_prices, self.execution_assets, completed_tase_cutoff(as_of))
        result["model_state"] = result.selected_asset
        result["previous_model_state"] = result.previous_asset
        result["target_weights"] = result.model_state.map(lambda state: self.state_weights[state].copy())
        result["previous_weights"] = result.previous_model_state.map(lambda state: self.state_weights[state].copy())
        result["selected_asset"] = result.model_state.map(self.state_labels)
        result["previous_asset"] = result.previous_model_state.map(self.state_labels)
        result["signal_close_at"] = market_session_times("XNYS", result.index, "close")
        result["scheduled_execution_date"] = scheduled_us_tase_execution_dates(result.index)
        result["scheduled_execution_timing"] = self.execution_timing
        result.attrs.update(local_daily_execution=True, signal_calendar="XNYS", execution_currency="ILS",
            execution_timing=self.execution_timing, us_data_assets=self.us_data_assets,
            execution_assets=self.execution_assets, annual_reset_states=self.annual_reset_states,
            us_completed_through=result.attrs.get("completed_through"),
            execution_prices_started_from=local.index[0],
            execution_prices_completed_through=local.index[-1], completed_through=local.index[-1],
            pending_price_dates=[str(date.date()) for date in pending],
            cash_start_date=str(pd.Timestamp(cash_start).date()) if cash_start is not None else None)
        return result


class RVolShifterUSTaseBlend(RVolShifterUSTase1x):
    name = "A-RVol V3 US Signals / TASE — 50:50 Middle"
    annual_reset_states = ("QLD",)
    state_weights = {**RVolShifterUSTase1x.state_weights, "QLD": {"RVOL_QQQ_IL": .5, "RVOL_3X_IL": .5}}
    state_labels = {**RVolShifterUSTase1x.state_labels, "QLD": "50% Harel x1 (1149038) / 50% MTF monthly x3 (1187079)"}
    risk_warning = "EXPERIMENTAL: unchanged US V3 signals; actual ILS TASE funds. Middle state enters 50% Harel 1149038 / 50% MTF 1187079, drifts, and resets on the first TASE session of each calendar year. Monthly-reset leverage is not QLD. Closing/NAV fills are modeled, not guaranteed. Reference December month-end reset timing is unverified and differs; reported taxable CAGR is not a reproduction target."
