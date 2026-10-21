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
    monkeypatch.setattr(cron.data, "download_fred_series", lambda symbols: pd.DataFrame({s: [2., None] for s in symbols}, index=dates))
    body = client.get("/api/cron/refresh-prices", headers={"Authorization": "Bearer mock-cron"}).json()
    assert not body["success"] and len(body["results"]) == 4 and len(writes) == 3
    assert body["results"][1]["error"] == "Exact mock provider failure [redacted]"
    assert {args[1] for args in writes} == {"SPY", "MOCK_IL", "T5YIE"}
    assert {tuple(mapping) for mapping in calls} == {("SPY",), ("QQQ",)}
    assert "refresh_id" in next(args[-1][0] for args in writes if args[1] == "SPY")
    assert len({args[-1][0]["refresh_id"] for args in writes}) == 1
    assert next(args[-1][1]["price"] for args in writes if args[1] == "T5YIE") is None


def test_cron_universes_use_provider_mappings_and_keep_macro_out_of_yahoo():
    assert "T5YIE" in cron.fred_universe()
    assert not set(cron.yahoo_universe()).intersection({"T5YIE", "OECD_CLI_DIFFUSION", *cron.tase_data.TASE_ISRAEL_ASSET_IDS})


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


def snapshot_store(monkeypatch, records):
    class Query:
        def table(self, name):
            assert name == "price_cache"
            return self
        def select(self, columns): return self
        def eq(self, key, value):
            self.source = value
            return self
        def in_(self, key, values):
            self.symbols = values
            return self
        def execute(self):
            return SimpleNamespace(data=[deepcopy(r) for (source, symbol), r in records.items()
                                         if source == self.source and symbol in self.symbols])
    monkeypatch.setattr(market_cache, "cache_client", Query)


def loader_bundle(monkeypatch, label):
    """Synthetic provider rows through the real live and snapshot assemblers."""
    from test_signals import fixtures
    from server import signals
    from haa.model_catalog import definition_for_label
    definition = definition_for_label(label)
    prices, _, _ = fixtures(label)
    tase = tuple(a for a in prices if a in cron.tase_data.TASE_ISRAEL_ASSET_IDS)
    local_meta = pd.DataFrame({"source": "Mock original TASE", "identifier": [cron.tase_data.TASE_ISRAEL_ASSET_IDS[a] for a in tase],
                              "price_field": "Mock adjusted NAV"}, index=pd.Index(tase, name="asset"))
    monkeypatch.setattr(signals.data, "download_yahoo_prices", lambda mapping, **kwargs: prices.reindex(columns=mapping).copy())
    monkeypatch.setattr(signals.data, "download_yahoo_daily_bars", lambda mapping: (prices.reindex(columns=mapping).copy(), prices.reindex(columns=mapping)*.99))
    monkeypatch.setattr(signals.data, "download_fred_series", lambda assets: prices.reindex(columns=assets).copy())
    monkeypatch.setattr(signals.tase_data, "download_tase_israel_prices", lambda assets: (prices.reindex(columns=assets).copy(), local_meta.reindex(assets).copy()))
    records = {}
    for asset in prices:
        source = cron.TASE_SOURCE if asset in tase else cron.FRED_SOURCE if asset in cron.FRED_ASSETS else cron.YAHOO_SOURCE
        symbol = asset if source != cron.YAHOO_SOURCE else cron.data.default_ticker_map([asset])[asset]
        rows = [{"date": date.isoformat(), "close": None if pd.isna(value) else float(value),
                 "open": None if pd.isna(value) else float(value*.99), "price": None if pd.isna(value) else float(value)}
                for date, value in prices[asset].items()]
        rows[0].update(refresh_id="mock-batch", index_name=prices.index.name)
        if asset in tase:
            rows[0].update(source=local_meta.loc[asset, "source"], field=local_meta.loc[asset, "price_field"], security_id=local_meta.loc[asset, "identifier"])
        records[source, symbol] = {"symbol": symbol, "updated_at": datetime.now(timezone.utc).isoformat(), "rows": rows}
    snapshot_store(monkeypatch, records)
    return definition, records


