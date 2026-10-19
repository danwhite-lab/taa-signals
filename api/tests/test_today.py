"""Today uses fake frozen prices/portfolios only, with all networking blocked."""
import ast
from copy import deepcopy
import json
from unittest.mock import Mock
import pandas as pd
import pytest

from test_api import ROOT, client
from test_private_api import signed_in, HEADERS
from test_signals import fixtures, AS_OF
from server import today as page, private_api as private, cache
from haa import data, portfolio_signals
from haa.portfolio import aggregate_holdings_by_currency, convert_currency, execution_security_label
from haa.signals import month_to_date_snapshot, latest_actionable_signal, latest_preview_signal

LABELS = ["HAA-Simple", "Orthogonal Alpha (BTAL/QLD)", "Inflation Compass Standard",
          "Buy and Hold SPY", "A-RVol Shifter V3 Cash-Only", "HAA-Simple Israel"]
CLOCK = AS_OF.tz_localize("UTC")


@pytest.fixture
def frozen(monkeypatch, signed_in):
    page.RESULTS.warm.clear()
    monkeypatch.setattr(page, "utc_now", lambda: CLOCK)
    old_monthly = portfolio_signals.to_month_end
    monkeypatch.setattr(portfolio_signals, "to_month_end", lambda frame: old_monthly(frame, as_of=AS_OF))
    monkeypatch.setattr(portfolio_signals, "latest_actionable_signal", lambda *a: latest_actionable_signal(*a, as_of=AS_OF))
    monkeypatch.setattr(page, "month_to_date_snapshot", lambda *a: month_to_date_snapshot(*a, as_of=AS_OF))
    monkeypatch.setattr(cache, "cache_client", lambda: (_ for _ in ()).throw(RuntimeError("Mock cache unavailable")))
    columns = {}
    for label in LABELS:
        prices, _, _ = fixtures(label)
        for key in prices:
            columns.setdefault(key, prices[key])
    combined = pd.DataFrame(columns)
    bundles = {}
    for label in LABELS:
        original, metadata, warnings = fixtures(label)
        frame = combined.loc[:, list(original)].dropna(how="all")
        bundles[label] = (frame, metadata, warnings)
    monkeypatch.setattr(page.signals_page, "load_inputs", lambda definition: deepcopy(bundles[definition.label]))
    return combined, bundles


def fake_portfolio(labels=LABELS[:2], **changes):
    payload = {"name": "PRIVATE-FAKE-NAME", "total_ils": 1234567.89, "ils_per_usd": 4.12345,
               "sleeves": [{"model": label, "weight": 100/len(labels)} for label in labels]}
    payload.update(changes)
    return [{"id": "PRIVATE-FAKE-ID", "is_default": True, "payload": payload}]


def route(monkeypatch, rows):
    monkeypatch.setattr(private.sync, "list_portfolios", lambda *a: deepcopy(rows))
    return client.get("/api/today", headers=HEADERS)


def direct_preview(label, prices):
    # Tests only: execute the original isolated pure helper, never the app/UI.
    tree = ast.parse((ROOT/"app.py").read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "next_portfolio_preview")
    namespace = {"MODEL_OPTIONS": page.MODEL_OPTIONS, "definition_for_label": page.definition_for_label,
        "ASSETS": page.ASSETS, "all_prices": prices, "monthly_strategy_input": portfolio_signals.monthly_strategy_input,
        "month_to_date_snapshot": page.month_to_date_snapshot, "latest_preview_signal": latest_preview_signal}
    exec(compile(ast.Module(body=[node], type_ignores=[]), "original-preview-test-only", "exec"), namespace)
    return namespace["next_portfolio_preview"](label)


