"""Authenticated daily market refresh using only the existing app loaders."""
from datetime import datetime, timezone
import hmac
import os
from time import perf_counter
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4
import pandas as pd

from fastapi import APIRouter, Header, HTTPException

from haa import data, tase_data
from haa.model_catalog import MODEL_CATALOG
from haa.constants import ASSETS, FRED_ASSETS, OECD_CLI_DIFFUSION_ASSET
from .cache import cache_client, write_prices

router = APIRouter()
YAHOO_SOURCE = "yfinance:adjusted-close-and-open:v1"
TASE_SOURCE = "tasekit:existing-adapter:v1"
FRED_SOURCE = "fred:existing-daily-loader:v1"


def catalog_assets():
    assets = set()
    for item in MODEL_CATALOG:
        strategy = item.model_class()
        assets.update(getattr(strategy, "data_assets", ASSETS))
        assets.add(getattr(strategy, "benchmark_asset", "SPY"))
    return assets


def fred_universe():
    return sorted(catalog_assets().intersection(FRED_ASSETS))


def yahoo_universe():
    assets = set(data.DEFAULT_TICKER_MAP.values())
    for item in MODEL_CATALOG:
        strategy = item.model_class()
        assets.update(getattr(strategy, "market_data_assets", getattr(strategy, "data_assets", ())))
    # TASE assets use their own adapter; this is not a proxy mapping.
    assets.update(catalog_assets())
    yahoo = assets - set(tase_data.TASE_ISRAEL_ASSET_IDS) - set(FRED_ASSETS) - {OECD_CLI_DIFFUSION_ASSET}
    return sorted(set(data.default_ticker_map(yahoo).values()))


def bars_rows(closes, opens, symbol):
    frame = pd.DataFrame({"close": closes[symbol], "open": opens[symbol]}).sort_index()
    return [{"date": date.isoformat(),
             "close": None if pd.isna(row.close) else float(row.close),
             "open": None if pd.isna(row.open) else float(row.open)}
            for date, row in frame.iterrows()]


@router.get("/api/cron/refresh-prices")
def refresh_prices(authorization: str | None = Header(default=None)):
    secret = os.environ.get("CRON_SECRET", "")
    if not secret or not hmac.compare_digest(authorization or "", "Bearer " + secret):
        raise HTTPException(401, "Cron authentication required.")
    try:
        client = cache_client()
    except Exception:
        raise HTTPException(503, "Server cache is not configured.") from None
    refresh_id = str(uuid4())

    def attempt(symbol, operation):
        started = perf_counter()
        try:
            as_of = operation()
            result = {"symbol": symbol, "success": True, "as_of": as_of}
        except Exception as exc:
            error = str(exc)
            for key in ("SUPABASE_SERVICE_ROLE_KEY", "SUPABASE_PUBLISHABLE_KEY", "CRON_SECRET"):
                secret_value = os.environ.get(key)
                if secret_value:
                    error = error.replace(secret_value, "[redacted]")
            result = {"symbol": symbol, "success": False, "error_type": type(exc).__name__,
                      "error": error, "note": "Previous cached series retained; no substitute."}
        result["seconds"] = round(perf_counter() - started, 6)
        return result

    def yahoo(symbol):
        closes, opens = data.download_yahoo_daily_bars({symbol: symbol})
        rows = bars_rows(closes, opens, symbol)
        if rows:
            rows[0]["refresh_id"] = refresh_id
            rows[0]["index_name"] = closes.index.name
            rows[0]["index_unit"] = closes.index.unit
        write_prices(client, symbol, YAHOO_SOURCE, rows)
        return rows[-1]["date"]

    def tase(asset):
        item = tase_data.TasePriceSource().fetch_asset(asset)
        rows = [{"date": date.isoformat(), "price": float(value), "field": item.field,
                 "source": item.source, "security_id": item.security_id,
                 "units": "Unmodified provider history units; not broker execution quotes"}
                for date, value in item.prices.dropna().sort_index().items()]
        if rows:
            rows[0].update(refresh_id=refresh_id, index_name=item.prices.index.name, index_unit=item.prices.index.unit)
        write_prices(client, asset, TASE_SOURCE, rows)
        return rows[-1]["date"]

    def fred(symbol):
        frame = data.download_fred_series((symbol,))
        rows = [{"date": date.isoformat(), "price": None if pd.isna(value) else float(value)}
                for date, value in frame[symbol].sort_index().items()]
        if rows:
            rows[0].update(refresh_id=refresh_id, index_name=frame.index.name, index_unit=frame.index.unit)
        write_prices(client, symbol, FRED_SOURCE, rows)
        return rows[-1]["date"]

    jobs = [(symbol, lambda s=symbol: yahoo(s)) for symbol in yahoo_universe()]
    jobs += [(asset, lambda a=asset: tase(a)) for asset in sorted(tase_data.TASE_ISRAEL_ASSET_IDS)]
    jobs += [(symbol, lambda s=symbol: fred(s)) for symbol in fred_universe()]
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda job: attempt(*job), jobs))
    return {"checked_at": datetime.now(timezone.utc).isoformat(),
            "success": all(row["success"] for row in results), "results": results,
            "note": "Provider history only; no proxy or gap fill. Catalog FRED daily observations are cached; OECD remains live."}
