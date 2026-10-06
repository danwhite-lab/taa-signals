# Chimeric supplied deep-history export

Received 2026-10-06. Source files: `Signal History - Chimeric.csv` and `Montly returns - Chimeric.csv`. Bundled byte-for-byte as `chimeric_signals.csv` and `chimeric_monthly_returns.csv`.

SHA-256:
- Signals: d685ac49105c97fadced31ecc6e9cbe3bca7231102224042260e09b2b3c1bdc0
- Returns: e49807be2b6149cb388a83373af78158f2f42e099d392fb1367408cefb43610d

Validation: 538 dated signal rows, February 26, 1982–September 9, 2026. No duplicate dates. There are 535 unique completed-period signal months (February 1982–August 2026), with no internal month gaps. All allocations total 100%. The first source row lacks the usual expand-marker column; the reader supports both layouts without dropping it.

Only September 2026 has multiple dated rows: September 4, September 8 and September 9, all explicitly labelled for October. Their allocations differ, so these are not identical duplicates. Whether they are previews, revisions or actual trades cannot be established from these files. All three are excluded from usable history, not collapsed to an assumed final trade.

536 monthly returns span March 1982–October 2026, with no duplicate months or internal gaps. March 1982 is +4.10%, September 2026 +2.60%, October 2026 +0.80%. October is unfinished at receipt and excluded. Reviewed usable coverage is fixed at March 1982–September 2026 (535 holding periods), so this raw October value cannot become finalized merely because time passes. Extending coverage requires a source review/update.

Source monthly returns have effective precision of 0.1 percentage points. Compounded monthly values differ from the supplied annual/YTD Total column by up to 0.4148103 percentage points. Totals are diagnostic only, not extra returns; values are not altered to force agreement.

This export uses BIL and IEF, not SGOV. It is kept separate from both app-implemented Chimeric variants. Exact variant fidelity, source currency, reconstructed early fund histories, transaction-cost treatment and execution conventions are not established by the CSVs. No actual ETF history back to 1982 is claimed. No dividends or inflation adjustments are added.

The existing Deep History adapter maps each signal to the following holding month and preserves supplied strategy returns. Components receive identical strategy-level NAV because security-level prices are absent. Optional tax is therefore an allocation-change proxy, not exact component-level realized gains. Multiple actual trades within a usable month would require additional daily/security-level data for reliable tax modeling. The adapter rejects repeated usable-month signals and gaps rather than double-counting a return or silently discarding trades.
