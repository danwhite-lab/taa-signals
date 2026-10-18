"""JSON/presentation conversion only. No trading or indicator calculations."""
from datetime import date, datetime
import math
import numbers

import pandas as pd


def clean(value):
    if isinstance(value, dict):
        return {str(key): clean(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [clean(item) for item in value]
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return clean(value.item())
    if isinstance(value, numbers.Real) and not math.isfinite(value):
        return None
    return value


def table(frame, *, formats=None, index=True):
    frame = frame.copy()
    if index:
        name = frame.index.name or "index"
        while name in frame.columns:
            name = "_" + name
        frame = frame.rename_axis(name).reset_index()
    rows = [clean(row) for row in frame.to_dict(orient="records")]
    rendered = []
    for row in rows:
        display = {}
        for column, value in row.items():
            fmt = formats.get(column) if isinstance(formats, dict) else formats
            display[column] = fmt.format(value) if fmt and isinstance(value, numbers.Real) else value
        rendered.append(display)
    result = {"columns": [str(column) for column in frame.columns], "rows": rows}
    # Do not duplicate thousands of identical daily-history rows in the JSON.
    # Raw values and the original CSV are always retained in full.
    if rendered != rows:
        result["display_rows"] = rendered
    return result


class SignalsCompression:
    """Compress Signals and Backtest transport, not other API responses."""
    def __init__(self, app):
        from starlette.middleware.gzip import GZipMiddleware
        self.app = app
        self.compressed = GZipMiddleware(app, minimum_size=1000)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        target = self.compressed if scope.get("type") == "http" and (path == "/api/signals" or path.startswith("/api/backtest")) else self.app
        await target(scope, receive, send)
