"""Carlson's Orthogonal Alpha core-satellite allocation."""
from __future__ import annotations

import pandas as pd

from ..constants import ORTHOGONAL_ALPHA_DATA_ASSETS
from ..momentum import momentum_13612u


class OrthogonalAlpha:
    """Monthly BTAL/QLD core-satellite model with a BIL relative-momentum gate."""

    name = "Orthogonal Alpha (BTAL/QLD)"
    data_assets = ORTHOGONAL_ALPHA_DATA_ASSETS
    signal_assets = ("BTAL", "BIL")
    is_multi_asset = True
    benchmark_asset = "SPY"
    backtest_available = True
    core_weights = {"QLD": 0.25, "BTAL": 0.25}
    satellite_weight = 0.50

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.data_assets]
        btal_momentum = momentum_13612u(prices["BTAL"])
        bil_momentum = momentum_13612u(prices["BIL"])
        rows: list[dict] = []
        previous_weights: dict[str, float] = {}
        for date in prices.index:
            btal_score, bil_score = btal_momentum.loc[date], bil_momentum.loc[date]
            if pd.isna(btal_score) or pd.isna(bil_score):
                continue
            satellite_asset = "BTAL" if btal_score > bil_score else "QLD"
            weights = self.core_weights.copy()
            weights[satellite_asset] = weights.get(satellite_asset, 0.0) + self.satellite_weight
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.data_assets},
                "BTAL_13612u": btal_score,
                "BIL_13612u": bil_score,
                "satellite_asset": satellite_asset,
                "regime": "risk-off" if satellite_asset == "BTAL" else "risk-on",
                "selected_asset": ", ".join(weights),
                "selected_assets": ", ".join(weights),
                "target_weights": weights,
                "previous_weights": previous_weights.copy(),
                "previous_asset": ", ".join(previous_weights) if previous_weights else None,
                "trade": weights != previous_weights,
            })
            previous_weights = weights
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
