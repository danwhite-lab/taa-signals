"""Grzegorz Link's Global Growth Cycle Enhanced Momentum strategy."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from ..constants import GGCEM_DATA_ASSETS, GGCEM_ISRAEL_DATA_ASSETS, GGCEM_MARKET_ASSETS, OECD_CLI_DIFFUSION_ASSET
from ..validation import ExecutionSpec, ParameterSpec, ProxySpec, ValidationProfile


class GGCEMLinkOriginal:
    """OECD CLI diffusion regime, then twelve-month relative momentum."""

    name = "GGCEM Link Original"
    data_assets = GGCEM_DATA_ASSETS
    market_data_assets = GGCEM_MARKET_ASSETS
    signal_assets = GGCEM_MARKET_ASSETS
    benchmark_asset = "SPY"
    lookback_months = 12
    validation_profile = ValidationProfile(
        profile_id="ggcem-link-original",
        published_parameters=(
            ParameterSpec("lookback_months", 12, (), "Completed month-end return lookback for both relative-momentum branches.", "months"),
            ParameterSpec("diffusion_threshold", "> 50%", (), "Strictly greater than half of available country CLIs rising is risk-on."),
            ParameterSpec("publication_lag", 1, (), "The previous month's published CLI diffusion is used at rebalance.", "months"),
        ),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        notes="Link original: SPY/VEU in risk-on and IEF/BIL in risk-off. The OECD CLI regime is strictly above 50%; a missing macro reading falls back to SPY-versus-BIL absolute momentum.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.market_data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.market_data_assets]
        returns = prices.div(prices.shift(self.lookback_months)).sub(1)
        diffusion = monthly_prices.get(OECD_CLI_DIFFUSION_ASSET, pd.Series(index=prices.index, dtype=float)).reindex(prices.index).shift(1)
        rows: list[dict[str, object]] = []
        previous: str | None = None
        for date, scores in returns.iterrows():
            if scores.isna().any():
                continue
            value = diffusion.loc[date]
            fallback = pd.isna(value)
            risk_on = scores["SPY"] > scores["BIL"] if fallback else bool(value > 0.5)
            if risk_on:
                selected = "SPY" if scores["SPY"] >= scores["VEU"] else "VEU"
                regime = "risk-on-us" if selected == "SPY" else "risk-on-international"
            else:
                selected = "IEF" if scores["IEF"] >= scores["BIL"] else "BIL"
                regime = "risk-off-bonds" if selected == "IEF" else "risk-off-bills"
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.market_data_assets},
                **{f"{asset}_12m_return": scores[asset] for asset in self.market_data_assets},
                "oecd_cli_diffusion": value,
                "macro_source": "SPY/BIL failsafe" if fallback else "OECD CLI diffusion",
                "risk_on": risk_on,
                "regime": regime,
                "selected_asset": selected,
                "previous_asset": previous,
                "trade": previous is None or selected != previous,
            })
            previous = selected
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class GGCEMLinkOriginalIsrael(GGCEMLinkOriginal):
    """Published GGCEM signals with U.S. execution-proxy backtest returns."""

    name = "GGCEM Link Original Israel"
    data_assets = GGCEM_ISRAEL_DATA_ASSETS
    execution_proxies = {"SPY": "SPY", "VEU": "ACWX", "IEF": "IEF", "BIL": "BIL"}
    validation_profile = replace(
        GGCEMLinkOriginal.validation_profile,
        profile_id="ggcem-link-original-israel-proxy",
        proxy_substitutions=(ProxySpec("VEU", "ACWX", "ACWX return proxy for the TASE AC World ex USA execution fund (5142476).", "USD"),),
        notes="Published GGCEM USD signals; its backtest uses ACWX as the U.S. return proxy for the Israeli international-equity fund, not TASE or ILS performance.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing execution-proxy assets: {sorted(missing)}")
        decisions = super().decisions(monthly_prices)
        if decisions.empty:
            return decisions
        mapped = decisions.copy()
        mapped["signal_selected_asset"] = mapped["selected_asset"]
        previous: str | None = None
        for date, row in mapped.iterrows():
            selected = self.execution_proxies[row["signal_selected_asset"]]
            mapped.at[date, "selected_asset"] = selected
            mapped.at[date, "previous_asset"] = previous
            mapped.at[date, "trade"] = previous is None or selected != previous
            previous = selected
        return mapped
