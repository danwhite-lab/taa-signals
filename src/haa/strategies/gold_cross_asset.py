"""Monthly absolute trend in gold and intermediate US Treasuries."""
import numpy as np
import pandas as pd

from ..constants import TACHLIT_HEDGED_GOLD_ASSET
from ..data import to_month_end
from ..market_sessions import us_equity_sessions
from ..portfolio import execution_security_label

INTERPRETATION = "Implementation interpretation - exact Laurent conventions unverified"
RULE = (
    "The supplied rule holds gold only when both gold and 7–10-year US Treasuries have risen over "
    "the previous 12 months. Otherwise it holds a near-cash fund. Treasuries supply a signal only. "
    "This implementation uses original USD Yahoo adjusted closes for GLD and IEF, including "
    "distribution adjustments. It compares the last US trading close of each completed month "
    "with the close exactly 12 calendar months earlier. Both returns must be strictly positive. "
    "A signal requires 13 consecutive valid month-end observations for both assets. "
    "Orders are modeled at the first eligible execution-market close or NAV in the following month. "
    "Switching can miss recoveries and incur fees and realized-sale tax. The rule can still lose money "
    "or remain underwater for long periods. Coverage is limited to actual fund history."
)


class GoldCrossAsset:
    name = "Gold Cross-Asset"
    signal_assets = market_data_assets = ("GLD", "IEF")
    execution_assets = ("GLD", "BIL")
    data_assets = (*signal_assets, "BIL")
    require_adjusted_assets = data_assets
    benchmark_asset = "GLD"
    execution_currency = "USD"
    execution_market = "US"
    uses_daily_signals = True
    backtest_available = True
    notes = f"{INTERPRETATION}. {RULE} USD holds GLD or BIL, a 1–3 month Treasury-bill ETF used as a cash proxy. Benchmark: buy-and-hold GLD. Actual histories only, with no pre-inception splice."

    def decisions(self, daily_prices, as_of=None, include_current_month=False):
        prices = daily_prices.loc[:, list(self.signal_assets)].sort_index()
        if prices.empty:
            return pd.DataFrame()
        clock = pd.Timestamp.now(tz="UTC") if as_of is None else pd.Timestamp(as_of)
        clock = clock.tz_localize(None)
        last_month = clock.to_period("M") - 1
        first_month = prices.index.min().to_period("M")
        if first_month > last_month:
            return pd.DataFrame()

        # Reuse completed-month processing, but require the actual US month-end
        # close for both legs. A quote missing on that session cannot fall back
        # to an earlier price from the same month.
        sessions = us_equity_sessions(str(first_month.start_time.date()), str(last_month.end_time.date()))
        final_sessions = sessions.to_series().groupby(sessions.to_period("M")).last()
        monthly = to_month_end(prices.reindex(pd.DatetimeIndex(final_sessions)), as_of=clock)
        monthly.index = monthly.index.to_period("M")
        periods = pd.period_range(first_month, last_month, freq="M")
        monthly = monthly.reindex(periods).astype(float)
        monthly = monthly.where(np.isfinite(monthly) & monthly.gt(0))
        valid = monthly.notna().all(axis=1).rolling(13).sum().eq(13)
        returns = monthly.div(monthly.shift(12)).sub(1)
        returns = returns.loc[valid & np.isfinite(returns).all(axis=1)]

        rows = []
        previous, previous_month = None, None
        for month, values in returns.iterrows():
            if previous_month != month - 1:
                previous = None
            gold = bool(values.gt(0).all())
            selected = self.execution_assets[0 if gold else 1]
            rows.append({
                "signal_date": final_sessions.loc[month],
                "source_month_end": month.to_timestamp("M"),
                "GLD_12m_return": values["GLD"],
                "IEF_12m_return": values["IEF"],
                "both_positive": gold,
                "regime": "risk-on" if gold else "risk-off",
                "selected_asset": selected,
                "previous_asset": previous,
                "trade": previous != selected,
                "target_weights": {selected: 1.0},
                "execution_currency": self.execution_currency,
            })
            previous, previous_month = selected, month
        result = pd.DataFrame(rows).set_index("signal_date") if rows else pd.DataFrame()
        result.attrs["monthly_execution_market"] = self.execution_market
        return result

    def signal_details(self, signal):
        return {
            "Signal month-end": pd.Timestamp(signal["source_month_end"]).date().isoformat(),
            "US close date": pd.Timestamp(signal.name).date().isoformat(),
            "GLD 12-month return": f"{signal['GLD_12m_return']:.2%}",
            "IEF 12-month return": f"{signal['IEF_12m_return']:.2%}",
            "Rule result": "Both positive" if signal["both_positive"] else "At least one non-positive",
            "Target holding": execution_security_label(signal["selected_asset"], self.execution_currency),
            "Execution currency": self.execution_currency,
        }


class GoldCrossAssetIsrael(GoldCrossAsset):
    name = "Gold Cross-Asset Israel"
    execution_assets = (TACHLIT_HEDGED_GOLD_ASSET, "RVOL_CASH_IL")
    data_assets = (*GoldCrossAsset.signal_assets, *execution_assets)
    require_adjusted_assets = GoldCrossAsset.signal_assets
    benchmark_asset = TACHLIT_HEDGED_GOLD_ASSET
    execution_currency = "ILS"
    execution_market = "TASE"
    notes = f"{INTERPRETATION}. {RULE} Israel uses the same USD signal. It holds hedged Tachlit gold (5141627) or Ayalon Kaspit (5117700), a shekel money-market fund used as near-cash. Benchmark: buy-and-hold hedged Tachlit gold. Returns use actual ILS redemption history only, with no earlier fund or USD proxy spliced in. Execution dates use TASE sessions and the hedged gold fund’s dealing schedule, including for the benchmark."
