"""Verbatim Research presentation and native SVG geometry, not validation math."""
import numpy as np
import pandas as pd
from . import backtest as base
from .research import WORDS as W, profile_summary
from .signals_wire import clean, table


def preview(frame):
    return {**table(frame.head(base.PREVIEW_ROWS), index=False), "total_rows": len(frame),
            "shown_rows": min(len(frame), base.PREVIEW_ROWS), "truncated": len(frame) > base.PREVIEW_ROWS}


def chart(frame, x, y, group=None, *, boxes=False):
    """Plot formatting only. Box summaries use all observations before sampling."""
    if frame.empty or y not in frame: return None
    data = frame.loc[np.isfinite(pd.to_numeric(frame[y], errors="coerce"))].copy()
    if data.empty: return None
    low, high = min(0., float(data[y].min())), max(0., float(data[y].max()))
    span = high-low or 1.
    def scale(v): return round(280-240*(float(v)-low)/span, 4)
    colors = ["#17645f", "#6488a3", "#b58a52", "#7b799c", "#89969b", "#ad6971"]
    categories = list(dict.fromkeys(data[x].astype(str)))
    groups = list(dict.fromkeys(data[group].astype(str))) if group else [""]
    width = 880/len(categories)
    marks, labels = [], []
    total = len(data)
    positions = np.unique(np.linspace(0, total-1, min(total, base.CHART_ROWS), dtype=int))
    reduced = data.iloc[positions]
    if boxes:
        for number, (category, values) in enumerate(data.groupby(x, sort=False)[y]):
            values = values.to_numpy(dtype=float)
            q1, median, q3 = np.quantile(values, [.25, .5, .75])
            iqr = q3-q1
            inside = values[(values >= q1-1.5*iqr) & (values <= q3+1.5*iqr)]
            lower, upper = inside.min(), inside.max()
            center = 60+width*(number+.5)
            outliers = values[(values < lower) | (values > upper)]
            outliers = outliers[np.unique(np.linspace(0, len(outliers)-1, min(len(outliers), base.CHART_ROWS), dtype=int))] if len(outliers) else []
            marks.append({"x": center, "width": min(80, width*.5), "q1": scale(q1), "median": scale(median), "q3": scale(q3),
                          "low": scale(lower), "high": scale(upper), "outliers": [scale(v) for v in outliers],
                          "tooltip": f"{category}: {q1:.2%} / {median:.2%} / {q3:.2%}"})
    else:
        for _, row in reduced.iterrows():
            category = str(row[x]); group_name = str(row[group]) if group else ""
            slot = width/len(groups)
            left = 60+categories.index(category)*width+groups.index(group_name)*slot
            value = float(row[y]); top = min(scale(value), scale(0))
            marks.append({"x": round(left+slot*.1, 4), "y": top, "width": round(slot*.8, 4), "height": abs(scale(value)-scale(0)),
                          "color": colors[groups.index(group_name) % len(colors)], "tooltip": f"{category} · {group_name}: {value:.2%}"})
    for number, label in enumerate(categories):
        center = round(60+width*(number+.5), 4)
        labels.append({"x": center, "text": label, "transform": f"rotate(-40 {center} 305)"})
    return clean({"kind": "box" if boxes else "bar", "marks": marks, "labels": labels, "zero_y": scale(0),
                  "minimum": f"{low:.2%}", "maximum": f"{high:.2%}", "legend": [{"label": g, "color": colors[i % len(colors)]} for i, g in enumerate(groups) if g],
                  "caption": W["chartLimit"].format(shown=min(total, base.CHART_ROWS), total=total) if total > base.CHART_ROWS else W["chartAll"]})


def present(report, request, selected, profile, loaded):
    complete = report.scenarios.loc[report.scenarios["status"] == "complete"].copy()
    baseline = complete.loc[complete["test"] == "baseline"]
    overall = report.scorecard.loc[report.scorecard["Category"] == "Overall robustness"]
    grade = str(overall.iloc[0]["Grade"]) if not overall.empty else W["notAssessed"]
    verdict = W["verdicts"].get(grade, W["verdicts"]["C"])
    evidence = report.scorecard.set_index("Category")["Evidence"] if not report.scorecard.empty else pd.Series(dtype=str)
    checks = [{W["checkColumns"][0]: item["name"], W["checkColumns"][1]: item["question"],
               W["checkColumns"][2]: evidence.get(item["category"], W["notAssessed"])} for item in W["checks"]]
    completed_rolling = report.rolling_periods.loc[report.rolling_periods["status"] == "complete"] if not report.rolling_periods.empty else pd.DataFrame()
    completed_bootstrap = report.monte_carlo.loc[report.monte_carlo["status"] == "complete"] if not report.monte_carlo.empty else pd.DataFrame()
    bootstrap = completed_bootstrap.melt(id_vars="horizon", value_vars=["CAGR p10", "CAGR median", "CAGR p90"], var_name="Outcome", value_name="CAGR") if not completed_bootstrap.empty else pd.DataFrame()
    tables = {"scenarios": report.scenarios, "rolling": report.rolling_periods, "subperiods": report.subperiods,
              "data_quality": report.data_quality, "scorecard": report.scorecard, "monte_carlo": report.monte_carlo,
              "execution": report.scenarios.loc[report.scenarios["test"].isin(["parameter_sweep", "execution_delay", "transaction_cost", "israeli_tax", "alternate_start", "rebalance_shift", "signal_perturbation"])],
              "proxies": report.scenarios.loc[report.scenarios["test"] == "proxy_substitution"]}
    prefix = selected.model_class().name.lower().replace(" ", "_")
    suffixes = {"scenarios": "validation_scenarios", "data_quality": "data_quality", "monte_carlo": "block_bootstrap", "scorecard": "robustness_scorecard"}
    downloads = {kind: {"label": W["downloads"][kind], "filename": f"{prefix}_{suffix}.csv", "csv": tables[kind].to_csv(index=False)} for kind, suffix in suffixes.items() if kind != "monte_carlo" or not report.monte_carlo.empty}
    public = {"gate": "available", "label": selected.label, "currency": selected.execution_currency, "initial": request.initial,
              "profile": profile_summary(profile), "history": loaded["history"], "data_validation": loaded["metadata"],
              "grade": grade, "verdict": verdict, "meaning": W["meanings"][verdict], "checks": table(pd.DataFrame(checks), index=False),
              "cards": [{"label": W["confidence"], "value": verdict},
                        {"label": W["cagr"], "value": f"{baseline.iloc[0]['CAGR']:.2%}" if not baseline.empty else W["unavailable"]},
                        {"label": W["drawdown"], "value": f"{baseline.iloc[0]['Maximum drawdown']:.2%}" if not baseline.empty else W["unavailable"]}],
              "tables": {kind: preview(frame) for kind, frame in tables.items()},
              "charts": {"scenarios": chart(complete, "scenario", "CAGR", "test"), "rolling": chart(completed_rolling, "scenario", "CAGR", boxes=True),
                         "monte_carlo": chart(bootstrap, "horizon", "CAGR", "Outcome")}, "has_bootstrap": not report.monte_carlo.empty}
    return clean({"kind": "research-v1", "public": public, "downloads": downloads})
