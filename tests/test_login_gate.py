from pathlib import Path
from streamlit.testing.v1 import AppTest
import streamlit.components.v1 as components
import haa.supabase_sync as sync


def test_signed_out_browser_cannot_render_investing_workspace():
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert [item.value for item in app.title] == ["TAA Signals"]
    assert not app.radio
    assert not app.dataframe
    assert not app.file_uploader


def test_signed_in_workspace_restores_account_preferences_before_render(monkeypatch):
    tokens = {"access_token": "test-access", "refresh_token": "test-refresh"}
    monkeypatch.setattr(components, "declare_component", lambda *args, **kwargs: lambda **kw: {"session": tokens})
    monkeypatch.setattr(sync, "verified_session", lambda *args: {**tokens, "user_id": "user-1", "email": "test@example.invalid"})
    monkeypatch.setattr(sync, "load_workspace", lambda *args: {"revision": 7, "payload": {"page": "Today", "portfolio_name": "Restored", "tax_enabled": True}})
    monkeypatch.setattr(sync, "list_portfolios", lambda *args: [])
    writes = []
    def save(*args):
        writes.append(args[3])
        return args[4] + 1
    monkeypatch.setattr(sync, "save_workspace", save)
    app = AppTest.from_file(str(Path(__file__).parents[1] / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert app.session_state["portfolio_name"] == "Restored"
    assert app.session_state["tax_enabled"] is True
    assert app.radio[0].value == "Today"
    assert writes and writes[0]["portfolio_name"] == "Restored"
    assert "supabase_session" not in writes[0]
