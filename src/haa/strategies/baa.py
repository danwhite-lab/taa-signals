"""Bold Asset Allocation, G4 Aggressive, as published by Wouter Keller."""
from __future__ import annotations

import pandas as pd

from ..constants import BAA_DEFENSIVE_ASSETS, BAA_G4_CANARY_ASSETS, BAA_G4_DATA_ASSETS, BAA_G4_OFFENSIVE_ASSETS
from ..momentum import momentum_13612w, momentum_sma12
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile


class BAAG4Aggressive:
    """BAA-G4: top-one offense and top-three, BIL-protected defense."""

    name = "BAA-G4 (Aggressive)"
    data_assets = BAA_G4_DATA_ASSETS
    canary_assets = BAA_G4_CANARY_ASSETS
    offensive_assets = BAA_G4_OFFENSIVE_ASSETS
    defensive_assets = BAA_DEFENSIVE_ASSETS
    top_offensive = 1
    top_defensive = 3
    is_multi_asset = True
    benchmark_asset = "SPY"
    backtest_available = True
    validation_profile = ValidationProfile(
        profile_id="baa-g4-aggressive",
        published_parameters=(
            ParameterSpec("offensive_selection", 1, (), "Top offensive assets selected from the four-asset G4 universe."),
            ParameterSpec("defensive_selection", 3, (), "Top defensive assets selected before BIL replacement."),
            ParameterSpec("canary_momentum", "13612W", (), "Published weighted 1/3/6/12-month canary momentum."),
            ParameterSpec("ranking_momentum", "SMA(12)", (), "Current price divided by the average of thirteen completed month-ends, minus one."),
        ),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        notes="Published BAA-G4 aggressive baseline. DBC is the paper's commodity holding; PDBC is not substituted.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.data_assets]
        canary_momentum = prices.loc[:, self.canary_assets].apply(momentum_13612w)
        relative_momentum = prices.apply(momentum_sma12)
        rows: list[dict] = []
        previous_weights: dict[str, float] = {}
        for date in prices.index:
            canary_scores = canary_momentum.loc[date]
            ranking_scores = relative_momentum.loc[date]
            if canary_scores.isna().any() or ranking_scores.isna().any():
                continue
            bad_count = int((canary_scores <= 0).sum())
            if bad_count:
                selected = ranking_scores.loc[list(self.defensive_assets)].sort_values(ascending=False, kind="stable").index[:self.top_defensive]
                bil_score = ranking_scores["BIL"]
                replacements = tuple(asset for asset in selected if asset != "BIL" and ranking_scores[asset] < bil_score)
                final_assets = tuple("BIL" if asset in replacements else asset for asset in selected)
                weights: dict[str, float] = {}
                for asset in final_assets:
                    weights[asset] = weights.get(asset, 0.0) + 1 / self.top_defensive
                regime = "risk-off"
            else:
                selected = ranking_scores.loc[list(self.offensive_assets)].sort_values(ascending=False, kind="stable").index[:self.top_offensive]
                replacements = ()
                weights = {asset: 1 / self.top_offensive for asset in selected}
                regime = "risk-on"
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.data_assets},
                **{f"{asset}_13612w": canary_scores[asset] for asset in self.canary_assets},
                **{f"{asset}_sma12": ranking_scores[asset] for asset in self.data_assets},
                "breadth_bad_count": bad_count,
                "selected_defensive_assets": ", ".join(selected) if regime == "risk-off" else None,
                "bil_replacements": ", ".join(replacements) if replacements else None,
                "regime": regime,
                "selected_asset": ", ".join(weights),
                "selected_assets": ", ".join(weights),
                "target_weights": weights,
                "previous_weights": previous_weights.copy(),
                "previous_asset": ", ".join(previous_weights) if previous_weights else None,
                "trade": weights != previous_weights,
            })
            previous_weights = weights
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class BAAG4AggressiveIsrael(BAAG4Aggressive):
    """Published USD BAA signals, executed through the specified TASE proxies."""

    name = "BAA-G4 (Aggressive) Israel"
    # The paper's signal universe remains intact, including SPY as the
    # canary-only input. The Portfolio layer maps each resulting holding to
    # its supplied TASE execution security in ILS.
    backtest_available = False
