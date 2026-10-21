"""Five-minute complete public loader snapshots; no symbol splicing or fills."""
from copy import deepcopy
from time import time
import pandas as pd
from .cache import ResultCache
from .performance import engine_revision, span

RESULTS = ResultCache()
TTL = 300


def pack(frame):
    return {"columns": list(frame.columns), "index": [str(v) for v in frame.index],
            "data": frame.astype(object).where(frame.notna(), None).values.tolist(),
            "dtypes": [str(v) for v in frame.dtypes], "name": frame.index.name,
            "attrs": deepcopy(frame.attrs),
            "index_unit": frame.index.unit if isinstance(frame.index, pd.DatetimeIndex) else None,
            "dates": isinstance(frame.index, pd.DatetimeIndex)}


def unpack(value):
    index = pd.to_datetime(value["index"]) if value["dates"] else value["index"]
    if value["dates"] and value.get("index_unit"):
        index = index.as_unit(value["index_unit"])
    frame = pd.DataFrame(value["data"], columns=value["columns"], index=index)
    frame.index.name = value["name"]
    frame = frame.astype(dict(zip(value["columns"], value["dtypes"])))
    frame.attrs = deepcopy(value.get("attrs", {}))
    return frame


class Degraded(Exception):
    def __init__(self, result): self.result = result


def inputs(strategy, daily_bars, compute):
    # Keys are canonical public instruments/settings only, never saved user IDs.
    params = {"assets": list(getattr(strategy, "data_assets", ())),
              "benchmark": getattr(strategy, "benchmark_asset", "SPY"),
              "strict": list(getattr(strategy, "us_data_assets", ())) if getattr(strategy, "signal_calendar", None)=="XNYS" else [],
              "daily_bars": daily_bars, "code": engine_revision()}
    def build():
        with span("download_seconds"): result = compute()
        if result[2] or result[0].empty or result[0].isna().all().any(): raise Degraded(result)
        return {"frames": [pack(result[0]), pack(result[1])],
                "opens": pack(result[3]) if daily_bars else None}
    try:
        with span("input_cache_seconds"):
            value, info = RESULTS.run(model="public-input-snapshot-v2", params=params,
                start=None, end=None, version=str(int(time()//TTL)), compute=build)
    except Degraded as error:
        return deepcopy(error.result)
    result = (unpack(value["frames"][0]), unpack(value["frames"][1]), list(info["warnings"]))
    return (*result, unpack(value["opens"])) if daily_bars else result
