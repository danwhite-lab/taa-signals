"""Request-local timings and bounded, public-input-only decision memoization."""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from pathlib import Path
from threading import RLock
from time import perf_counter
import pandas as pd
from .cache import digest

CURRENT = ContextVar("performance", default=None)
MEMO = OrderedDict()
LOCK = RLock()


@contextmanager
def measure():
    values = {}
    token = CURRENT.set(values)
    try: yield values
    finally: CURRENT.reset(token)


@contextmanager
def span(name):
    began = perf_counter()
    try: yield
    finally:
        values = CURRENT.get()
        if values is not None: values[name] = values.get(name, 0.) + perf_counter()-began


@lru_cache(maxsize=1)
def engine_revision():
    root = Path(__file__).resolve().parents[1]/"src/haa"
    return digest({str(p.relative_to(root)):p.read_text() for p in sorted(root.rglob("*.py"))})


def frame_version(frame):
    return digest({"columns":list(frame.columns), "dtypes":[str(d) for d in frame.dtypes],
        "observations":hashlib.sha256(pd.util.hash_pandas_object(frame,index=True).values.tobytes()).hexdigest()})


def clone(frame):
    result=frame.copy(deep=True)
    # pandas deep copies arrays, not dict/list objects inside object cells.
    for column in frame:
        if frame[column].dtype == object:
            result[column]=frame[column].map(deepcopy).astype(frame[column].dtype)
    result.attrs=deepcopy(frame.attrs)
    return result


def decisions(strategy, prices, **kwargs):
    """Reuse exact original decisions, never optimize/reconstruct strategy maths."""
    cutoff = str(strategy.completed_cutoff()) if hasattr(strategy,"completed_cutoff") else None
    key = digest({"class":type(strategy).__module__+"."+type(strategy).__name__, "engine":engine_revision(),
        "data":frame_version(prices), "kwargs":{k:str(v) for k,v in kwargs.items()},
        "utc_date":str(datetime.now(timezone.utc).date()), "cutoff":cutoff})
    with LOCK:
        if key in MEMO:
            MEMO.move_to_end(key)
            return clone(MEMO[key])
        with span("signal_seconds"): result = strategy.decisions(prices,**kwargs)
        if not result.empty:
            MEMO[key] = clone(result)
            while len(MEMO)>16: MEMO.popitem(last=False)
        return result
