"""Compare presentation expressions ported literally, using existing metrics."""
import pandas as pd
from haa.metrics import performance_metrics, annual_returns
from haa.backtest_options import result_metrics
from . import backtest as base
from .backtest_presentation import PERCENTAGE_ROWS, RATIO_ROWS, NUMERIC_ROWS
from .compare import WORDS as W
from .signals_wire import clean, table


def preview(frame, *, percentages=False, summary=False):
    value = table(frame.head(base.PREVIEW_ROWS))
    value.update(total_rows=len(frame), shown_rows=min(len(frame), base.PREVIEW_ROWS), truncated=len(frame)>base.PREVIEW_ROWS)
    if percentages or summary:
        rows = []
        for row in value["rows"]:
            metric = row.get("metric")
            rows.append({k: (f"{v:.2%}" if percentages or metric in PERCENTAGE_ROWS else f"{v:.2f}")
                if isinstance(v, (int, float)) and (percentages or metric in PERCENTAGE_ROWS+RATIO_ROWS+NUMERIC_ROWS) else v for k,v in row.items()})
        value["display_rows"] = rows
    return value


def plot(frame):
    value = base.chart(frame)
    value["caption"] = W["chartLimit" if value["reduced"] else "chartAll"]
    return value


def present(request, comparison, loaded, bounds):
    models = request.mode == "models"
    initial = request.initial
    first = next(iter(comparison.results.values()))
    benchmarks = {}
    if models:
        for name, model in loaded["inputs"].items():
            benchmarks.setdefault(W["benchmark"].format(asset=model.benchmark_asset), comparison.results[name])
    else:
        benchmarks[W["benchmark"].format(asset="SPY")] = first
    benchmark = ", ".join(benchmarks)
    tables, charts, downloads = {}, {}, {}
    def export(kind, frame, filename, label):
        downloads[kind] = {"csv": frame.to_csv(), "filename": filename, "label": label}
    for taxed in (False, True) if request.tax_enabled else (False,):
        column = "after_tax_value" if taxed else "pre_tax_value"
        retcolumn = "after_tax_monthly_return" if taxed else "pre_tax_monthly_return"
        suffix = "after" if taxed else "pre"
        summary = pd.DataFrame({name: (performance_metrics(r.monthly[column], initial) if models and request.monthly_contribution == 0 else result_metrics(r, column, initial)) for name,r in comparison.results.items()})
        if not models or not taxed:
            for label, result in benchmarks.items():
                summary[label] = performance_metrics(result.monthly.benchmark_value, initial) if models and request.monthly_contribution == 0 else result_metrics(result, "benchmark_value", initial)
        if models and not taxed:
            years = len(comparison.common_index)/12
            for name,r in comparison.results.items():
                changes = int(r.monthly.allocation_change.sum())
                turnover = r.monthly.turnover.sum()/years if "turnover" in r.monthly and years else changes/years if years else 0
                summary.loc["Allocation changes", name] = changes
                summary.loc["Average changes/year", name] = changes/years if years else 0
                summary.loc["Annual turnover", name] = turnover
        if not models:
            observed = first.daily if first.daily is not None and not first.daily.empty else first.monthly
            summary.loc["Tested from (first observation)"] = observed.index.min().strftime("%Y-%m-%d")
            summary.loc["Tested through (last observation)"] = observed.index.max().strftime("%Y-%m-%d")
        tables["summary_"+suffix] = preview(summary.rename_axis("metric"), summary=True)
        if models or taxed == request.tax_enabled:
            curves = pd.DataFrame({name: (r.daily if not models and request.method == "daily" else r.monthly)[column] for name,r in comparison.results.items()})
            if not models or not taxed:
                for label, result in benchmarks.items():
                    curves[label] = (result.daily if not models and request.method == "daily" else result.monthly).benchmark_value
            charts["value_"+suffix] = plot(curves)
            if not taxed or not models:
                peaks = curves.cummax() if models else curves.cummax().clip(lower=initial)
                charts["drawdown"] = plot(curves.div(peaks).sub(1))
            returns = pd.DataFrame({name: r.monthly[retcolumn] for name,r in comparison.results.items()})
            if not models or not taxed:
                for label, result in benchmarks.items():
                    returns[label] = result.monthly.benchmark_monthly_return
            annual = pd.DataFrame({name: annual_returns(returns[name]) for name in returns})
            tables["monthly_"+suffix] = preview(returns, percentages=True)
            if models:
                tables["annual_"+suffix] = preview(annual, percentages=True)
                kind = "after-tax-monthly-returns" if taxed else "monthly-returns"
                export(kind, returns, "haa_model_comparison_after_tax_monthly_returns.csv" if taxed else "haa_model_comparison_monthly_returns.csv", W["downloads"][kind])
            else: export("portfolio-returns", returns, "portfolio_comparison.csv", W["downloads"]["portfolio-returns"])
    if models:
        allocations = []
        for name,r in comparison.results.items():
            latest = r.monthly.iloc[-1]
            weights = latest.get("target_weights")
            allocation = ", ".join(f"{a} {w:.0%}" for a,w in weights.items()) if isinstance(weights, dict) else latest["selected_asset"]
            allocations.append({"model":name,"signal_date":latest["signal_date"],"regime":latest["regime"],"target allocation":allocation})
            filename = name.lower().replace(" ", "_").replace("(", "").replace(")", "")+"_comparison_audit.csv"
            export("audit:"+name, r.audit, filename, W["auditDownload"].format(name=name))
        tables["allocation"] = preview(pd.DataFrame(allocations).set_index("model"))
    common = comparison.common_index
    window = {"start": str(common.min().date()), "end": str(common.max().date()), "periods": len(common)}
    public = {"gate":"available", "mode":request.mode, "method":request.method, "tax_enabled":request.tax_enabled,
        "window":window, "bounds":{"start":str(bounds[0]), "end":str(bounds[1])}, "benchmark":benchmark,
        "success":W["success"].format(start=window["start"],end=window["end"],n=len(common)) if models else None,
        "source_caption":W["sharedSource"].format(start=bounds[0],end=bounds[1]) if models else None,
        "coverage":preview(comparison.available_periods), "tables":tables, "charts":charts, "data_validation":loaded["metadata"]}
    return clean({"kind":f"compare-{request.mode}-v1", "public":public, "downloads":downloads})
