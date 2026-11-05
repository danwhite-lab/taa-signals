# USD-equivalent backtests

“Test USD equivalents” is an optional research setting, off by default, in single-strategy and portfolio Backtest and both Compare modes. It runs the existing USD implementation for the **entire** requested period. It does not reconstruct Israeli fund returns, convert USD returns to ILS, splice histories or extend ETFs before inception. It is separate from bundled Deep History.

Saved-portfolio Compare and its date options validate execution currencies after mapping when this setting is on. A supported Israeli portfolio can therefore be compared with a USD portfolio, including mixed-origin sleeves, while preserving every sleeve weight. With the setting off, the original single-currency restrictions remain in force.

Capital and monthly contributions become USD amounts without numeric conversion. Portfolio weights, saved portfolio records and live holdings/signals are unchanged. Results exclude USD/ILS movements, Israeli tracking differences and hedging costs. The existing realized-gain tax approximation remains an approximation, not a reconstruction of actual Israeli fund tax treatment.

## Coverage

The explicit registry is `data/usd_equivalents.json`. Original USD selections retain their implementation. Supported Israeli strategies map to their existing USD originals: HAA-Simple, HAA 4, the three Inflation Compass variants, Century Momentum, Century Momentum Move to Cash, Growth-Inflation Concentrated, GEM, GGCEM Link Original and BAA-G4 Aggressive. Move to Cash retreats to BIL, not IEF.

Buy-and-hold mappings cover SPY, QQQ, semiconductors, global equities and gold. Functional mappings require particular care:

- Global uses ACWI, which follows a different index from FTSE All-World.
- Harel government bonds use IEF: US government bonds have different rates, duration and inflation exposure from Israeli bonds.
- World Value uses IVLU, which excludes US stocks and is not an exact world-value match.
- Nasdaq-100 x3 Monthly uses TQQQ, whose **daily** reset differs materially from a monthly reset.
- S&P 500 x3 uses UPRO, with different financing, tracking and local implementation.

Unmapped strategies fail explicitly before data loading; no sleeve is silently omitted or reweighted. These include Israeli-only signals/indices, A-RVol TASE implementations without a defensible identical counterpart, Japan (the current USD catalog entry is a price index rather than an ETF total-return counterpart), TA-125 and DAX leverage products.

## Dates, fees and reporting

Date options are refreshed from mapped inputs. Portfolio/Compare availability intersects executable periods after strategy warm-up and benchmark coverage. Valid selected dates survive a toggle; dates outside the newly available bounds reset to valid bounds. Actual result dates are displayed separately from availability. Missing provider history remains an error, rather than a fallback to another fund.

Backtest uses the existing USD fee tariff ($5 per order by default), or explicitly selected legacy fee settings. Compare retains its existing percentage fee setting; it does not acquire Backtest’s flat per-order tariff. Existing monthly sleeve weight resets and initial-weight daily valuation retain their different behaviours. Results across screens require matched methodology and fees before interpretation.

Every research result includes original labels/security identifiers, resolved USD inputs, caveats, actual tested dates and a mapping version. Cache identity includes the research flag and registry/content version. CSV exports carry research provenance and a separate mapping download. Unsupported mappings and missing histories do not create successful results.

## Verification

`api/tests/test_usd_equivalents.py` uses deterministic fixture prices and the real strategy/backtest engines. It verifies default-off behaviour, earlier USD date coverage, one-sleeve parity across single/portfolio/Compare models with matched assumptions, saved-portfolio immutability, unsupported-sleeve rejection, tax/deposit/USD-fee parity, cache separation/version changes and CSV provenance. UI tests cover all four paths, date preservation, labels and disclosures.

For example, the fixture’s Israeli HAA input begins in January 2004 while its USD input begins in January 2000. Enabling the toggle exposes earlier USD bounds; strategy warm-up still limits executable history. These are **test fixtures**, not a claim about live provider coverage or historical investment results. Live availability continues to depend on the repository’s existing providers and data validation.

Validation for this change: 10 focused API/packaging tests, 5 focused UI tests and 55 existing engine tests passed; production build and TypeScript checks passed. Chromium smoke checks rendered all four paths with fixture responses, including a 390px mobile viewport without document overflow. The wider affected API run had 151 passes and 9 failures; all 9 reproduced against the original main modules (baseline run stopped after reproducing them). The affected UI run had 20 passes and 28 failures, all present in the original-page baseline. These existing failures remain unresolved by this feature.
