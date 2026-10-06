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


@dataclass(frozen=True)
class DeepHistoryBenchmarkSpec:
    asset_id: str
    label: str
    returns_file: str
    caveat: str


DEEP_HISTORY_SPECS = {
    "century_momentum": DeepHistorySpec("century_momentum", "Century Momentum", "century_momentum_signals.csv", "century_momentum_monthly_returns.csv"),
    "haa_simple": DeepHistorySpec("haa_simple", "HAA-Simple", "haa_simple_signals.csv", "haa_simple_monthly_returns.csv"),
    "inflation_compass": DeepHistorySpec("inflation_compass", "Inflation Compass", "inflation_compass_signals.csv", "inflation_compass_monthly_returns.csv"),
}

US_TOTAL_MARKET_BENCHMARK = DeepHistoryBenchmarkSpec(
    asset_id="US_TOTAL_MARKET_VTI_PROXY",
    label="US Total Market VTI Proxy",
    returns_file="us_total_market_vti_proxy_monthly_returns.csv",
    caveat="Before May 2001, this series uses stand-in funds (VTSMX and VFINX). It is a simulated total-U.S.-market proxy, not actual pre-inception VTI or S&P 500/SPY history.",
)


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
            if len(row) < 4:
                continue
            match = re.search(r"(\d{4}-\d{2}-\d{2})", row[1])
            if not match:
                continue
            rows.append({"signal_date": pd.Timestamp(match.group(1)), "regime": row[2], "target_weights": _parse_allocations(row[3])})
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
    series = pd.Series(dict(rows), dtype=float).sort_index()
    if series.empty or series.index.has_duplicates:
        raise ValueError(f"Monthly return history is empty or has duplicate months: {path.name}")
    return series


def load_deep_history(spec: DeepHistorySpec) -> tuple[pd.DataFrame, pd.Series]:
    signals = _read_signals(DEEP_HISTORY_DIR / spec.signal_file)
    returns = _read_monthly_returns(DEEP_HISTORY_DIR / spec.returns_file)
    return signals, returns


def deep_history_model_input(
    spec: DeepHistorySpec,
    benchmark: DeepHistoryBenchmarkSpec = US_TOTAL_MARKET_BENCHMARK,
) -> ModelInput:
    """Create synthetic monthly prices from the supplied strategy NAV returns.

    Each allocation component receives the same strategy-level NAV. This is
    intentional: component-level security returns are not present in the CSVs,
    so tax events are an allocation-change proxy, not a claim about individual
    security tax lots. The result is restricted to the independently supplied
    benchmark's usable months; no benchmark pre-history is invented.
    """
    signals, returns = load_deep_history(spec)
    rows: list[tuple[pd.Timestamp, dict[str, float], float]] = []
    for signal_date, signal in signals.iterrows():
        # Some early source rows use the penultimate trading day rather than
        # the calendar month-end; normalize before advancing one month.
        holding_month = signal_date + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1)
        if holding_month in returns.index:
            rows.append((signal_date, signal["target_weights"], float(returns.loc[holding_month])))
    benchmark_returns = _read_monthly_returns(DEEP_HISTORY_DIR / benchmark.returns_file)
    rows = [
        row for row in rows
        if row[0] + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1) in benchmark_returns.index
    ]
    if len(rows) < 2:
        raise ValueError(f"{spec.label} has fewer than two aligned proxy holding periods.")
    rows.sort(key=lambda item: item[0])
    levels = [100.0]
    for _, _, period_return in rows[:-1]:
        levels.append(levels[-1] * (1 + period_return))
    index = pd.DatetimeIndex([row[0] for row in rows])
    assets = sorted({asset for _, weights, _ in rows for asset in weights} | {"SPY"})
    prices = pd.DataFrame({asset: levels for asset in assets}, index=index)
    benchmark_holding_months = pd.DatetimeIndex(
        signal_date + pd.offsets.MonthEnd(0) + pd.offsets.MonthEnd(1)
        for signal_date, _, _ in rows[:-1]
    )
    benchmark_levels = [100.0]
    for holding_month in benchmark_holding_months:
        benchmark_levels.append(benchmark_levels[-1] * (1 + float(benchmark_returns.loc[holding_month])))
    prices[benchmark.asset_id] = benchmark_levels
    decisions = pd.DataFrame(
        [{"target_weights": weights, "selected_asset": next(iter(weights)) if len(weights) == 1 else ", ".join(weights), "proxy_return": period_return} for _, weights, period_return in rows],
        index=index,
    )
    # The final return is represented by the next price point only when there
    # is a following signal; run_backtest therefore excludes the open last row.
    return ModelInput(spec.label, decisions, prices, None, benchmark.asset_id)
