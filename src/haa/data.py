"""Yahoo Finance acquisition and transparent daily/month-end data preparation."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import re
from typing import Iterable, Mapping

import pandas as pd

from .constants import ASSETS

OECD_CLI_COUNTRIES = ("AUS", "CAN", "FRA", "DEU", "ITA", "JPN", "KOR", "MEX", "ESP", "TUR", "GBR", "USA", "BRA", "CHN", "IND", "IDN", "ZAF")
OECD_CLI_URL = "https://sdmx.oecd.org/public/rest/data/OECD.SDD.STES,DSD_STES@DF_CLI,4.1/.M.LI...AA...H?dimensionAtObservation=AllDimensions&format=csvfile"

DEFAULT_TICKER_MAP = {
    **{asset: asset for asset in ASSETS},
    "CSPX_IL": "1159250.TA",
    "IEF_IL": "1159268.TA",
    "AYALON_KASPIT": "5136866.TA",
}


def default_ticker_map(assets: Iterable[str]) -> dict[str, str]:
    return {asset: DEFAULT_TICKER_MAP.get(asset, asset) for asset in assets}


def _normalise_frame(frame: pd.DataFrame, asset: str) -> pd.Series:
    """Extract an adjusted close series, falling back to Close only if necessary."""
    if isinstance(frame.columns, pd.MultiIndex):
        # yfinance can return either (field, ticker) or (ticker, field).
        for field in ("Adj Close", "Close"):
            if field in frame.columns.get_level_values(0):
                candidate = frame[field]
                return candidate[asset] if isinstance(candidate, pd.DataFrame) else candidate
            if field in frame.columns.get_level_values(1):
                return frame.xs(field, axis=1, level=1)[asset]
    for field in ("Adj Close", "Close"):
        if field in frame.columns:
            return frame[field]
    raise ValueError(f"{asset}: CSV/data must include 'Adj Close' or 'Close'.")


def parse_ticker_map(text: str, required_assets: Iterable[str] = ASSETS) -> dict[str, str]:
    """Parse canonical-role-to-Yahoo-ticker entries such as ``SPY=SPY``.

    Roles stay fixed for HAA-Simple. The editable ticker is only a transparent
    data-source replacement for that role, useful for validation.
    """
    required = tuple(required_assets)
    mapping: dict[str, str] = {}
    entries = [entry.strip() for entry in re.split(r"[,\n]+", text) if entry.strip()]
    for entry in entries:
        if "=" not in entry:
            raise ValueError(f"Use ROLE=TICKER entries, for example SPY=SPY; received '{entry}'.")
        role, ticker = (part.strip().upper() for part in entry.split("=", 1))
        if role not in required:
            raise ValueError(f"'{role}' is not valid for this model. Use only: {', '.join(required)}.")
        if not ticker:
            raise ValueError(f"{role}: Yahoo ticker cannot be empty.")
        if role in mapping:
            raise ValueError(f"{role} appears more than once.")
        mapping[role] = ticker
    missing = set(required) - set(mapping)
    if missing:
        raise ValueError(f"Missing Yahoo ticker mapping for: {', '.join(sorted(missing))}.")
    return mapping


def upload_asset_from_filename(filename: str, allowed_assets: Iterable[str] = ASSETS) -> str:
    """Resolve the canonical target role from a CSV filename, e.g. ``SPY.csv``."""
    tokens = set(filter(None, re.split(r"[^A-Z0-9]+", Path(filename).stem.upper())))
    allowed = tuple(allowed_assets)
    matches = tokens.intersection(allowed)
    if len(matches) != 1:
        raise ValueError(f"{filename}: name the file with exactly one valid asset ({', '.join(allowed)}), e.g. SPY.csv.")
    return matches.pop()


def download_yahoo_prices(ticker_map: Mapping[str, str] | None = None) -> pd.DataFrame:
    """Download each canonical role from its selected Yahoo ticker source."""
    import yfinance as yf

    sources = dict(ticker_map or DEFAULT_TICKER_MAP)
    if not sources:
        raise ValueError("Provide at least one Yahoo ticker mapping.")
    raw = yf.download(list(sources.values()), period="max", auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError("Yahoo Finance returned no data. Try again or upload CSV files.")
    result = pd.DataFrame({asset: _normalise_frame(raw, ticker) for asset, ticker in sources.items()})
    result = _clean_prices(result)
    unavailable = [asset for asset in sources if result[asset].dropna().empty]
    if unavailable:
        raise RuntimeError(
            "Yahoo Finance returned no usable price history for: "
            f"{', '.join(unavailable)}. Try again later or verify the ticker mapping."
        )
    return result


def adjusted_yahoo_daily_bars(raw: pd.DataFrame, sources: Mapping[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Extract close/open on one total-return scale; never substitute a close for an open."""
    def field(name: str, ticker: str) -> pd.Series:
        if isinstance(raw.columns, pd.MultiIndex):
            if name in raw.columns.get_level_values(0):
                return raw[name][ticker]
            if name in raw.columns.get_level_values(1):
                return raw.xs(name, axis=1, level=1)[ticker]
        elif name in raw.columns:
            return raw[name]
        raise ValueError(f"{ticker}: next-open execution requires Open, Close and Adj Close from the same source.")
    closes, opens = {}, {}
    for asset, ticker in sources.items():
        adjusted = field('Adj Close', ticker)
        close = field('Close', ticker)
        opening = field('Open', ticker)
        factor = adjusted / close.where(close > 0)
        closes[asset] = adjusted
        opens[asset] = opening * factor
    return _clean_prices(pd.DataFrame(closes)), _clean_prices(pd.DataFrame(opens))