@pytest.mark.parametrize("label", LABELS)
def test_current_signal_matches_original_combined_frame_and_pure_helper(frozen, monkeypatch, label):
    combined, bundles = frozen
    response = route(monkeypatch, fake_portfolio([label]))
    assert response.status_code == 200
    public = response.json()["public_sleeves"][0]
    original, error = portfolio_signals.portfolio_signal(page.MODEL_OPTIONS[label], combined.loc[:AS_OF])
    assert original is not None, error
    assert public["current"]["weights"] == original["weights"]
    assert public["current"]["signal_date"] == original["decision"].name.isoformat()
    assert public["current"]["regime"] == original["decision"]["regime"]
    assert public["current"]["trade"] == bool(original["decision"].get("trade", False))
    assert public["current"]["decision"] == page.signals_page.decision_record(original["decision"])
    assert response.headers["cache-control"] == "no-store, private"


@pytest.mark.parametrize("label", LABELS)
def test_preview_is_exact_original_helper_for_all_branches(frozen, label):
    combined, _ = frozen
    actual, error = page.preview_for(label, combined.loc[:AS_OF])
    expected, reason = direct_preview(label, combined.loc[:AS_OF])
    assert error == reason
    if expected is None:
        assert actual is None
    else:
        assert actual["weights"] == expected["weights"]
        assert actual["price_as_of"] == expected["price_as_of"]
        pd.testing.assert_series_equal(actual["decision"], expected["decision"])


def test_preview_source_verbatim_and_all_original_page_words_preserved():
    source = ast.parse((ROOT/"app.py").read_text())
    original = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == "next_portfolio_preview")
    copied = next(n for n in ast.walk(ast.parse((ROOT/"server/today.py").read_text())) if isinstance(n, ast.FunctionDef) and n.name == "next_portfolio_preview")
    assert ast.dump(original) == ast.dump(copied)
    content = json.loads((ROOT/"web/content/today.json").read_text())
    values = json.dumps(content, ensure_ascii=False)
    for phrase in ("What to hold now", "Monthly action", "Sleeve signals", "Set up a portfolio, then choose **Use as Today default** on the Portfolio page. It will sync privately across your devices.",
                   "This signal may be stale. Check that the data sources are up to date before acting.",
                   "Edit this portfolio or choose a different default on the Portfolio page."):
        assert phrase in values
    # The production helper is baked source, not an app.py runtime reader.
    production = (ROOT/"server/today.py").read_text()
    assert "read_text" not in production and "exec(" not in production


@pytest.mark.parametrize("label,reason,stamp", [("HAA-Simple", "No common current-month price row is available for the preview.", None),
    ("HAA-Simple", None, None), ("Orthogonal Alpha (BTAL/QLD)", "Required asset data is unavailable for the preview.", None)])
def test_missing_snapshot_reasons_verbatim(frozen, monkeypatch, label, reason, stamp):
    combined, _ = frozen
    monkeypatch.setattr(page, "month_to_date_snapshot", lambda *a: (None, stamp, reason))
    actual = page.preview_for(label, combined)
    assert actual == direct_preview(label, combined)
    assert actual == (None, reason or "No common current-month price row is available.")


@pytest.mark.parametrize("reason", ["No preview is available: insufficient valid history.", "No preview is available from the current-month prices.", None])
def test_missing_preview_decision_reasons(frozen, monkeypatch, reason):
    from haa.signals import PreviewStatus
    combined, _ = frozen
    monkeypatch.setattr(page, "latest_preview_signal", lambda *a: PreviewStatus(None, reason, AS_OF))
    assert page.preview_for("HAA-Simple", combined) == (None, reason or "No preview is available.")


def test_two_currency_composition_uses_saved_fx_and_exact_helpers(frozen, monkeypatch):
    rows = fake_portfolio(["HAA-Simple", "HAA-Simple Israel"])
    response = route(monkeypatch, rows).json()
    valid = [{"name": p["model"], "weight": 50., "currency": p["currency"], "target_weights": p["current"]["weights"]} for p in response["public_sleeves"]]
    expected = aggregate_holdings_by_currency(valid)
    assert {g["currency"] for g in response["holdings"]} == {"USD", "ILS"}
    for group in response["holdings"]:
        for actual, (asset, value) in zip(group["rows"], sorted(expected[group["currency"]].items())):
            amount = convert_currency(rows[0]["payload"]["total_ils"] * value["weight"], "ILS", group["currency"], rows[0]["payload"]["ils_per_usd"])
            assert actual["holding"] == execution_security_label(asset, group["currency"])
            assert actual["weight"] == value["weight"] and actual["amount"] == amount
            assert actual["amount_text"] == f"{amount:,.2f}" and actual["weight_text"] == f'{value["weight"]:.2%}'


