import numpy as np
import pandas as pd

from haa.strategies import GGCEMLinkOriginal, GGCEMLinkOriginalIsrael


ASSETS = ("SPY", "VEU", "IEF", "BIL")


def prices(steps, diffusion=0.6, extra=()):
    index = pd.date_range("2020-01-31", periods=14, freq="ME")
    frame = pd.DataFrame({asset: 100 * (1 + steps[asset]) ** np.arange(len(index)) for asset in ASSETS}, index=index)
    frame["OECD_CLI_DIFFUSION"] = diffusion
    for asset, step in extra:
        frame[asset] = 100 * (1 + step) ** np.arange(len(index))
    return frame


def test_risk_on_uses_stronger_equity_leg():
    decision = GGCEMLinkOriginal().decisions(prices({"SPY": .02, "VEU": .03, "IEF": .01, "BIL": .005})).iloc[-1]
    assert decision["selected_asset"] == "VEU"
    assert decision["regime"] == "risk-on-international"


def test_exactly_half_diffusion_is_risk_off_and_selects_best_defensive_leg():
    decision = GGCEMLinkOriginal().decisions(prices({"SPY": .03, "VEU": .02, "IEF": .002, "BIL": .005}, diffusion=.5)).iloc[-1]
    assert decision["selected_asset"] == "BIL"
    assert decision["regime"] == "risk-off-bills"


def test_missing_macro_uses_disclosed_spy_bil_failsafe():
    frame = prices({"SPY": .02, "VEU": .03, "IEF": .01, "BIL": .005})
    frame["OECD_CLI_DIFFUSION"] = np.nan
    decision = GGCEMLinkOriginal().decisions(frame).iloc[-1]
    assert decision["selected_asset"] == "VEU"
    assert decision["macro_source"] == "SPY/BIL failsafe"


def test_israel_implementation_maps_veu_to_acwx_proxy():
    frame = prices({"SPY": .02, "VEU": .03, "IEF": .01, "BIL": .005}, extra=(("ACWX", .025),))
    decision = GGCEMLinkOriginalIsrael().decisions(frame).iloc[-1]
    assert decision["signal_selected_asset"] == "VEU"
    assert decision["selected_asset"] == "ACWX"
