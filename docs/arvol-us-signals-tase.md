# A-RVol V3 — US Signals / TASE Execution

Two separate selectable implementations sit beside the unchanged **Israel**
implementation in the A-RVol Shifter / V3 Cash-Only catalogue:

| Model state | 1x Middle (A) | 50:50 Middle (B) |
| --- | --- | --- |
| TQQQ | 100% MTF monthly-reset Nasdaq x3, 1187079 | Same |
| QLD | 100% Harel Nasdaq-100 x1, 1149038 | 50% Harel 1149038 + 50% MTF 1187079 |
| BIL | 100% Ayalon cash, 5117700 | Same |

5117700 is intentional; this is not the other Ayalon mapping, 5136866.
The benchmark remains actual ILS Tachlit S&P 500, 1144385.

## Signals and data

The original `RVolShifterCashOnly` indicator and transition implementation is
called directly, without changing its source. QQQ supplies RVol, VR, Donchian
and recovery; SPY supplies trend; adjusted HYG/LQD supplies credit. Thresholds,
comparison boundaries, transition priority, lock, US-session age and the initial
cash state are unchanged. The conservative live cutoff remains 17:00 New York.

Yahoo Finance through the existing yfinance adapter supplies real adjusted US
prices. The original decision validator also requires actual TQQQ, QLD and BIL
history, so these are downloaded to preserve its initialization and decisions
exactly. They are not TASE return proxies. Original tickers and adjusted closes
are required; signal ticker substitutions, raw Close fallback and US CSV
replacements are disabled for these exact-reference implementations.

Actual local prices reuse `tase_data.py`: published adjusted closing marks for
the ETF roles and Maya redemption prices for Ayalon. Published no-trade marks
are valuations, not proof of executable liquidity. Any existing local field
fallback is labelled by the source metadata. No modeled leverage, synthetic
prehistory, fabricated FX returns, or filled internal prices is used.

US and TASE frames are validated on their own calendars. The joined transport
frame is never an inner-joined indicator history. Leading fund unavailability
sets the earliest execution date; missing internal sessions fail. An incomplete
latest NAV tail ends valuation at the last complete local session and is shown
separately from the latest US signal date.

## Execution

The original US state machine processes every completed US session. Each signal
is eligible at the first TASE opening strictly after its actual US close;
that TASE session's closing/NAV value is the modeled fill. Timezone-aware XNYS
and XTAE timestamps handle DST and early closes. The existing calendar fixes and
January 2026 Sunday–Thursday to Monday–Friday transition are preserved.

When TASE opens during a US holiday, holdings are marked using actual TASE
prices and the latest eligible US state persists. No extra US observation or
defensive-age increment is invented. When US trading continues through a TASE
closure, every US decision is retained in signal history but only the newest
eligible state executes at reopening. Intervening virtual trades are not booked.
Additional execution delays, if requested, count TASE sessions.

A holds one security in each state and has no annual basket reset. B enters
its middle basket at 50:50, allows weight drift, and resets on the first TASE
session of each calendar year. State changes trade only required security
amounts. It is not a daily-reset QLD replica. Fund expenses already in prices
are not subtracted again. Broker deadlines, NAV publication, liquidity and
redemption timing can differ from the modeled fill.

Single-strategy Backtest and ILS daily-valued portfolio sleeves are supported.
The shared engine paths are opt-in through `signal_calendar="XNYS"`; original
US and Israel strategies retain their existing paths. Generic monthly Research,
monthly Model Compare, USD-only Portfolio Compare and synthetic Deep History
do not represent these implementations.

## Reference comparison — known differences

The user's reference window is **15 November 2022–13 October 2026**, starting in
cash with the blended middle. Reported taxable annualized CAGR was **34.7% for
US signals** versus **18.9% for local ILS signals**. These are user-supplied
results, not results reproduced or verified by this repository.

The reference used 0.05% commission per side (minimum ILS 2), 0.10% spread per
side, 25% FIFO tax on each sale, and final liquidation of everything. The app
uses its existing average-cost realized-tax model, no modeled spread and no
terminal sale. Its percentage-plus-fixed fee inputs are not the reference's
minimum-commission rule. Taxable CAGR is therefore **not** a reproduction target.

The reference's December month-end reset was assumed to use the last TASE
session of the month, then filled at the next TASE close. That reset-date
assumption is unverified. B keeps the approved first-TASE-session-of-year reset;
it is not shifted to force a reference match.

Normal strategy decisions preserve the original US history and initialization.
The separate **Reference replay: restart V3 in cash at backtest start** option
retains all earlier indicator warm-up but restarts the original transition loop
in BIL on that date. The execution book starts in Ayalon at the start-session
close before the first eligible new US signal. Its initialization row has no
US signal date; it is explicitly marked, not presented as a fabricated signal.

Compare US-state timelines, actual execution dates and zero-cost pre-tax NAV.
First compare the pure original-US decision stream for exact parity; separately
compare the cash-start replay. Explain any annual-reset timing discrepancy.
Daily execution CSV includes source US signal date, TASE execution date,
model state, actual/target weights, security orders and whether a new US
observation became eligible. Daily drawdown uses closing/NAV marks, not
intraday lows. The short sample does not establish robustness.

No external reference state/NAV CSV was supplied, so the tests validate exact
US parity and a hand-calculated zero-cost book, not equality to an unavailable
external reference path.
