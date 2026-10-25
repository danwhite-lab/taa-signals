# Companion holding and Compare brief — clarified

This records the resolved requirement for companion-sleeve-compare-ils.

A companion is an existing account position linked to a selected target fund.
Its value counts toward the anchor's actual weight and shortfall, but only the
anchor can receive new buys. The companion is shown separately without its own
target or gap. The anchor need not already be held. No self-links, chains,
simultaneous explicit exclusion, or target/companion conflicts are allowed.

**Unmatched anchor (Daniel's approved Option 1):** when the anchor is not a
target in the selected portfolio, the companion behaves exactly like an
Outside the rebalance holding: it remains visible, is excluded from the
rebalance total, has no target, and receives no buys. Its face value remains in
the full account total when price and FX are available. Missing/stale prices
for an unmatched companion do not block the included holdings' buy plan.
The link remains saved and becomes active again if its anchor is selected.
This replaces the original ambiguous wording that said it remained in the pot.

Example: Fund A targets 45% of the included account. Fund B is its companion,
worth 10% of that account. If A itself is worth 20%, the current gap is
45% minus (20% + 10%) = 15%. New money updates the target amount in the existing
allocator; purchases go to A, never B. Excluded holdings do not enter this pot.

Companion links belong to real account holdings, not historical strategy rules.
Compare continues backtesting saved sleeve weights, not reconstructing the
historical return of a user's legacy position. A companion link does not prevent
that saved portfolio from being compared.

Compare supports portfolios sharing one execution currency, USD or ILS, through
the existing portfolio engines, prices, percentage-cost input and tax ledger.
Daily ILS valuation uses TASE sessions and the existing local benchmark path;
monthly-reset benchmarks retain the existing Backtest convention. No new FX
conversion or proxy series is created. Mixed USD/ILS comparisons are explicitly
rejected because the existing engine has no historical cross-currency valuation.
Daily sleeves still require daily valuation, and missing history still fails.

Before use, check the selected portfolio, companion links, price/FX dates, and
the displayed comparison currency/method. Buys remain estimates; no orders are
placed. No database schema or legacy Streamlit page is changed.
