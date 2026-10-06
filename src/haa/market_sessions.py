"""US equity-session completeness and explicitly scheduled execution dates."""
from functools import lru_cache

import pandas as pd


@lru_cache(maxsize=32)
def us_equity_sessions(start: str, end: str) -> pd.DatetimeIndex:
    """XNYS calendar includes holidays, early closes and special closures.

    exchange_calendars also aliases NASDAQ to this US equity-session calendar.
    No weekday-only fallback: unavailable calendar validation must fail closed.
    """
    try:
        import exchange_calendars as xcals
        # Padding keeps holiday/weekend query bounds inside the calendar's
        # first/last actual session and also permits a one-session history.
        calendar = xcals.get_calendar("XNYS", start=pd.Timestamp(start) - pd.Timedelta(days=7),
                                      end=pd.Timestamp(end) + pd.Timedelta(days=7))
        sessions = calendar.sessions_in_range(start, end)
    except Exception as exc:
        raise ValueError("US exchange calendar unavailable; cannot safely validate daily sessions.") from exc
    return sessions.tz_localize(None) if sessions.tz is not None else sessions


def validate_us_equity_sessions(prices: pd.DataFrame) -> None:
    """Reject unexplained internal gaps before rolling windows or returns.

    Coverage is the supplied history's first through last observed session,
    not invented prehistory or an assumption of current provider freshness.
    Entirely empty internal trading-session rows count as missing too.
    """
    observed = prices.dropna(how="all").index
    if not len(observed):
        return
    if not isinstance(observed, pd.DatetimeIndex) or observed.tz is not None:
        raise ValueError("Daily session dates must be a timezone-naive DatetimeIndex.")
    if observed.has_duplicates or observed.hasnans or not observed.equals(observed.normalize()):
        raise ValueError("Daily session dates must be unique valid midnight session labels.")
    expected = us_equity_sessions(str(observed.min().date()), str(observed.max().date()))
    unexpected = observed.difference(expected)
    if len(unexpected):
        raise ValueError(f"Quotes on non-trading US equity dates: {', '.join(str(d.date()) for d in unexpected[:8])}.")
    missing = expected.difference(observed)
    if len(missing):
        raise ValueError(f"Missing US equity trading sessions ({len(missing)}): {', '.join(str(d.date()) for d in missing[:8])}. Refusing to bridge missing sessions; repair the source data.")


def scheduled_execution_dates(decision_dates: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """Next exchange-session CLOSE dates, not claimed or observed fills."""
    if not len(decision_dates):
        return pd.DatetimeIndex([])
    # Extend beyond the final observation only to schedule a date, never a
    # future quote, return or backtest fill.
    sessions = us_equity_sessions(str(decision_dates.min().date()),
                                 str((decision_dates.max() + pd.Timedelta(days=14)).date()))
    positions = sessions.searchsorted(decision_dates, side="right")
    return sessions.take(positions)