@pytest.mark.parametrize("delta,visible", [(0., True), (5e-10, True), (2e-9, False), (.01, False)])
def test_exact_weight_tolerance(frozen, delta, visible):
    rows = fake_portfolio(["Buy and Hold SPY"]); rows[0]["payload"]["sleeves"][0]["weight"] += delta
    result = page.compose(rows, "code", CLOCK)
    assert (result["holdings"] is not None) is visible


@pytest.mark.parametrize("change", [{"sleeves": []}, {"sleeves": None}, {"sleeves": [{"model": "Unknown", "weight": 100}]},
    {"sleeves": [{"model": "HAA-Simple", "weight": "bad"}]}, {"sleeves": [{"weight": 100}]}, {"total_ils": None}, {"ils_per_usd": 0}, {"ils_per_usd": "bad"}])
def test_defensive_invalid_payload_parts_never_500_or_invent_values(frozen, monkeypatch, change):
    response = route(monkeypatch, fake_portfolio(**change))
    assert response.status_code == 200 and response.json()["holdings"] is None


def test_no_default_missing_keys_and_multiple_defaults(frozen, monkeypatch):
    assert route(monkeypatch, []).json()["has_default"] is False
    row = fake_portfolio()[0]; row["is_default"] = False
    assert route(monkeypatch, [row]).json()["has_default"] is False
    row["is_default"] = True; row.pop("payload")
    assert route(monkeypatch, [row]).json()["issues"] == ["invalid_payload"]
    assert route(monkeypatch, fake_portfolio()+fake_portfolio()).json()["issues"] == ["multiple_defaults"]
    assert route(monkeypatch, fake_portfolio(name=None)).json()["caption"] is None


def fake_public(weights=None, preview=True, trade=False, date="2024-05-31"):
    weights = weights or {"SPY": 1.}
    return {"model": "HAA-Simple", "currency": "USD", "current": {"weights": weights, "signal_date": date,
      "decision": {"trade": trade}, "holding": "Fake SPY 100%", "status": "Ready · fake"}, "reason": None,
      "preview": {"weights": weights, "price_as_of": "2024-06-13", "allocation": "Fake SPY 100%"} if preview else None,
      "preview_reason": "Mock unavailable" if not preview else None, "warnings": [], "fallback_warnings": [], "cache": {"hit": None, "warnings": []}, "timing": {}}


@pytest.mark.parametrize("changed,preview,expected", [(False, True, "no"), (True, True, "yes"), (False, False, None)])
def test_change_yes_no_dash_from_exact_weights(frozen, monkeypatch, changed, preview, expected):
    public = fake_public(preview=preview)
    if changed: public["preview"]["weights"] = {"IEF": 1.}
    monkeypatch.setattr(page, "public_sleeve", lambda *a: public)
    result = page.compose(fake_portfolio(["HAA-Simple"]), "code", CLOCK)
    assert result["previews"][0]["change"] == expected


@pytest.mark.parametrize("age,stale", [(45, False), (46, True)])
def test_stale_threshold_exact_boundary(frozen, monkeypatch, age, stale):
    public = fake_public(date=(AS_OF-pd.Timedelta(days=age)).date().isoformat())
    monkeypatch.setattr(page, "public_sleeve", lambda *a: public)
    assert page.compose(fake_portfolio(["HAA-Simple"]), "code", CLOCK)["stale"] is stale


