"""BestFolio Momentum-Correlation Triplet (Standard)."""
from __future__ import annotations

from itertools import combinations

import pandas as pd

from ..data import to_month_end


class MomentumCorrelationTriplet:
    """Top-five composite momentum, then the least-correlated triplet."""

    name = "Momentum-Correlation Triplet"
    # BIL is the cash hurdle and not a ranked candidate.
    candidate_assets = ("BWX", "EEM", "EWJ", "GLDM", "IEF", "PDBC", "QQQ", "RWX", "SCZ", "SPY", "TIP", "TLT", "VGK", "VNQ")
    data_assets = (*candidate_assets, "BIL")
    signal_assets = data_assets
    benchmark_asset = "SPY"
    is_multi_asset = True
    uses_daily_signals = True
    backtest_available = True
    top_n = 5
    holdings = 3
    correlation_window = 252

    def decisions(self, daily_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(daily_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        monthly = to_month_end(daily_prices.loc[:, self.data_assets])
        scores = (monthly.pct_change(3) + monthly.pct_change(6) + monthly.pct_change(12)) / 3
        daily_returns = daily_prices.loc[:, self.data_assets].pct_change()
        rows: list[dict] = []
        previous_weights: dict[str, float] = {}
        for date in monthly.index:
            score = scores.loc[date]
            bil_score = score["BIL"]
            if pd.isna(bil_score):
                continue
            ranked = score.loc[list(self.candidate_assets)].dropna()
            ranked = ranked.loc[ranked > bil_score].sort_values(ascending=False, kind="stable").index[:self.top_n].tolist()
            selected = ranked[:self.holdings]
            mean_correlation = None
            if len(ranked) >= self.holdings:
                candidates: list[tuple[float, tuple[str, ...]]] = []
                # Correlations use only dates on which every member actually
                # traded. No cross-calendar forward fill is permitted.
                returns_to_date = daily_returns.loc[:date]
                for triplet in combinations(ranked, self.holdings):
                    aligned = returns_to_date.loc[:, list(triplet)].dropna().tail(self.correlation_window)
                    if len(aligned) < self.correlation_window:
                        continue
                    corr = aligned.corr()
                    average = (corr.iloc[0, 1] + corr.iloc[0, 2] + corr.iloc[1, 2]) / 3
                    candidates.append((float(average), triplet))
                if candidates:
                    # combinations preserves ranked order, giving deterministic
                    # published-universe tie handling.
                    mean_correlation, selected = min(candidates, key=lambda item: item[0])
            weights: dict[str, float] = {}
            for asset in selected:
                weights[asset] = weights.get(asset, 0.0) + 1 / self.holdings
            if len(selected) < self.holdings:
                weights["BIL"] = weights.get("BIL", 0.0) + (self.holdings - len(selected)) / self.holdings
            rows.append({
                "signal_date": date, "bil_composite_momentum": bil_score,
                "qualified_assets": ", ".join(ranked), "selected_assets": ", ".join(weights),
                "selected_asset": ", ".join(weights), "average_pairwise_correlation": mean_correlation,
                "target_weights": weights, "previous_weights": previous_weights.copy(),
                "previous_asset": ", ".join(previous_weights) if previous_weights else None,
                "trade": weights != previous_weights,
            })
            previous_weights = weights
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
