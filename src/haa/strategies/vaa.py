"""Vigilant Asset Allocation: reusable breadth-momentum strategy logic."""
from __future__ import annotations

import pandas as pd

from ..constants import VAA_DEFENSIVE_ASSETS, VAA_G4_DATA_ASSETS, VAA_OFFENSIVE_ASSETS
from ..momentum import momentum_13612w


class VAABase:
    """VAA's universe-level breadth protection with configurable T and B."""

    data_assets: tuple[str, ...] = ()
    offensive_assets: tuple[str, ...] = ()
    defensive_assets: tuple[str, ...] = ()
    top_selection = 1
    breadth_threshold = 1
    is_multi_asset = True
    benchmark_asset = "SPY"
    backtest_available = True

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.data_assets]
        momenta = prices.apply(momentum_13612w)
        rows: list[dict] = []
        previous_weights: dict[str, float] = {}
        for date, scores in momenta.iterrows():
            if scores.isna().any():
                continue
            offensive_scores = scores.loc[list(self.offensive_assets)].sort_values(ascending=False, kind="stable")
            defensive_scores = scores.loc[list(self.defensive_assets)].sort_values(ascending=False, kind="stable")
            bad_count = int((scores.loc[list(self.offensive_assets)] <= 0).sum())
            offensive_winner = offensive_scores.index[0]
            defensive_winner = defensive_scores.index[0]
            if bad_count >= self.breadth_threshold:
                weights, regime = {defensive_winner: 1.0}, "risk-off"
            else:
                selected = tuple(offensive_scores.index[:self.top_selection])
                weights = {asset: 1 / self.top_selection for asset in selected}
                regime = "risk-on"
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.data_assets},
                **{f"{asset}_13612w": scores[asset] for asset in self.data_assets},
                "breadth_bad_count": bad_count,
                "breadth_threshold": self.breadth_threshold,
                "offensive_winner": offensive_winner,
                "defensive_winner": defensive_winner,
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


class VAAG4(VAABase):
    """Classic VAA Global-4, Top-1 with immediate B=1 protection."""

    name = "VAA-G4 (T1/B1)"
    data_assets = VAA_G4_DATA_ASSETS
    offensive_assets = VAA_OFFENSIVE_ASSETS
    defensive_assets = VAA_DEFENSIVE_ASSETS
    top_selection = 1
    breadth_threshold = 1