def test_trade_banner_and_invalid_sleeve(frozen, monkeypatch):
    public = fake_public(trade=True)
    monkeypatch.setattr(page, "public_sleeve", lambda *a: public)
    assert page.compose(fake_portfolio(["HAA-Simple"]), "code", CLOCK)["monthly_action"] == "changed"
    public["current"]["decision"]["trade"] = False
    assert page.compose(fake_portfolio(["HAA-Simple"]), "code", CLOCK)["monthly_action"] == "unchanged"
    rows = fake_portfolio(); rows[0]["payload"]["sleeves"][0]["model"] = "unknown"
    result = page.compose(rows, "code", CLOCK)
    assert result["holdings"] is None and result["monthly_action"] == "unavailable"


def test_cache_hit_revised_data_parameters_and_no_private_cache_contents(frozen, monkeypatch):
    combined, bundles = frozen
    actual_run = page.RESULTS.run; calls = []
    def run(**kwargs):
        calls.append({k: v for k,v in kwargs.items() if k != "compute"})
        return actual_run(**kwargs)
    monkeypatch.setattr(page.RESULTS, "run", run)
    rows = fake_portfolio(["Buy and Hold SPY"])
    first = page.compose(rows, "code", CLOCK); second = page.compose(rows, "code", CLOCK)
    assert first["public_sleeves"][0]["cache"]["hit"] is None
    assert second["public_sleeves"][0]["cache"]["hit"] == "memory"
    rows[0]["payload"].update(name="ANOTHER-PRIVATE-NAME", total_ils=9999876.54, ils_per_usd=9.87654)
    assert page.compose(rows, "code", CLOCK)["public_sleeves"][0]["cache"]["hit"] == "memory"
    serialized = json.dumps({"calls": calls, "cached": list(page.RESULTS.warm.values())})
    for private_value in ("PRIVATE-FAKE", "ANOTHER-PRIVATE", "1234567.89", "4.12345", "9999876.54", "9.87654", "total_ils", "ils_per_usd", "portfolio"):
        assert private_value not in serialized
    assert calls[0]["params"]["presentation"] == "today-v1"
    prices = bundles["Buy and Hold SPY"][0]
    prices.iloc[0,0] += .01
    assert page.compose(rows, "code", CLOCK)["public_sleeves"][0]["cache"]["hit"] is None
    assert page.compose(rows, "new-code", CLOCK)["public_sleeves"][0]["cache"]["hit"] is None
    assert page.public_sleeve("Buy and Hold SPY", "new-code", CLOCK+pd.Timedelta(days=1))["cache"]["hit"] is None


@pytest.mark.parametrize("failure", ["load", "current", "preview", "degraded"])
def test_failures_unavailable_and_degraded_results_not_cached(frozen, monkeypatch, failure):
    if failure == "load": monkeypatch.setattr(page.signals_page, "load_inputs", lambda *a: (_ for _ in ()).throw(ValueError("Mock data failure")))
    if failure == "current": monkeypatch.setattr(page, "portfolio_signal", lambda *a: (None, "Mock unavailable current"))
    if failure == "preview": monkeypatch.setattr(page, "preview_for", lambda *a: (None, "Mock unavailable preview"))
    if failure == "degraded": frozen[1]["HAA-Simple"][2].append("Mock disclosed provider fallback")
    for _ in range(2):
        result = page.public_sleeve("HAA-Simple", "code", CLOCK)
        assert result["cache"]["hit"] is None
    assert not page.RESULTS.warm
    if failure == "degraded": assert "Mock disclosed provider fallback" in result["warnings"]


def test_cache_failure_does_not_compute_twice(frozen, monkeypatch):
    compute = Mock(wraps=page.build_sleeve); monkeypatch.setattr(page, "build_sleeve", compute)
    result = page.public_sleeve("HAA-Simple", "code", CLOCK)
    assert compute.call_count == 1 and result["cache"]["warnings"]


