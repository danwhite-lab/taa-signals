"""Bundled long-history proxy inputs for strategy-level backtests.

These files contain strategy return streams, not investable security prices.
The adapter deliberately labels the result as a proxy and uses the existing
monthly engine so its realized-gain tax behavior remains consistent with the
ordinary backtest path.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .comparison import ModelInput


DEEP_HISTORY_DIR = Path(__file__).resolve().parents[2] / "data" / "deep_history"


@dataclass(frozen=True)
class DeepHistorySpec:
    key: str
    label: str
    signal_file: str
    returns_file: str
    buy_and_hold: bool = False
    holding_asset: str = "SP500_TOTAL_RETURN_PROXY"
    completed_only: bool = False
    caveat: str = ""
    usable_through: str | None = None
    daily_signal_history: bool = False
    daily_nav_history: bool = False


@dataclass(frozen=True)
class DeepHistoryBenchmarkSpec:
    asset_id: str
    label: str
    returns_file: str
    caveat: str


DEEP_HISTORY_SPECS = {
    "chimeric": DeepHistorySpec("chimeric", "Chimeric Asset Allocation (supplied proxy)", "chimeric_signals.csv", "chimeric_monthly_returns.csv", completed_only=True, usable_through="2026-09-30", caveat="Supplied strategy-level history from March 1982. Uses BIL, not the implemented variants' SGOV; variant fidelity and pre-ETF reconstruction are unverified. Three September 2026 rows all target October and are excluded, together with October's unfinished return. Reviewed coverage ends September 2026 and requires a source update to extend. Any repeated usable-month signals are rejected, never counted as separate monthly returns. Tax is an allocation-change approximation, not exact security-level CGT."),
    "buy_and_hold_sp500": DeepHistorySpec("buy_and_hold_sp500", "Buy & Hold S&P 500 Total Return", "", "sp500_total_return_proxy_monthly_returns.csv", True),
    "buy_and_hold_global": DeepHistorySpec("buy_and_hold_global", "Buy & Hold Global All-Country Equity USD Proxy", "", "global_all_country_usd_monthly_returns.csv", True, "GLOBAL_EQUITY_TOTAL_RETURN_PROXY"),
    "century_momentum": DeepHistorySpec("century_momentum", "Century Momentum", "century_momentum_signals.csv", "century_momentum_monthly_returns.csv"),
    "haa_simple": DeepHistorySpec("haa_simple", "HAA-Simple", "haa_simple_signals.csv", "haa_simple_monthly_returns.csv"),
    "inflation_compass": DeepHistorySpec("inflation_compass", "Inflation Compass", "inflation_compass_signals.csv", "inflation_compass_monthly_returns.csv"),
    "gem": DeepHistorySpec("gem", "GEM", "gem_signals.csv", "gem_monthly_returns.csv"),
}

SP500_TOTAL_RETURN_BENCHMARK = DeepHistoryBenchmarkSpec(
    asset_id="SP500_TOTAL_RETURN_PROXY",
    label="S&P 500 Total Return Proxy",
    returns_file="sp500_total_return_proxy_monthly_returns.csv",
    caveat="Long monthly S&P Composite total-return proxy with dividends reinvested. It is not actual SPY, and its pre-1957 history is a reconstructed historical composite rather than the modern S&P 500.",
)

GLOBAL_TOTAL_RETURN_BENCHMARK = DeepHistoryBenchmarkSpec(
    asset_id="GLOBAL_EQUITY_TOTAL_RETURN_PROXY",
    label="Global All-Country Equity USD Proxy",
    returns_file="global_all_country_usd_monthly_returns.csv",
    caveat="Nominal USD monthly returns with dividends reinvested, January 1970–September 2026. User-supplied ACWI export from LazyPortfolioETF; history through December 2008 uses equivalent ETFs/assets. Rounded to 0.01 percentage points. This is not actual ACWI/ISAC history throughout, nor an exact FTSE All-World index series. No inflation adjustment or additional dividend tax is applied.",
)

DEEP_HISTORY_BENCHMARKS = {
    "sp500": SP500_TOTAL_RETURN_BENCHMARK,
    "global": GLOBAL_TOTAL_RETURN_BENCHMARK,
}

# Daily imports need explicit handling: synthetic NAV can be blended through
# its monthly adapter and frozen inputs now support modeled trade-level tax;
# the older monthly-return/daily-signal import remains tax unsupported.
DEEP_HISTORY_SINGLE_SPECS = {
    "rvol_synthetic": DeepHistorySpec("rvol_synthetic", "A-RVol Shifter (long synthetic history)",
        "", "arvol_synthetic_v5/daily.csv", holding_asset="ARVOL_SYNTHETIC_NAV_PROXY",
        completed_only=True, usable_through="2026-09-30", daily_signal_history=True, daily_nav_history=True,
        caveat="Fully modeled USD exposure, not actual ETF performance. State transitions match the app on these proxy inputs. Uses NDX price returns without dividends, synthetic leveraged funds and T-bill cash; credit is disabled before May 2007. Execution is next-close before 2001 and next-open thereafter. Optional tax reconstructs daily sale proceeds, average cost and separate sleeve loss carryforwards; cash is an accumulating proxy taxed on sale. No FX/indexation, interest withholding, cross-sleeve loss offsets or terminal liquidation. Additional trading fees remain unsupported. Standalone tests preserve daily NAV; blends use complete months without daily portfolio risk statistics. The benchmark has monthly observations only. Complete months run December 1986–September 2026. Live rules are unchanged."),
    "rvol_daily": DeepHistorySpec("rvol_daily", "A-RVol Shifter (daily supplied proxy)",
        "rvol_daily_signals.csv", "rvol_daily_monthly_returns.csv",
        holding_asset="ARVOL_STRATEGY_NAV_PROXY", completed_only=True,
        usable_through="2026-09-30", daily_signal_history=True,
        caveat="Single strategy only. Supplied monthly returns of a daily-traded model, January 2003–September 2026. All 231 source signal changes are retained, not collapsed to monthly trades. Daily prices, trade values, source fee treatment and exact variant fidelity are unverified. Tax and additional trade-fee modeling are unavailable: monthly NAV cannot reconstruct daily realized gains. Risk statistics and drawdown use monthly observations, not daily drawdown. October's unfinished return is excluded. Live A-RVol rules are unchanged."),
}
ALL_DEEP_HISTORY_SPECS = {**DEEP_HISTORY_SPECS, **DEEP_HISTORY_SINGLE_SPECS}


def deep_history_options(sleeve_count: int) -> tuple[str, ...]:
    specs = ALL_DEEP_HISTORY_SPECS if sleeve_count == 1 else {**DEEP_HISTORY_SPECS, "rvol_synthetic": DEEP_HISTORY_SINGLE_SPECS["rvol_synthetic"]}
    return tuple(sorted(specs, key=lambda key: specs[key].label.casefold()))


def _parse_percent(value: str) -> float | None:
    value = value.strip().replace("%", "")
    if value in {"", "—", "-", "n.a."}:
        return None
    return float(value) / 100


def _parse_allocations(value: str) -> dict[str, float]:
    weights: dict[str, float] = {}
    for item in value.split(","):
        match = re.fullmatch(r"\s*([A-Za-z0-9_]+)\s+([0-9.]+)%\s*", item)
        if not match:
            raise ValueError(f"Unrecognised proxy allocation: {value!r}")
        weights[match.group(1)] = float(match.group(2)) / 100
    if not weights or abs(sum(weights.values()) - 1.0) > 1e-6:
        raise ValueError(f"Proxy allocation does not total 100%: {value!r}")
    return weights


def _read_signals(path: Path) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.reader(handle):
            if not row or row[0] == "Signal date":
                continue
            # Exports can omit the expand-marker cell on the first row.
            date_column = next((i for i in (0, 1) if i < len(row) and re.search(r"\d{4}-\d{2}-\d{2}", row[i])), None)
            if date_column is None or len(row) < date_column + 3:
                continue
            match = re.search(r"(\d{4}-\d{2}-\d{2})", row[date_column])
            if not match:
                continue
            rows.append({"signal_date": pd.Timestamp(match.group(1)), "regime": row[date_column + 1], "target_weights": _parse_allocations(row[date_column + 2])})
    frame = pd.DataFrame(rows).set_index("signal_date").sort_index()
    if frame.empty or frame.index.has_duplicates:
        raise ValueError(f"Signal history is empty or has duplicate dates: {path.name}")
    return frame


def _read_monthly_returns(path: Path) -> pd.Series:
    rows: list[tuple[pd.Timestamp, float]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            year = int(row["Year"])
            for month in range(1, 13):
                value = _parse_percent(row[pd.Timestamp(year, month, 1).strftime("%b")])
                if value is not None:
                    rows.append((pd.Timestamp(year, month, 1) + pd.offsets.MonthEnd(0), value))
    series = pd.Series([value for _, value in rows], index=pd.DatetimeIndex([date for date, _ in rows]), dtype=float).sort_index()
    if series.empty or series.index.has_duplicates:
        raise ValueError(f"Monthly return history is empty or has duplicate months: {path.name}")
    return series


def _read_long_monthly_returns(path: Path) -> pd.Series:
    """Read a tidy year/month nominal-return series without changing its precision."""
    rows: list[tuple[pd.Timestamp, float]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append((
                pd.Timestamp(int(row["year"]), int(row["month"]), 1) + pd.offsets.MonthEnd(0),
                float(row["nominalReturn"]),
            ))
    series = pd.Series([value for _, value in rows], index=pd.DatetimeIndex([date for date, _ in rows]), dtype=float).sort_index()
    if series.empty or series.index.has_duplicates:
        raise ValueError(f"Monthly return history is empty or has duplicate months: {path.name}")
    return series


def _read_benchmark_returns(spec: DeepHistoryBenchmarkSpec) -> pd.Series:
    path = DEEP_HISTORY_DIR / spec.returns_file
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = set(reader.fieldnames or ())
        if "Year" in fieldnames:
            return _read_monthly_returns(path)
        if {"year", "month", "nominalReturn"}.issubset(fieldnames):
            rows = [
                (pd.Timestamp(int(row["year"]), int(row["month"]), 1) + pd.offsets.MonthEnd(0), float(row["nominalReturn"]))
                for row in reader
            ]
        elif {"Date", "Return (%)"}.issubset(fieldnames):
            rows = [
                (pd.to_datetime(row["Date"], format="%m/%Y") + pd.offsets.MonthEnd(0), float(row["Return (%)"]) / 100)
                for row in reader
            ]
        else:
            raise ValueError(f"Unsupported benchmark CSV columns: {path.name}")
    series = pd.Series([value for _, value in rows], index=pd.DatetimeIndex([date for date, _ in rows]), dtype=float).sort_index()
    if series.empty or series.index.has_duplicates:
        raise ValueError(f"Benchmark history is empty or has duplicate months: {path.name}")
    return series


def load_deep_history(spec: DeepHistorySpec) -> tuple[pd.DataFrame, pd.Series]:
    if spec.daily_nav_history:
        from .synthetic_history import load_synthetic_daily
        daily = load_synthetic_daily(DEEP_HISTORY_DIR / spec.returns_file)
        ends = daily.groupby(daily.index.to_period("M")).nav.last()
        returns = ends.pct_change().iloc[1:]
        returns.index = returns.index.to_timestamp("M")
        returns = returns.loc[returns.index <= pd.Timestamp(spec.usable_through)]
        return daily, returns
    signals = _read_signals(DEEP_HISTORY_DIR / spec.signal_file)
    returns = _read_monthly_returns(DEEP_HISTORY_DIR / spec.returns_file)
    if spec.key == "chimeric":
        # User's updated history, supplied 2026-10-07. Preserve the original
        # CSV verbatim; apply this single auditable correction on import.
        corrected_date = pd.Timestamp("2026-08-31")
        if corrected_date not in signals.index:
            raise ValueError("Chimeric source lacks the reviewed August 31 correction row.")
        signals.at[corrected_date, "target_weights"] = {"UPRO": .25, "ERX": .25, "PDBC": .25, "BIL": .25}
        signals.at[corrected_date, "regime"] = "Risk-Off"
    if spec.completed_only:
        cutoff = (pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M") - 1).to_timestamp("M")
        if spec.usable_through:
            cutoff = min(cutoff, pd.Timestamp(spec.usable_through))
        returns = returns.loc[returns.index <= cutoff]
        holding_months = signals.index if spec.daily_signal_history else signals.index + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1)
        signals = signals.loc[holding_months <= cutoff]
    return signals, returns


def deep_history_model_input(
    spec: DeepHistorySpec,
    benchmark: DeepHistoryBenchmarkSpec = SP500_TOTAL_RETURN_BENCHMARK,
) -> ModelInput:
    """Create synthetic monthly prices from the supplied strategy NAV returns.

    Each allocation component receives the same strategy-level NAV. This is
    intentional: component-level security returns are not present in the CSVs,
    so tax events are an allocation-change proxy, not a claim about individual
    security tax lots. The result is restricted to the independently supplied
    benchmark's usable months; no benchmark pre-history is invented.
    """
    if spec.daily_nav_history:
        from .synthetic_history import synthetic_model_input
        return synthetic_model_input(spec.label, DEEP_HISTORY_DIR / spec.returns_file,
            _read_benchmark_returns(benchmark), benchmark.asset_id, spec.usable_through)
    if spec.buy_and_hold or spec.daily_signal_history:
        path = DEEP_HISTORY_DIR / spec.returns_file
        returns = (load_deep_history(spec)[1] if spec.daily_signal_history else
                   _read_monthly_returns(path) if spec.key == "buy_and_hold_global" else _read_long_monthly_returns(path))
        benchmark_returns = _read_benchmark_returns(benchmark)
        common_months = returns.index.intersection(benchmark_returns.index)
        returns = returns.loc[common_months]
        if len(returns) < 2:
            raise ValueError(f"{spec.label} has fewer than two aligned proxy holding periods.")
        expected = pd.date_range(returns.index.min(), returns.index.max(), freq="ME")
        if not returns.index.equals(expected):
            raise ValueError(f"{spec.label} has gaps in aligned proxy holding periods.")
        signal_index = pd.DatetimeIndex(returns.index - pd.offsets.MonthEnd(1))
        levels = [100.0]
        for period_return in returns:
            levels.append(levels[-1] * (1 + float(period_return)))
        terminal_date = returns.index[-1]
        prices = pd.DataFrame(
            {spec.holding_asset: levels},
            index=signal_index.append(pd.DatetimeIndex([terminal_date])),
        )
        benchmark_levels = [100.0]
        for period_return in benchmark_returns.loc[common_months]:
            benchmark_levels.append(benchmark_levels[-1] * (1 + float(period_return)))
        prices[benchmark.asset_id] = benchmark_levels
        decisions = pd.DataFrame(
            [{"target_weights": {spec.holding_asset: 1.0}, "selected_asset": spec.holding_asset} for _ in signal_index],
            index=signal_index,
        )
        if spec.daily_signal_history:
            # Monthly observation dates are not source trade dates. This NAV
            # must never masquerade as a no-tax daily implementation.
            decisions.attrs.update(single_strategy_only=True, tax_supported=False, trade_cost_supported=False)
        return ModelInput(spec.label, decisions, prices, None, benchmark.asset_id)
    signals, returns = load_deep_history(spec)
    rows: list[tuple[pd.Timestamp, dict[str, float], float]] = []
    for signal_date, signal in signals.iterrows():
        # Some early source rows use the penultimate trading day rather than
        # the calendar month-end; normalize before advancing one month.
        holding_month = signal_date + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1)
        if holding_month in returns.index:
            rows.append((signal_date, signal["target_weights"], float(returns.loc[holding_month])))
    benchmark_returns = _read_benchmark_returns(benchmark)
    rows = [
        row for row in rows
        if row[0] + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1) in benchmark_returns.index
    ]
    if len(rows) < 2:
        raise ValueError(f"{spec.label} has fewer than two aligned proxy holding periods.")
    rows.sort(key=lambda item: item[0])
    signal_index = pd.DatetimeIndex(
        signal_date + pd.offsets.MonthEnd(0) for signal_date, _, _ in rows
    )
    if signal_index.has_duplicates:
        raise ValueError(f"{spec.label} has duplicate calendar-month signals. Monthly returns cannot reconstruct intramonth trades; supply confirmed final monthly allocations or daily security-level history.")
    expected = pd.date_range(signal_index.min(), signal_index.max(), freq="ME")
    if not signal_index.equals(expected):
        raise ValueError(f"{spec.label} has gaps in aligned proxy holding periods; missing months cannot be bridged.")
    terminal_date = signal_index[-1] + pd.offsets.MonthEnd(1)
    levels = [100.0]
    for _, _, period_return in rows:
        levels.append(levels[-1] * (1 + period_return))
    assets = sorted({asset for _, weights, _ in rows for asset in weights} | {"SPY"})
    prices = pd.DataFrame({asset: levels for asset in assets}, index=signal_index.append(pd.DatetimeIndex([terminal_date])))
    benchmark_holding_months = pd.DatetimeIndex(
        signal_date + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1)
        for signal_date, _, _ in rows
    )
    benchmark_levels = [100.0]
    for holding_month in benchmark_holding_months:
        benchmark_levels.append(benchmark_levels[-1] * (1 + float(benchmark_returns.loc[holding_month])))
    prices[benchmark.asset_id] = benchmark_levels
    decisions = pd.DataFrame(
        [{"target_weights": weights, "selected_asset": next(iter(weights)) if len(weights) == 1 else ", ".join(weights), "proxy_return": period_return} for _, weights, period_return in rows],
        index=signal_index,
    )
    # Add the known return of the final signal as a terminal price. It is based
    # solely on its supplied monthly return; no subsequent signal is invented.
    return ModelInput(spec.label, decisions, prices, None, benchmark.asset_id)
