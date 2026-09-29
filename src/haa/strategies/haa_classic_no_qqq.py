"""Classic HAA without QQQ: TIP canary and a four-asset offensive basket."""
from __future__ import annotations

import pandas as pd

from ..constants import CLASSIC_DATA_ASSETS, CLASSIC_DEFENSIVE_ASSETS, CLASSIC_OFFENSIVE_ASSETS
from ..momentum import momentum_13612u
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile


class HAAClassicNoQQQ:
    """HAA's TIP gate with the top four of eight assets, equal weighted."""

    name = "HAA Classic (No QQQ)"
    data_assets = CLASSIC_DATA_ASSETS
    offensive_assets = CLASSIC_OFFENSIVE_ASSETS
    defensive_assets = CLASSIC_DEFENSIVE_ASSETS
    is_multi_asset = True
    validation_profile = ValidationProfile(
        profile_id="haa-classic-no-qqq",
        published_parameters=(ParameterSpec("momentum_formula", "13612U / Top-4", (), "Published TIP gate and equal-weighted Top-4 offensive allocation without QQQ."),),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        notes="The published universe, Top-4 selection, and 13612U formula are immutable; this profile declares no parameter sweep.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"HAA Classic (No QQQ) is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.data_assets]
        momenta = prices.apply(momentum_13612u)
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
                selected = tuple(candidates.index[:4])
                weights = {asset: 0.25 for asset in selected}
                regime = "risk-on"
                ranks = {asset: (int(candidates.index.get_loc(asset)) + 1 if asset in candidates.index else pd.NA) for asset in self.offensive_assets}
            else:
                defensive = scores.loc[list(self.defensive_assets)].dropna()
                if defensive.empty:
                    continue
                selected_asset = defensive.sort_values(ascending=False, kind="stable").index[0]
                selected = (selected_asset,)
                weights = {selected_asset: 1.0}
                regime = "risk-off"
                ranks = {asset: pd.NA for asset in self.offensive_assets}
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.data_assets},
                **{f"{asset}_13612u": scores[asset] for asset in self.data_assets},
                **{f"{asset}_rank": ranks[asset] for asset in self.offensive_assets},
                "regime": regime,
                "selected_asset": ", ".join(selected),
                "selected_assets": ", ".join(selected),
                "target_weights": weights,
                "previous_weights": previous_weights.copy(),
                "previous_asset": ", ".join(previous_weights) if previous_weights else None,
                "trade": weights != previous_weights,
            })
            previous_weights = weights
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
