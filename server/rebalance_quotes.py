"""Actual unit quotes and the dashboard's shared signal path, kept separate."""
from __future__ import annotations

from datetime import date, datetime, timezone

import pandas as pd
from .rebalance_ttl import cache_data

from haa import data
from haa.constants import ASSETS, FRED_ASSETS, OECD_CLI_DIFFUSION_ASSET
from haa.market_sessions import tase_equity_sessions, us_equity_sessions
from haa.model_catalog import MODEL_CATALOG, definition_for_label
from haa.portfolio_signals import portfolio_signal
from haa.rebalance_holdings import number
from haa.tase_data import (TASE_ISRAEL_ASSET_IDS, TASE_ETF_ASSETS,
                        download_published_eod_closes, download_tase_israel_prices)


# Holdings valuation only: never alter strategy/backtest price routing.
# These specific ILS funds have ₪1 nominal units; MAYA redemption quotes
# are percentages of nominal, so /100 gives actual ILS per held unit.
# Verification documents and dates are recorded in docs/rebalance-holdings.md.
MAYA_ILS_UNIT_FUNDS = {
    "5117700": {"isin": "IL0051177009", "fund_type_id": 1},
    "5131792": {"isin": "IL0051317928", "fund_type_id": 4},
    "5140850": {"isin": "IL0051408503", "fund_type_id": 4},
}


def quote_from_maya_fund(published, instrument, as_of=None):
    """Normalize only explicitly verified fund units; fail closed on changes."""
    identifier = instrument["identifier"]
    verified = MAYA_ILS_UNIT_FUNDS.get(identifier)
    if not verified or instrument["market"] != "TASE" or instrument["currency"] != "ILS":
        raise ValueError("This fund's native per-unit conversion is not verified.")
    if (str(published.get("fundId")).lstrip("0") != identifier
            or published.get("isin") != verified["isin"]
            or published.get("fundTypeId") != verified["fund_type_id"]
            or published.get("mutualFundSubType") != 1
            or published.get("deleted") is not False
            or "mergingLiquidationStatus" not in published
            or published["mergingLiquidationStatus"] is not None):
        raise ValueError("Fund identity or structure could not be verified; enter a dated manual price.")
    currency_flags = [f.get("enabled") for f in published.get("features", [])
                      if f.get("title") == "יחידות הקרן נקובות ב- $"]
    if currency_flags != [False]:
        raise ValueError("Fund currency metadata changed or is missing; no conversion was guessed.")
    stamp = published.get("ratesAsOf")
    if not isinstance(stamp, str):
        raise ValueError("Published fund price needs its actual observation date.")
    date.fromisoformat(stamp)
    raw = number(published.get("redemptionPrice"), positive=True)
    return assess_quote({"price": str(raw / 100), "currency": "ILS", "as_of": stamp,
                         "fetched_at": utc_now(), "source": "Official MAYA via public tasekit endpoint; published redemption valuation, not a live execution price",
                         "source_url": f"https://maya.tase.co.il/api/v1/funds/mutual/{identifier}",
                         "field": "Published fund redemption valuation", "valuation_kind": "fund_nav",
                         "raw_published_value": str(raw), "raw_unit": "% of ILS 1 nominal per unit",
                         "quote_divisor": "100", "is_execution_price": False}, "TASE", as_of)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def last_completed_session(market, as_of=None):
    import exchange_calendars as xcals
    now = pd.Timestamp.now(tz="UTC") if as_of is None else pd.Timestamp(as_of)
    now = now.tz_localize("UTC") if now.tzinfo is None else now.tz_convert("UTC")
    start, end = (now - pd.Timedelta(days=20)).date().isoformat(), now.date().isoformat()
    sessions = (tase_equity_sessions if market == "TASE" else us_equity_sessions)(start, end)
    calendar = xcals.get_calendar("XTAE" if market == "TASE" else "XNYS", start=pd.Timestamp(start)-pd.Timedelta(days=7), end=pd.Timestamp(end)+pd.Timedelta(days=7))
    completed = [day for day in sessions if calendar.session_close(day) <= now]
    if not completed:
        raise ValueError("Cannot verify the last completed exchange session.")
    return completed[-1]


