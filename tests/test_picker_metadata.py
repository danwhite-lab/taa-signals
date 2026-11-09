"""Presentation metadata must remain in sync with the selectable catalogue."""
import json

from haa.model_catalog import MODEL_CATALOG
from scripts.build_picker_metadata import CONTENT, metadata


def test_generated_picker_records_match_repository_declarations():
    labels, details = metadata()
    assert labels == json.loads((CONTENT / "picker-labels.json").read_text())
    assert details == json.loads((CONTENT / "picker-metadata.json").read_text())
    assert set(labels["models"]) == {model.label for model in MODEL_CATALOG}
    assert details["models"].keys() == labels["models"].keys()
    for model in details["models"].values():
        assert all(key in details["funds"] for key in model["held"] or ())


def test_actual_holdings_are_separate_from_series_and_return_proxies():
    _, details = metadata()
    models, funds = details["models"], details["funds"]
    assert "TASE:5142476" in models["HAA 4 Israel"]["held"]
    assert "US:VXUS" not in models["HAA 4 Israel"]["held"]
    assert [proxy["series"]["identifier"] for proxy in models["HAA 4 Israel"]["proxies"]] == ["VXUS"]
    assert "US:TIP" not in models["HAA-Simple"]["held"]
    assert models["Buy and Hold Japan Nikkei 225"]["held"] == []
    assert models["Buy and Hold Japan Nikkei 225"]["benchmark"]["identifier"] == "^N225"
    assert funds["TASE:1159250"]["provider_identifiers"] == ["1159250.TA"]
    assert funds["TASE:1159250"]["ticker"] is None
    assert funds["TASE:1159250"]["ucits"] is True
    assert funds["TASE:1159250"]["market"] == "TASE"
    assert funds["TASE:1147875"]["id"] != funds["TASE:5141627"]["id"]


def test_declared_execution_securities_stay_in_their_market():
    _, details = metadata()
    models = details["models"]
    for label in ("HAA-Simple", "Century Momentum Move to Cash", "A-RVol Shifter V3 Cash-Only"):
        assert "US:BIL" in models[label]["held"]
    assert models["GEM"]["held"] == ["US:SPY", "US:VEU", "US:AGG"]
    assert "BIL" in {series["identifier"] for series in models["GEM"]["signal"]}
    for definition in MODEL_CATALOG:
        if definition.implementation in {"Original", "Documented interpretation"}:
            assert all(key.startswith("US:") for key in models[definition.label]["held"])
    assert models["HAA-Simple Israel"]["held"] == ["TASE:1159250", "TASE:1159268", "TASE:5136866"]
    assert models["Century Momentum Move to Cash Israel"]["held"] == ["TASE:5140850", "TASE:5117700"]
    assert models["Buy and Hold Gold Israel"]["held"] == ["TASE:5141627"]
    assert models["Buy and Hold Gold Israel"]["benchmark"]["identifier"] == "1147875"
    assert details["funds"]["TASE:1159102"]["full_name"] is None
