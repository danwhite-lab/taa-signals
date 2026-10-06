# Chimeric Asset Allocation — experimental

## Full Retreat variant

Separate catalog variant under Chimeric Asset Allocation. A strictly negative TIP 13612U sends 100% to the stronger IEF/SGOV (IEF wins a tie). Zero or positive TIP follows unchanged Standard allocation. Scoring, universe, data integrity, warm-up, execution, fee and tax treatment are shared. This is an ablation, not the Standard published allocation; no reported historical performance comparison is presented as verified by this app.

Implemented from the creator's replication note and defensive-selection clarification:
https://www.reddit.com/r/LETFs/comments/1w6rva4/chimeric_asset_allocation_drink_the_koolaid/

Monthly strategy with daily adjusted-price inputs. Nine raw signals use 63/126/252 daily returns/path-efficiency horizons and 3/6/12 monthly price averages. Correlation uses 252 daily simple returns to the equal-weight ten-asset universe, including the evaluated asset. Adjust raw signals before ranking; average exact percentile ties; average nine percentiles.

Select top four, each 25%; own equal-weight 1/3/6/12-month momentum must be strictly positive. With negative TIP momentum retain only the best-ranked equity and diversifiers ranked in the overall top three. These filters apply to original top-four slots; never promote a lower-ranked asset to replace one. Rejected slots use stronger IEF/SGOV momentum in either regime.

Explicit conventions not uniquely fixed by the post: ERX rather than DIG; alphabetical overall-score ties; IEF on a defensive tie; zero TIP is normal mode. Undefined correlation (including denominator effectively zero) or zero path length fails closed rather than inventing a score.

Data: actual ETF history only; no reconstructed leveraged funds, DBC splice or BIL/SGOV splice. All thirteen assets must be available. Trim pre-common-inception rows and require 12 prior monthly observations plus 252 daily returns. Missing internal sessions, partial quotes, duplicates and invalid prices are rejected. The first common monthly observation can be a partial inception month, consistent with existing month-end conversion. Provider-adjusted closes are used as supplied; no dividends added twice. Leveraged ETFs' historical leverage changes remain in their real fund histories.

Execution: existing monthly weighted engine, next available session CLOSE after month-end. Existing per-side fees and optional realized-gain tax/loss-carryforward model apply; no claim of identical creator execution or published returns. Current-month portfolio previews are explicitly non-actionable. No deep-history dataset is supplied for this strategy. Generic Research validation is not certification of fidelity or future profitability.