@pytest.mark.parametrize("label,daily_bars", [("HAA-Simple", False), ("HAA-Simple Israel", False),
    ("Inflation Compass Standard", False), ("A-RVol Shifter V3 Cash-Only", True)])
def test_model_snapshot_exact_live_frames_metadata_and_decisions(monkeypatch, label, daily_bars):
    from server import signals, today
    definition, _ = loader_bundle(monkeypatch, label)
    live = signals.live_inputs(definition, daily_bars=daily_bars)
    cached = market_cache.model_inputs(definition, lambda: pytest.fail("Complete snapshot must not use live"), daily_bars=daily_bars)
    assert not cached[2]
    assert cached[0].attrs["input_source"]["source"] == "daily_snapshot"
    # Source bookkeeping is not part of a price series or engine calculation.
    plain = cached[0].copy(); plain.attrs = {}
    pd.testing.assert_frame_equal(plain, live[0], check_exact=True, check_freq=False)
    pd.testing.assert_frame_equal(cached[1], live[1], check_exact=True)
    if daily_bars:
        pd.testing.assert_frame_equal(cached[3], live[3], check_exact=True, check_freq=False)
    from haa import portfolio_signals
    from haa.signals import latest_actionable_signal
    original_monthly = portfolio_signals.to_month_end
    monkeypatch.setattr(portfolio_signals, "to_month_end", lambda frame: original_monthly(frame, as_of=pd.Timestamp("2024-06-14")))
    monkeypatch.setattr(portfolio_signals, "latest_actionable_signal", lambda *a: latest_actionable_signal(*a, as_of=pd.Timestamp("2024-06-14")))
    assert today.build_sleeve(definition, plain, cached[1], [], False) == today.build_sleeve(definition, live[0], live[1], [], False)


@pytest.mark.parametrize("damage", ["missing_symbol", "missing_close", "missing_opens", "all_null_close", "nonfinite", "mixed_refresh", "missing_refresh", "old", "future", "duplicate_date", "invalid_date", "empty_rows"])
def test_model_snapshot_rejects_whole_batch_and_preserves_live_warning(monkeypatch, damage):
    from server import signals
    definition, records = loader_bundle(monkeypatch, "A-RVol Shifter V3 Cash-Only")
    key = next(iter(records)); record = records[key]
    if damage == "missing_symbol": del records[key]
    elif damage == "missing_close":
        for row in record["rows"]: row.pop("close")
    elif damage == "missing_opens":
        for row in record["rows"]: row.pop("open")
    elif damage == "all_null_close":
        for row in record["rows"]: row["close"] = None
    elif damage == "nonfinite": record["rows"][0]["close"] = float("inf")
    elif damage == "mixed_refresh": record["rows"][0]["refresh_id"] = "other-batch"
    elif damage == "missing_refresh": record["rows"][0].pop("refresh_id")
    elif damage == "old": record["updated_at"] = "2000-01-01T00:00:00+00:00"
    elif damage == "future": record["updated_at"] = "2100-01-01T00:00:00+00:00"
    elif damage == "duplicate_date": record["rows"][1]["date"] = record["rows"][0]["date"]
    elif damage == "invalid_date": record["rows"][0]["date"] = "not-a-date"
    else: record["rows"] = []
    original = signals.live_inputs(definition, daily_bars=True)
    live = MagicMock(return_value=(*original[:2], ["Mock original warning"], original[3]))
    result = market_cache.model_inputs(definition, live, daily_bars=True)
    live.assert_called_once()
    assert result[0] is original[0] and result[3] is original[3]
    assert result[2] == ["Mock original warning", market_cache.FALLBACK_WARNING]
    assert result[0].attrs["input_source"]["snapshot_fallback"] is True


