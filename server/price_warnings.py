"""Keep valuation warnings visible and inseparable from generated CSV results."""
import csv
from io import StringIO
import json
from pathlib import Path

_WORDS = json.loads((Path(__file__).resolve().parents[1]/"web/content/backtest.json").read_text())


def annotate_price_warnings(bundle, warnings):
    warnings = list(dict.fromkeys(warnings))
    if not warnings:
        return bundle
    public = bundle["public"]
    public["price_warnings"] = warnings
    public["warnings"] = list(dict.fromkeys([*public.get("warnings", []), *warnings]))
    for item in bundle["downloads"].values():
        # These are generated result CSVs; raw source history is never rewritten.
        rows = list(csv.reader(StringIO(item["csv"])))
        width = max((len(row) for row in rows), default=0)
        if not rows:
            rows = [[]]
        rows[0] += [""] * (width-len(rows[0])) + ["Price warnings"]
        if len(rows) == 1:
            rows.append([""] * width)
        for index, row in enumerate(rows[1:], 1):
            row += [""] * (width-len(row)) + [" | ".join(warnings) if index == 1 else ""]
        stream = StringIO()
        csv.writer(stream, lineterminator="\n").writerows(rows)
        item["csv"] = stream.getvalue()
    stream = StringIO()
    csv.writer(stream, lineterminator="\n").writerows([["Price warning"], *[[w] for w in warnings]])
    bundle["downloads"]["price-warnings"] = {"label":_WORDS["priceWarningsDownload"],
        "filename":"price_warnings.csv", "csv":stream.getvalue()}
    return bundle
