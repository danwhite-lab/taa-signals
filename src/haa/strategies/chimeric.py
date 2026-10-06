"""Creator-published Chimeric rules, with actual ETF prices only."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..data import to_month_end
from ..market_sessions import validate_us_equity_sessions
from ..momentum import momentum_13612u


class ChimericAssetAllocation:
    name = "Chimeric Asset Allocation"
    equity_assets = ("UPRO", "TQQQ", "EURL", "EDC", "TNA")
    diversifier_assets = ("PDBC", "ERX", "UGL", "EDV", "TMF")
    offensive_assets = (*equity_assets, *diversifier_assets)
    defensive_assets = ("IEF", "SGOV")
    data_assets = (*offensive_assets, *defensive_assets, "TIP")
    signal_assets = data_assets
    benchmark_asset = "SPY"
    is_multi_asset = True
    uses_daily_signals = True  # Daily inputs, MONTHLY decisions and execution.
    execution_frequency = "monthly"
    backtest_available = True
    full_retreat = False
    risk_warning = (
        "EXPERIMENTAL leveraged monthly strategy: severe losses are possible. "
        "Creator-published rules, not independently validated against a reference implementation. "
        "ERX energy; IEF/SGOV defense. Actual adjusted ETF prices only, with full warm-up; "
        "no reconstructed prehistory. Backtests execute at the next available session close, "
        "using the app's existing fees and realized-gain tax model. Published returns are not replicated."
    )

    def allocate(self, scores: pd.Series, momenta: pd.Series) -> dict[str, float]:
        """Four ranked slots; replacements never promote fifth-place assets."""
        ranked = scores.reindex(sorted(self.offensive_assets)).sort_values(ascending=False, kind="stable")
        defense = momenta.loc[list(self.defensive_assets)].sort_values(ascending=False, kind="stable").index[0]
        if self.full_retreat and momenta["TIP"] < 0:
            return {defense: 1.0}
        best_equity = next(asset for asset in ranked.index if asset in self.equity_assets)
        partial = momenta["TIP"] < 0
        weights: dict[str, float] = {}
        for rank, asset in enumerate(ranked.index[:4], start=1):
            keep = momenta[asset] > 0
            if partial:
                keep = keep and (asset == best_equity or (asset in self.diversifier_assets and rank <= 3))
            holding = asset if keep else defense
            weights[holding] = weights.get(holding, 0.0) + 0.25
        return weights

    def decisions(self, daily_prices: pd.DataFrame, include_current_month: bool = False) -> pd.DataFrame:
        missing = set(self.data_assets) - set(daily_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = daily_prices.loc[:, self.data_assets].dropna(how="all").copy()
        if not prices.index.is_monotonic_increasing or prices.index.has_duplicates:
            raise ValueError("Chimeric requires unique, increasing daily dates.")
        # Leading pre-inception NaNs are allowed, but never splice or fill them.
        complete = prices.notna().all(axis=1)
        if not complete.any():
            return pd.DataFrame()
        prices = prices.loc[complete[complete].index[0]:]
        if prices.isna().any().any() or not np.isfinite(prices.to_numpy()).all() or (prices <= 0).any().any():
            raise ValueError("Chimeric requires complete, finite positive ETF closes after common inception.")
        validate_us_equity_sessions(prices)
        as_of = prices.index[-1] + pd.offsets.MonthBegin(1) if include_current_month else None
        monthly = to_month_end(prices, as_of=as_of)
        momenta = monthly.apply(momentum_13612u)
        offensive = prices.loc[:, self.offensive_assets]
        simple_returns = offensive.pct_change(fill_method=None)
        universe = simple_returns.mean(axis=1, skipna=False)
        correlations = simple_returns.rolling(252, min_periods=252).corr(universe)
        logs = np.log(offensive).diff()
        raw: dict[str, pd.DataFrame] = {}
        for n in (63, 126, 252):
            raw[f"tr_{n}"] = offensive.div(offensive.shift(n)).sub(1)
            path = logs.abs().rolling(n, min_periods=n).sum()
            raw[f"pe_{n}"] = np.log(offensive.div(offensive.shift(n))).div(path.where(path > 0))
        for w in (3, 6, 12):
            raw[f"pma_{w}"] = monthly.loc[:, self.offensive_assets].div(
                monthly.loc[:, self.offensive_assets].rolling(w, min_periods=w).mean()
            ).sub(1)
        rows = []
        previous: dict[str, float] = {}
        for date in monthly.index:
            momentum = momenta.loc[date]
            if momentum.isna().any():
                continue
            rho = correlations.loc[date]
            denominator = 1 + rho
            if rho.isna().any() or (denominator <= 1e-12).any():
                raise ValueError(f"Undefined Chimeric correlation at {date.date()}; no signal computed.")
            signals = pd.DataFrame({key: values.loc[date] for key, values in raw.items()})
            if not np.isfinite(signals.to_numpy()).all():
                raise ValueError(f"Undefined Chimeric path/return signal at {date.date()}; no signal computed.")
            adjusted = signals.div(denominator, axis=0)
            scores = adjusted.rank(axis=0, method="average", pct=True).mean(axis=1)
            ranked = scores.reindex(sorted(self.offensive_assets)).sort_values(ascending=False, kind="stable")
            weights = self.allocate(scores, momentum)
            rows.append({
                "signal_date": date,
                "regime": ("risk-off" if self.full_retreat else "partial-risk-off") if momentum["TIP"] < 0 else "risk-on",
                "defensive_winner": momentum.loc[list(self.defensive_assets)].sort_values(ascending=False, kind="stable").index[0],
                "ranked_assets": ", ".join(ranked.index),
                "selected_asset": ", ".join(weights), "selected_assets": ", ".join(weights),
                "target_weights": weights, "previous_weights": previous.copy(),
                "previous_asset": ", ".join(previous) if previous else None, "trade": weights != previous,
                **{f"{a}_13612u": float(momentum[a]) for a in self.data_assets},
                **{f"{a}_score": float(scores[a]) for a in self.offensive_assets},
                **{f"{a}_correlation": float(rho[a]) for a in self.offensive_assets},
                **{f"{a}_{key}": float(signals.loc[a, key]) for a in self.offensive_assets for key in raw},
            })
            previous = weights.copy()
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class ChimericFullRetreat(ChimericAssetAllocation):
    """Ablation: negative TIP replaces all four slots with defense."""

    name = "Chimeric Asset Allocation Full Retreat"
    full_retreat = True
    risk_warning = (
        "Full Retreat variant: negative TIP momentum sends 100% to the stronger IEF/SGOV. "
        "This is an ablation, not the creator's standard partial-retreat rule. "
        + ChimericAssetAllocation.risk_warning
    )
