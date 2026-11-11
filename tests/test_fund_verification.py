from types import SimpleNamespace

import pandas as pd
import pytest

from haa import fund_verification as verify


def test_report_needs_matching_cover_and_explicit_unit_statements(monkeypatch):
    cover = "(5139837 :הסרוב רפסמ)"
    unit = verify.NOMINAL_STATEMENTS[0]
    redemption = verify.REDEMPTION_STATEMENTS[0]

    def check(*pages):
        monkeypatch.setattr("pypdf.PdfReader", lambda *args, **kwargs: SimpleNamespace(
            is_encrypted=False, pages=[SimpleNamespace(extract_text=lambda text=text, **_: text) for text in pages]))
        return verify.report_verifies_units(b"fixture", "5139837", "IL0051398373")

    assert check(cover, unit, redemption)
    assert not check(cover, unit)
    assert not check(cover, redemption)
    assert not check("The fund mentions 5139837 but it is not identified", unit, redemption)
    assert not check(cover, unit, "מספר בורסה: 5132972 " + redemption)
    assert not check("מספר בורסה: 5132972", unit, redemption)


@pytest.mark.parametrize("flags,status,reason", [
    (False, "Merged", "inactive"), (False, "Liquidation", "inactive"),
    (True, None, "tase_currency"), (None, None, "tase_currency"),
])
def test_ineligible_tase_metadata_fails_before_pdf_or_price(monkeypatch, flags, status, reason):
    monkeypatch.setattr(verify, "_maya", lambda _: ("mutual", {
        "deleted": False, "mergingLiquidationStatus": status,
        "features": [{"title": verify.DOLLAR_UNITS, "enabled": flags}]}))
    with pytest.raises(verify.FundVerificationError) as error:
        verify.verify_fund("TASE", "5139837")
    assert error.value.reason == reason


@pytest.mark.parametrize("kind,currency,reason", [
    ("ETF", "USD", None), ("INDEX", "JPY", "fund_type"), ("EQUITY", "USD", "fund_type"),
    ("ETF", "GBp", "currency"), ("ETF", "EUR", None), ("ETF", "GBP", None),
])
def test_yahoo_type_and_exact_currency(monkeypatch, kind, currency, reason):
    identifier = "TEST"
    metadata = {"instrumentType": kind, "symbol": identifier, "currency": currency, "exchangeName": "TEST", "longName": "Test"}
    ticker = SimpleNamespace(get_history_metadata=lambda: metadata, history=lambda **_: pd.DataFrame(
        {"Close": [101]}, index=pd.DatetimeIndex(["2025-12-30"])))
    monkeypatch.setattr(verify, "yahoo_ticker", lambda _: ticker)
    monkeypatch.setattr(verify, "fx_to_ils", lambda value: {
        "price": "3.5", "as_of": "2025-12-30", "source": f"Yahoo {value}/ILS"})
    if reason:
        with pytest.raises(verify.FundVerificationError) as error:
            verify.verify_fund("Global", identifier)
        assert error.value.reason == reason
    else:
        fund, quote = verify.verify_fund("Global", identifier)
        assert fund["currency"] == currency and currency in fund["fx"]["source"]
        assert quote["price"] == "101" and quote["as_of"] == "2025-12-30"


def mutual_identity():
    return ({"identifier": "5139837", "market": "TASE", "name": "Fixture fund",
             "kind": "mutual", "currency": "ILS", "isin": "IL0051398373"},
            {"lastAnnualReportId": 1732868, "redemptionPrice": 108.32,
             "ratesAsOf": "2026-11-09"})


def test_missing_pdf_dependency_is_an_unexpected_verification_failure(monkeypatch):
    import sys

    monkeypatch.setattr(verify, "tase_identity", lambda _: mutual_identity())
    monkeypatch.setattr(verify, "fetch_report", lambda _: b"fixture")
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(verify.FundVerificationError) as error:
        verify.verify_fund("TASE", "5139837")
    assert error.value.reason == "verification"
    assert str(error.value) != verify.ERRORS["price"]


def test_mutual_verification_with_pdf_dependency_and_explicit_units(monkeypatch):
    monkeypatch.setattr(verify, "tase_identity", lambda _: mutual_identity())
    monkeypatch.setattr(verify, "fetch_report", lambda _: b"fixture")
    pages = ["מספר בורסה: 5139837", verify.NOMINAL_STATEMENTS[0],
             verify.REDEMPTION_STATEMENTS[0]]
    monkeypatch.setattr("pypdf.PdfReader", lambda *args, **kwargs: SimpleNamespace(
        is_encrypted=False,
        pages=[SimpleNamespace(extract_text=lambda text=text, **_: text) for text in pages]))
    fund, quote = verify.verify_fund("TASE", "5139837")
    assert fund["unit_report"] == 1732868
    assert quote["price"] == "1.0832"
    assert quote["as_of"] == "2026-11-09"


@pytest.mark.parametrize("failure", [RuntimeError("provider bug"), TypeError("bad payload")])
def test_unexpected_identity_exception_is_not_a_price_failure(monkeypatch, failure):
    def fail(_):
        raise failure

    monkeypatch.setattr(verify, "_maya", fail)
    with pytest.raises(verify.FundVerificationError) as error:
        verify.verify_fund("TASE", "5139837")
    assert error.value.reason == "verification"


