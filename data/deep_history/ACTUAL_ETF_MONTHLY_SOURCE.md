# Actual GLD and IEF monthly histories

Retrieved 16 October 2026 using the existing Yahoo Finance/yfinance adapter,
with `auto_adjust=False` and **Adj Close required**, not a raw Close fallback:

- https://finance.yahoo.com/quote/GLD/history/
- https://finance.yahoo.com/quote/IEF/history/

The two `*_actual_monthly_returns.csv` files contain actual ETF histories.
Deep History prepends the separately documented early segments below.
The adapter's synthetic monthly accounting NAV is distinct from actual execution
prices. No daily valuation, daily drawdown or broker fill is fabricated.

Files retain the two observed month-end dates and provider-adjusted prices
behind each monthly return. Source prices were transported at ten decimal
places; returns retain floating-point precision and are not rounded to whole
basis points. Reproduction is `adjustedClose / previousAdjustedClose - 1`.
Every anchor must be the actual last NYSE session of its month. No filled prices
or returns are used. The partial inception month is excluded; the first observed
month-end supplies an anchor, not a fabricated full-month return.

| File | First anchor | Complete return months | Rows |
| --- | --- | --- | ---: |
| gld_actual_monthly_returns.csv | 2004-11-30 | Dec 2004–Sep 2026 | 262 |
| ief_actual_monthly_returns.csv | 2002-07-31 | Aug 2002–Sep 2026 | 290 |

October 2026 was unfinished and is excluded. Coverage is pinned to September
2026, matching the reviewed comparison benchmark. Refreshing requires a new
source snapshot and validation, not silent forward-fill. Yahoo can revise
historical adjustment factors; frozen snapshots make these runs reproducible.

Fund expenses already affect the prices. No additional expense deduction is
applied. IEF adjustments incorporate provider distribution adjustments;
Deep History's existing accumulating-NAV sale-tax treatment does not separately
model dividend/coupon withholding or cash distributions. Existing monthly
portfolio reset conventions remain unchanged. Combining these files with
synthetic A-RVol keeps that sleeve's disclosed modeled history, tax and fee
limitations; it does not make the whole portfolio real-fund-only.

Saved GLD and IEF models map to their extended Deep History entries. No mapping
is added for TASE gold or Harel bonds. A five-sleeve CM / IC / GLD / IEF /
synthetic A-RVol Deep History test now starts in January 1999.

## Early history supplied by the user on 16 October 2026

- `gld_pre_etf_monthly_returns.csv`: 71 returns, January 1999–November 2004.
  Bank of England XUMLGPD month-end gold price in USD per troy ounce.
  Original and cleaned files reconcile exactly. Dates are calendar month-end
  labels, not assertions about exchange execution. No GLD expense deduction
  is added to this spot-price segment. Actual GLD begins December 2004.
- `ief_pre_etf_monthly_returns.csv`: 43 returns, January 1999–July 2002.
  VFITX Yahoo adjusted NAV, last observed New York session of each month.
  This is a different, intermediate-term Treasury mutual fund, not actual IEF
  or a 7–10-year Treasury index. Its own expenses and provider distribution
  adjustments are embedded. Actual IEF begins August 2002.

Only month-to-month ratios are chained. Prices from different assets are never
divided by each other at the join. Source changes are not portfolio trades and
do not reset tax basis. No interpolation, synthetic return, overlap averaging,
performance calibration, extra fee deduction or final liquidation is applied.
Actual ETF files and their returns remain unchanged. Complete combined history:
333 months, January 1999–September 2026. These extensions apply exclusively to
Deep History, not live signals or ordinary real-fund backtests.

The private-app owner requested direct integration and no extra UI warnings.
Source identity and provenance remain in CSV fields, model metadata and this
document. Supplied source notes do not establish a public redistribution
licence; private use is not evidence of permission for public redistribution.
The original downloaded files remain unchanged outside this repository.

Source URLs:

- https://www.bankofengland.co.uk/boeapps/database/FromShowColumns.asp?searchText=gold
- https://query1.finance.yahoo.com/v8/finance/chart/VFITX

Original supplied file SHA-256:

- Gold original: `2b333a514f9f960a70e31f18faae1c67668350dae8313dfceebe9112f2de46a2`
- Gold cleaned: `a21c508956641b6656187c78ede80e483597daec465ccc2c31f47e30aac665a3`
- VFITX original: `e815fbd153637707c35bcff489bf986108fd940b47af986c4a845a8ba64a2c6d`

SHA-256:

- gld_actual_monthly_returns.csv: `3736bbc3c6d16c2752d85fef1e9124dd39e33a75d3c6ddb59ce5096774355a9f`
- ief_actual_monthly_returns.csv: `290df83c3c93dd25d319b7236f4c0e63fcad5631e78deea6723eaa27edb6a804`
- gld_pre_etf_monthly_returns.csv: `e31fc801bc1384e0c57f26d9f97eaf645b083a107958c4930c54e8457d9da7e9`
- ief_pre_etf_monthly_returns.csv: `8394a85828c6a68ae7c83107e9ecf806b4e9751cf3d289c1c0b4059d22673bca`
