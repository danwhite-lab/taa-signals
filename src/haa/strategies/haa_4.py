"""Published Keller & Keuning HAA-4 hybrid allocation strategy."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from ..constants import HAA4_DATA_ASSETS, HAA4_DEFENSIVE_ASSETS, HAA4_ISRAEL_DATA_ASSETS, HAA4_OFFENSIVE_ASSETS
from ..momentum import momentum_13612u
from ..validation import ExecutionSpec, ParameterSpec, ProxySpec, ValidationProfile


class HAA4:
    """Top two of four, with TIP and absolute-momentum protection.

    A bad TIP canary sends the full allocation defensive.  With a positive
    canary, each bad asset *after* the top-two offensive selection is replaced
    by the defensive winner.  This is the hybrid feature of published HAA-4.
    """

    name = "HAA 4"
    data_assets = HAA4_DATA_ASSETS
    signal_assets = HAA4_DATA_ASSETS
    offensive_assets = HAA4_OFFENSIVE_ASSETS
    defensive_assets = HAA4_DEFENSIVE_ASSETS
    is_multi_asset = True
    validation_profile = ValidationProfile(
        profile_id="haa-4",
        published_parameters=(ParameterSpec("momentum_formula", "13612U / Top-2", (), "Published TIP gate, Top-2 ranking, and sleeve-level absolute-momentum replacement."),),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        notes="The published TIP gate, Top-2 count, and 13612U formula are immutable; this profile declares no parameter sweep.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.signal_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"HAA 4 is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.signal_assets]
        momenta = prices.apply(momentum_13612u)
        rows: list[dict] = []
        previous_weights: dict[str, float] = {}

        for date, scores in momenta.iterrows():
            # The defensive winner is needed in either TIP regime and all
            # six scores are part of an auditable HAA-4 decision.
            if scores.isna().any():
                continue
            defensive = scores.loc[list(self.defensive_assets)].sort_values(ascending=False, kind="stable")
            defensive_winner = defensive.index[0]
            ranks = {asset: pd.NA for asset in self.offensive_assets}
            selected_offensive: tuple[str, ...] = ()
            replaced_offensive: tuple[str, ...] = ()

            if scores["TIP"] <= 0:
                weights = {defensive_winner: 1.0}
                regime = "risk-off"
            else:
                # This matches the app's existing offensive tie convention:
                # alphabetical ticker order, then stable descending ranking.
                candidates = scores.loc[list(self.offensive_assets)].reindex(sorted(self.offensive_assets))
                candidates = candidates.sort_values(ascending=False, kind="stable")
                selected_offensive = tuple(candidates.index[:2])
                ranks = {
                    asset: int(candidates.index.get_loc(asset)) + 1
                    for asset in self.offensive_assets
                }
                weights: dict[str, float] = {}
                replaced: list[str] = []
                for asset in selected_offensive:
                    # Absolute momentum is applied only after selecting Top2.
                    holding = asset if scores[asset] > 0 else defensive_winner
                    if holding != asset:
                        replaced.append(asset)
                    weights[holding] = weights.get(holding, 0.0) + 0.5
                replaced_offensive = tuple(replaced)
                regime = "risk-on" if not replaced_offensive else "risk-on-defensive-replacement"

            selected = tuple(weights)
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.signal_assets},
                **{f"{asset}_13612u": scores[asset] for asset in self.signal_assets},
                **{f"{asset}_rank": ranks[asset] for asset in self.offensive_assets},
                "defensive_winner": defensive_winner,
                "selected_offensive_assets": ", ".join(selected_offensive),
                "replaced_offensive_assets": ", ".join(replaced_offensive),
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


class HAA4Israel(HAA4):
    """Published HAA-4 signals with declared U.S. execution-proxy returns."""

    name = "HAA 4 Israel"
    data_assets = HAA4_ISRAEL_DATA_ASSETS
    execution_proxies = {"SPY": "SPY", "VEA": "VXUS", "VNQ": "VNQ", "IEF": "IEF", "BIL": "BIL"}
    validation_profile = replace(
        HAA4.validation_profile,
        profile_id="haa-4-israel-proxy",
        proxy_substitutions=(ProxySpec("VEA", "VXUS", "VXUS return proxy for IBI MSCI AC World ex USA (5142476).", "USD"),),
        notes="Published HAA-4 USD signals; backtests use VXUS for the IBI ex-US execution fund. Results are not TASE-fund or ILS performance.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing execution-proxy assets: {sorted(missing)}")
        decisions = super().decisions(monthly_prices)
        if decisions.empty:
            return decisions
        mapped = decisions.copy()
        previous_weights: dict[str, float] = {}
        mapped["signal_target_weights"] = mapped["target_weights"]
        for date, decision in mapped.iterrows():
            weights: dict[str, float] = {}
            for asset, weight in decision["signal_target_weights"].items():
                proxy = self.execution_proxies[asset]
                weights[proxy] = weights.get(proxy, 0.0) + float(weight)
            mapped.at[date, "target_weights"] = weights
            mapped.at[date, "selected_asset"] = ", ".join(weights)
            mapped.at[date, "selected_assets"] = ", ".join(weights)
            mapped.at[date, "previous_weights"] = previous_weights.copy()
            mapped.at[date, "previous_asset"] = ", ".join(previous_weights) if previous_weights else None
            mapped.at[date, "trade"] = weights != previous_weights
            previous_weights = weights
        return mapped