def assess_quote(quote, market, as_of=None):
    result = dict(quote)
    try:
        expected = last_completed_session(market, as_of)
        observed = pd.Timestamp(result["as_of"])
        if observed.tzinfo:
            observed = observed.tz_localize(None)
        observed = observed.normalize()
        now = pd.Timestamp.now(tz="UTC") if as_of is None else pd.Timestamp(as_of)
        today = now.date()
        number(result["price"], positive=True)
        if observed.date() > today:
            raise ValueError("Price is dated in the future.")
        if result.get("field") == "Manual per-unit price":
            # Explicit broker observations can be intraday; never call them closes.
            fresh = observed >= expected
        else:
            fresh = observed == expected
        result.update(fresh=fresh, expected_through=str(expected.date()),
                      status="Current observation" if fresh else f"Stale: latest completed session is {expected.date()}")
    except Exception as exc:
        result.update(fresh=False, error=str(exc), status="Unavailable / unverified")
    return result


def quote_from_history(frame, instrument, source, divisor, as_of=None):
    """No adjusted prices, forward fill, or prior-row fallback for bad closes."""
    expected = last_completed_session(instrument["market"], as_of)
    if "Close" not in frame:
        raise ValueError("Actual unadjusted Close is unavailable; adjusted prices cannot value units.")
    dates = pd.to_datetime(frame.index)
    if dates.tz is not None:
        dates = dates.tz_convert("Asia/Jerusalem" if instrument["market"] == "TASE" else "America/New_York").tz_localize(None)
    if dates.normalize().has_duplicates:
        raise ValueError("Duplicate daily price observations.")
    closes = pd.Series(frame.Close.to_numpy(), index=dates.normalize()).sort_index().loc[:expected]
    if closes.empty:
        raise ValueError("No completed-session raw close is available.")
    price = number(closes.iloc[-1], positive=True) / number(divisor, positive=True)
    return assess_quote({"price": str(price), "currency": instrument["currency"],
                         "as_of": str(closes.index[-1].date()), "fetched_at": utc_now(),
                         "source": source, "field": "Unadjusted close", "quote_divisor": str(divisor)}, instrument["market"], as_of)


@cache_data(ttl=300, show_spinner=False)
def fetch_unit_quote(instrument):
    if instrument["market"] == "US":
        import yfinance as yf
        ticker = yf.Ticker(instrument["identifier"])
        frame = ticker.history(period="1mo", interval="1d", auto_adjust=False)
        currency = ticker.get_history_metadata().get("currency")
        if currency != instrument["currency"]:
            raise ValueError("Provider currency is missing or does not match this holding.")
        return quote_from_history(frame, instrument, "Yahoo Finance daily raw Close (not live)", 1)
    if instrument["identifier"] in MAYA_ILS_UNIT_FUNDS and instrument["currency"] == "ILS":
        from tasekit.api import TaseClient
        return quote_from_maya_fund(TaseClient().fetch_maya_fund_info(instrument["identifier"]), instrument)
    known_exchange_ids = {TASE_ISRAEL_ASSET_IDS[asset] for asset in TASE_ETF_ASSETS}
    if instrument["identifier"] not in known_exchange_ids or instrument["currency"] != "ILS":
        # Surface an available publication, but do not mistake a NAV quoted
        # as percent of nominal value for currency per actual unit.
        from tasekit.api import TaseClient
        published = TaseClient().fetch_maya_fund_info(instrument["identifier"])
        return {"error": "This fund's raw quote currency/unit is not verified. Enter a dated broker price per unit in its native currency; no conversion is guessed.",
                "raw_published_value": published.get("redemptionPrice"), "as_of": published.get("ratesAsOf"),
                "fetched_at": utc_now(), "source": "Public Maya via tasekit; raw redemption publication, NOT a normalized per-unit price",
                "field": "Unverified quote unit", "fresh": False, "status": "Per-unit conversion unverified"}
    # TASE listed-security EOD quotes are agorot (0.01 ILS), not shekels.
    # https://market.tase.co.il/en/market_data/securities
    frame = download_published_eod_closes(instrument["identifier"])
    return quote_from_history(frame, instrument, "Public TASE via tasekit; EOD close in agorot / 100 (not live)", 100)


