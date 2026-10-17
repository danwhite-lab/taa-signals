# Rebalance Holdings

This page is an account notebook and buy-only cash allocator. It never submits
broker orders, recommends selling, alters strategy rules, or rewrites a saved
portfolio. Today, Signals and Portfolio continue to use the same actionable
signal calculation, now shared in `portfolio_signals.py`.

## One account, many comparisons

The default screen shows account value, a four-column target/actual comparison,
new money, and What to buy. Results show whole units, estimated costs and leftover
cash; Record these buys opens actual-fill confirmation. Portfolio selection and
signal dates, the holdings/units editor and manual overrides, and price/FX sources
and dates remain available in collapsed sections. They have not been removed.
Cash and FX controls use stable widget identities across saved book revisions.
Only relevant one-line notes explain overweight funds (no top-up at current
weights; no selling suggestions) and an invalidated buy list (select What to buy
again). The latter clears after generating a new list. An empty cash field on
Save holdings has its own prompt; enter zero explicitly when there is no cash.

`holdings_account` is a single versioned JSON record in the signed-in user's
existing `user_settings.payload`, not a separate record for each portfolio.
Selecting or renaming a comparison portfolio does not copy or reset positions.
Positions are keyed by actual market/security ID, not by sleeve or label. Two
strategy roles mapped by the existing execution labels to one TASE security
are combined; an actual US ETF and its TASE implementation remain distinct.
The existing USD BIL execution label maps to TASE fund 5139076; the page does
not silently change that dashboard mapping to US-listed BIL. US:BIL can also
be recorded explicitly as a separate actual holding.

The book stores units, native execution currency, optional dated manual prices,
optional explicitly entered minimum orders, unallocated ILS cash, a revision
and the last operation ID. Decimal strings preserve values without binary-float
rounding inside the allocator. TASE units must be whole. Existing fractional
US positions can be recorded, but proposed purchases use whole units: broker
fractional-share support is not assumed. Users must update units after splits
or other corporate actions; the app does not infer them from adjusted prices.

## Prices and freshness

The valuation path is separate from adjusted-return history. Automatic US
quotes use Yahoo Finance raw daily Close, with the provider currency checked.
Only completed sessions are eligible. Signal data continues through the same
strategy calculation and source settings as the dashboards; provisional
month-to-date previews are never used as targets. Signal ticker substitutions
and user-uploaded replacements are identified on the page, not silently used
as actual holdings prices.

For configured ILS TASE listed-security IDs, the existing public TASE EOD CSV
adapter supplies raw Close, divided by 100 from agorot into ILS per unit.
Adjusted Close is never substituted. TASE documents listed-security price
units as 0.01 ILS:
https://market.tase.co.il/en/market_data/securities

The free public endpoints are not guaranteed live or complete. For other funds
(including Maya-only redemption feeds and USD-denominated TASE funds), native
quote units have not been verified in this implementation. Automatic sizing
therefore requires an explicitly entered, dated broker per-unit price in the
holding's native currency. It does not guess a divisor, value the fund using a
US proxy, or interpolate missing observations. In particular, a Maya redemption
price must not silently be presented as an executable purchase price. Where
available, the raw Maya redemption publication and its actual publication date
are shown in a separate unverified-unit column, never multiplied by holdings.

Prices and target calculations cache for five minutes. Refresh clears only
this page's quote/target caches. Every quote shows its actual observation date,
source, price field and retrieval/entry timestamp. The completed-session check
uses the existing US and TASE calendars, including holidays and market close
times. An observation older than the most recent completed session is flagged
and blocks sizing for that fund. No assumed mutual-fund publication lag is
silently excused. Delayed fund publication may therefore require a dated broker
observation. A manual observation can be intraday and is identified as manual,
not mislabelled as an exchange close. Future dates are rejected for valuation.

A small main-screen warning offers a dated native-currency manual price. An
inline manual-price observation date starts empty and must be entered explicitly;
the app never assigns today's date to a copied price by default. An
unpriced or stale target with zero units can be excluded while sizing the other
funds, retaining their original weights (no redistribution). If the affected
fund has units, its value is necessary to calculate account weights: sizing
remains blocked until it has a usable quote. No account value is guessed.

USD values use a dated, indicative Yahoo ILS=X quote (ILS per USD), or an
explicitly entered dated broker FX rate. Stale/missing FX blocks sizing just as
stale/missing holding prices do. These are not promised broker conversion or
execution rates. Manual overrides remain in force until cleared and become
visibly stale rather than being refreshed to today's date automatically.

## Buy list and confirmation

Current value includes all nonzero account positions and unallocated cash,
including funds not present in the selected targets. New money is additional
cash, not a replacement for account value. Existing unallocated cash is also
included in the available purchase budget and shown explicitly.

Target values use account value plus the new deposit. Continuous funding first
narrows the largest positive ILS shortfalls; whole-unit allocation and feasible
minimum order lots follow without overshooting a fund's target shortfall or
the available budget. Unknown broker minimums are marked not configured. A
minimum commission is never treated as a minimum purchase. Infeasible cash
remains unallocated. Whole-unit costs retain their actual decimal precision;
the UI does not round per-unit prices to whole shekels before sizing.

Quoted costs exclude automatically modeled commissions/spreads. Users should
allow a cash buffer. After trading, enter actual units purchased and actual ILS
paid, including costs charged to this cash budget. USD purchases require the
actual ILS equivalent used. Partial or skipped orders are allowed. Confirmed
units cannot exceed the proposed whole-unit order; unexpected additional buys
must be recorded by correcting holdings or generating a new plan. Actual spend
cannot exceed available cash. Done records those confirmed units and remaining
cash, not an assumed fill at the indicative quote. A deposit with no feasible
orders may be confirmed as unallocated cash without fabricating purchases.

Holdings, target, quote, FX, portfolio or budget changes invalidate a pending
plan. A unique operation ID and the updated book are saved in the same
revision-checked workspace write. A lost response triggers readback of that
exact book, not a repeated mutation. Another-device conflicts stop saves and
require a workspace reload. Unconfirmed local edits are not autosaved as if
they were completed purchases. No auth tokens, fetched prices, pending plans,
or purchase-confirmation drafts are persisted in the workspace JSON.

On this page a revision conflict is a small sync-paused notice, with explanation
in sync details. It means the server revision changed since this session loaded;
another tab or concurrent request can cause it, not necessarily another device.
Only a readback equal to the complete local payload can safely acknowledge an
already-saved revision. Differing payloads still block writes and require reload.
Other pages retain their existing conflict notices.

No schema migration, new auth policy, service-role key, tax-lot ledger, historic
portfolio recalculation, annual blend engine or broker integration is added.
