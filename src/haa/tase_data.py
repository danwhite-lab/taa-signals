"""Public TASE/Maya acquisition for the Israel-local HAA model.

This adapter deliberately has no TASE Data Hub credential.  ``tasekit`` reads
the public TASE and Maya endpoints, so it is appropriate for personal research
only and can be unavailable when those endpoints change or are blocked.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable

import pandas as pd


TASE_ISRAEL_ASSET_IDS = {
    "CSPX_IL": "1159250",
    "IEF_IL": "1159268",
    "AYALON_KASPIT": "5136866",
    "TA125_SMART_MOMENTUM": "5134713",
    "XLE_IL": "1145903",
    "XLK_IL": "1159193",
    "XLV_IL": "1150390",
    "XLP_IL": "1150366",
}
TASE_ETF_ASSETS = frozenset({"CSPX_IL", "IEF_IL", "XLE_IL", "XLK_IL", "XLV_IL", "XLP_IL"})
PUBLIC_HISTORY_YEARS = 5


class TaseDataError(RuntimeError):
    """Raised when a public TASE/Maya series cannot be safely used."""


@dataclass(frozen=True)
class TaseSeries:
    asset: str
    security_id: str
    prices: pd.Series
    field: str
    source: str


def _normalise_series(frame: pd.DataFrame, field: str, asset: str) -> pd.Series:
    if field not in frame.columns:
        raise TaseDataError(f"{asset}: TASE/Maya did not return the expected '{field}' field.")
    series = pd.to_numeric(frame[field], errors="coerce")
    index = pd.to_datetime(frame.index, errors="coerce")
    if getattr(index, "tz", None) is not None:
        index = index.tz_localize(None)
    result = pd.Series(series.to_numpy(), index=index, name=asset).dropna()
    result = result[~result.index.isna() & ~result.index.duplicated(keep="last")].sort_index()
    if result.empty:
        raise TaseDataError(f"{asset}: TASE/Maya returned no usable price observations.")
    return result


def select_etf_price_field(frame: pd.DataFrame, asset: str) -> tuple[str, str]:
    """Choose the most suitable published field without inventing total return.

    ``Adj Close`` is used only when provided by tasekit.  Otherwise the
    published ETF NAV is preferable to its exchange close; Close is the final
    transparent fallback.  Both fallbacks are labelled in the UI.
    """
    for field, label in (
        ("Adj Close", "Adjusted close"),
        ("NAV", "Published ETF NAV"),
        ("Close", "End-of-day close"),
    ):
        if field in frame.columns and pd.to_numeric(frame[field], errors="coerce").notna().any():
            return field, label
    raise TaseDataError(f"{asset}: TASE ETF history has none of Adj Close, NAV, or Close.")


def _default_security_factory(security_id: str):
    try:
        import tasekit
    except ImportError as exc:  # pragma: no cover - exercised by installed dependency in production
        raise TaseDataError("tasekit is not installed. Install the project's required dependencies.") from exc
    return tasekit.Security(security_id)


class TasePriceSource:
    """Fetch and cache immutable copies of public TASE/Maya price histories."""

    def __init__(self, security_factory: Callable[[str], object] | None = None):
        self._security_factory = security_factory or _default_security_factory
        self._cache: dict[str, TaseSeries] = {}

    def fetch_asset(self, asset: str) -> TaseSeries:
        if asset not in TASE_ISRAEL_ASSET_IDS:
            raise TaseDataError(f"{asset}: no TASE/Maya mapping is configured.")
        if asset in self._cache:
            cached = self._cache[asset]
            return TaseSeries(cached.asset, cached.security_id, cached.prices.copy(), cached.field, cached.source)
        security_id = TASE_ISRAEL_ASSET_IDS[asset]
        try:
            security = self._security_factory(security_id)
            if asset in TASE_ETF_ASSETS:
                # These are TASE-listed *foreign* ETFs.  tasekit's dedicated
                # ``etf_history`` endpoint is for a different ETF endpoint
                # and returns no data for them; normal security history is
                # the supported public series and contains Adj Close.
                frame = security.history(years=PUBLIC_HISTORY_YEARS)
                field, label = select_etf_price_field(frame, asset)
                source = f"TASE via tasekit ({label})"
            else:
                # tasekit maps a regular mutual fund's Close to Maya's
                # published redemption price.  Do not replace it with a proxy.
                frame = security.history(years=PUBLIC_HISTORY_YEARS)
                field, label = "Close", "Maya published redemption price"
                source = f"Maya via tasekit ({label})"
            series = _normalise_series(frame, field, asset)
        except TaseDataError:
            raise
        except Exception as exc:
            raise TaseDataError(
                f"{asset} ({security_id}): public TASE/Maya retrieval failed: {exc}. "
                "Try refresh later or upload an official CSV replacement."
            ) from exc
        result = TaseSeries(asset, security_id, series, label, source)
        self._cache[asset] = result
        return TaseSeries(result.asset, result.security_id, result.prices.copy(), result.field, result.source)

    def fetch_all(self, assets: Iterable[str] = TASE_ISRAEL_ASSET_IDS) -> tuple[pd.DataFrame, pd.DataFrame]:
        series: dict[str, pd.Series] = {}
        metadata: list[dict[str, str]] = []
        for asset in assets:
            item = self.fetch_asset(asset)
            series[asset] = item.prices
            metadata.append({"asset": asset, "source": item.source, "identifier": item.security_id, "price_field": item.field})
        return pd.DataFrame(series), pd.DataFrame(metadata).set_index("asset")


def download_tase_israel_prices() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download the three Israeli sleeves used by HAA-Simple Israel."""
    return TasePriceSource().fetch_all()
