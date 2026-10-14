from copy import deepcopy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import streamlit.components.v1 as components
from streamlit.testing.v1 import AppTest

import haa.data as market
import haa.supabase_sync as sync


@pytest.fixture
def account(monkeypatch):
    rows = []
    tokens = {"access_token": "test-access", "refresh_token": "test-refresh"}
    monkeypatch.setattr(components, "declare_component", lambda *a, **k: lambda **kw: {"session": tokens})
    monkeypatch.setattr(sync, "verified_session", lambda *a: {**tokens, "user_id": "same-account", "email": "test@example.invalid"})
    monkeypatch.setattr(sync, "load_workspace", lambda *a: {"revision": 1, "payload": {}})
    # A stale settings session must never block an explicit portfolio save.
    monkeypatch.setattr(sync, "save_workspace", lambda *a: None)
    monkeypatch.setattr(sync, "list_portfolios", lambda *a: deepcopy(rows))
    def save(*args, existing_id=None, is_default=False, **kwargs):
        row = {"id": existing_id or str(len(rows) + 1), "name": args[3]["name"],
               "payload": deepcopy(args[3]), "is_default": is_default,
               "updated_at": str(sum(len(r["name"]) for r in rows) + 1)}
        rows[:] = [r for r in rows if r["id"] != row["id"]] + [row]
        return deepcopy(row)
    monkeypatch.setattr(sync, "save_portfolio", save)
    monkeypatch.setattr(sync, "delete_portfolio", lambda *a: rows.__setitem__(slice(None), [r for r in rows if r["id"] != a[3]]))
    days = pd.bdate_range("2023-01-01", "2026-10-01")
    monkeypatch.setattr(market, "download_yahoo_prices", lambda mappings: pd.DataFrame({asset: np.linspace(100, 150, len(days)) for asset in mappings}, index=days))
    monkeypatch.setattr(market, "download_latest_yahoo_close", lambda *a: (3.7, pd.Timestamp("2026-10-01")))
    return rows


def open_app():
    return AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=30).run()


def button(app, label):
    return next(item for item in app.button if item.label == label)


def test_named_save_syncs_to_fresh_device_and_can_be_edited(account):
    desktop = open_app()
    desktop.radio(key="page").set_value("Portfolio").run()
    assert not desktop.exception
    desktop.text_input(key="portfolio_name").set_value("Chosen name").run()
    button(desktop, "Save portfolio").click().run()
    assert not desktop.exception
    assert account[0]["name"] == "Chosen name"
    assert any("Saved Chosen name" in item.value for item in desktop.success)
    saved_id = account[0]["id"]

    phone = open_app()
    assert phone.session_state["browser_portfolio_library"][0]["name"] == "Chosen name"
    phone.radio(key="page").set_value("Portfolio").run()
    button(phone, "Edit saved portfolio").click().run()
    assert phone.text_input(key="portfolio_name").value == "Chosen name"
    phone.text_input(key="portfolio_name").set_value("Renamed").run()
    button(phone, "Save changes").click().run()
    assert not phone.exception
    assert len(account) == 1
    assert account[0]["name"] == "Renamed" and account[0]["id"] == saved_id
    assert phone.session_state["workspace_shadow"]["portfolio_name"] == "Renamed"
    phone.radio(key="page").set_value("Today").run()
    assert phone.session_state["workspace_shadow"]["portfolio_name"] == "Renamed"
    phone.radio(key="page").set_value("Portfolio").run()
    assert phone.text_input(key="portfolio_name").value == "Renamed"


def test_failed_save_does_not_claim_success_or_add_to_library(account, monkeypatch):
    app = open_app()
    app.radio(key="page").set_value("Portfolio").run()
    app.text_input(key="portfolio_name").set_value("Unsaved").run()
    def fail(*a, **k):
        raise RuntimeError("network unavailable")
    monkeypatch.setattr(sync, "save_portfolio", fail)
    button(app, "Save portfolio").click().run()
    assert not app.exception
    assert not account
    assert not app.success
    assert any("Portfolio was not saved" in item.value for item in app.error)
