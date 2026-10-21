# Optional Backtest trading fees

The Next.js Backtest assumptions default to fees enabled:

- ILS execution: `max(trade notional × 0.05%, ₪2)` on each side.
- USD execution: $5 on each side, without FX conversion.

All three numbers are editable. Turning fees off uses the existing no-fee
execution path. Old API requests that omit `fees_enabled` retain their legacy
`fee_type` / `fee_value` behavior; explicitly setting it to false disables both
legacy and new fees. Other engine callers remain unchanged unless they pass a
`TradingFees` policy. Legacy requests do not claim a fee total because their
turnover estimates do not expose a complete per-side fee ledger.

Buy fees come out of available purchase cash, and percentage fees use actual
trade notional, not the fee-inclusive cash budget. Rebalances charge each
security sale and purchase separately; retained positions are not charged.
Monthly deposit purchases also incur fees. Orders stay separate across sleeves.
Insufficient capital to cover fees produces an explicit error, not borrowing.
There is no added final liquidation and the comparison benchmark remains free
of broker fees. Fund expenses embedded in prices are not added again.

The existing average-cost realized-sale ledger, tax rate, loss carryforward and
no-final-sale convention are retained. Sale proceeds are net of the sale fee;
acquisition fees enter cost basis. Mixed-portfolio sleeve transfers retain the
existing sleeve-level tax approximation; this is not a new tax model. Their
funded holdings are replayed using the existing execution schedules so later
flat fees remain flat after capital moves between sleeves (not scaled returns).
The existing restriction on combining sleeve transfers with monthly deposits
remains in place.

Results expose separate pre-tax and after-tax fee totals in the backtest's own
currency. These are alternative simulations, not totals to add together. Daily
results sum fees across all sessions; monthly reporting aggregates those fees.
Actual orders and fees are included in execution/audit downloads.

Imported Deep History NAV/return streams without execution notionals cannot
support these fees. Fees-on runs reject them explicitly and ask for fees to be
turned off; no trade dates, values, prices or proxies are invented.
