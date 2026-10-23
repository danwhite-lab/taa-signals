import pandas as pd
import pytest

from haa.tase_data import TASE_ISRAEL_ASSET_IDS, TaseDataError, TasePriceSource, select_etf_price_field
from haa.tase_data import parse_published_eod_closes


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
        "NASDAQ_X3_MONTHLY_IL": "1187079",
        "TA125_X3_IL": "5117684",
        "RVOL_3X_IL": "1187079",
        "RVOL_QQQ_IL": "1149038",
        "RVOL_SPY_IL": "1144385",
        "RVOL_LQD_IL": "1159185",
        "RVOL_HYG_IL": "1159078",
        "RVOL_CASH_IL": "5117700",
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
        "XLU_IL": "1150507",
        "GOLD_IL": "1147875",
        "HAREL_GOV_BONDS_IL": "5131792",
    }


def test_etf_prefers_adjusted_close_then_nav_then_close():
    assert select_etf_price_field(pd.DataFrame({"Adj Close": [1], "NAV": [2], "Close": [3]}), "CSPX_IL") == ("Adj Close", "Adjusted close")
    assert select_etf_price_field(pd.DataFrame({"NAV": [2], "Close": [3]}), "CSPX_IL") == ("NAV", "Published ETF NAV")
    assert select_etf_price_field(pd.DataFrame({"Close": [3]}), "CSPX_IL") == ("Close", "End-of-day close")


def test_leveraged_plain_assets_use_etf_and_maya_paths_without_proxies():
    from haa.tase_data import TASE_ETF_ASSETS, plain_holding_provenance
    calls=[]
    dates=pd.to_datetime(["2024-01-02","2024-01-03"])
    frame=pd.DataFrame({"Adj Close":[100.,110.],"Close":[90.,95.]},index=dates)
    source=TasePriceSource(factory_for({"1187079":frame,"5117684":frame},calls))
    prices,metadata=source.fetch_all(("NASDAQ_X3_MONTHLY_IL","TA125_X3_IL"))
    assert "NASDAQ_X3_MONTHLY_IL" in TASE_ETF_ASSETS
    assert "TA125_X3_IL" not in TASE_ETF_ASSETS
    assert prices.NASDAQ_X3_MONTHLY_IL.tolist()==[100.,110.]
    assert prices.TA125_X3_IL.tolist()==[90.,95.]
    assert metadata.loc["NASDAQ_X3_MONTHLY_IL","price_field"]=="Adjusted close"
    assert metadata.loc["TA125_X3_IL","price_field"]=="Maya published redemption price"
    assert metadata.loc["NASDAQ_X3_MONTHLY_IL","identifier"]=="1187079"
    assert metadata.loc["TA125_X3_IL","identifier"]=="5117684"
    assert metadata.source.str.contains("proxy",case=False).sum()==0
    assert plain_holding_provenance(metadata,prices.columns).history_kind.eq("Actual fund history").all()
    assert calls==[("1187079","history"),("5117684","history")]


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


def test_plain_gold_and_harel_bonds_use_exact_local_security_histories():
    calls = []
    dates = pd.to_datetime(["2024-01-02", "2024-01-03"])
    source = TasePriceSource(factory_for({
        "1147875": pd.DataFrame({"Adj Close": [100., 102.], "Close": [99., 101.]}, index=dates),
        "5131792": pd.DataFrame({"Close": [100., 100.1]}, index=dates),
    }, calls))
    frame, metadata = source.fetch_all(("GOLD_IL", "HAREL_GOV_BONDS_IL"))
    assert frame.GOLD_IL.tolist() == [100., 102.]
    assert metadata.loc["HAREL_GOV_BONDS_IL", "price_field"] == "Maya published redemption price"
    assert calls == [("1147875", "history"), ("5131792", "history")]
    from haa.tase_data import plain_holding_provenance
    actual = plain_holding_provenance(metadata, frame.columns)
    assert actual.history_kind.eq("Actual fund history").all()
    flagged = plain_holding_provenance(metadata, frame.columns, {"GOLD_IL": frame.GOLD_IL})
    assert "stand-in" in flagged.loc["GOLD_IL", "history_kind"]
    assert not flagged.automatic_proxy_extension.any()