def test_expected_missing_quote_keeps_price_message(monkeypatch):
    fund, detail = mutual_identity()
    detail["ratesAsOf"] = None
    monkeypatch.setattr(verify, "tase_identity", lambda _: (fund, detail))
    monkeypatch.setattr(verify, "fetch_report", lambda _: b"fixture")
    monkeypatch.setattr(verify, "report_verifies_units", lambda *args: True)
    with pytest.raises(verify.FundVerificationError) as error:
        verify.verify_fund("TASE", "5139837")
    assert error.value.reason == "price"


@pytest.fixture
def foreign_provider(monkeypatch):
    import json
    from pathlib import Path
    from tasekit.api import TaseClient
    from haa.tase_data import parse_published_eod_closes

    root = Path(__file__).parent / "fixtures/foreign_etfs"
    listings = {n: json.loads((root / f"{n}.json").read_text())
                for n in ("1209220", "1159169", "1159151", "1159250")}

    def no_maya(_):
        raise verify.FundVerificationError("identity")

    monkeypatch.setattr(verify, "_maya", no_maya)
    monkeypatch.setattr(TaseClient, "fetch_security_data", lambda self, n: listings[n])
    monkeypatch.setattr(verify, "download_published_eod_closes", lambda n:
                        parse_published_eod_closes((root / f"{n}.csv").read_text()))
    return listings


@pytest.mark.parametrize("identifier", ["1209220", "1159169", "1159151", "1159250"])
def test_official_foreign_etf_fixtures_pass_with_dated_ils_close(foreign_provider, identifier):
    fund, quote = verify.verify_fund("TASE", identifier)
    assert fund["isin"] == foreign_provider[identifier]["ISIN"]
    assert fund["kind"] == "etf" and fund["currency"] == "ILS"
    assert quote["as_of"] == "2026-11-10"
    assert verify.positive(quote["price"]) > 0


@pytest.mark.parametrize("changes,reason", [
    ({"Type": "Share", "IsForeignETF": False}, "fund_type"),
    ({"Type": "Index", "IsForeignETF": False}, "fund_type"),
    ({"Type": "Bond", "ShareType": "2301"}, "fund_type"),
    ({"SecuritySubType": "Warrant"}, "fund_type"),
    ({"ShareType": "9999"}, "fund_type"),
    ({"SuspendStatus": "Suspended"}, "inactive"),
    ({"isTrading": False}, "inactive"),
    ({"Id": "01159169"}, "identity"),
    ({"ISIN": None}, "identity"),
    ({"LongName": ""}, "identity"),
])
def test_foreign_admission_fails_closed(foreign_provider, changes, reason):
    foreign_provider["1209220"].update(changes)
    with pytest.raises(verify.FundVerificationError) as error:
        verify.verify_fund("TASE", "1209220")
    assert error.value.reason == reason


def test_foreign_ils_units_must_be_explicit_in_official_history(monkeypatch, foreign_provider):
    from pathlib import Path
    from haa.tase_data import parse_published_eod_closes

    csv = (Path(__file__).parent / "fixtures/foreign_etfs/1209220.csv").read_text()
    for header in ("Closing Price (USD)", "Closing Price", "Closing Price (0.01 USD)"):
        frame = parse_published_eod_closes(csv.replace("Closing Price (0.01 ILS)", header))
        monkeypatch.setattr(verify, "download_published_eod_closes", lambda _, frame=frame: frame)
        with pytest.raises(verify.FundVerificationError) as error:
            verify.verify_fund("TASE", "1209220")
        assert error.value.reason == "foreign_currency"


def test_foreign_without_dated_price_is_rejected(monkeypatch, foreign_provider):
    frame = pd.DataFrame({"Close": []}, index=pd.DatetimeIndex([]))
    frame.attrs["close_unit"] = "0.01 ILS"
    monkeypatch.setattr(verify, "download_published_eod_closes", lambda _: frame)
    with pytest.raises(verify.FundVerificationError) as error:
        verify.verify_fund("TASE", "1209220")
    assert error.value.reason == "price"


def test_foreign_class_admission_is_not_a_security_number_allowlist(monkeypatch, foreign_provider):
    from tasekit.api import TaseClient

    listing = {**foreign_provider["1209220"], "Id": "01234567"}
    frame = verify.download_published_eod_closes("1209220")
    monkeypatch.setattr(TaseClient, "fetch_security_data", lambda self, _: listing)
    monkeypatch.setattr(verify, "download_published_eod_closes", lambda _: frame)
    fund, _ = verify.verify_fund("TASE", "1234567")
    assert fund["identifier"] == "1234567"
    assert fund["currency"] == "ILS"


def test_foreign_missing_suspension_status_is_not_assumed_active(foreign_provider):
    del foreign_provider["1209220"]["SuspendStatus"]
    with pytest.raises(verify.FundVerificationError) as error:
        verify.verify_fund("TASE", "1209220")
    assert error.value.reason == "inactive"


def test_provider_failure_does_not_trigger_foreign_fallback(monkeypatch):
    def unavailable(_):
        raise verify.FundVerificationError("price")

    def forbidden(_):
        pytest.fail("Foreign fallback must only run after MAYA identity is unavailable")

    monkeypatch.setattr(verify, "_maya", unavailable)
    monkeypatch.setattr(verify, "foreign_tase_identity", forbidden)
    with pytest.raises(verify.FundVerificationError) as error:
        verify.verify_fund("TASE", "1209220")
    assert error.value.reason == "price"


def test_foreign_saved_fund_identity_remains_consistent(foreign_provider):
    from haa.my_funds import matches_identity

    saved, _ = verify.verify_fund("TASE", "1209220")
    current, _ = verify.tase_identity("1209220")
    assert matches_identity(saved, current)