def download_yahoo_daily_bars(ticker_map: Mapping[str, str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download adjusted closes and correspondingly adjusted opens in one request."""
    import yfinance as yf
    sources = dict(ticker_map)
    if not sources:
        raise ValueError("Provide at least one Yahoo ticker mapping.")
    raw = yf.download(list(sources.values()), period='max', auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError("Yahoo Finance returned no daily bars.")
    closes, opens = adjusted_yahoo_daily_bars(raw, sources)
    if any(closes[a].dropna().empty or opens[a].dropna().empty for a in sources):
        raise RuntimeError("Required adjusted close/open history is unavailable; refusing close-price execution fallback.")
    return closes, opens


def download_latest_yahoo_close(ticker: str) -> tuple[float, pd.Timestamp]:
    """Return Yahoo Finance's most recent available close and its timestamp.

    A short intraday history makes this suitable for an informational quote in
    the Portfolio page.  It deliberately does not participate in backtests.
    """
    import yfinance as yf

    history = yf.Ticker(ticker).history(period="5d", interval="1h", auto_adjust=False)
    if history.empty or "Close" not in history:
        raise RuntimeError(f"Yahoo Finance returned no recent close for {ticker}.")
    closes = pd.to_numeric(history["Close"], errors="coerce").dropna()
    if closes.empty:
        raise RuntimeError(f"Yahoo Finance returned no usable close for {ticker}.")
    timestamp = pd.Timestamp(closes.index[-1])
    if timestamp.tzinfo is not None:
        timestamp = timestamp.tz_convert("UTC").tz_localize(None)
    return float(closes.iloc[-1]), timestamp


def download_fred_series(series_ids: Iterable[str]) -> pd.DataFrame:
    """Download public daily FRED observations without fabricating gaps."""
    series = tuple(series_ids)
    result: dict[str, pd.Series] = {}
    for series_id in series:
        url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}"
        try:
            frame = pd.read_csv(url)
        except Exception as exc:
            raise RuntimeError(f"FRED download failed for {series_id}: {exc}") from exc
        date_column = next((column for column in frame.columns if str(column).strip().lower() in {"date", "observation_date"}), None)
        if date_column is None:
            raise RuntimeError(f"FRED response for {series_id} did not contain a date column.")
        if series_id not in frame.columns:
            raise RuntimeError(f"FRED response did not contain {series_id}.")
        frame[date_column] = pd.to_datetime(frame[date_column], errors="coerce")
        result[series_id] = pd.to_numeric(frame.dropna(subset=[date_column]).set_index(date_column)[series_id], errors="coerce")
    return _clean_prices(pd.DataFrame(result))


def download_oecd_cli_diffusion() -> pd.DataFrame:
    """Return the dynamic-country OECD CLI diffusion index as a daily series.

    The source is monthly.  Expanding each released value across calendar days
    lets the strategy align it with market month-ends; the strategy itself
    applies the mandatory one-month publication lag.
    """
    try:
        frame = pd.read_csv(OECD_CLI_URL)
    except Exception as exc:
        raise RuntimeError(f"OECD CLI download failed: {exc}") from exc
    columns = {str(column).strip().upper().replace(" ", "_"): column for column in frame.columns}
    try:
        area, period, value = (columns["REF_AREA"], columns["TIME_PERIOD"], columns["OBS_VALUE"])
    except KeyError as exc:
        raise RuntimeError("OECD CLI response did not contain REF_AREA, TIME_PERIOD, and OBS_VALUE.") from exc
    panel = frame.loc[frame[area].isin(OECD_CLI_COUNTRIES), [area, period, value]].copy()
    panel[period] = pd.to_datetime(panel[period], errors="coerce")
    panel[value] = pd.to_numeric(panel[value], errors="coerce")
    panel = panel.dropna(subset=[period]).pivot_table(index=period, columns=area, values=value, aggfunc="last").sort_index()
    if panel.empty:
        raise RuntimeError("OECD CLI response contained no usable individual-country observations.")
    changes = panel.diff()
    diffusion = changes.gt(0).where(changes.notna()).mean(axis=1).rename("OECD_CLI_DIFFUSION")
    # OECD periods arrive as month labels.  Daily forward fill only carries the
    # published monthly reading; the decision rule delays it by one month.
    return diffusion.resample("D").ffill().to_frame()


def read_uploaded_csv(content: bytes, asset: str) -> pd.Series:
    """Read a validation replacement CSV with Date plus Adj Close or Close."""
    frame = pd.read_csv(BytesIO(content))
    date_col = next((c for c in frame.columns if c.lower() in {"date", "datetime"}), None)
    if date_col is None:
        raise ValueError(f"{asset}: CSV requires a Date column.")
    frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
    frame = frame.dropna(subset=[date_col]).set_index(date_col).sort_index()
    series = _normalise_frame(frame, asset).rename(asset)
    return _clean_prices(series.to_frame())[asset]


def combine_replacements(downloaded: pd.DataFrame, replacements: Mapping[str, pd.Series], assets: Iterable[str] = ASSETS) -> pd.DataFrame:
    """Replace whole asset histories supplied for validation; never fill invented data."""
    combined = downloaded.copy()
    for asset, series in replacements.items():
        combined = combined.drop(columns=asset, errors="ignore").join(series.rename(asset), how="outer")
    return _clean_prices(combined.reindex(columns=tuple(assets)))


def _clean_prices(prices: pd.DataFrame) -> pd.DataFrame:
    result = prices.copy()
    result.index = pd.to_datetime(result.index).tz_localize(None)
    result = result[~result.index.duplicated(keep="last")].sort_index()
    return result.apply(pd.to_numeric, errors="coerce")


def to_month_end(daily_prices: pd.DataFrame, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Return completed month observations without inventing trading sessions.

    The current calendar month is deliberately excluded.  This prevents a
    partial month from being relabelled as its future calendar month-end.

    Each asset contributes its own final valid close in a completed calendar
    month.  The row is indexed by the latest of those actual sessions.  Thus,
    for a U.S. Friday month-end and a TASE Thursday month-end, the Friday row
    contains Friday's U.S. close and Thursday's already-known TASE close.  No
    series is forward-filled across exchange calendars.
    """
    prices = _clean_prices(daily_prices)
    timestamp = pd.Timestamp.now(tz="UTC").tz_localize(None) if as_of is None else pd.Timestamp(as_of).tz_localize(None)
    completed_month = timestamp.to_period("M") - 1
    periods = prices.index.to_period("M")
    completed = prices.loc[periods <= completed_month]
    if completed.empty:
        return completed
    rows: list[pd.Series] = []
    dates: list[pd.Timestamp] = []
    for _, month in completed.groupby(completed.index.to_period("M")):
        # ``apply`` selects the last actual observation for each column; it
        # does not carry values into a date on which that market was closed.
        values = month.apply(lambda series: series.dropna().iloc[-1] if series.notna().any() else float("nan"))
        last_dates = [series.dropna().index[-1] for _, series in month.items() if series.notna().any()]
        if last_dates:
            rows.append(values)
            dates.append(max(last_dates))
    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates), columns=prices.columns)


def date_ranges(prices: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for asset in prices.columns:
        valid = prices[asset].dropna()
        rows.append({"asset": asset, "first_available": valid.index.min(), "last_available": valid.index.max(), "observations": len(valid)})
    return pd.DataFrame(rows).set_index("asset")


def common_monthly_period(monthly_prices: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    complete = monthly_prices.dropna(how="any")
    if complete.empty:
        return None, None
    return complete.index.min(), complete.index.max()