@pytest.mark.parametrize("label,source", [("HAA-Simple Israel", cron.TASE_SOURCE), ("Inflation Compass Standard", cron.FRED_SOURCE)])
@pytest.mark.parametrize("damage", ["missing", "mixed"])
def test_cross_provider_gap_or_mixed_batch_falls_back_whole_model(monkeypatch, label, source, damage):
    from server import signals
    definition, records = loader_bundle(monkeypatch, label)
    key = next(k for k in records if k[0] == source)
    if damage == "missing": del records[key]
    else: records[key]["rows"][0]["refresh_id"] = "another-refresh"
    live = MagicMock(side_effect=lambda: signals.live_inputs(definition))
    result = market_cache.model_inputs(definition, live)
    assert live.call_count == 1 and result[2] == [market_cache.FALLBACK_WARNING]
    assert result[0].attrs["input_source"]["source"] == "live"


def test_partial_missing_observations_are_not_forward_filled(monkeypatch):
    definition, records = loader_bundle(monkeypatch, "A-RVol Shifter V3 Cash-Only")
    record = next(iter(records.values()))
    record["rows"][1]["close"] = None
    record["rows"][1]["open"] = None
    prices, _, warnings, opens = market_cache.model_inputs(definition, lambda: pytest.fail("No missing series"), daily_bars=True)
    assert not warnings
    assert pd.isna(prices.iloc[1, 0]) and pd.isna(opens.iloc[1, 0])


def test_oecd_stays_whole_live_and_failed_live_is_not_swallowed(monkeypatch):
    from haa.model_catalog import definition_for_label
    definition = definition_for_label("GGCEM Link Original")
    monkeypatch.setattr(market_cache, "cache_client", lambda: pytest.fail("Do not read a partial OECD snapshot"))
    frame = pd.DataFrame({"FAKE": [1.]})
    live = MagicMock(return_value=(frame, pd.DataFrame(), ["Mock OECD issue"]))
    assert market_cache.model_inputs(definition, live)[2] == ["Mock OECD issue", market_cache.FALLBACK_WARNING]
    with pytest.raises(RuntimeError, match="Mock live failure"):
        market_cache.model_inputs(definition, lambda: (_ for _ in ()).throw(RuntimeError("Mock live failure")))


def test_shared_input_cache_keeps_origin_but_live_bypasses_both_caches(monkeypatch):
    from server import signals, input_cache
    definition, _ = loader_bundle(monkeypatch, "HAA-Simple")
    # A working result store avoids unrelated cache-unavailable warnings.
    query = MagicMock()
    query.table.return_value = query.select.return_value = query.eq.return_value = query.upsert.return_value = query
    query.execute.return_value = SimpleNamespace(data=[])
    monkeypatch.setattr(cache, "cache_client", lambda: query)
    first = signals.load_inputs(definition)
    monkeypatch.setattr(market_cache, "model_inputs", lambda *a, **kw: pytest.fail("Warm input hit"))
    repeated = signals.load_inputs(definition)
    assert repeated[0].attrs == first[0].attrs
    pd.testing.assert_frame_equal(repeated[0], first[0], check_exact=True, check_freq=False)
    monkeypatch.setattr(input_cache, "inputs", lambda *a, **kw: pytest.fail("Live must bypass input cache"))
    with signals.input_policy(force_live=True):
        live = signals.load_inputs(definition)
        assert signals.FORCE_LIVE.get() is True
    assert signals.FORCE_LIVE.get() is False
    assert live[0].attrs["input_source"]["source"] == "live"
    assert not live[0].attrs["input_source"]["snapshot_fallback"]
    assert signals.load_inputs(definition, force_live=True)[0].attrs["input_source"]["source"] == "live"


def test_warm_input_cache_cannot_extend_snapshot_past_36_hours(monkeypatch):
    from server import signals, input_cache
    definition, _ = loader_bundle(monkeypatch, "HAA-Simple")
    old = signals.live_inputs(definition)
    old[0].attrs["input_source"] = {"source": "daily_snapshot", "refresh_stamps": ["2000-01-01T00:00:00+00:00"]}
    monkeypatch.setattr(input_cache, "inputs", lambda *a, **kw: old)
    result = signals.load_inputs(definition)
    assert result[0].attrs["input_source"]["source"] == "daily_snapshot"
    assert result[0].attrs != old[0].attrs
