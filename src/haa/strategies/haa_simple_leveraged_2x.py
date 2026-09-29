"""HAA-Simple 2x: SPY signals with SSO exposure in risk-on periods."""
from __future__ import annotations

import pandas as pd

from ..constants import LEVERAGED_ASSETS
from ..validation import ExecutionSpec, ParameterSpec, ValidationProfile
from .haa_simple import HAASimple


class HAASimpleLeveraged2x(HAASimple):
    """Use unleveraged SPY for the gate and SSO only as the risk-on holding."""

    name = "HAA-Simple Leveraged 2x (SSO)"
    risk_on_asset = "SSO"
    data_assets = ("SPY", "TIP", "IEF", "BIL", *LEVERAGED_ASSETS)
    risk_warning = "High-drawdown satellite, not a core holding."
    validation_profile = ValidationProfile(
        profile_id="haa-simple-leveraged-2x",
        published_parameters=(ParameterSpec("momentum_formula", "13612U", (), "Published SPY/TIP gate and IEF/BIL defense; SSO is a fixed risk-on execution holding."),),
        execution=ExecutionSpec("monthly", "Next available trading-day close after the month-end signal", (0, 1, 2), (-2, -1, 0, 1, 2)),
        applicable_tests=frozenset({"execution_delay", "rebalance_shift", "alternate_start_dates", "rolling_windows", "subperiods", "transaction_costs", "israeli_tax", "signal_perturbation", "block_bootstrap", "data_quality"}),
        notes="The published HAA-Simple rule and fixed SSO execution mapping are immutable; this profile declares no parameter sweep.",
    )

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        if "SSO" not in monthly_prices.columns:
            raise ValueError("HAA-Simple Leveraged 2x requires SSO price history.")
        decisions = super().decisions(monthly_prices)
        if decisions.empty:
            return decisions
        decisions["SSO_price"] = monthly_prices.loc[decisions.index, "SSO"]
        risk_on = decisions["regime"].eq("risk-on")
        # SSO price availability is required for a risk-on trade, but SSO
        # momentum is deliberately never used to determine the regime.
        decisions = decisions.loc[~(risk_on & decisions["SSO_price"].isna())].copy()
        decisions.loc[decisions["regime"].eq("risk-on"), "selected_asset"] = "SSO"
        decisions["previous_asset"] = decisions["selected_asset"].shift()
        decisions["trade"] = decisions["previous_asset"].isna() | decisions["selected_asset"].ne(decisions["previous_asset"])
        return decisions
