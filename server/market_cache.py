"""Read one complete same-refresh Yahoo snapshot, or use the live loader.

Never splice symbols from different refreshes, forward-fill, or proxy data.
"""
from datetime import datetime, timedelta, timezone
import pandas as pd

from haa import data
from .cache import cache_client
from .cron import YAHOO_SOURCE


def arvol_inputs(assets):
    try:
        rows = (cache_client().table("price_cache").select("symbol,rows,updated_at")
                .eq("source", YAHOO_SOURCE).in_("symbol", list(assets)).execute().data)
        if {row["symbol"] for row in rows} != set(assets):
            raise ValueError("Incomplete snapshot")
        refreshes = {row["rows"][0].get("refresh_id") for row in rows}
        if None in refreshes or len(refreshes) != 1:
            raise ValueError("Mixed refresh snapshots")
        now = datetime.now(timezone.utc)
        stamps = [datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00")) for row in rows]
        if any(now - stamp > timedelta(hours=36) or stamp > now for stamp in stamps):
            raise ValueError("Snapshot refresh is too old")
        # Each symbol may have its actual own observation dates. Missing opens
        # stay missing; the unchanged engine decides whether execution is valid.
        closes, opens = {}, {}
        for row in rows:
            frame = pd.DataFrame(row["rows"]).set_index("date")
            frame.index = pd.to_datetime(frame.index)
            if frame.index.has_duplicates or frame.empty:
                raise ValueError("Invalid cached rows")
            closes[row["symbol"]] = frame["close"].astype(float)
            opens[row["symbol"]] = frame["open"].astype(float)
        return pd.DataFrame(closes), pd.DataFrame(opens), "Supabase price_cache (unfilled provider rows)", []
    except Exception:
        closes, opens = data.download_yahoo_daily_bars({asset: asset for asset in assets})
        return closes, opens, "Existing live Yahoo adjusted-bars loader", [
            "Price cache missing, invalid or older than 36 hours; loaded the complete live data set. No splice."]
