"""Canonical HAA-Simple decision rules only; no portfolio accounting lives here."""
from __future__ import annotations

import pandas as pd

from ..constants import ASSETS, STRATEGY_NAME
from ..momentum import momentum_13612u
from ..validation import ExecutionSpec, ParameterSpec, ProxySpec, ValidationProfile


class HAASimple:
    name = STRATEGY_NAME
    validation_profile = ValidationProfile(
        profile_id="haa-simple",
        published_parameters=(
            ParameterSpec("momentum_formula", "13612U", (), "Equal-weighted 1/3/6/12-month momentum."),
        ),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "proxy_substitution", "signal_perturbation", "data_quality"}),
        proxy_substitutions=(ProxySpec("SPY", "CSPX_IL", "Israeli-listed S&P 500 UCITS execution proxy.", "ILS"),),
        notes="The published 13612U formula is immutable; this profile declares no parameter sweep.",
    )

    @staticmethod
    def select_asset(spy_momentum: float, tip_momentum: float, ief_momentum: float, bil_momentum: float) -> tuple[str, str]:
        """Return (regime, selected asset) for one fully known month-end signal."""
        if spy_momentum > 0 and tip_momentum > 0:
            return "risk-on", "SPY"
        return "risk-off", "IEF" if ief_momentum > bil_momentum else "BIL"

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        """Make month-end decisions, leaving execution to the next holding period.

        Every canonical asset must have a valid 12-month score.  In particular,
        the strategy does not create pre-inception BIL history or silently use
        IEF as a substitute for unavailable BIL data.
        """
        missing = set(ASSETS) - set(monthly_prices.columns)
        if missing:
            raise ValueError(f"Missing canonical assets: {sorted(missing)}")
        prices = monthly_prices.loc[:, ASSETS].copy()
        momenta = prices.apply(momentum_13612u)
        rows: list[dict] = []
        previous: str | None = None
        for date, values in momenta.iterrows():
            if values.isna().any():
                continue
            if values["SPY"] > 0 and values["TIP"] > 0:
                regime, selected = "risk-on", "SPY"
            else:
                regime = "risk-off"
                # Published rule says "higher"; make an exact tie deterministic.
                selected = "IEF" if values["IEF"] >= values["BIL"] else "BIL"
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": prices.loc[date, asset] for asset in ASSETS},
                **{f"{asset}_13612u": values[asset] for asset in ASSETS},
                "regime": regime,
                "selected_asset": selected,
                "previous_asset": previous,
                "trade": previous is None or selected != previous,
            })
            previous = selected
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
