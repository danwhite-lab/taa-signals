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
