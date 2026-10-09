# Mixed-frequency portfolio backtests

Selecting A-RVol in Backtest > Portfolio uses daily security prices rather than
blending monthly return summaries. One, two or more USD sleeves are supported;
positive initial weights must total 100%. Monthly-only portfolios continue to
use the existing monthly-reset engine unchanged.

## Capital and timing

Each sleeve receives its initial portion of portfolio capital. There are no
transfers, monthly sleeve resets, or fees/tax from hypothetical sleeve resets.
Weights drift with performance. Initial and ending pre-tax weights are shown.

All sleeves start afresh over their shared executable history; capital and tax
bases restart at the selected start date, while decisions retain prior signal
history. A-RVol buys at the first eligible session's open and follows daily
next-open decisions. The old holding earns the overnight move before a switch;
the new holding earns the subsequent intraday move. The existing daily engine
handles A-RVol without changing its rules.

Monthly sleeves initially buy their last known target at the first shared
session's close; their capital is cash until that close. Later decisions execute
at the next US session's close, with holdings marked daily between trades.
Monthly baskets rebalance security weights at their scheduled closes, not daily.
Buy-and-hold sleeves remain invested and do not incur artificial sale/buy events.
Fees and tax can slightly reduce the amounts available for new purchases.

SPY enters at the first shared session's open and is marked at daily closes.
Portfolio drawdown and risk metrics use daily closing values (including starting
capital), not unobserved intraday extremes. Monthly and annual returns compound
the daily return stream; partial boundary months are included. No prices,
missing sessions or proxy returns are padded or synthesized.

Turnover in the daily audit is the pre-tax value of actual purchases divided
by the prior portfolio closing value (starting capital for the first session).
It is a one-way measure, not the sum of buys and sells.

## Fees and tax

In mixed-frequency mode fees apply to actual purchases and sales, per side.
This is explicit and differs from the legacy monthly-only engine's one-way
turnover fee convention. A monthly basket sells only overweight/removed
positions, retains other positions and spends available cash proportionally
on purchases. Security cost bases include acquisition fees; sale fees reduce
realized proceeds. No final liquidation is forced.

Each sleeve keeps its own tax bases and loss carryforward under the existing
simplified realized-gain tax model. Losses are not netted across sleeves; this
can overstate taxes relative to account-level offsetting. FX/inflation tax rules
and full Israeli tax treatment are not modeled. No tax is charged merely
because a sleeve weight drifts. Audit and tax event downloads identify sleeves.

## Limits

This first version requires USD sleeves with real daily execution-security data
on the US trading calendar. ILS/TASE sleeves, monthly-only proxy histories and
close-only CSV price replacements cannot silently join this mixed model.
The imported daily A-RVol Deep History proxy remains standalone: its monthly
returns and event history do not provide daily security values for tax modeling.
Monthly Compare remains separate and does not support A-RVol.

Downloads include daily total NAV, daily pre-tax sleeve NAV, security execution
audits and tax events. These are model calculations, not confirmed broker fills.

## Checks

Tests cover one/two/three sleeves, next-open singleton equivalence, drifting
weights, next-close monthly transitions, partial-month compounding, start-date
capital/tax reset, retained security lots, fees, missing decisions/prices/opens,
intramonth drawdown, future-data invariance and currency/benchmark guards.
A real-price 40% A-RVol / 60% SPY audit over March 2010 through October 6, 2026
reconciled with independent sleeve calculations over 4,177 sessions, with and
without fees and tax. No live deployed-UI check was performed.
