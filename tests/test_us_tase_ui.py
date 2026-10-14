"""Exercise both opt-in implementations through the real Streamlit pages."""
import numpy as np
import pandas as pd
import pytest

import haa.data as market
import haa.tase_data as tase
import haa.supabase_sync as sync
from haa.market_sessions import us_equity_sessions, tase_equity_sessions
from haa.strategies.rvol_shifter import completed_daily_cutoff
from haa.strategies.rvol_shifter_israel import completed_tase_cutoff
from haa.strategies.rvol_shifter_us_tase import RVolShifterUSTase1x, RVolShifterUSTaseBlend
from test_saved_portfolio_ui import account, open_app


@pytest.mark.parametrize("model", [RVolShifterUSTase1x, RVolShifterUSTaseBlend])
def test_new_variants_render_backtest_cash_replay_and_signals(account, monkeypatch, model):
    us_dates = us_equity_sessions("2021-01-04", str(completed_daily_cutoff().date()))
    local_dates = tase_equity_sessions("2022-11-15", str(completed_tase_cutoff().date()))
    x = np.arange(len(us_dates))
    us = pd.DataFrame({asset: 100*np.exp(np.cumsum(.0007 + .006*np.sin(x)))
                       if asset in ("QQQ", "SPY", "QLD", "TQQQ") else 100+x/1000
                       for asset in model.us_data_assets}, index=us_dates)
    local = pd.DataFrame(100., index=local_dates, columns=model.execution_assets)
    monkeypatch.setattr(market, "download_yahoo_prices", lambda mappings, **kw: us.loc[:, list(mappings)])
    metadata = pd.DataFrame({"source": "Test actual-session fixture", "price_field": "Close",
                             "identifier": [tase.TASE_ISRAEL_ASSET_IDS[a] for a in model.execution_assets]},
                            index=model.execution_assets)
    monkeypatch.setattr(tase, "download_tase_israel_prices", lambda assets: (local.loc[:, list(assets)], metadata.loc[list(assets)]))
    monkeypatch.setattr(sync, "load_workspace", lambda *a: {"revision": 1, "payload": {
        "model_name": model.name, "signals_model_name": model.name}})
    app = open_app()
    app.radio(key="page").set_value("Backtest").run()
    assert not app.exception
    assert not app.error, [item.value for item in app.error]
    app.checkbox(key="us_tase_cash_replay").check().run()
    assert not app.exception
    assert not app.error, [item.value for item in app.error]
    app.radio(key="page").set_value("Signals").run()
    assert not app.exception
    assert not app.error, [item.value for item in app.error]
    assert any("US signal" in item.value for item in app.caption)
