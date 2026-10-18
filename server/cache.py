"""Server-only market/result caches. No private account data may enter here."""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from threading import Lock

from supabase import create_client


def cache_client():
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Server cache is not configured.")
    return create_client(url, key)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def data_version(rows):
    dates = [row["date"] for series in rows.values() for row in series]
    return f"{max(dates, default='empty')}:{digest(rows)}"


class ResultCache:
    def __init__(self):
        self.warm = OrderedDict()
        self.lock = Lock()

    def run(self, *, model, params, start, end, version, compute):
        key = digest({"model": model, "params": params, "start": start,
                      "end": end, "data_version": version})
        warnings = []
        # One computation per key per warm worker. Across cold workers duplicate
        # computation is harmless; upserts contain only fixed public diagnostics.
        with self.lock:
            if key in self.warm:
                self.warm.move_to_end(key)
                return deepcopy(self.warm[key]), {"hit": "memory", "key": key, "warnings": []}
            client = None
            try:
                client = cache_client()
                rows = client.table("results_cache").select("result").eq("cache_key", key).execute().data
                if rows:
                    value = rows[0]["result"]
                    self._remember(key, value)
                    return deepcopy(value), {"hit": "supabase", "key": key, "warnings": []}
            except Exception:
                warnings.append("Result cache unavailable; calculated with the existing engine.")
            value = compute()  # Never catch/retry engine errors or cache failed results.
            self._remember(key, value)
            if client is not None:
                try:
                    client.table("results_cache").upsert({"cache_key": key, "result": value}).execute()
                except Exception:
                    warnings.append("Result was calculated but could not be stored in the shared cache.")
            return deepcopy(value), {"hit": None, "key": key, "warnings": warnings}

    def _remember(self, key, value):
        self.warm[key] = deepcopy(value)
        while len(self.warm) > 32:
            self.warm.popitem(last=False)


def write_prices(client, symbol, source, rows):
    if not rows:
        raise ValueError("Existing loader returned no observations; previous cache retained.")
    client.table("price_cache").upsert({
        "symbol": symbol, "source": source, "as_of": max(row["date"] for row in rows),
        "rows": rows, "updated_at": datetime.now(timezone.utc).isoformat(),
    }, on_conflict="symbol,source").execute()
