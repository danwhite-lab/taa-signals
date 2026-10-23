from datetime import date
from haa.workspace_sync import snapshot, restore


def test_workspace_roundtrip_preserves_preferences_and_dates_but_not_secrets():
    state = {
        "portfolio_name": "My portfolio",
        "portfolio_sleeves": [{"id": 1, "weight": 100.0, "model": "HAA-Simple"}],
        "compare_start": date(2020, 1, 1),
        "supabase_session": {"access_token": "must-not-sync"},
        "uploaded_replacements": {"SPY": "must-not-sync"},
        "computed_result": "must-not-sync",
        "page": "Portfolio",
        "browser_portfolio_library": [{"name": "Separate account record"}],
        "browser_default_portfolio": {"name": "Separate account default"},
    }
    recovered = restore(snapshot(state))
    assert recovered == {key: state[key] for key in ("portfolio_name", "portfolio_sleeves", "compare_start")}


def test_restore_rejects_unknown_fields_and_bad_dates():
    assert restore({"supabase_session": {}, "compare_start": {"__date__": "not a date"}, "tax_enabled": False}) == {"tax_enabled": False}


def test_snapshot_does_not_store_nonfinite_or_non_json_values():
    assert snapshot({"initial": float("nan"), "portfolio_sleeves": object()}) == {}


def test_allocation_mode_is_a_validated_preference_not_a_reservation():
    import pytest
    from haa.allocation_mode import DEFAULT_ALLOCATION_MODE, ALLOCATION_MODE_ERROR
    assert DEFAULT_ALLOCATION_MODE == "proportional"
    for mode in ("proportional","biggest_gap_first"):
        assert restore(snapshot({"rebalance_allocation_mode":mode,"unspent_by_fund":{"fake":"100"}})) == {"rebalance_allocation_mode":mode}
    assert restore({}) == {}  # No artificial stored default.
    for invalid in (None, "", False, [], "other"):
        for function in (snapshot,restore):
            with pytest.raises(ValueError,match=ALLOCATION_MODE_ERROR):
                function({"rebalance_allocation_mode":invalid})
