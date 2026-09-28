import numpy as np
import pandas as pd

from haa.engine import run_backtest
from haa.strategies import HAASimple
from haa.validation import ValidationInput, data_quality_report, profile_for, run_deterministic_validation


def validation_input():
    monthly_index = pd.date_range("2010-01-31", periods=156, freq="ME")
    monthly = pd.DataFrame({
        "SPY": 100 * 1.008 ** np.arange(len(monthly_index)),
        "TIP": 100 * 1.002 ** np.arange(len(monthly_index)),
        "IEF": 100 * 1.003 ** np.arange(len(monthly_index)),
        "BIL": 100 * 1.001 ** np.arange(len(monthly_index)),
    }, index=monthly_index)
    daily_index = pd.bdate_range(monthly_index.min(), monthly_index.max() + pd.Timedelta(days=5))
    daily = monthly.reindex(daily_index).ffill()
    decisions = HAASimple().decisions(monthly)
    return ValidationInput("HAA-Simple", decisions, monthly, daily, "SPY", profile_for(HAASimple))


def test_validation_runs_baseline_delay_cost_tax_and_start_scenarios_without_changing_decisions():
    input_data = validation_input()
    original = input_data.decisions.copy(deep=True)
    report = run_deterministic_validation(input_data, 10_000)
    scenarios = report.scenarios
    assert (scenarios["test"] == "baseline").any()
    assert set(scenarios.loc[scenarios["test"] == "execution_delay", "scenario"]) == {"+0 business day(s)", "+1 business day(s)", "+2 business day(s)"}
    assert (scenarios["test"] == "transaction_cost").sum() == 3
    assert scenarios.loc[scenarios["test"] == "israeli_tax", "status"].item() == "complete"
    assert (scenarios["test"] == "alternate_start").any()
    pd.testing.assert_frame_equal(input_data.decisions, original)


def test_validation_reports_real_rolling_subperiod_and_adapter_requirements():
    report = run_deterministic_validation(validation_input())
    assert set(report.rolling_periods.loc[report.rolling_periods["status"] == "complete", "scenario"]) == {"5y", "10y"}
    assert not report.subperiods.loc[report.subperiods["status"] == "complete"].empty
    adapter_tests = report.scenarios.loc[report.scenarios["status"] == "requires_strategy_adapter", "test"].tolist()
    assert adapter_tests == ["rebalance_shift"]
    assert report.scenarios.loc[report.scenarios["test"] == "proxy_substitution", "status"].item() == "unavailable"


def test_execution_delay_moves_entries_after_the_production_execution_day():
    input_data = validation_input()
    production = run_backtest(input_data.decisions, input_data.monthly_prices, 10_000, daily_prices=input_data.daily_prices)
    delayed = run_backtest(input_data.decisions, input_data.monthly_prices, 10_000, daily_prices=input_data.daily_prices, execution_delay_business_days=1)
    assert delayed.monthly.iloc[0]["execution_date"] > production.monthly.iloc[0]["execution_date"]


def test_declared_execution_proxy_uses_its_prices_without_rewriting_production_signals():
    input_data = validation_input()
    proxy_monthly = pd.Series(90 * 1.006 ** np.arange(len(input_data.monthly_prices)), index=input_data.monthly_prices.index)
    proxy_daily = proxy_monthly.reindex(input_data.daily_prices.index).ffill()
    with_proxy = ValidationInput(
        input_data.name,
        input_data.decisions,
        input_data.monthly_prices,
        input_data.daily_prices,
        input_data.benchmark_asset,
        input_data.profile,
        {"CSPX_IL": proxy_monthly},
        {"CSPX_IL": proxy_daily},
    )
    report = run_deterministic_validation(with_proxy)
    proxy_row = report.scenarios.loc[report.scenarios["test"] == "proxy_substitution"].iloc[0]
    assert proxy_row["scenario"] == "SPY → CSPX_IL"
    assert proxy_row["status"] == "complete"
    assert (input_data.decisions["selected_asset"] == "SPY").all()


def test_data_quality_reports_source_issues_and_no_look_ahead_check():
    input_data = validation_input()
    baseline_quality = data_quality_report(input_data)
    daily = input_data.daily_prices.copy()
    daily.loc[daily["TIP"].first_valid_index(), "TIP"] = np.nan
    daily.loc[daily["BIL"].first_valid_index(), "BIL"] = 0
    changed = ValidationInput(input_data.name, input_data.decisions, input_data.monthly_prices, daily, input_data.benchmark_asset, input_data.profile)
    baseline = run_backtest(changed.decisions, changed.monthly_prices, 10_000, daily_prices=changed.daily_prices)
    report = data_quality_report(changed, baseline)
    tip = report.loc[(report["kind"] == "asset") & (report["asset"] == "TIP")].iloc[0]
    bil = report.loc[(report["kind"] == "asset") & (report["asset"] == "BIL")].iloc[0]
    look_ahead = report.loc[(report["kind"] == "check") & (report["check"] == "look_ahead")].iloc[0]
    original_tip = baseline_quality.loc[(baseline_quality["kind"] == "asset") & (baseline_quality["asset"] == "TIP")].iloc[0]
    assert tip["missing_observations"] == original_tip["missing_observations"] + 1
    assert bil["non_positive_observations"] == 1
    assert look_ahead["status"] == "pass"
