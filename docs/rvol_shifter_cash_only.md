# A-RVol Shifter V3 Cash-Only

Status: documented interpretation, not independently matched to BestFolio signals or published performance. Original creator: u/Wongkok. Selected holdings: TQQQ, QLD, BIL; QQQ/SPY/HYG/LQD are signal inputs, not extra holdings. No defensive-sector rotation is part of Cash-Only.

Sources inspected:
- V3: https://www.reddit.com/r/TQQQ/comments/1se30ow/update_2_arvol_v3_adding_credit_spreads_and/
- Original post and volatility code: https://www.reddit.com/r/TQQQ/comments/1rpzweg/stop_blindly_holding_3x_the_rvol_shifter_for_the/
- Strategy flavour: https://bestfolio.app/strategies/rvol-shifter

## Rules and chosen conventions

RVol = sample standard deviation of 15 daily QQQ log returns × square root of 252. The original thread supplies the 15-day concept and sample-volatility correction code; its later code comment mentions V4, so exact V3 replication is not asserted. VR = RVol / trailing 252-session arithmetic mean of RVol, including the current session. This mean convention is an explicit assumption interpreting the creator's trailing yearly average, not recovered source code. Credit = 20-session percentage change in the HYG/LQD price ratio. Trend = SPY / SMA(200) − 1.

TQQQ downshifts to QLD if RVol >18%, VR >1.25, or trend <−3%. QLD exits to BIL if RVol >36%, VR >1.40, trend <−3%, or credit <−4%. Otherwise a QQQ close at its rolling 40-session closing low and RVol ≥20% triggers a Donchian exit. Ordinary exits take priority if several conditions coincide; only Donchian-only exits lock price-recovery re-entry. QLD upgrades to TQQQ if RVol <14%, VR <0.90 and trend >3%. Ordinary BIL re-entry to QLD needs RVol <25%, VR <1.10 and trend >−1.5%.

Donchian-only defensive exits re-enter QLD on QQQ recovery ≥3% from its rolling five-session closing low, or after 20 subsequent trading sessions. These replace rather than supplement ordinary re-entry gates, following the creator's reply. Rolling lows include the current closing observation; no intraday lows are available in this implementation. Timeout counts trading sessions, not calendar days. One state transition per close. Initial signal state is BIL, without the old V1 arming requirement; history is replayed from the first fully warmed-up observation with actual execution ETF data. The selected backtest start resets capital and tax basis, not the strategy state.

All indicators use the app's adjusted-close series (its provider has a Close fallback); raw-close versus adjusted-close differences can change signals. No leveraged pre-inception synthetic prices are added. Full indicators need at least 267 observed sessions, but signal history can warm up before the latest execution ETF's inception. Missing individual prices after the first valid signal fail explicitly instead of bridging gaps. Macro-only rows containing no model ETF observations are omitted.

## Execution, reporting and tax

Signals use completed daily closes, considered eligible after 17:00 New York. Same-day/intraday observations before this cutoff are excluded. Live status blocks data more than seven calendar days stale, which is a coarse freshness guard rather than a complete exchange-calendar validation. A Yahoo close is not independently guaranteed final by this timing convention.

Execution is the next observed trading-session CLOSE. This is intentionally different from the creator's stated next-open convention because the app currently loads adjusted closes, not opening prices. It also differs from the BestFolio same-signal-close assumption. No signal earns the return before its execution: the old asset carries to the execution close, then a switch occurs. The last close can execute the prior signal; the last signal has no invented future fill. Benchmark is frictionless SPY over those exact execution-close dates.

The fee setting applies per side: an initial buy pays once, and a switch pays both a sell fee and a buy fee. This differs from the legacy monthly engine's entry/change convention. Daily tax uses the existing IsraeliTaxState realized-gain accounting and loss carryforward, with the configured default 25% rate. Acquisition fees are included in cost basis and sale fees reduce proceeds. No terminal liquidation tax or tax on an unchanged position is invented. This remains the app's simplified CGT model, not a complete Israeli tax-law implementation (no new FX/inflation tax adjustments).

Daily NAV, execution audits and tax events are downloadable. Monthly returns are compounded daily net returns for reporting only, including partial first/last months. Risk metrics and maximum drawdown use daily NAV (including initial capital); CAGR uses calendar elapsed time. Best/worst months use the monthly aggregates. Equity and drawdown charts use daily NAV; annual/monthly return tables use reporting aggregates. Daily intramonth drawdowns are not silently replaced by monthly-only drawdowns. Original assets only: substitution backtests are explicitly blocked until daily shared-history alignment is supported.

Available: standalone Backtest, Rules, daily Signals, and live Portfolio/Today allocation display. Not enabled: monthly portfolio backtests, monthly Compare, generic monthly Research, or a Deep History proxy. Backend guards reject daily models in monthly portfolio/Compare paths because their execution periods and tax reset integration have not yet been reconciled. Existing monthly engines are unchanged.

Validation: deterministic tests cover all state transitions and strict threshold boundaries, Donchian locking/recovery/timeout/priority, exact volatility and VR calculation, warm-up, future-data invariance, completed-session cutoff, stale/missing data, next-close execution, per-side fees, realized-gain tax, no final liquidation, start-date reset, extra execution delay, daily intramonth drawdown and unsupported blends. Local environment lacks Streamlit/yfinance/pytest; validation uses bundled Python/pandas/numpy and unittest, not a live provider or deployed-UI test.