def unit_quote(instrument, position):
    try:
        if position.get("manual_price") is not None:
            return assess_quote({"price": position["manual_price"], "currency": instrument["currency"],
                                 "as_of": position["manual_price_date"], "fetched_at": position.get("manual_entered_at"),
                                 "source": "Manual broker observation", "field": "Manual per-unit price"}, instrument["market"])
        # Reassess the cached quote against *now*, including a just-completed session.
        quote = fetch_unit_quote(instrument)
        return dict(quote) if quote.get("error") else assess_quote(quote, instrument["market"])
    except Exception as exc:
        return {"error": str(exc), "fresh": False, "status": "Unavailable", "source": "No substitute used"}


@cache_data(ttl=300, show_spinner=False)
def fetch_fx_quote():
    value, stamp = data.download_latest_yahoo_close("ILS=X")
    return {"price": str(number(value, positive=True)), "as_of": pd.Timestamp(stamp).isoformat(),
            "fetched_at": utc_now(), "source": "Yahoo Finance ILS=X: ILS per USD; delayed indicative quote"}


def fx_quote(account):
    try:
        quote = ({"price": account["manual_fx"], "as_of": account["manual_fx_date"],
                  "source": "Manual ILS per USD", "fetched_at": account.get("updated_at")}
                 if account.get("manual_fx") is not None else dict(fetch_fx_quote()))
        number(quote["price"], positive=True)
        observed = pd.Timestamp(quote["as_of"]).date()
        expected = max(last_completed_session("US"), last_completed_session("TASE")).date()
        today = pd.Timestamp.now(tz="UTC").date()
        quote["fresh"] = expected <= observed <= today
        quote["status"] = "Current indicative FX" if quote["fresh"] else f"Stale/unverified FX: need {expected} or later"
        return quote
    except Exception as exc:
        return {"error": str(exc), "fresh": False, "status": "FX unavailable"}


@cache_data(ttl=300, show_spinner=False)
def load_portfolio_signals(labels, ticker_items, replacements):
    """Use the same sources and shared actionable calculation as the dashboard."""
    models = {item.label: item.model_class for item in MODEL_CATALOG}
    tickers = dict(ticker_items)
    results, errors = [], []
    for label in labels:
        try:
            model = models[label]
            assets = getattr(model, "data_assets", ASSETS)
            local = tuple(a for a in assets if a in TASE_ISRAEL_ASSET_IDS)
            fred = tuple(a for a in assets if a in FRED_ASSETS)
            yahoo = tuple(a for a in assets if a not in (*local, *fred, OECD_CLI_DIFFUSION_ASSET))
            strict = getattr(model, "us_data_assets", ()) if getattr(model, "signal_calendar", None) == "XNYS" else ()
            sources = {a: tickers.get(a, a) for a in yahoo}
            if strict and (any(sources.get(a) != a for a in strict) or set(replacements).intersection(strict)):
                raise ValueError("This exact US V3 signal requires original US sources, not replacements.")
            frames = []
            if yahoo:
                frames.append(data.download_yahoo_prices(sources, require_adjusted_assets=strict) if strict else data.download_yahoo_prices(sources))
            if local:
                frames.append(download_tase_israel_prices(local)[0])
            if fred:
                frames.append(data.download_fred_series(fred))
            if OECD_CLI_DIFFUSION_ASSET in assets:
                frames.append(data.download_oecd_cli_diffusion())
            prices = pd.concat(frames, axis=1, sort=True)
            prices = data.combine_replacements(prices, replacements, assets)
            signal, error = portfolio_signal(model, prices)
            if error:
                raise ValueError(error)
            notes = [f"{a}={sources[a]}" for a in yahoo if sources[a] != a]
            notes += [f"{a}: user replacement / unverified source" for a in assets if a in replacements]
            results.append({"name": label, "currency": definition_for_label(label).execution_currency,
                            "target_weights": signal["weights"], "signal_date": str(pd.Timestamp(signal["decision"].name).date()),
                            "source_notes": notes})
        except Exception as exc:
            errors.append(f"{label}: {exc}")
    return results, errors


def clear_rebalance_quotes():
    fetch_unit_quote.clear()
    fetch_fx_quote.clear()
    load_portfolio_signals.clear()
