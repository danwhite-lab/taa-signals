"""Israel-local-investability HAA-Simple using TIP as a signal-only canary."""
from __future__ import annotations

import pandas as pd

from ..constants import ASSETS, ISRAEL_SIMPLE_ASSETS
from ..momentum import momentum_13612u
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile


class HAASimpleIsrael:
    """TIP canary plus ILS-traded CSPX, Treasury, and money-market sleeves."""

    name = "HAA-Simple Israel"
    data_assets = ISRAEL_SIMPLE_ASSETS
    signal_assets = ASSETS
    market_data_assets = ISRAEL_SIMPLE_ASSETS
    benchmark_asset = "CSPX_IL"
    equity_asset = "CSPX_IL"
    defensive_bond_asset = "IEF_IL"
    defensive_cash_asset = "AYALON_KASPIT"
    execution_proxies = {"SPY": equity_asset, "IEF": defensive_bond_asset, "BIL": defensive_cash_asset}
    validation_profile = ValidationProfile(
        profile_id="haa-simple-israel",
        published_parameters=(ParameterSpec("momentum_formula", "13612U", (), "Published U.S. SPY/TIP/IEF/BIL signal mapped to CSPX, IEF, and Ayalon Kaspit local execution sleeves."),),
        execution=ExecutionSpec("monthly", "Next available TASE trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        data_confidence="moderate",
        notes="The published U.S. 13612U signal is immutable; TASE/Maya funds are execution holdings only. This profile declares no parameter sweep or synthetic cash proxy.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.signal_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"HAA-Simple Israel is missing assets: {sorted(missing)}")
        signal_prices = monthly_prices.loc[:, self.signal_assets].copy()
        momenta = signal_prices.apply(momentum_13612u)
        rows: list[dict] = []
        previous: str | None = None
        for date, scores in momenta.iterrows():
            if scores.isna().any():
                continue
            if scores["TIP"] > 0 and scores["SPY"] > 0:
                regime, signal_selected = "risk-on", "SPY"
            else:
                regime = "risk-off"
                signal_selected = "IEF" if scores["IEF"] >= scores["BIL"] else "BIL"
            selected = self.execution_proxies[signal_selected]
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": signal_prices.loc[date, asset] for asset in self.signal_assets},
                **{f"{asset}_13612u": scores[asset] for asset in self.signal_assets},
                "regime": regime,
                "signal_selected_asset": signal_selected,
                "selected_asset": selected,
                "previous_asset": previous,
                "trade": previous is None or selected != previous,
            })
            previous = selected
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
