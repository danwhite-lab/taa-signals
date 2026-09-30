# TAA Signals

A deliberately small, auditable Streamlit backtester for defined HAA variants. It implements no optimization, parameter sweeps, or synthetic data.

## Available models

- **HAA-Simple:** uses SPY and TIP 13612U signals; holds SPY only when both are positive, otherwise the stronger of IEF/BIL.
- **HAA 4:** published four-asset HAA variant. TIP is the canary; a non-positive TIP signal holds the stronger of IEF/BIL. With a positive TIP signal, it ranks SPY, VEA, VNQ, and IEF, holds the top two at 50% each, and replaces each selected non-positive-momentum sleeve with the stronger IEF/BIL defensive asset. IEF is intentionally eligible in both universes.
- **HAA 4 Leveraged 2x:** applies the same HAA-4 decisions using unleveraged TIP, SPY, VEA, VNQ, IEF, and BIL data, then maps executed holdings to SPY→SSO, VEA→EFO, VNQ→URE, IEF→UST, and BIL→BIL. The 2× ETFs never influence a signal. EFO and URE are practical execution proxies rather than exact tracker matches for VEA and VNQ; their returns target 2× daily performance and can differ materially from 2× over longer periods. This is a high-drawdown satellite, not a core holding.
- **Inflation Compass Steady (80-day):** compares SPY with its 200-day SMA and reads the prior trading day's five-year breakeven inflation rate (FRED `T5YIE`). Inflation is on above 2% when either the breakeven is higher than 80 valid trading observations earlier or the 80-day linear-regression slope of the published, daily-rebalanced sector indicator is positive. It holds XLE, XLK, XLU, or 50/50 XLP/IEF by regime. This post-breakeven implementation has no CPI fallback, so it begins in 2003.
- **HAA-Simple Leveraged 2x (SSO):** uses the *same unleveraged SPY and TIP signals* but holds SSO in risk-on periods. It always de-risks to unleveraged IEF/BIL. SSO momentum never controls the gate. This is a high-drawdown satellite, not a core holding.
- **HAA-Simple Israel:** retains TIP as a U.S. signal-only canary, uses TASE-listed CSPX (1159250) for the equity signal/holding, and compares TASE-listed iShares $ Treasury Bond 7–10yr UCITS (1159268) with Ayalon Kaspit (5136866) in risk-off periods. It is an ILS local-investability variant with its own CSPX benchmark; it does not use MAKAM 800 as a holding series. TIP is downloaded from Yahoo Finance; the three Israeli sleeves are downloaded from public TASE/Maya endpoints through tasekit.
- **TA-125 Smart Momentum:** an internally managed Israeli equity momentum sleeve held continuously through Migdal MTF TA-125 Smart Momentum (5134713). The fund's underlying index performs the momentum weighting and rebalancing, so the app presents no investor-level BUY/SELL/CASH signal. Public TASE/Maya fund history is used without a synthetic pre-fund proxy; the suggested maximum portfolio weight is 20% (guidance only).
- **HAA Classic (No QQQ):** TIP is the sole canary. When TIP 13612U is positive, it holds the top four assets at 25% each from IEF, SPY, IWM, PDBC, TLT, VEA, VNQ, and VWO. IEF is eligible in both the risk-on ranking and the IEF/BIL defensive choice; BIL is defensive-only. QQQ and leverage are intentionally excluded.
- **HAA Classic Leveraged 2x (No QQQ):** calculates the same TIP gate and top-four ranking on the 1× Classic no-QQQ universe, then holds 2× substitutes: IEF→UST, SPY→SSO, IWM→UWM, TLT→UBT, VEA→EFO, VNQ→URE, and VWO→EET. PDBC and BIL remain unleveraged. Risk-off compares 1× IEF/BIL momentum and holds UST or BIL. This is a high-drawdown satellite, not a core holding.

## What it does

At each completed month it uses Yahoo Finance adjusted close data for TIP and the non-Israel ETF models; Inflation Compass additionally uses FRED's daily `T5YIE` observation as a signal-only macro input. HAA-Simple Israel and TA-125 Smart Momentum use public TASE/Maya data through tasekit for their Israeli sleeves. A user replacement CSV can replace any asset. It calculates HAA's equal-weighted **13612U** composite:

```
(1-month return + 3-month return + 6-month return + 12-month return) / 4
```

Each return is `price at the signal date / price at the corresponding earlier month-end - 1`. This needs 12 prior observations for every asset involved in the decision; no pre-inception cash proxy is created. The signal is calculated after the final complete trading-day close, entered on the next valid execution date, and exited on the next monthly execution date. The current incomplete month is excluded.

The **Signals** page also shows a separate **Next Month Preview** when a common current-month price row is available. It reruns the same rules with the latest available common trading-day close, retaining that real date rather than inventing a month-end price. The preview is explicitly provisional, is not a trading instruction, and can change before the month closes; the completed month-end signal remains the only official app signal.

## Install and run

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -e '.[dev]'
streamlit run app.py
```

The app downloads Yahoo Finance history automatically. In the sidebar, enter the source ticker for each Yahoo role as `ROLE=TICKER` (for example, `SPY=SPY` or `SPY=VOO` for a validation replacement). Leveraged models also request their actual execution tickers; HAA 4 Leveraged 2x uses `SSO`, `EFO`, `URE`, and `UST`. Classic requests IWM, PDBC, TLT, VEA, VNQ, and VWO. `CSPX_IL`, `IEF_IL`, `AYALON_KASPIT`, and `TA125_SMART_MOMENTUM` are not Yahoo-configurable: they map respectively to TASE IDs `1159250`, `1159268`, `5136866`, and `5134713`.

The Israel adapter uses the first available published ETF field in this order: `Adj Close`, `NAV`, then `Close`. For Ayalon Kaspit it uses the Maya-published mutual-fund redemption price. It preserves native ILS and USD exposure and does not perform FX conversion. Successful public TASE/Maya requests are cached for six hours; this is a personal-research data source, not a guaranteed production feed. The public endpoints can change or be blocked. If a retrieval fails or lacks history, the app makes this visible and does not fabricate a series.

For independent validation, use the single multi-file upload control and name each CSV with its target role, for example `SPY.csv`, `CSPX_IL.csv`, or `AYALON_KASPIT.csv`. A CSV needs `Date` and `Adj Close` (preferred) or `Close`; the upload replaces that asset's full history rather than silently filling gaps. Before relying on an Israel backtest, compare several month-end values for IDs `1159250`, `1159268`, and `5136866` with their official TASE/Maya history pages, then download the app's raw/monthly data and audit CSV to confirm the same observations are used.

## Test

```bash
pytest
```

Tests cover the decision branches, a manually calculated 13612U example, future-data isolation, next-period execution, unchanged-allocation trade handling, matching benchmark dates, Classic HAA top-four selection and tie-breaking, weighted portfolio execution, realized-only tax accounting including partial sales, and mocked TASE/Maya ID mapping, field selection, failure, and caching behavior.

## Compare models

The **Compare Models** tab runs two or more existing models independently over the intersection of their valid, completed monthly holding periods. It restarts every selected model at the first shared period, so all curves, returns, and the SPY benchmark use identical dates and initial value. Classic HAA can shorten the comparison period because its PDBC history begins later. The comparison is informational only and does not recommend one model.

## Tax treatment

Tax is optional and defaults to 25%. The independent tax module taxes only realized positive gains when a position is sold on an allocation change. It records cost basis and uses prior realized losses to offset later realized gains. It does not liquidate or tax the final, unrealized position.

## Deployment

This is a standard Streamlit project. Create an app at [Streamlit Community Cloud](https://share.streamlit.io/) and point it to `app.py` on the `main` branch. Community Cloud installs the root `requirements.txt`; local development can use `pip install -e '.[dev]'`. The tasekit integration needs no API key. Do not represent the app as an official TASE data distribution service; use the official TASE Data Hub if you need contractual availability or distribution rights.

## Independent checks built into the UI

The Rules tab shows data coverage, common backtest period, first valid signal, raw and month-end price data, and a downloadable audit row per decision. Classic HAA audit rows additionally show all asset scores, offensive ranks, selected basket, current/previous target weights, trade flag, and the following holding-period return. For weighted portfolios, annual turnover is the one-way fraction of portfolio value purchased at each rebalance, annualized.
