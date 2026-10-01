"""Gary Antonacci's Global Equities Momentum (GEM)."""
from __future__ import annotations

from dataclasses import replace

import pandas as pd

from ..constants import GEM_DATA_ASSETS, GEM_ISRAEL_DATA_ASSETS
from ..validation import ExecutionSpec, ParameterSpec, ProxySpec, ValidationProfile


class GEM:
    """Monthly dual momentum across U.S., ex-U.S., and aggregate bonds."""

    name = "GEM"
    data_assets = GEM_DATA_ASSETS
    signal_assets = GEM_DATA_ASSETS
    benchmark_asset = "SPY"
    lookback_months = 12
    validation_profile = ValidationProfile(
        profile_id="gem-standard",
        published_parameters=(ParameterSpec("lookback_months", 12, (), "Completed month-end return lookback for absolute and relative momentum.", "months"),),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        notes="Published GEM rule: SPY must exceed BIL over twelve months; an exact SPY/VEU tie selects SPY.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.signal_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.signal_assets]
        returns = prices.div(prices.shift(self.lookback_months)).sub(1)
        rows: list[dict[str, object]] = []
        previous: str | None = None
        for date, scores in returns.iterrows():
            if scores.isna().any():
                continue
            if scores["SPY"] > scores["BIL"]:
                selected = "SPY" if scores["SPY"] >= scores["VEU"] else "VEU"
                regime = "risk-on-us" if selected == "SPY" else "risk-on-international"
            else:
                selected = "AGG"
                regime = "risk-off"
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.signal_assets},
                **{f"{asset}_12m_return": scores[asset] for asset in self.signal_assets},
                "regime": regime,
                "selected_asset": selected,
                "previous_asset": previous,
                "trade": previous is None or selected != previous,
            })
            previous = selected
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()


class GEMIsrael(GEM):
    """Published GEM signals with U.S. proxies for Israeli execution funds."""

    name = "GEM Israel"
    data_assets = GEM_ISRAEL_DATA_ASSETS
    execution_proxies = {"SPY": "SPY", "VEU": "ACWX", "AGG": "BNDW"}
    validation_profile = replace(
        GEM.validation_profile,
        profile_id="gem-israel-proxy",
        proxy_substitutions=(
            ProxySpec("VEU", "ACWX", "ACWX return proxy for the TASE AC World ex USA execution fund (5142476).", "USD"),
            ProxySpec("AGG", "BNDW", "BNDW return proxy for the TASE BNDW execution fund (1159102).", "USD"),
        ),
        notes="Published GEM signals; backtests use ACWX and BNDW U.S. execution-proxy returns, not TASE fund or ILS performance.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"{self.name} is missing execution-proxy assets: {sorted(missing)}")
        decisions = super().decisions(monthly_prices)
        if decisions.empty:
            return decisions
        mapped = decisions.copy()
        previous: str | None = None
        mapped["signal_selected_asset"] = mapped["selected_asset"]
        for date, decision in mapped.iterrows():
            selected = self.execution_proxies[decision["signal_selected_asset"]]
            mapped.at[date, "selected_asset"] = selected
            mapped.at[date, "previous_asset"] = previous
            mapped.at[date, "trade"] = previous is None or selected != previous
            previous = selected
        return mapped
