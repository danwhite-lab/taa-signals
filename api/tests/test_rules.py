import ast
import json
from pathlib import Path

from test_api import ROOT, client, module


def original_literal_rules():
    tree = ast.parse((ROOT / "app.py").read_text())
    declaration = next(node for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == "MODEL_RULES"
                               for target in node.targets))
    return ast.literal_eval(declaration.value)


def test_rules_preserve_original_words_and_all_catalogue_implementations():
    from haa.model_catalog import MODEL_CATALOG

    response = client.get("/api/rules")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["source"] == "app.py:MODEL_RULES"
    assert [row["label"] for row in body["models"]] == [item.label for item in MODEL_CATALOG]
    by_label = {row["label"]: row for row in body["models"]}
    for label, text in original_literal_rules().items():
        assert by_label[label]["markdown"] == text
    for item in MODEL_CATALOG:
        assert by_label[item.label]["risk_warning"] == getattr(item.model_class, "risk_warning", None)
    assert "**13612U:**" in body["implementation_notes"]


def test_generated_tase_rules_and_missing_descriptions_are_not_replaced():
    body = client.get("/api/rules").json()
    rows = {row["label"]: row for row in body["models"]}
    assert "50% 1187079 / 50% 1149038" in rows["A-RVol Shifter V3 Cash-Only Israel"]["markdown"]
    for label, row in rows.items():
        if label.startswith("A-RVol V3 US Signals / TASE"):
            assert row["markdown"].startswith(rows["A-RVol Shifter V3 Cash-Only"]["markdown"])
            assert row["risk_warning"] in row["markdown"]
    missing = {row["label"] for row in rows.values() if row["description_missing"]}
    assert missing == {"Inflation Compass Standard Israel", "Inflation Compass Fast (40-day) Israel",
                       "Inflation Compass Steady (80-day) Israel", "Momentum-Correlation Triplet"}
    assert all(rows[label]["markdown"] is None for label in missing)


def test_rules_need_no_live_market_data_or_streamlit_execution(monkeypatch):
    from haa import data, tase_data
    def forbidden(*args, **kwargs):
        raise AssertionError("Rules must not fetch market data")
    monkeypatch.setattr(data, "download_yahoo_prices", forbidden)
    monkeypatch.setattr(data, "download_yahoo_daily_bars", forbidden)
    monkeypatch.setattr(tase_data, "TasePriceSource", forbidden)
    module._shared_rules.cache_clear()
    assert client.get("/api/rules").status_code == 200


def test_rule_source_failure_is_visible(monkeypatch):
    def failed():
        raise ValueError("Shared rule source is missing")
    monkeypatch.setattr(module, "_shared_rules", failed)
    response = client.get("/api/rules")
    assert response.status_code == 500
    assert response.json()["detail"] == "ValueError: Shared rule source is missing"


def test_deployment_bundles_source_and_navigation_names_the_catalogue():
    assert "/app.py" not in (ROOT / ".vercelignore").read_text().splitlines()
    source = (ROOT / "web" / "components" / "top-navigation.tsx").read_text()
    tree = ast.parse((ROOT / "app.py").read_text())
    navigation = next(node for node in ast.walk(tree) if isinstance(node, ast.Call)
                      and isinstance(node.func, ast.Attribute) and node.func.attr == "radio"
                      and node.args and isinstance(node.args[0], ast.Constant)
                      and node.args[0].value == "Primary navigation")
    for name in ast.literal_eval(navigation.args[1]):
        name = "Strategy Catalogue" if name == "Rules" else name
        assert f'"{name}"' in source
    assert 'aria-disabled="true"' not in source
    assert '<div className="brand">Signalboard <TestLoginBadge /></div>' in source


def test_plain_rules_match_supplied_text_without_changing_technical_fields():
    supplied = json.loads((ROOT / "data" / "strategy_plain_language.json").read_text())["strategies"]
    for row in client.get("/api/rules").json()["models"]:
        expected = supplied.get(row["label"], {})
        assert row["plain_text"] == expected.get("plain_language")
        assert row["plain_flags"] == expected.get("flags", [])


def test_missing_plain_label_is_safe(monkeypatch):
    monkeypatch.setattr(module, "_plain_rules", lambda: {})
    rows = client.get("/api/rules").json()["models"]
    assert rows
    assert all(row["plain_text"] is None and row["plain_flags"] == [] for row in rows)


def test_plain_file_is_read_once(monkeypatch):
    module._plain_rules.cache_clear()
    original = Path.read_text
    reads = []
    def counted(path, *args, **kwargs):
        if path.name == "strategy_plain_language.json":
            reads.append(path)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", counted)
    try:
        assert client.get("/api/rules").status_code == 200
        assert client.get("/api/rules").status_code == 200
        assert len(reads) == 1
    finally:
        module._plain_rules.cache_clear()
