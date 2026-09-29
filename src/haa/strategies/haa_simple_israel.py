"""Israel-local-investability HAA-Simple using TIP as a signal-only canary."""
from __future__ import annotations

import pandas as pd

from ..constants import ISRAEL_SIMPLE_ASSETS
from ..momentum import momentum_13612u
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile


class HAASimpleIsrael:
    """TIP canary plus ILS-traded CSPX, Treasury, and money-market sleeves."""

    name = "HAA-Simple Israel"
    data_assets = ISRAEL_SIMPLE_ASSETS
    signal_assets = ISRAEL_SIMPLE_ASSETS
    benchmark_asset = "CSPX_IL"
    equity_asset = "CSPX_IL"
    defensive_bond_asset = "IEF_IL"
    defensive_cash_asset = "AYALON_KASPIT"
    validation_profile = ValidationProfile(
        profile_id="haa-simple-israel",
        published_parameters=(ParameterSpec("momentum_formula", "13612U", (), "Published TIP canary with CSPX, IEF, and Ayalon Kaspit local execution sleeves."),),
        execution=ExecutionSpec("monthly", "Next available TASE trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        data_confidence="moderate",
        notes="The published 13612U formula and the real TASE/Maya sleeves are immutable; this profile declares no parameter sweep or synthetic cash proxy.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        missing = set(self.data_assets) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"HAA-Simple Israel is missing assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, self.data_assets].copy()
        momenta = prices.apply(momentum_13612u)
        rows: list[dict] = []
        previous: str | None = None
        for date, scores in momenta.iterrows():
            # Every series must have real history; neither MAKAM nor another
            # cash proxy is synthesized for the Ayalon fund.
            if scores.isna().any():
                continue
            if scores["TIP"] > 0 and scores[self.equity_asset] > 0:
                regime, selected = "risk-on", self.equity_asset
            else:
                regime = "risk-off"
                selected = self.defensive_bond_asset if scores[self.defensive_bond_asset] >= scores[self.defensive_cash_asset] else self.defensive_cash_asset
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in self.data_assets},
                **{f"{asset}_13612u": scores[asset] for asset in self.data_assets},
                "regime": regime,
                "selected_asset": selected,
                "previous_asset": previous,
                "trade": previous is None or selected != previous,
            })
            previous = selected
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
