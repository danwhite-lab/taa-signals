# Global all-country USD proxy

The active global benchmark and buy-and-hold sleeve use `global_all_country_usd_monthly_returns.csv`, supplied by the user as `Montly returns - World.csv` on 2026-10-06.

Source: https://www.lazyportfolioetf.com/etf/ishares-msci-acwi/

The source reports USD returns with dividends reinvested, before transaction fees and capital-gains tax. The user confirmed inflation adjustment was off. Source methodology says returns through December 2008 use equivalent ETFs/assets; their exact identities/weights are not specified in this export. Do not describe the early data as official ACWI index or actual ETF history, or as an exact FTSE All-World series. Source redistribution rights have not independently been established; the supplied export is not represented as an openly licensed dataset.

Validation: 681 consecutive monthly observations, January 1970 through September 2026. No duplicate years/months, internal missing months, nonfinite returns or returns at/below -100%. October–December 2026 are blank and excluded, not zero-filled. Export values are percentages rounded to 0.01 percentage points; compounding them reconciles with the annual/YTD Return column within 0.0175 percentage points. Annual Return and Drawdown columns are retained for audit but never used as additional monthly observations. Anchor returns: January 1970 -7.87%; September 2026 -1.19%. Do not add dividends or inflation again.

The preceding GBP file `global_equity_total_return_proxy_monthly_returns.csv` remains for provenance but is no longer referenced by either the active benchmark or a sleeve. It must not be compared directly with USD strategy returns.

Both buy-and-hold adapters intersect sleeve and benchmark months without invented prehistory. The December 1969 NAV of 100 is only a normalization anchor, not an observed return. Switching benchmarks never changes the sleeve's holding identity or return stream. Existing realized-gain tax logic remains unchanged; continuous buy-and-hold does not realize a gain merely because a month ends. Portfolio sleeve reductions can realize gains.