def test_gld_source_substitution_is_flagged_as_stand_in():
    from haa.tase_data import plain_holding_provenance
    metadata = pd.DataFrame({"source": ["Yahoo Finance"], "identifier": ["GLD"],
                             "price_field": ["Adj Close"]}, index=["GLD"])
    assert plain_holding_provenance(metadata, ("GLD",)).loc["GLD", "history_kind"] == "Actual fund history"
    metadata.loc["GLD", "identifier"] = "IAU"
    assert "stand-in" in plain_holding_provenance(metadata, ("GLD",)).loc["GLD", "history_kind"]


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


@pytest.mark.parametrize("headers", [
    "Date,Adjusted Closing Price,Closing Price (0.01 ILS),Opening Price,High Price,Low Price,Turnover(ILS)",
    "תאריך,שער נעילה מתואם,שער נעילה (באגורות),שער פתיחה,שער גבוה,שער נמוך,מחזור",
])
def test_published_closes_keep_no_trade_rows_without_filling_missing_adjusted_prices(headers):
    raw = "title\nrange\n" + headers + "\n" + (
        "05/01/2025,100,100,100,101,99,1000\n"
        "06/01/2025,100,100,0,,,0\n"
        "07/01/2025,,102,102,103,101,1000\n")
    frame = parse_published_eod_closes(raw)
    assert frame.loc["2025-01-06", "Adj Close"] == 100.
    assert pd.isna(frame.loc["2025-01-07", "Adj Close"])
    assert "Open" not in frame
    assert list(frame.index) == list(pd.date_range("2025-01-05", periods=3))


def test_published_close_parser_rejects_malformed_or_duplicate_dates():
    with pytest.raises(TaseDataError, match="Cannot parse"):
        parse_published_eod_closes("title\nrange\nDate,Volume\n05/01/2025,1")
    with pytest.raises(TaseDataError, match="Duplicate"):
        parse_published_eod_closes("title\nrange\nDate,Adjusted Closing Price\n05/01/2025,100\n05/01/2025,101")


def test_default_rvol_source_uses_published_closes_other_sources_are_unchanged(monkeypatch):
    import haa.tase_data as module
    frame = pd.DataFrame({"Adj Close": [100.]}, index=pd.DatetimeIndex(["2025-01-05"]))
    calls = []
    monkeypatch.setattr(module, "_default_security_factory", factory_for({"1149038": frame, "1159250": frame}, calls))
    downloaded = []
    monkeypatch.setattr(module, "download_published_eod_closes", lambda sid: downloaded.append(sid) or frame)
    source = TasePriceSource()
    local = source.fetch_asset("RVOL_QQQ_IL")
    source.fetch_asset("CSPX_IL")
    assert downloaded == ["1149038"]
    assert calls == [("1159250", "history")]
    assert "no-trade valuations retained" in local.source


def test_compass_extended_window_is_per_source_and_default_stays_five_years(monkeypatch):
    import haa.tase_data as module
    frame = pd.DataFrame({"Adj Close": [100.]}, index=pd.DatetimeIndex(["2019-01-02"]))
    calls = []
    class Security:
        def history(self, **kwargs):
            calls.append(kwargs)
            return frame
    TasePriceSource(lambda _: Security()).fetch_asset("XLE_IL")
    TasePriceSource(lambda _: Security(), history_years=module.INFLATION_COMPASS_HISTORY_YEARS).fetch_asset("XLU_IL")
    assert calls == [{"years": 5}, {"years": 8}]
    assert module.PUBLIC_HISTORY_YEARS == 5
    assert "XLU_IL" in module.TASE_ETF_ASSETS
    downloaded = []
    monkeypatch.setattr(module, "_default_security_factory", lambda _: Security())
    monkeypatch.setattr(module, "download_published_eod_closes", lambda sid, **kw: downloaded.append((sid, kw)) or frame)
    result = TasePriceSource(history_years=8).fetch_asset("XLU_IL")
    assert downloaded == [("1150507", {"history_years": 8})]
    assert result.prices.index.min() == pd.Timestamp("2019-01-02")
    assert "actual available history starts 2019-01-02" in result.source
