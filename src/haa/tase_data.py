"""Public TASE/Maya acquisition for the Israel-local HAA model.

This adapter deliberately has no TASE Data Hub credential.  ``tasekit`` reads
the public TASE and Maya endpoints, so it is appropriate for personal research
only and can be unavailable when those endpoints change or are blocked.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping

import pandas as pd


TASE_ISRAEL_ASSET_IDS = {
    "RVOL_3X_IL": "1187079",
    "RVOL_QQQ_IL": "1149038",
    "RVOL_SPY_IL": "1144385",
    "RVOL_LQD_IL": "1159185",
    "RVOL_HYG_IL": "1159078",
    "RVOL_CASH_IL": "5117700",
    "CSPX_IL": "1159250",
    "FTSE_ALL_WORLD_IL": "1209220",
    "QQQ_IL": "1186063",
    "IEF_IL": "1159268",
    "SPMO_IL": "5140850",
    "AYALON_KASPIT": "5136866",
    "TA125_SMART_MOMENTUM": "5134713",
    "XLE_IL": "1145903",
    "XLK_IL": "1159193",
    "XLV_IL": "1150390",
    "XLP_IL": "1150366",
}
TASE_ETF_ASSETS = frozenset({"RVOL_3X_IL", "RVOL_QQQ_IL", "RVOL_SPY_IL", "RVOL_LQD_IL", "RVOL_HYG_IL", "CSPX_IL", "FTSE_ALL_WORLD_IL", "QQQ_IL", "IEF_IL", "SPMO_IL", "XLE_IL", "XLK_IL", "XLV_IL", "XLP_IL"})
PUBLIC_HISTORY_YEARS = 5

# Default locally tradable implementations for the substitution mode. They
# deliberately represent practical Israeli execution choices, not claims that
# their return histories or exposures are identical to the original U.S. role.
ISRAEL_DEFAULT_TASE_SUBSTITUTIONS = {
    "SPY": "1159250",
    "IEF": "1159268",
    "BIL": "5136866",
    "SPMO": "5140850",
    "XLE": "1145903",
    "XLK": "1159193",
    "XLV": "1150390",
    "XLP": "1150366",
    "VEA": "5142476",
    "VNQ": "5131834",
    "VWO": "1159169",
    "BND": "1146638",
    "AGG": "1146638",
    "TIP": "1159060",
    "DBC": "1147875",
    "LQD": "1159185",
}


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


def download_tase_israel_prices(assets: Iterable[str] = TASE_ISRAEL_ASSET_IDS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download the requested Israeli security histories."""
    return TasePriceSource().fetch_all(assets)


def download_tase_security_prices(role_to_security_id: Mapping[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch user-selected TASE security histories under canonical asset roles.

    Custom mode accepts numeric TASE *security* identifiers. TASE indices use
    a different public endpoint and are intentionally not treated as a
    security ticker here. The UI makes that distinction explicit.
    """
    series: dict[str, pd.Series] = {}
    metadata: list[dict[str, str]] = []
    for role, raw_identifier in role_to_security_id.items():
        security_id = str(raw_identifier).strip()
        if not security_id.isdigit():
            raise TaseDataError(f"{role}: TASE security ID must contain digits only.")
        try:
            security = _default_security_factory(security_id)
            frame = security.history(years=PUBLIC_HISTORY_YEARS)
            field, label = select_etf_price_field(frame, role)
            series[role] = _normalise_series(frame, field, role)
            metadata.append({"asset": role, "source": f"TASE via tasekit ({label})", "identifier": security_id, "price_field": label})
        except TaseDataError:
            raise
        except Exception as exc:
            raise TaseDataError(
                f"{role} ({security_id}): public TASE retrieval failed: {exc}. "
                "Verify the security ID or use a Yahoo ticker/CSV history instead."
            ) from exc
    return pd.DataFrame(series), pd.DataFrame(metadata).set_index("asset")
