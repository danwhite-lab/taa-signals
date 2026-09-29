"""Leveraged Classic HAA without QQQ, gated and ranked on 1x underlyings."""
from __future__ import annotations

import pandas as pd

from ..constants import (
    CLASSIC_DATA_ASSETS,
    CLASSIC_DEFENSIVE_ASSETS,
    CLASSIC_LEVERAGED_DATA_ASSETS,
    CLASSIC_LEVERAGED_SUBSTITUTIONS,
    CLASSIC_OFFENSIVE_ASSETS,
)
from ..momentum import momentum_13612u
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile


class HAAClassicLeveragedNoQQQ:
    """TIP-gated Classic HAA with 2x holdings chosen from 1x momentum scores."""

    name = "HAA Classic Leveraged 2x (No QQQ)"
    data_assets = CLASSIC_LEVERAGED_DATA_ASSETS
    signal_assets = CLASSIC_DATA_ASSETS
    offensive_assets = CLASSIC_OFFENSIVE_ASSETS
    defensive_assets = CLASSIC_DEFENSIVE_ASSETS
    substitutions = CLASSIC_LEVERAGED_SUBSTITUTIONS
    is_multi_asset = True
    risk_warning = "High-drawdown leveraged satellite, not a core holding. Signals and rankings use 1x underlyings; holdings use the 2x substitution table."
    validation_profile = ValidationProfile(
        profile_id="haa-classic-leveraged-2x-no-qqq",
        published_parameters=(ParameterSpec("momentum_formula", "13612U / Top-4", (), "Published 1x TIP gate and Top-4 ranking with fixed 2x execution mapping."),),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        notes="The published signal universe and fixed leveraged mapping are immutable; this profile declares no parameter sweep.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"HAA Classic Leveraged 2x (No QQQ) is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.data_assets]
        signal_prices = prices.loc[:, self.signal_assets]
        momenta = signal_prices.apply(momentum_13612u)
        rows: list[dict] = []
        previous_weights: dict[str, float] = {}
        for date, scores in momenta.iterrows():
            if pd.isna(scores["TIP"]):
                continue
            if scores["TIP"] > 0:
                candidates = scores.loc[list(self.offensive_assets)].dropna()
                candidates = candidates.reindex(sorted(candidates.index)).sort_values(ascending=False, kind="stable")
                if len(candidates) < 4:
                    continue
                selected_underlyings = tuple(candidates.index[:4])
                regime = "risk-on"
                ranks = {asset: (int(candidates.index.get_loc(asset)) + 1 if asset in candidates.index else pd.NA) for asset in self.offensive_assets}
            else:
                defensive = scores.loc[list(self.defensive_assets)].dropna()
                if defensive.empty:
                    continue
                selected_underlyings = (defensive.sort_values(ascending=False, kind="stable").index[0],)
                regime = "risk-off"
                ranks = {asset: pd.NA for asset in self.offensive_assets}

            selected_holdings = tuple(self.substitutions[asset] for asset in selected_underlyings)
            if prices.loc[date, list(selected_holdings)].isna().any():
                # The signal is valid, but it cannot be traded until each mapped
                # instrument has real price history. No proxy is introduced.
                continue
            weight = 1.0 / len(selected_holdings)
            weights = {asset: weight for asset in selected_holdings}
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.data_assets},
                **{f"{asset}_13612u": scores[asset] for asset in self.signal_assets},
                **{f"{asset}_rank": ranks[asset] for asset in self.offensive_assets},
                "regime": regime,
                "selected_asset": ", ".join(selected_holdings),
                "selected_assets": ", ".join(selected_underlyings),
                "selected_underlying_assets": ", ".join(selected_underlyings),
                "mapped_holding_assets": ", ".join(selected_holdings),
                "target_weights": weights,
                "previous_weights": previous_weights.copy(),
                "previous_asset": ", ".join(previous_weights) if previous_weights else None,
                "trade": weights != previous_weights,
            })
            previous_weights = weights
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
