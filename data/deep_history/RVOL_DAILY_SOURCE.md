# A-RVol daily-strategy supplied history

Received 2026-10-06, bundled byte-for-byte from `Signal History - A-Rvol (daily).csv` and `Montly returns - A-Rvol.csv`.

SHA-256 signals: fc4ff920b7b34bca9b38193e649e100127e25bf4ff7a72227e45f364a5e432c9

SHA-256 returns: 3b431650a0b9f2e465a262a8da4f6c71c8d815ebe0276bdd163d3942087e05e2

231 signal change rows, January 2, 2003–August 28, 2026. No duplicate dates. 61 months contain multiple changes. All source allocations total 100%, using TQQQ, QLD or BIL. Changes are preserved as a separate audit history, not aggregated into fictitious monthly trades. Missing dates between rows are not missing daily observations: this is an event log, not a full daily holdings/price file. Its completeness or execution-date convention is not independently verified.

286 contiguous monthly return observations, January 2003–October 2026. January 2003 is -3.50%, September 2026 +11.30%, October 2026 +7.30%. October is unfinished at receipt and excluded. Reviewed usable coverage is pinned to September 2026: 285 completed monthly returns. No prehistory is invented, no dividends or CPI adjustment are added, and annual Total is not an additional observation.

Available only as a standalone Deep History strategy with the existing S&P 500 or global benchmark, date range, initial capital and rolling-return displays. A synthetic strategy-level NAV compounds supplied monthly returns directly, without shifting them based on daily signal dates or interpolating daily prices. Its constant NAV holding identifier is an accounting representation, not a buy-and-hold claim about the daily strategy. Early ETF/proxy construction, currency, source costs and variant fidelity are unverified; live A-RVol implementation is unchanged.

Daily trade-level values/security prices are absent. Therefore tax and additional trade-fee calculations are disabled, and attempting them through the engine fails explicitly. No zero-tax result is claimed for actual daily trading. Blend/portfolio and generic multi-model comparison adapters reject this input. Monthly volatility/drawdown are reported; daily drawdown and trade-level tax cannot be derived from these files.