def test_auth_read_only_no_user_id_and_no_mutations(frozen, monkeypatch):
    for name in ("save_workspace", "save_holdings_workspace", "save_portfolio", "delete_portfolio"):
        monkeypatch.setattr(private.sync, name, lambda *a, **k: pytest.fail("Today must not mutate user data"))
    assert client.get("/api/today").status_code == 401
    assert route(monkeypatch, fake_portfolio()).status_code == 200
    assert client.get("/api/today?user_id=other", headers=HEADERS).status_code == 400
    assert client.post("/api/today", headers=HEADERS, json={}).status_code == 405
    monkeypatch.setattr(private.sync, "verified_session", lambda *a: (_ for _ in ()).throw(ValueError("bad token")))
    assert client.get("/api/today", headers=HEADERS).status_code == 401


def test_vercel_rewrite_parameter_does_not_block_today(frozen, monkeypatch):
    monkeypatch.setattr(private.sync, "list_portfolios", lambda *a: [])
    direct = client.get("/api/today", headers=HEADERS)
    rewritten = client.get("/api/today?path=today", headers=HEADERS)
    assert rewritten.status_code == 200, rewritten.text
    assert rewritten.json()["has_default"] == direct.json()["has_default"] is False
    monkeypatch.setattr(private.sync, "list_portfolios", lambda *a: fake_portfolio(["Buy and Hold SPY"]))
    direct = client.get("/api/today", headers=HEADERS).json()
    rewritten = client.get("/api/today?path=today", headers=HEADERS)
    assert rewritten.status_code == 200
    for field in ("signals", "holdings", "previews", "monthly_action"):
        assert rewritten.json()[field] == direct[field]
    assert rewritten.headers["cache-control"] == "no-store, private"


@pytest.mark.parametrize("query", ["path=other", "path=today&path=today", "path=today&path=other", "path=today&user_id=other", "label=SPY"])
def test_today_rejects_options_even_with_routing_parameter(frozen, query):
    response = client.get(f"/api/today?{query}", headers=HEADERS)
    assert response.status_code == 400
    assert response.json()["detail"] == "Today reads your saved default portfolio; query parameters are not supported."


def test_today_configuration_and_private_read_errors_remain_safe(frozen, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL")
    response = client.get("/api/today?path=today", headers=HEADERS)
    assert response.status_code == 503
    assert response.json()["detail"] == "Sign-in service is not configured."
    monkeypatch.setenv("SUPABASE_URL", "https://mock.invalid")
    monkeypatch.setattr(private.sync, "list_portfolios", Mock(side_effect=RuntimeError("fake private provider details")))
    response = client.get("/api/today?path=today", headers=HEADERS)
    assert response.status_code == 502
    assert "fake private provider details" not in response.text


def test_future_observations_do_not_enter_cache_and_daily_cutoff_is_keyed(frozen, monkeypatch):
    prices = frozen[1]["A-RVol Shifter V3 Cash-Only"][0]
    result = page.public_sleeve("A-RVol Shifter V3 Cash-Only", "code", CLOCK)
    assert result["current"]
    prices.loc[pd.Timestamp("2024-06-28"), "QQQ"] = 999999.
    repeated = page.public_sleeve("A-RVol Shifter V3 Cash-Only", "code", CLOCK)
    assert repeated["cache"]["hit"] == "memory"
    captured = []
    original = page.RESULTS.run
    def run(**kwargs):
        captured.append(kwargs["params"])
        return original(**kwargs)
    monkeypatch.setattr(page.RESULTS, "run", run)
    page.public_sleeve("A-RVol Shifter V3 Cash-Only", "code", CLOCK)
    assert captured[0]["daily_cutoff"] == str(page.MODEL_OPTIONS["A-RVol Shifter V3 Cash-Only"]().completed_cutoff(CLOCK))


def test_preview_exception_keeps_current_signal_but_never_caches(frozen, monkeypatch):
    monkeypatch.setattr(page, "preview_for", lambda *a: (_ for _ in ()).throw(ValueError("Mock preview failure")))
    result = page.public_sleeve("HAA-Simple", "code", CLOCK)
    assert result["current"] and result["preview"] is None
    assert result["preview_reason"] == "Mock preview failure" and not page.RESULTS.warm
