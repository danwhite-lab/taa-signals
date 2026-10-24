# Research-only ILS x3 scenarios

These are standalone modelled scenarios, not the histories or verified trading
rules of Ayalon 5117684 or MTF 1187079. They never extend or splice real funds.
Both scenarios and both matching ILS benchmarks contain exactly 273 monthly
decimal returns, January 2004–September 2026. A return of 0.0123 means 1.23%.
October 2026 is excluded. Fund-style management/trustee fees are already inside
the scenarios; the app must not subtract them again.

## Currency and use

DeepHistorySpec and DeepHistoryBenchmarkSpec now carry currency, default USD.
Existing USD series, default benchmarks and calculations retain their behavior.
The new ILS specs are single-strategy options only. Choose the matching ILS
benchmark explicitly in the existing Deep History benchmark picker:

| Scenario key | Benchmark key |
|---|---|
| research_ta125_x3_ils | ta125_ils |
| research_nasdaq100_x3_ils | nasdaq100_ils |

The unchanged default USD benchmark is rejected for an ILS scenario. Blending,
comparison, DCA-mixing, saved-portfolio FX conversion, other FX conversion and
inflation adjustment are unsupported and fail closed. Enter nominal ILS capital
directly. Standalone monthly deposits use the existing trade ledger, but the
scenario is not a reliable reconstruction of real fund DCA. There is no automatic
mapping from either actual-only fund to these research scenarios.

The exact supplied banner is carried on every result:

> Research-only modelled scenario in ILS. NOT the history of Ayalon 5117684 or MTF 1187079 and not a reliable DCA result. Reset rules are assumed; the MTF emergency-reset rule is unknown (none modelled, so Oct 2008 loses 64% in one month); Nasdaq-100 NTR before Oct 2011 is derived, not official; swap spreads and similar costs are not modelled; TA-125 modelled returns run about 2pp/yr above the real fund over 2014-2026. Entry/redemption fees and tax are not included and come from the trade ledger, not a flat haircut.

No entry/redemption load is automatically invented. Explicit trading-fee
assumptions and tax use the existing ledger. No final liquidation or flat tax
haircut is added. The supplied banner is a limitation statement, not a claim
that an unconfigured fund-specific entry fee is automatically charged.

## Supplied method and limits

The generator is preserved as supplied in build_synthetic.py, not integrated
into live strategies. NAV earns the cash rate; drifting fixed notional earns
the index return less cash. Fees accrue by calendar days.

- TA-125: index 137 gross total return (linked TA-100 predecessor before
  2017-02-09), Makam index 800 as a cash proxy; 1.85% + 0.04% annual fees.
  Exposure outside 280–320% resets to 300% at daily close. The reset target
  and timing are assumptions; the exposure band is described as official by
  the supplier. FX is zero in the scenario although the fund permits up to 10%.
  Entry addition is excluded.
- Nasdaq: official XNDXNNR from 2011-10-10; earlier NTR is derived from NDX
  price and XNDX gross returns using 70% dividend reinvestment. One-times
  USD/ILS applies to the whole NAV. Monthly reset uses the last TASE day;
  no emergency reset is modelled because its rule is unknown. Annual fees
  are 1.35% + 0.03%, supplied from secondary sources, not a verified prospectus.
- US closes and bill rates strictly precede the TASE observation. BoI FX dates
  are no later than the TASE day; intraday fixing/valuation ordering is unknown.
- The single missing bill value on 2010-10-11 is explicitly forward-filled and
  logged by the generator. No missing app return months are filled. Makam and
  T-bills are financing proxies, not proven fund borrowing costs. Swap spreads
  and similar costs are zero in the scenario.
- Supplied validation is limited: TA-125 runs approximately 2 percentage
  points/year above the fund over 2014–2026; MTF has only about 50 validation
  months with wide uncertainty. No tuning or performance promise is implied.
  The supplier has not re-verified Makam's TR classification in this delivery.

## Inputs and reproducibility

The original workbooks remain unchanged outside this repository. The four
CSV files in the parent directory were regenerated offline from raw_inputs.xlsx
and matched every exported workbook cell exactly at the supplied 8-decimal
precision. Source rows, transformations and retrieval dates below are supplied
metadata, not a new independent verification of each financial methodology.

| Original attachment | SHA-256 |
|---|---|
| raw_inputs.xlsx | ffa72d538ff0c34402ce6b839ad43cc1aa6643b7dce8c510f2bd8589c0649742 |
| synthetic_x3_results.xlsx | ea29797d8b82e08daf737a69cf998c6dcd5a1d619cba714482b3c6bde8defbee |
| build_synthetic.py | 0c7942bd093a19fd78e7926dc239ffb094ced9f6bd027b63ad7ea6f6c26e6cda |

With the original raw workbook, NumPy, pandas, openpyxl and xlsxwriter:

    python data/deep_history/ils_x3_research/build_synthetic.py raw_inputs.xlsx OUT

The generator writes the four monthly CSVs plus diagnostic outputs in OUT;
matplotlib charts are optional. No network is used. Raw inputs and diagnostic
workbooks are not bundled into production or used to fetch live prices.

## Sources recorded in raw_inputs.xlsx, Sources sheet

All source retrieval dates are 2026-10-23.

- TASE indices 137 and 800: https://api.tase.co.il/api/index/historyeod
  (POST oId 137/800, pType 8), 2003-01-01–2026-10-23, index points.
  TA-125 methodology reference:
  https://market.tase.co.il/en/market_data/index/137/about
- NDX, XNDX, XNDXNNR: https://indexes.nasdaq.com/Index/HistoryData
  (POST id), index points. NDX begins 1999-01-04, XNDX 1999-03-04;
  official XNDXNNR begins 2011-10-10. Derivation reference:
  https://indexes.nasdaq.com/docs/index_versions_ndx.pdf
- BoI USD/ILS: https://edge.boi.gov.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/EXR/1.0/
  (OF00, USD, series RER_USD_ILS), ILS per USD, 2003-01-02–2026-10-23.
- US 13-week Treasury bill coupon-equivalent rate:
  https://home.treasury.gov/resource-center/data-chart-center/interest-rates
  (daily Treasury bill CSVs 2003–2026). Percent values converted to annual
  decimals; one original missing observation retained for the logged fill.
- Actual validation series only: Maya
  https://maya.tase.co.il/api/v1/funds/mutual/5117684/history/file
  (redemption prices, 2012-12-30–2026-10-22), and TASE
  https://api.tase.co.il/api/security/historyeod
  (oId 1187079, pType 8, closes in agorot, 2022-07-05–2026-10-23).
- MTF fee references supplied by the user:
  https://finance.themarker.com/etf/1187079 and
  https://www.superfunds.ai/fund/1187079
