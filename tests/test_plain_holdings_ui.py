import numpy as np
import pandas as pd
import pytest

import haa.supabase_sync as sync
import haa.tase_data as tase
from haa.market_sessions import tase_equity_sessions
from haa.strategies import BuyAndHoldGoldIsrael, BuyAndHoldHarelBondsIsrael, BuyAndHoldGLD
from test_saved_portfolio_ui import account, open_app


def test_gld_usd_implementation_renders_as_plain_buy_and_hold(account, monkeypatch):
    monkeypatch.setattr(sync, "load_workspace", lambda *a: {"revision": 1, "payload": {
        "model_name": BuyAndHoldGLD.name, "signals_model_name": BuyAndHoldGLD.name}})
    app = open_app()
    app.radio(key="page").set_value("Backtest").run()
    assert not app.exception
    assert not app.error, [e.value for e in app.error]
    assert app.session_state["model_name"] == BuyAndHoldGLD.name
    app.radio(key="page").set_value("Rules").run()
    assert not app.exception
    assert any("Execution currency: USD" in item.value for item in app.markdown)
    assert not any("Internally managed momentum strategy" in item.value for item in app.info)
    app.radio(key="page").set_value("Signals").run()
    assert not app.exception
    assert any("GLD is held continuously" in item.value for item in app.info)


@pytest.mark.parametrize("cls", [BuyAndHoldGoldIsrael, BuyAndHoldHarelBondsIsrael])
def test_plain_holdings_pages_and_replacement_warning(account, monkeypatch, cls):
    asset = cls.holding_asset
    dates = tase_equity_sessions("2023-01-01", "2026-10-15")
    local = pd.DataFrame({asset: np.linspace(100., 120., len(dates))}, index=dates)
    metadata = pd.DataFrame({"source": "Test local fund", "identifier": tase.TASE_ISRAEL_ASSET_IDS[asset],
                             "price_field": "Adjusted close" if asset == "GOLD_IL" else "Maya published redemption price"}, index=[asset])
    monkeypatch.setattr(tase, "download_tase_israel_prices", lambda assets: (local.loc[:, list(assets)], metadata.loc[list(assets)]))
    monkeypatch.setattr(sync, "load_workspace", lambda *a: {"revision": 1, "payload": {
        "model_name": cls.name, "signals_model_name": cls.name}})
    app = open_app()
    app.radio(key="page").set_value("Backtest").run()
    assert not app.exception
    assert not app.error, [e.value for e in app.error]
    assert any("history_kind" in table.value.columns and table.value.history_kind.eq("Actual fund history").all()
               for table in app.dataframe)
    app.radio(key="page").set_value("Rules").run()
    assert not app.exception
    assert any("history_history_kind" in table.value.columns and table.value.history_history_kind.eq("Actual fund history").all()
               for table in app.dataframe)
    assert any("held continuously" in item.value for item in app.info)
    assert not any("Internally managed momentum strategy" in item.value for item in app.info)
    app.radio(key="page").set_value("Signals").run()
    assert not app.exception
    assert any("held continuously" in item.value for item in app.info)
    app.session_state["uploaded_replacements"] = {asset: local[asset]}
    app.run()
    assert not app.exception
    assert any("possible stand-in" in item.value for item in app.warning)
