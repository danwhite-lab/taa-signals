import pandas as pd

from haa.signals import latest_actionable_signal, latest_preview_signal, month_to_date_snapshot


def signal_inputs():
    index = pd.to_datetime(["2026-07-31", "2026-08-31", "2026-09-30"])
    prices = pd.DataFrame({asset: [100.0, 101.0, 102.0] for asset in ("SPY", "TIP", "IEF", "BIL")}, index=index)
    decisions = pd.DataFrame(
        {"selected_asset": ["SPY", "SPY", "IEF"], "regime": ["risk-on", "risk-on", "risk-off"]}, index=index
    )
    return decisions, prices


def test_signal_uses_latest_completed_month_not_partial_current_month():
    decisions, prices = signal_inputs()
    status = latest_actionable_signal(decisions, prices, ("SPY", "TIP", "IEF", "BIL"), as_of=pd.Timestamp("2026-09-21"))
    assert status.reason is None
    assert status.decision is not None
    assert status.decision.name == pd.Timestamp("2026-08-31")
    assert status.decision["selected_asset"] == "SPY"


def test_missing_completed_month_data_blocks_signal():
    decisions, prices = signal_inputs()
    prices.loc[pd.Timestamp("2026-08-31"), "TIP"] = None
    status = latest_actionable_signal(decisions, prices, ("SPY", "TIP", "IEF", "BIL"), as_of=pd.Timestamp("2026-09-21"))
    assert status.decision is None
    assert "missing completed-month" in status.reason


def test_signal_is_the_strategy_decision_without_reimplemented_rules():
    decisions, prices = signal_inputs()
    status = latest_actionable_signal(decisions, prices, ("SPY", "TIP", "IEF", "BIL"), as_of=pd.Timestamp("2026-09-21"))
    assert status.decision is not None
    pd.testing.assert_series_equal(status.decision, decisions.loc[pd.Timestamp("2026-08-31")])


def test_month_to_date_preview_keeps_the_real_latest_common_trading_date():
    completed = pd.DataFrame(
        {"SPY": [100.0], "TIP": [101.0]}, index=pd.to_datetime(["2026-08-31"])
    )
    daily = pd.DataFrame(
        {"SPY": [102.0, 103.0], "TIP": [None, 104.0]},
        index=pd.to_datetime(["2026-09-29", "2026-09-30"]),
    )

    snapshot, price_as_of, reason = month_to_date_snapshot(
        completed, daily, ("SPY", "TIP"), as_of=pd.Timestamp("2026-09-30")
    )

    assert reason is None
    assert price_as_of == pd.Timestamp("2026-09-30")
    assert snapshot is not None
    assert snapshot.index[-1] == pd.Timestamp("2026-09-30")
    assert snapshot.loc[price_as_of, "SPY"] == 103.0


def test_preview_returns_only_a_current_month_decision():
    decisions = pd.DataFrame(
        {"selected_asset": ["SPY", "IEF"]},
        index=pd.to_datetime(["2026-08-31", "2026-09-30"]),
    )

    status = latest_preview_signal(decisions, pd.Timestamp("2026-09-30"))

    assert status.reason is None
    assert status.decision is not None
    assert status.decision.name == pd.Timestamp("2026-09-30")
    assert status.decision["selected_asset"] == "IEF"
