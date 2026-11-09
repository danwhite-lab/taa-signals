"""Request-local account funds and their public market observations."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, timedelta

import pandas as pd

from .fund_verification import (
    FundVerificationError, fx_to_ils, maya_observation, tase_identity, yahoo_fund_info, yahoo_ticker,
)
from .tase_data import download_published_eod_closes

PREFIX = "MY-FUND-"
_active = ContextVar("account_my_funds", default={})


@contextmanager
def use_funds(funds):
    token = _active.set({fund["model"]: fund for fund in funds})
    try:
        yield
    finally:
        _active.reset(token)


def account_funds():
    return tuple(_active.get().values())


def registered_fund(model):
    return _active.get().get(model)


def instrument(fund):
    return {"id": fund["model"], "identifier": fund["identifier"], "market": fund["market"],
            "currency": fund["currency"], "label": fund["name"]}


def matches_identity(fund, current):
    return all(fund.get(key) == current.get(key) for key in
               ("identifier", "market", "currency", "kind", "isin", "fund_type_id"))


def _tase(fund):
    current, detail = tase_identity(fund["identifier"])
    if not matches_identity(fund, current):
        raise FundVerificationError("identity")
    return detail


def _yahoo(fund, period):
    ticker = yahoo_ticker(fund["identifier"])
    frame = ticker.history(period=period, interval="1d", auto_adjust=False, timeout=8)
    meta = yahoo_fund_info(ticker, fund["identifier"], frame)
    kind = "mutual" if meta["instrumentType"] == "MUTUALFUND" else "etf"
    if (meta["currency"], meta["exchangeName"], kind) != (fund["currency"], fund["exchange"], fund["kind"]):
        raise FundVerificationError("identity")
    return frame


def quote(fund):
    from server.rebalance_quotes import assess_quote, quote_from_history, utc_now

    identifier = fund["identifier"]
    if fund["market"] == "TASE":
        detail = _tase(fund)
        if fund["kind"] == "mutual":
            value = maya_observation(detail)
            value.update(currency="ILS", field="Published fund redemption valuation",
                         valuation_kind="fund_nav", dealing_schedule=detail.get("designatedHours"), fetched_at=utc_now())
            return assess_quote(value, "TASE")
        return quote_from_history(download_published_eod_closes(identifier), instrument(fund), "TASE close (agorot / 100)", 100)
    frame = _yahoo(fund, "1mo")
    closes = frame["Close"].dropna().sort_index()
    if closes.empty:
        raise FundVerificationError("price")
    # The observed trading date is local to the actual listing.
    value = float(closes.iloc[-1])
    if not 0 < value < float("inf"):
        raise FundVerificationError("price")
    return {"price": str(value), "as_of": closes.index[-1].date().isoformat(),
            "source": f"Yahoo Finance {identifier} daily close", "currency": fund["currency"],
            "field": "Unadjusted close", "fetched_at": utc_now(), "fresh": (date.today() - closes.index[-1].date()).days <= 4}


def history(fund):
    if fund["market"] == "TASE":
        _tase(fund)
        if fund["kind"] == "mutual":
            from tasekit.api import TaseClient
            from tasekit.parsers import parse_maya_fund_csv

            today = date.today()
            start = today - timedelta(days=365 * 5)
            frame = parse_maya_fund_csv(TaseClient().fetch_maya_fund_history_csv(
                fund["identifier"], f"{start}T00:00:00.000Z", f"{today}T00:00:00.000Z"))
            field = "Close"
        else:
            frame = download_published_eod_closes(fund["identifier"])
            field = "Adj Close" if "Adj Close" in frame and frame["Adj Close"].notna().any() else "Close"
        values = frame[field] / 100
    else:
        frame = _yahoo(fund, "max")
        field = "Adj Close" if "Adj Close" in frame and frame["Adj Close"].notna().any() else "Close"
        values = frame[field]
    values = values.dropna().astype(float).sort_index()
    values.index = pd.DatetimeIndex(values.index).tz_localize(None).normalize()
    values = values.loc[~values.index.duplicated(keep="last")]
    values = values[(values > 0) & (values < float("inf"))]
    if values.empty:
        raise FundVerificationError("price")
    return values.rename(fund["model"]), field


def valuations(funds):
    rates = {}
    for currency in sorted(set(funds) - {"ILS", "USD"}):
        try:
            rates[currency] = fx_to_ils(currency)
        except FundVerificationError as exc:
            rates[currency] = {"error": str(exc)}
    return rates


def model_definition(fund):
    from .model_catalog import ModelDefinition
    from .strategies.buy_and_hold import BuyAndHoldSPY

    model = fund["model"]

    class AccountBuyAndHold(BuyAndHoldSPY):
        name = model
        holding_asset = benchmark_asset = model
        data_assets = market_data_assets = (model,)
        actual_history_only = False
        validation_profile = None

    implementation = "Israel" if fund["market"] == "TASE" else fund["exchange"]
    return ModelDefinition("Buy and Hold", fund["name"], implementation, model, AccountBuyAndHold,
                           fund["currency"], "buy_and_hold", "internal")
