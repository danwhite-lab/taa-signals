"""Reusable internally managed strategies held continuously by the investor."""
from __future__ import annotations

import pandas as pd

from ..constants import TA125_SMART_MOMENTUM_ASSET


class TA125SmartMomentum:
    """A fund-held implementation; momentum selection happens inside its index."""

    name = "TA-125 Smart Momentum"
    data_assets = (TA125_SMART_MOMENTUM_ASSET, "SPY")
    market_data_assets = data_assets
    signal_assets: tuple[str, ...] = ()
    benchmark_asset = "SPY"
    strategy_mode = "buy_and_hold"
    signal_mode = "internal"
    backtest_available = True

    def decisions(self, monthly_prices: pd.DataFrame) -> pd.DataFrame:
        """Remain fully invested whenever fund and benchmark prices are available."""
        prices = monthly_prices.loc[:, self.data_assets]
        rows: list[dict[str, object]] = []
        for date, values in prices.dropna(how="any").iterrows():
            rows.append({
                "signal_date": date,
                **{f"{asset}_price": values[asset] for asset in self.data_assets},
                "regime": "buy-and-hold",
                "selected_asset": TA125_SMART_MOMENTUM_ASSET,
                "previous_asset": TA125_SMART_MOMENTUM_ASSET if rows else None,
                "trade": not rows,
            })
        return pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
