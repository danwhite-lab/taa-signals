"""Removal targets stable sleeve IDs, never row positions or model labels."""
import pytest

import haa.supabase_sync as sync
from test_saved_portfolio_ui import account, open_app


@pytest.mark.parametrize("state_key,next_key,page,mode,prefix,add_key,models", [
    ("portfolio_sleeves", "portfolio_next_id", "Portfolio", None, "portfolio", "portfolio_add_sleeve", ["Buy and Hold SPY"] * 3),
    ("backtest_sleeves", "backtest_next_id", "Backtest", "Portfolio", "backtest_sleeve", "backtest_add_sleeve", ["Buy and Hold SPY"] * 3),
    ("deep_proxy_sleeves", "deep_proxy_next_id", "Backtest", "Deep History / Proxy", "deep_proxy_sleeve", "deep_proxy_add_sleeve", ["buy_and_hold_sp500", "haa_simple", "gem"]),
])
def test_remove_chosen_sleeve_preserves_other_ids_weights_and_add_counter(
        account, monkeypatch, state_key, next_key, page, mode, prefix, add_key, models):
    sleeves = [{"id": sid, "model": model, "weight": weight}
               for sid, model, weight in zip([11, 22, 33], models, [20., 30., 50.])]
    payload = {state_key: sleeves, next_key: 34}
    if mode:
        payload["backtest_mode"] = mode
    monkeypatch.setattr(sync, "load_workspace", lambda *a: {"revision": 1, "payload": payload})
    app = open_app()
    app.radio(key="page").set_value(page).run()
    assert not app.exception
    app.button(key=f"{prefix}_22_remove").click().run()
    assert not app.exception
    remaining = app.session_state[state_key]
    assert [(s["id"], s["model"], s["weight"]) for s in remaining] == [
        (11, models[0], 20.), (33, models[2], 50.)]
    assert app.session_state[next_key] == 34
    app.button(key=f"{prefix}_11_remove").click().run()
    assert not app.exception
    assert [s["id"] for s in app.session_state[state_key]] == [33]
    assert app.button(key=f"{prefix}_33_remove").disabled
    app.button(key=add_key).click().run()
    assert not app.exception
    assert [s["id"] for s in app.session_state[state_key]] == [33, 34]
    assert app.session_state[next_key] == 35
    app.button(key=f"{prefix}_34_remove").click().run()
    assert not app.exception
    assert [s["id"] for s in app.session_state[state_key]] == [33]
