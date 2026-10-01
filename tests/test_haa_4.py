import pandas as pd

from haa.strategies import HAA4, HAA4Israel


HAA4_ASSETS = ("TIP", "BIL", "SPY", "VEA", "VNQ", "IEF")


def prices_with_terminal_scores(scores):
    index = pd.date_range("2020-01-31", periods=13, freq="ME")
    prices = pd.DataFrame({asset: [100.0] * 13 for asset in HAA4_ASSETS}, index=index)
    for asset, score in scores.items():
        prices.loc[index[-1], asset] = 100 * (1 + score)
    return prices


def test_bad_tip_is_fully_defensive():
    decision = HAA4().decisions(prices_with_terminal_scores({"TIP": 0, "IEF": .1, "BIL": .2})).iloc[-1]
    assert decision["regime"] == "risk-off"
    assert decision["target_weights"] == {"BIL": 1.0}


def test_positive_tip_holds_top_two_positive_offensive_assets_equally():
    decision = HAA4().decisions(prices_with_terminal_scores({"TIP": .1, "SPY": .7, "VEA": .6, "VNQ": .2, "IEF": .1})).iloc[-1]
    assert decision["regime"] == "risk-on"
    assert decision["target_weights"] == {"SPY": .5, "VEA": .5}


def test_bad_selected_offensive_sleeve_is_replaced_by_defensive_winner():
    decision = HAA4().decisions(prices_with_terminal_scores({"TIP": .1, "SPY": .3, "VEA": -.1, "VNQ": -.2, "IEF": -.3, "BIL": .1})).iloc[-1]
    assert decision["regime"] == "risk-on-defensive-replacement"
    assert decision["selected_offensive_assets"] == "SPY, VEA"
    assert decision["replaced_offensive_assets"] == "VEA"
    assert decision["target_weights"] == {"SPY": .5, "BIL": .5}


def test_two_bad_selected_sleeves_consolidate_to_full_defensive_allocation():
    decision = HAA4().decisions(prices_with_terminal_scores({"TIP": .1, "SPY": -.1, "VEA": -.2, "VNQ": -.3, "IEF": -.4, "BIL": -.5})).iloc[-1]
    assert decision["target_weights"] == {"IEF": 1.0}


def test_ief_can_be_offensive_and_absorb_a_replaced_sleeve():
    decision = HAA4().decisions(prices_with_terminal_scores({"TIP": .1, "IEF": .4, "SPY": -.1, "VEA": -.2, "VNQ": -.3, "BIL": .1})).iloc[-1]
    assert decision["selected_offensive_assets"] == "IEF, SPY"
    assert decision["defensive_winner"] == "IEF"
    assert decision["target_weights"] == {"IEF": 1.0}


def test_zero_tip_and_zero_selected_asset_are_nonpositive():
    defensive = HAA4().decisions(prices_with_terminal_scores({"TIP": 0, "IEF": .1, "BIL": .2})).iloc[-1]
    replacement = HAA4().decisions(prices_with_terminal_scores({"TIP": .1, "SPY": .2, "VEA": 0, "VNQ": -.1, "IEF": -.2, "BIL": .05})).iloc[-1]
    assert defensive["target_weights"] == {"BIL": 1.0}
    assert replacement["target_weights"] == {"SPY": .5, "BIL": .5}


def test_ties_follow_existing_deterministic_conventions():
    decision = HAA4().decisions(prices_with_terminal_scores({"TIP": .1, "SPY": .2, "VEA": .2, "VNQ": .2, "IEF": .2, "BIL": .2})).iloc[-1]
    # Offensive ties use alphabetical ticker order; defensive ties use IEF,
    # matching the existing Classic and Simple defensive conventions.
    assert decision["selected_offensive_assets"] == "IEF, SPY"
    assert decision["defensive_winner"] == "IEF"


def test_unchanged_final_weights_do_not_create_a_trade():
    index = pd.date_range("2020-01-31", periods=14, freq="ME")
    prices = pd.DataFrame({asset: [100.0] * len(index) for asset in HAA4_ASSETS}, index=index)
    decisions = HAA4().decisions(prices)
    assert len(decisions) == 2
    assert decisions.iloc[0]["target_weights"] == decisions.iloc[1]["target_weights"]
    assert not decisions.iloc[1]["trade"]


def test_future_prices_do_not_change_an_earlier_decision():
    base = prices_with_terminal_scores({"TIP": .1, "SPY": .3, "VEA": .2, "VNQ": .1, "IEF": 0, "BIL": -.1})
    decision_date = base.index[-1]
    extended = base.copy()
    extended.loc[decision_date + pd.offsets.MonthEnd()] = [1.0, 10_000.0, 1.0, 10_000.0, 1.0, 10_000.0]
    earlier = HAA4().decisions(base).loc[decision_date]
    with_future = HAA4().decisions(extended).loc[decision_date]
    assert earlier["target_weights"] == with_future["target_weights"]


def test_israel_variant_keeps_published_signal_logic_and_uses_vxus_execution_proxy():
    prices = prices_with_terminal_scores({"TIP": .1, "SPY": .2, "VEA": .4, "VNQ": .1, "IEF": .05})
    prices["VXUS"] = 100.0
    decision = HAA4Israel().decisions(prices).iloc[-1]
    assert decision["signal_target_weights"] == {"VEA": .5, "SPY": .5}
    assert decision["target_weights"] == {"VXUS": .5, "SPY": .5}
