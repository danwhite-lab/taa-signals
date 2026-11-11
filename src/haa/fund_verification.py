"""Fail-closed admission checks for new user funds.

Provider data proves a listing and quote convention. Saved instruments and
existing allowlists are deliberately outside this verification path.
"""
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO
import json
from pathlib import Path
import re

import pandas as pd
import requests

from .tase_data import download_published_eod_closes


WORDS = json.loads((Path(__file__).resolve().parents[2] / "data/my_funds.json").read_text())
ERRORS = WORDS["errors"]
MAX_REPORT_BYTES = 8 * 1024 * 1024
DOLLAR_UNITS = "יחידות הקרן נקובות ב- $"
REPORT_KEYS = ("lastAnnualReportId", "lastFinancialReportId", "lastProspectusReportId")
GLOBAL_CURRENCIES = frozenset({"USD", "EUR", "GBP", "ILS"})


class FundVerificationError(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__(ERRORS[reason])


def positive(value):
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise FundVerificationError("price") from None
    if not result.is_finite() or result <= 0:
        raise FundVerificationError("price")
    return result


def observation(value, stamp, source):
    try:
        observed = date.fromisoformat(stamp)
    except (TypeError, ValueError):
        raise FundVerificationError("price") from None
    if observed > pd.Timestamp.now(tz="UTC").date():
        raise FundVerificationError("price")
    return {"price": str(positive(value)), "as_of": observed.isoformat(), "source": source}


def _compact(text):
    return re.sub(r'[\s\u200e\u200f"׳״\']', "", text.replace("ð", "נ"))


# Fixed statement patterns in the official report templates. Support the
# left-to-right visual order used by some PDF fonts as well as logical order.
NOMINAL_STATEMENTS = (
    'המטבע בו נקובות יחידות הקרן 1 שקל חדש ע"נ',
    'הערך הנקוב של היחידות במחזור בנות 1 ש"ח',
    'הערך הנקוב של היחידות שבמחזור בנות 1 ש"ח ערך נקוב',
)
REDEMPTION_STATEMENTS = (
    "מחיר הפדיון ליום המסחר האחרון של התקופה (באחוזים מהערך הנקוב של יחידה בקרן)",
    'מחיר הפדיון ליחידה בת 1 ש"ח ערך נקוב: באחוזים',
    'מחיר הפדיון ליחידה בת 1 ש"ח ערך נקוב (באחוזים)',
)


def _matches_statement(text, statements):
    for statement in statements:
        value = _compact(statement).replace(":", "").replace("(", "").replace(")", "")
        if value in text or value[::-1] in text:
            return True
    return False


def _fund_numbers(text):
    text = _compact(text)
    marker = r"(?:מספרבורסה|מסבורסה|הסרוברפסמ|הסרובסמ)"
    return {left or right for left, right in
            re.findall(rf"([0-9]{{7}})[:()\-]*{marker}|{marker}[:()\-]*([0-9]{{7}})", text)}


def report_verifies_units(document, identifier, isin):
    from pypdf import PdfReader

    try:
        pdf = PdfReader(BytesIO(document), strict=True)
        if pdf.is_encrypted or not 1 <= len(pdf.pages) <= 100:
            return False
        cover = pdf.pages[0].extract_text(extraction_mode="layout")
        numbers = _fund_numbers(cover)
        if numbers != {identifier} and (numbers or not re.search(
                rf"(?<![A-Z0-9]){re.escape(isin)}(?![A-Z0-9])", cover)):
            return False
        pages = []
        for page in pdf.pages:
            extracts = (page.extract_text(), page.extract_text(extraction_mode="layout"))
            if any(_fund_numbers(extract) - {identifier} for extract in extracts):
                continue
            pages.extend(re.sub(r"[:()]", "", _compact(extract)) for extract in extracts)
        nominal = any(_matches_statement(page, NOMINAL_STATEMENTS) for page in pages)
        redemption_table = re.compile(
            _compact('מחיר הפדיון ליחידה בת 1 ש"ח ערך נקוב') +
            r"ליום[0-9]{1,2}ב[א-ת]+20[0-9]{2}20[0-9]{2}באחוזים")
        redemption = any(_matches_statement(page, REDEMPTION_STATEMENTS) or redemption_table.search(page)
                         for page in pages)
        return nominal and redemption
    except Exception:
        return False


def fetch_report(report_id):
    if type(report_id) is not int or not 1 <= report_id <= 9_999_999:
        raise FundVerificationError("document")
    lower = (report_id - 1) // 1000 * 1000 + 1
    url = f"https://mayafiles.tase.co.il/rpdf/{lower}-{lower + 999}/P{report_id}-00.pdf"
    with requests.get(url, timeout=(4, 8), allow_redirects=False, stream=True) as response:
        if response.status_code != 200 or response.headers.get("Content-Type", "").split(";")[0].lower() != "application/pdf":
            raise FundVerificationError("document")
        blob = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            blob.extend(chunk)
            if len(blob) > MAX_REPORT_BYTES:
                raise FundVerificationError("document")
        if not blob.startswith(b"%PDF-"):
            raise FundVerificationError("document")
        return bytes(blob)


def _maya(identifier):
    for kind in ("mutual", "etf"):
        url = f"https://maya.tase.co.il/api/v1/funds/{kind}/{identifier}"
        response = requests.get(url, timeout=(4, 8), allow_redirects=False)
        if response.status_code in {400, 404}:
            continue
        if response.status_code != 200:
            raise FundVerificationError("price")
        detail = response.json()
        if isinstance(detail, dict) and str(detail.get("fundId")) == identifier:
            return kind, detail
    raise FundVerificationError("identity")


def foreign_tase_identity(identifier):
    from tasekit.api import TaseClient

    listing = TaseClient().fetch_security_data(identifier)
    if not isinstance(listing, dict) or str(listing.get("Id", "")).lstrip("0") != identifier:
        raise FundVerificationError("identity")
    # Official company/securitydata classes, not security-number allowlists.
    classes = {"4401": "Trade foreign fund Equity", "4501": "Traded foreign fund Bonds"}
    if (listing.get("IsForeignETF") is not True or listing.get("Type") != "Foreign ETF"
            or listing.get("ShareType") not in classes
            or listing.get("SecuritySubType") != classes[listing["ShareType"]]):
        raise FundVerificationError("fund_type")
    if ("SuspendStatus" not in listing or listing["SuspendStatus"] is not None
            or listing.get("isTrading") is not True):
        raise FundVerificationError("inactive")
    name, isin = listing.get("LongName"), listing.get("ISIN")
    if (not isinstance(name, str) or not name.strip() or not isinstance(isin, str)
            or not re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}[0-9]", isin)):
        raise FundVerificationError("identity")
    # Foreign fund base currencies are not the local listing's quote currency.
    # Establish units here too: saved funds recheck this identity for quotes/history.
    frame = download_published_eod_closes(identifier)
    if frame.attrs.get("close_unit") != "0.01 ILS":
        raise FundVerificationError("foreign_currency")
    return {"identifier": identifier, "market": "TASE", "name": name.strip(),
            "kind": "etf", "currency": "ILS", "isin": isin}, {"published_eod": frame}


def tase_identity(identifier):
    if not re.fullmatch(r"[1-9][0-9]{6}", identifier):
        raise FundVerificationError("security_number")
    try:
        try:
            kind, detail = _maya(identifier)
        except FundVerificationError as exc:
            if exc.reason != "identity":
                raise
            return foreign_tase_identity(identifier)
        if detail.get("deleted") is not False or "mergingLiquidationStatus" not in detail or detail["mergingLiquidationStatus"] is not None:
            raise FundVerificationError("inactive")
        flags = [item.get("enabled") for item in detail.get("features", []) if item.get("title") == DOLLAR_UNITS]
        if flags != [False]:
            raise FundVerificationError("tase_currency")
        name = detail.get("longName") or detail.get("name")
        if not isinstance(name, str) or not name.strip():
            raise FundVerificationError("identity")
        isin = detail.get("isin")
        if kind == "etf":
            from tasekit.api import TaseClient

            listing = TaseClient().fetch_security_data(identifier)
            if (detail.get("fundTypeId") != 5 or not listing
                    or str(listing.get("Id", "")).lstrip("0") != identifier
                    or listing.get("SecuritySubType") != "ETF (stock market)"
                    or listing.get("SuspendStatus") or (isin and listing.get("ISIN") != isin)):
                raise FundVerificationError("identity")
            isin = listing.get("ISIN")
        elif detail.get("mutualFundSubType") != 1 or type(detail.get("fundTypeId")) is not int:
            raise FundVerificationError("fund_type")
        if not isinstance(isin, str) or not re.fullmatch(r"IL[0-9A-Z]{10}", isin):
            raise FundVerificationError("identity")
        return {"identifier": identifier, "market": "TASE", "name": name.strip(), "kind": kind,
                "currency": "ILS", "isin": isin, "fund_type_id": detail["fundTypeId"]}, detail
    except FundVerificationError:
        raise
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        raise FundVerificationError("verification") from None


def maya_observation(detail):
    return observation(positive(detail.get("redemptionPrice")) / 100, detail.get("ratesAsOf"), WORDS["mayaBasis"])


def _close(frame, column, source):
    values = frame[column].dropna().sort_index()
    if values.empty:
        raise FundVerificationError("price")
    return observation(values.iloc[-1], values.index[-1].date().isoformat(), source)


def yahoo_ticker(identifier):
    import yfinance as yf

    if not re.fullmatch(r"[A-Z][A-Z0-9-]{0,14}(?:\.[A-Z]{1,5})?", identifier):
        raise FundVerificationError("ticker")
    return yf.Ticker(identifier)


def yahoo_fund_info(ticker, identifier, frame):
    if frame.empty:
        raise FundVerificationError("price")
    meta = ticker.get_history_metadata()
    if meta.get("instrumentType") not in {"ETF", "MUTUALFUND"}:
        raise FundVerificationError("fund_type")
    if meta.get("symbol") != identifier or not meta.get("exchangeName"):
        raise FundVerificationError("identity")
    if meta.get("currency") not in GLOBAL_CURRENCIES:
        raise FundVerificationError("currency")
    return meta


def fx_to_ils(currency):
    import yfinance as yf

    symbol = {"USD": "ILS=X", "EUR": "EURILS=X", "GBP": "GBPILS=X"}.get(currency)
    if not symbol:
        raise FundVerificationError("fx")
    try:
        ticker = yf.Ticker(symbol)
        frame = ticker.history(period="1mo", interval="1d", auto_adjust=False, timeout=8)
        meta = ticker.get_history_metadata()
        if meta.get("symbol") != symbol or meta.get("currency") != "ILS" or meta.get("instrumentType") != "CURRENCY":
            raise FundVerificationError("fx")
        return _close(frame, "Close", f"Yahoo Finance {symbol} (ILS per {currency})")
    except Exception:
        raise FundVerificationError("fx") from None


def verify_fund(market, value):
    identifier = value.strip().upper()
    try:
        if market == "TASE":
            fund, detail = tase_identity(identifier)
            if fund["kind"] == "mutual":
                for report_id in dict.fromkeys(detail.get(key) for key in REPORT_KEYS):
                    if type(report_id) is not int:
                        continue
                    try:
                        document = fetch_report(report_id)
                    except (requests.RequestException, FundVerificationError):
                        continue
                    if report_verifies_units(document, identifier, fund["isin"]):
                        fund["unit_report"] = report_id
                        break
                else:
                    raise FundVerificationError("document")
                return fund, maya_observation(detail)
            frame = detail["published_eod"] if "published_eod" in detail else download_published_eod_closes(identifier)
            return fund, _close(frame.assign(Close=frame["Close"] / 100), "Close", "TASE closing price (agorot / 100)")
        ticker = yahoo_ticker(identifier)
        frame = ticker.history(period="1mo", interval="1d", auto_adjust=False, timeout=8)
        meta = yahoo_fund_info(ticker, identifier, frame)
        name = meta.get("longName") or meta.get("shortName")
        if not isinstance(name, str) or not name.strip():
            raise FundVerificationError("identity")
        fund = {"identifier": identifier, "market": "Global", "name": name.strip(),
                "kind": "mutual" if meta["instrumentType"] == "MUTUALFUND" else "etf",
                "currency": meta["currency"], "exchange": meta["exchangeName"]}
        if fund["currency"] != "ILS":
            fund["fx"] = fx_to_ils(fund["currency"])
        return fund, _close(frame, "Close", f"Yahoo Finance {identifier} daily close")
    except FundVerificationError:
        raise
    except Exception:
        raise FundVerificationError("verification") from None
