"""Presentation expressions ported from the Portfolio/Deep History app blocks."""
from datetime import datetime, timezone
import pandas as pd
from haa.backtest_options import result_metrics, unit_curves
from haa.metrics import annual_returns, performance_metrics, rolling_annualized_returns, worst_rolling_annualized_return
from haa.tase_data import plain_holding_provenance
from . import backtest as base
from .backtest_multi import WORDS as W, deep
from .signals_wire import clean, table


def summary_table(frame):
    value = table(frame.rename_axis("metric"))
    percentages = ["CAGR", "Total return", "Maximum drawdown", "Daily maximum drawdown", "Annualized volatility", "Worst 5-year rolling CAGR", "Best month", "Worst month", "Annual turnover"]
    numeric = ["Sharpe", "Sortino", "Calmar", "Final value", "Total contributed", "Investment gain", "Allocation changes", "Average changes/year"]
    value["display_rows"] = [{k: (f"{v:.2%}" if row["metric"] in percentages else f"{v:.2f}") if isinstance(v, (int, float)) and row["metric"] in percentages+numeric else v for k, v in row.items()} for row in value["rows"]]
    return value


def report(request, result, models, passed, benchmark_asset, metadata, bounds, chosen, timing):
    proxy = request.mode == "deep"
    blend = len(request.sleeves) > 1
    specs = [deep.ALL_DEEP_HISTORY_SPECS[s.model] for s in request.sleeves] if proxy else []
    spec = specs[0] if proxy and not blend else None
    taxed = passed["tax_enabled"]
    initial = request.initial
    mixed = not proxy and result.daily is not None
    pre = W["blendPre"] if proxy and blend else W["singlePre"].format(label=spec.label) if proxy else W["portfolioPre"]
    after = W["blendAfter"] if proxy and blend else W["singleAfter"].format(label=spec.label) if proxy else W["portfolioAfter"]
    benchmark = deep.DEEP_HISTORY_BENCHMARKS[request.benchmark] if proxy else None
    benchmark_label = benchmark.label if proxy else W["localSpy"] if benchmark_asset == "RVOL_SPY_IL" else W["spy"]
    mapping = {pre: "pre_tax_value", **({after: "after_tax_value"} if taxed else {}), benchmark_label: "benchmark_value"}
    raw_metrics = {"pre_tax": result_metrics(result, "pre_tax_value", initial), "after_tax": result_metrics(result, "after_tax_value", initial), "benchmark": result_metrics(result, "benchmark_value", initial)}
    summary = pd.DataFrame({label: result_metrics(result, column, initial) for label, column in mapping.items()})
    if proxy:
        for label, column in mapping.items():
            returns_column = {"pre_tax_value": "pre_tax_monthly_return", "after_tax_value": "after_tax_monthly_return", "benchmark_value": "benchmark_monthly_return"}[column]
            summary.loc["Worst 5-year rolling CAGR", label] = worst_rolling_annualized_return(result.monthly[returns_column], 5)
        if spec and spec.daily_nav_history:
            daily_units = initial*(1+result.daily.pre_tax_daily_return).cumprod()
            daily_drawdown = daily_units/daily_units.cummax().clip(lower=initial)-1
            summary.loc["Daily maximum drawdown", pre] = daily_drawdown.min()
            if taxed:
                after_units = initial*(1+result.daily.after_tax_daily_return).cumprod()
                summary.loc["Daily maximum drawdown", after] = (after_units/after_units.cummax().clip(lower=initial)-1).min()
            summary.loc["Daily maximum drawdown", benchmark_label] = float("nan")
    nav = result.daily if mixed else result.monthly
    observed = result.daily if result.daily is not None and not result.daily.empty else result.monthly
    summary.loc["Tested from (first observation)"] = observed.index.min().strftime("%Y-%m-%d")
    summary.loc["Tested through (last observation)"] = observed.index.max().strftime("%Y-%m-%d")
    curves = pd.DataFrame({label: nav[column] for label, column in mapping.items()})
    units = unit_curves(result, mapping, initial)
    drawdowns = units.div(units.cummax().clip(lower=initial)).sub(1)
    monthly_returns = pd.DataFrame({label: result.monthly[{"pre_tax_value": "pre_tax_monthly_return", "after_tax_value": "after_tax_monthly_return", "benchmark_value": "benchmark_monthly_return"}[column]] for label, column in mapping.items()})
    annual = pd.DataFrame({label: annual_returns(monthly_returns[label]) for label in monthly_returns})
    captions, warnings, downloads, extra_tables, extra_charts = [], ([base.MINIMUM_NOTE] if request.fees_enabled is None and request.fee_value else []), {}, [], []
    if not proxy:
        warnings += [risk for sleeve in request.sleeves
                     if (risk := getattr(base.definition(sleeve.model).model_class, "risk_warning", None))]

    def download(kind, frame, filename, label, index=True, raw=False):
        downloads[kind] = {"csv": frame if raw else frame.to_csv(index=index), "filename": filename, "label": label}

    if not proxy:
        assets = tuple(asset for s in request.sleeves if getattr(base.definition(s.model).model_class, "actual_history_only", False) for asset in base.definition(s.model).model_class.data_assets)
        if assets:
            provenance = plain_holding_provenance(metadata, assets)
            captions.append(W["plainCaption"])
            for asset, row in provenance.iterrows():
                if row.history_kind != "Actual fund history": warnings.append(W["plainStandIn"].format(asset=asset, kind=row.history_kind))
                elif row.price_field in {"Published ETF NAV", "End-of-day close"}: warnings.append(W["plainUnverified"].format(asset=asset, field=row.price_field))
            extra_tables.append({"label": W["plainSources"], "value": base.preview(provenance)})
            download("history_sources", provenance, "plain_holdings_history_sources.csv", W["plainDownload"])
        captions += [W["common"].format(lower=bounds[0], upper=bounds[1]), W["taxCaption"]]
        if mixed:
            captions += [W[{"none": "mixedNone", "rvol_cap": "mixedCap", "annual_target": "mixedAnnual"}[request.sleeve_rebalance_mode]], W["mixedTax"]]
            download("portfolio_nav", result.daily, "mixed_portfolio_daily_nav.csv", W["downloads"]["portfolio_nav"])
            download("sleeve_nav", result.sleeve_nav, "mixed_portfolio_sleeve_nav.csv", W["downloads"]["sleeve_nav"])
            download("executions", result.audit, "mixed_portfolio_executions.csv", W["downloads"]["executions"], False)
            if taxed: download("sleeve_tax", result.tax_events, "mixed_portfolio_tax_events.csv", W["downloads"]["sleeve_tax"], False)
        else: captions.append(W["monthlyReset"])
        captions.append(W["holdingPeriods"].format(lower=result.common_index.min().date(), upper=result.common_index.max().date()))
        if request.monthly_contribution or passed["fixed_fee"]: captions.append(W["sleeveFeeCaption"])
        # Same per-sleeve summary expressions as the Streamlit block.
        sleeve_summary = pd.DataFrame([
            {"Sleeve": s.model, "Initial weight" if mixed else "Target weight": s.weight/100,
             "CAGR": performance_metrics((1+result.sleeve_returns[f"{s.model} ({s.id})"]).cumprod()*initial, initial).get("CAGR"),
             "Total return": performance_metrics((1+result.sleeve_returns[f"{s.model} ({s.id})"]).cumprod()*initial, initial).get("Total return")}
            for s in request.sleeves])
        if mixed:
            sleeve_summary["Ending weight (pre-tax)"] = [result.sleeve_nav[f"{s.model} ({s.id})"].iloc[-1]/result.daily.pre_tax_value.iloc[-1] for s in request.sleeves]
            elapsed_years = max((result.daily.index[-1]-result.daily.index[0]).days+6.5/24, 6.5/24)/365.25
            if not request.monthly_contribution:
                sleeve_summary["CAGR"] = [(result.sleeve_nav[f"{s.model} ({s.id})"].iloc[-1]/(initial*s.weight/100))**(1/elapsed_years)-1 for s in request.sleeves]
        extra_tables.append({"label": W["selected"], "value": base.preview(sleeve_summary)})
    else:
        warnings.append(W["proxyCaption"])
        warnings += [s.caveat for s in specs if s.caveat]
        if any(s.currency == "ILS" for s in specs):
            warnings.append("RESEARCH ONLY")
        if any(s.daily_signal_history for s in specs) and request.fee_value: warnings.append(W["unsupportedFees"])
        if any(s.key == "rvol_synthetic" for s in specs): warnings.append(W["syntheticTax"])
        captions.append(W["commonProxy" if blend else "availableProxy"].format(lower=bounds[0], upper=bounds[1]))
        captions.append(W["proxyTax"].format(benchmark=benchmark.label) if not spec or spec.key != "rvol_daily" else W["dailyCaption"])
        caption = W["proxyPeriods"].format(lower=result.monthly.index.min().date(), upper=result.monthly.index.max().date(), benchmark=benchmark.label, caveat=benchmark.caveat)
        if blend:
            caption = f"{' / '.join(f'{s.weight/100:.0%} {deep.ALL_DEEP_HISTORY_SPECS[s.model].label}' for s in request.sleeves)}. " + caption
            warnings.append(W["blendWarning"])
        elif not spec.actual_etf_ticker and not spec.daily_signal_history: warnings.append(W["proxyWarning"])
        captions.append(caption)
        captions.append(W["syntheticMetrics"].format(count=len(result.tax_events)) if spec and spec.daily_nav_history else W["dailyMetrics"] if spec and spec.daily_signal_history else W["ledgerCount"].format(count=len(result.tax_events)))
        if blend and taxed:
            download("proxy_tax", result.tax_events, "deep_history_portfolio_tax_ledger.csv", W["downloads"]["proxy_tax"], False)
            if result.audit is not None: download("proxy_audit", result.audit, "deep_history_portfolio_transactions.csv", W["downloads"]["proxy_audit"], False)
        if spec and spec.daily_nav_history:
            extra_charts += [{"label": W["syntheticCurve"], "value": base.chart(result.daily.pre_tax_value.rename(pre).to_frame())},
                             {"label": W["syntheticDrawdown"], "value": base.chart(daily_drawdown.rename(pre).to_frame())}]
            if taxed:
                download("synthetic_tax", result.tax_events, "arvol_synthetic_tax_ledger.csv", W["downloads"]["synthetic_tax"], False)
                download("synthetic_nav", result.daily, "arvol_synthetic_funded_nav.csv", W["downloads"]["synthetic_nav"])
                download("synthetic_audit", result.audit, "arvol_synthetic_transactions.csv", W["downloads"]["synthetic_audit"], False)
        for selected in specs:
            for segment, path in (("Actual", selected.returns_file if selected.actual_etf_ticker else None), ("Early", selected.pre_etf_returns_file)):
                if path:
                    download(f"source_{selected.key}_{segment.lower()}", (deep.DEEP_HISTORY_DIR/path).read_bytes().decode("utf-8"), path,
                             W["source"+segment].format(ticker=selected.actual_etf_ticker), raw=True)
        if spec and spec.daily_signal_history:
            visible = deep.load_deep_history(spec)[0].copy()
            if spec.daily_nav_history:
                captions.append(W["sourceCaption"])
                download("synthetic_source", visible, "arvol_synthetic_daily.csv", W["downloads"]["synthetic_source"])
                visible = visible.loc[visible.position != visible.position_end_of_day]
            else:
                visible["target_weights"] = visible["target_weights"].map(lambda weights: ", ".join(f"{a} {w:.0%}" for a, w in weights.items()))
            visible = visible.sort_index(ascending=False)
            extra_tables.append({"label": W["dailySignals"], "value": base.preview(visible)})
            if not spec.daily_nav_history: download("daily_source", visible, "rvol_daily_signal_history.csv", W["downloads"]["daily_source"])
    rolling = []
    if proxy:
        for years in (1, 3, 5, 10):
            if len(monthly_returns) < years*12: continue
            frame = pd.DataFrame({c: rolling_annualized_returns(monthly_returns[c], years) for c in monthly_returns}).dropna(how="all")
            if frame.empty: continue
            rolling.append({"years": years, "label": W["rollingLabel"].format(years=years), "table": base.preview(frame), "chart": base.chart(frame)})
    audit = result.audit if result.audit is not None else result.monthly
    validation = metadata
    if not proxy:
        observed_prices = pd.DataFrame({asset: model.daily_prices[asset] for _, model in models.values() for asset in model.daily_prices})
        validation = metadata.join(base.data.date_ranges(observed_prices))
    settings = request.model_dump(mode="json")
    settings.pop("label", None)
    settings.pop("reference_replay", None)
    settings.update(start=str(chosen[0]), end=str(chosen[1]))
    public = {"label": W["blendTitle"] if proxy and blend else f"{spec.label} — {W['deep']}" if proxy else W["portfolioTitle"],
        "currency": next(iter(models.values()))[1].execution_currency, "settings": settings, "engine_parameters": {"initial_investment": initial, **passed},
        "summary": summary_table(summary), "metrics": raw_metrics, "value_chart": base.chart(curves), "drawdown_chart": base.chart(drawdowns),
        "periods": base.preview(audit), "tax_events": base.preview(result.tax_events), "annual": base.preview(annual), "monthly": base.preview(monthly_returns),
        "extra_tables": extra_tables, "extra_charts": extra_charts, "rolling": rolling,
        "tax_event_count": len(result.tax_events), "report_rows": len(observed), "monthly_rows": len(result.monthly),
        "first_date": observed.index.min().isoformat(), "last_date": observed.index.max().isoformat(),
        "captions": captions, "warnings": warnings, "data_validation": table(validation),
        "calculated_at": datetime.now(timezone.utc).isoformat(), "calculation_timing": timing,
        "data_origin": W["proxyCaption"] if proxy else W["liveOrigin"]}
    currency = next(iter(models.values()))[1].execution_currency
    public['fees'] = base.fee_report(result, request, currency)
    if request.fees_enabled:
        public['engine_parameters']['trading_fees'] = vars(passed['trading_fees'])
    cards = [{"label": W["blendCagr" if proxy and blend else "proxyCagr" if proxy else "portfolioCagr"], "value": f"{summary.loc['CAGR', pre]:.2%}"}]
    if taxed:
        cards += [{"label": W["afterCagr"], "value": f"{summary.loc['CAGR', after]:.2%}", "delta": f"{summary.loc['CAGR', after]-summary.loc['CAGR', pre]:+.2%}"},
                  {"label": W["preFinal"], "value": f"{summary.loc['Final value', pre]:,.0f}"},
                  {"label": W["afterFinal"], "value": f"{summary.loc['Final value', after]:,.0f}"}]
    elif not proxy:
        cards.append({"label": W["maxDrawdown"], "value": f"{summary.loc['Maximum drawdown', pre]:.2%}"})
    if not taxed: cards.append({"label": W["final"], "value": f"{summary.loc['Final value', pre]:,.0f}"})
    if proxy: cards.append({"label": W["benchmarkCagr"], "value": f"{summary.loc['CAGR', benchmark_label]:.2%}"})
    public.update(cards=cards, value_title=W["proxyBlendCurve" if proxy and blend else "proxyCurve" if proxy else "equityCurve"],
                  drawdown_title=W["proxyBlendDrawdown" if proxy and blend else "proxyDrawdown" if proxy else "drawdownTitle"],
                  summary_title=W["performanceDetails"] if proxy else None)
    from .price_warnings import annotate_price_warnings
    return clean(annotate_price_warnings({"kind": "backtest-deep-history-v1" if proxy else "backtest-portfolio-v1", "public": public, "downloads": downloads}, result.price_warnings))
