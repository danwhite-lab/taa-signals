from copy import deepcopy
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pandas as pd
import pytest

from test_api import ROOT, client
from server import cache, cron, market_cache


def test_cache_hit_reuses_result_and_exact_rows_revision_invalidates(monkeypatch):
    monkeypatch.setattr(cache, "cache_client", lambda: (_ for _ in ()).throw(RuntimeError("Unavailable")))
    memo = cache.ResultCache()
    compute = MagicMock(return_value={"fake_result": 1})
    rows = {"SPY": [{"date": "2026-01-01", "close": 10, "open": 9}]}
    args = dict(model="Fake", params={"tax_enabled": True}, start="2026-01-01", end="2026-01-01", compute=compute)
    one, info = memo.run(**args, version=cache.data_version(rows))
    assert info["hit"] is None and info["warnings"]
    one["fake_result"] = 99
    two, info = memo.run(**args, version=cache.data_version(rows))
    assert info["hit"] == "memory" and two == {"fake_result": 1} and compute.call_count == 1
    rows["SPY"][0]["close"] = 11
    memo.run(**args, version=cache.data_version(rows))
    assert compute.call_count == 2
    memo.run(**{**args, "params": {"tax_enabled": False}}, version=cache.data_version(rows))
    assert compute.call_count == 3


def test_shared_cache_hit_and_failed_write_dont_repeat_compute(monkeypatch):
    query = MagicMock()
    query.table.return_value = query.select.return_value = query.eq.return_value = query.upsert.return_value = query
    query.execute.return_value = SimpleNamespace(data=[{"result": {"fake": True}}])
    monkeypatch.setattr(cache, "cache_client", lambda: query)
    compute = MagicMock(return_value={"new": True})
    args = dict(model="Fake", params={}, start=None, end=None, version="one", compute=compute)
    assert cache.ResultCache().run(**args)[1]["hit"] == "supabase"
    compute.assert_not_called()
    query.execute.side_effect = [SimpleNamespace(data=[]), RuntimeError("Write unavailable")]
    value, info = cache.ResultCache().run(**args)
    assert value == {"new": True} and compute.call_count == 1 and info["warnings"]


def test_failed_calculation_is_not_cached(monkeypatch):
    monkeypatch.setattr(cache, "cache_client", lambda: (_ for _ in ()).throw(RuntimeError()))
    memo = cache.ResultCache()
    for _ in range(2):
        with pytest.raises(ValueError, match="Mock engine failure"):
            memo.run(model="Fake", params={}, start=None, end=None, version="v", compute=lambda: (_ for _ in ()).throw(ValueError("Mock engine failure")))
    assert not memo.warm


@pytest.mark.parametrize("secret,header", [(None, None), ("mock-cron", None), ("mock-cron", "Bearer wrong")])
def test_cron_unauthorized_never_loads_or_writes(monkeypatch, secret, header):
    if secret:
        monkeypatch.setenv("CRON_SECRET", secret)
    monkeypatch.setattr(cron, "cache_client", lambda: pytest.fail("No access before auth"))
    assert client.get("/api/cron/refresh-prices", headers={"Authorization": header} if header else {}).status_code == 401


def test_cron_reuses_loaders_keeps_failures_visible_and_previous_rows(monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "mock-cron")
    monkeypatch.setattr(cron, "cache_client", lambda: object())
    monkeypatch.setattr(cron, "yahoo_universe", lambda: ["SPY", "QQQ"])
    monkeypatch.setattr(cron.tase_data, "TASE_ISRAEL_ASSET_IDS", {"MOCK_IL": "1234567"})
    dates = pd.to_datetime(["2026-01-01", "2026-01-02"])
    calls, writes = [], []
    def download(mapping):
        calls.append(mapping)
        symbol = next(iter(mapping))
        if symbol == "QQQ":
            raise ValueError("Exact mock provider failure mock-cron")
        return pd.DataFrame({symbol: [1., 2.]}, index=dates), pd.DataFrame({symbol: [.9, 1.9]}, index=dates)
    monkeypatch.setattr(cron.data, "download_yahoo_daily_bars", download)
    monkeypatch.setattr(cron.tase_data, "TasePriceSource", lambda: SimpleNamespace(fetch_asset=lambda asset: SimpleNamespace(
        prices=pd.Series([10., 11.], index=dates), field="Mock NAV", source="Mock Maya", security_id="1234567")))
    monkeypatch.setattr(cron, "write_prices", lambda *args: writes.append(args))
    body = client.get("/api/cron/refresh-prices", headers={"Authorization": "Bearer mock-cron"}).json()
    assert not body["success"] and len(body["results"]) == 3 and len(writes) == 2
    assert body["results"][1]["error"] == "Exact mock provider failure [redacted]"
    assert {args[1] for args in writes} == {"SPY", "MOCK_IL"}
    assert {tuple(mapping) for mapping in calls} == {("SPY",), ("QQQ",)}
    assert "refresh_id" in next(args[-1][0] for args in writes if args[1] == "SPY")


def test_price_cache_has_no_public_policies_or_private_tables():
    sql = (ROOT / "supabase/cache_tables.sql").read_text().lower()
    assert sql.count("enable row level security") == 2
    assert "create policy" not in sql and "security definer" not in sql
    assert "to service_role" in sql and "from public, anon, authenticated" in sql
    assert "alter table public.user_settings" not in sql and "alter table public.portfolios" not in sql
    assert len(list((ROOT / "api").glob("*.py"))) == 1


def test_market_snapshot_preserves_nulls_and_rejects_mixed_refresh(monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    records = [{"symbol": symbol, "updated_at": now, "rows": [
        {"date": "2026-01-01T00:00:00", "close": 10, "open": None, "refresh_id": "mock-batch"}]} for symbol in ["SPY", "QQQ"]]
    query = MagicMock()
    query.table.return_value = query.select.return_value = query.eq.return_value = query.in_.return_value = query
    query.execute.return_value = SimpleNamespace(data=records)
    monkeypatch.setattr(market_cache, "cache_client", lambda: query)
    live = MagicMock(return_value=("mock live closes", "mock live opens"))
    monkeypatch.setattr(market_cache.data, "download_yahoo_daily_bars", live)
    closes, opens, source, warnings = market_cache.arvol_inputs(["SPY", "QQQ"])
    assert closes.iloc[0, 0] == 10 and pd.isna(opens.iloc[0, 0]) and not warnings
    live.assert_not_called()
    records[1]["rows"][0]["refresh_id"] = "different-refresh"
    closes, opens, source, warnings = market_cache.arvol_inputs(["SPY", "QQQ"])
    assert closes == "mock live closes" and warnings and live.call_count == 1
    records[1]["rows"][0]["refresh_id"] = "mock-batch"
    records[0]["updated_at"] = "2000-01-01T00:00:00+00:00"
    assert market_cache.arvol_inputs(["SPY", "QQQ"])[3]
