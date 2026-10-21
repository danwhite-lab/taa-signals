"""Read complete same-refresh model inputs, or use the original live loader.

Never splice symbols from different refreshes, forward-fill, or proxy data.
"""
from datetime import datetime, timedelta, timezone
import math
import pandas as pd

from haa import data, tase_data
from haa.constants import ASSETS, FRED_ASSETS, OECD_CLI_DIFFUSION_ASSET
from .cache import cache_client
from .cron import YAHOO_SOURCE, TASE_SOURCE, FRED_SOURCE

FALLBACK_WARNING = "Daily price snapshot missing, invalid, mixed-refresh or older than 36 hours; used the complete existing live loader. No cached/live splice or gap fill."


def fresh(stamps):
    now = datetime.now(timezone.utc)
    try:
        return bool(stamps) and all(timedelta(0) <= now - datetime.fromisoformat(stamp.replace("Z", "+00:00")) <= timedelta(hours=36) for stamp in stamps)
    except (TypeError, ValueError, AttributeError):
        return False


def read_snapshot(requests):
    """Read all requested (source, symbol) pairs, or reject the entire batch."""
    client = cache_client()
    found = {}
    for source in dict.fromkeys(source for source, _ in requests):
        symbols = list(dict.fromkeys(symbol for s, symbol in requests if s == source))
        rows = (client.table("price_cache").select("symbol,rows,updated_at")
                .eq("source", source).in_("symbol", symbols).execute().data)
        if len(rows) != len(symbols) or {row["symbol"] for row in rows} != set(symbols):
            raise ValueError("Incomplete snapshot")
        found.update({(source, row["symbol"]): row for row in rows})
    refreshes = {row["rows"][0].get("refresh_id") for row in found.values()}
    stamps = [row["updated_at"] for row in found.values()]
    if not refreshes or any(not isinstance(value, str) or not value for value in refreshes) or len(refreshes) != 1:
        raise ValueError("Mixed refresh snapshots")
    if not fresh(stamps):
        raise ValueError("Snapshot refresh is too old")
    return found, {"source": "daily_snapshot", "refresh_id": next(iter(refreshes)),
                   "updated_at": min(stamps), "refresh_stamps": stamps}


def snapshot_frame(row):
    frame = pd.DataFrame(row["rows"]).set_index("date")
    frame.index = pd.to_datetime(frame.index, format="ISO8601").as_unit(row["rows"][0].get("index_unit", "ns"))
    if frame.index.has_duplicates or frame.index.hasnans or frame.empty:
        raise ValueError("Invalid cached rows")
    frame.index.name = row["rows"][0].get("index_name")
    return frame.sort_index()


def model_inputs(definition, live_loader, *, daily_bars=False):
    """Whole selected-model snapshot or whole original live-loader result."""
    try:
        strategy = definition.model_class()
        assets = tuple(getattr(strategy, "data_assets", ASSETS))
        runtime = tuple(dict.fromkeys((*assets, getattr(strategy, "benchmark_asset", "SPY"))))
        if OECD_CLI_DIFFUSION_ASSET in runtime:
            raise ValueError("OECD stays on the existing live loader")
        tase = tuple(a for a in runtime if a in tase_data.TASE_ISRAEL_ASSET_IDS)
        fred = tuple(a for a in runtime if a in FRED_ASSETS)
        yahoo = tuple(a for a in runtime if a not in (*tase, *fred))
        mapping = data.default_ticker_map(yahoo)
        requests = {a: (TASE_SOURCE, a) if a in tase else (FRED_SOURCE, a) if a in fred
                    else (YAHOO_SOURCE, mapping[a]) for a in runtime}
        records, origin = read_snapshot(tuple(dict.fromkeys(requests.values())))
        closes, opens = {}, {}
        metadata = pd.DataFrame(index=pd.Index(runtime, name="asset"), columns=["source", "identifier", "price_field"])
        for asset, key in requests.items():
            row = records[key]
            frame = snapshot_frame(row)
            closes[asset] = frame["close" if asset in yahoo else "price"].astype(float)
            if closes[asset].dropna().empty or not closes[asset].dropna().map(math.isfinite).all():
                raise ValueError("Missing price history")
            if asset in yahoo:
                metadata.loc[asset] = ["Yahoo Finance", mapping[asset], "Adj Close (Close fallback)"]
                if daily_bars:
                    opens[asset] = frame["open"].astype(float)
                    if opens[asset].dropna().empty or not opens[asset].dropna().map(math.isfinite).all():
                        raise ValueError("Missing adjusted opens")
                    metadata.loc[asset, "price_field"] = "Adjusted close and adjusted open from the same source; no raw Close fallback"
            elif asset in fred:
                metadata.loc[asset] = ["FRED", asset, "Daily observation"]
            else:
                first = row["rows"][0]
                if str(first["security_id"]) != str(tase_data.TASE_ISRAEL_ASSET_IDS[asset]):
                    raise ValueError("TASE security mismatch")
                metadata.loc[asset] = [first["source"], first["security_id"], first["field"]]
        metadata = pd.DataFrame({column: metadata[column].tolist() for column in metadata}, index=metadata.index)
        strict = tuple(getattr(strategy, "us_data_assets", ())) if getattr(strategy, "signal_calendar", None) == "XNYS" else ()
        if strict and not daily_bars:
            metadata.loc[list(strict), "price_field"] = "Required adjusted close; no raw Close fallback"
        # Use the same normalization as live_inputs. No ffill/dropna/splicing.
        prices = data.combine_replacements(pd.DataFrame(closes), {}, runtime)
        origin["price_data_through"] = {a: closes[a].last_valid_index().isoformat() for a in runtime}
        prices.attrs["input_source"] = origin
        result = prices, metadata, []
        return (*result, data._clean_prices(pd.DataFrame(opens))) if daily_bars else result
    except Exception:
        result = live_loader()  # Original live errors/partial-data handling propagate unchanged.
        result[0].attrs["input_source"] = {"source": "live", "loaded_at": datetime.now(timezone.utc).isoformat(), "snapshot_fallback": True}
        return (result[0], result[1], [*result[2], FALLBACK_WARNING], *result[3:])


def arvol_inputs(assets):
    try:
        records, _ = read_snapshot([(YAHOO_SOURCE, asset) for asset in assets])
        # Each symbol may have its actual own observation dates. Missing opens
        # stay missing; the unchanged engine decides whether execution is valid.
        closes, opens = {}, {}
        for row in records.values():
            frame = snapshot_frame(row)
            closes[row["symbol"]] = frame["close"].astype(float)
            opens[row["symbol"]] = frame["open"].astype(float)
        return pd.DataFrame(closes), pd.DataFrame(opens), "Supabase price_cache (unfilled provider rows)", []
    except Exception:
        closes, opens = data.download_yahoo_daily_bars({asset: asset for asset in assets})
        return closes, opens, "Existing live Yahoo adjusted-bars loader", [
            "Price cache missing, invalid or older than 36 hours; loaded the complete live data set. No splice."]
