import pandas as pd
import pytest

from haa.tase_data import TASE_ISRAEL_ASSET_IDS, TaseDataError, TasePriceSource, select_etf_price_field


class FakeSecurity:
    def __init__(self, security_id, responses, calls):
        self.security_id = security_id
        self.responses = responses
        self.calls = calls

    def history(self, **_):
        self.calls.append((self.security_id, "history"))
        return self.responses[self.security_id]


def factory_for(responses, calls):
    return lambda security_id: FakeSecurity(security_id, responses, calls)


def test_israel_asset_ids_are_fixed_to_tase_and_maya_instruments():
    assert TASE_ISRAEL_ASSET_IDS == {
        "CSPX_IL": "1159250",
        "FTSE_ALL_WORLD_IL": "1209220",
        "QQQ_IL": "1186063",
        "IEF_IL": "1159268",
        "SPMO_IL": "5140850",
        "AYALON_KASPIT": "5136866",
        "TA125_SMART_MOMENTUM": "5134713",
        "XLE_IL": "1145903",
        "XLK_IL": "1159193",
        "XLV_IL": "1150390",
        "XLP_IL": "1150366",
    }


def test_etf_prefers_adjusted_close_then_nav_then_close():
    assert select_etf_price_field(pd.DataFrame({"Adj Close": [1], "NAV": [2], "Close": [3]}), "CSPX_IL") == ("Adj Close", "Adjusted close")
    assert select_etf_price_field(pd.DataFrame({"NAV": [2], "Close": [3]}), "CSPX_IL") == ("NAV", "Published ETF NAV")
    assert select_etf_price_field(pd.DataFrame({"Close": [3]}), "CSPX_IL") == ("Close", "End-of-day close")


def test_etf_normalisation_uses_selected_field_and_real_dates_only():
    calls = []
    frame = pd.DataFrame(
        {"Adj Close": [100.0, None, 102.0], "Close": [99.0, 101.0, 103.0]},
        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]),
    )
    source = TasePriceSource(factory_for({"1159250": frame}, calls))
    result = source.fetch_asset("CSPX_IL")
    assert result.field == "Adjusted close"
    assert result.prices.to_dict() == {pd.Timestamp("2024-01-02"): 100.0, pd.Timestamp("2024-01-04"): 102.0}
    assert calls == [("1159250", "history")]


def test_mutual_fund_uses_maya_redemption_price_close():
    calls = []
    frame = pd.DataFrame({"Close": [100.0, 100.1]}, index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    source = TasePriceSource(factory_for({"5136866": frame}, calls))
    result = source.fetch_asset("AYALON_KASPIT")
    assert result.field == "Maya published redemption price"
    assert result.prices.iloc[-1] == 100.1
    assert calls == [("5136866", "history")]


def test_cache_avoids_duplicate_public_requests_and_returns_safe_copies():
    calls = []
    frame = pd.DataFrame({"Close": [100.0]}, index=pd.to_datetime(["2024-01-02"]))
    source = TasePriceSource(factory_for({"5136866": frame}, calls))
    first = source.fetch_asset("AYALON_KASPIT")
    first.prices.iloc[0] = -1
    second = source.fetch_asset("AYALON_KASPIT")
    assert calls == [("5136866", "history")]
    assert second.prices.iloc[0] == 100.0


def test_missing_expected_data_fails_without_fabricating_prices():
    calls = []
    source = TasePriceSource(factory_for({"1159268": pd.DataFrame({"Volume": [1]}, index=pd.to_datetime(["2024-01-02"]))}, calls))
    with pytest.raises(TaseDataError, match="none of Adj Close, NAV, or Close"):
        source.fetch_asset("IEF_IL")


def test_fetch_failure_is_actionable_for_csv_fallback():
    class BrokenSecurity:
        def history(self, **_):
            raise ConnectionError("blocked")

    source = TasePriceSource(lambda _: BrokenSecurity())
    with pytest.raises(TaseDataError, match="upload an official CSV replacement"):
        source.fetch_asset("CSPX_IL")
