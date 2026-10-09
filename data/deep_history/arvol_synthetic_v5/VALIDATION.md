# Synthetic A-RVol v5 validation

Reviewed 2026-10-09. This is modeled exposure, not verified historical ETF performance or a live signal source. No live strategy rules changed.

## Reproduction and rule fidelity

All eight input hashes and both output hashes match the supplied manifest. Generator run from the frozen inputs reproduces both outputs byte-for-byte. Its independent audit reports zero state mismatches, 24 lock releases (including nine under ordinary stress), and zero indicator prefix-test failures across 40 sampled cutoffs.

A separate check feeds the reconstructed synthetic indicators into the actual app's `RVolShifterCashOnly.transition`, including the app's lock-age handling. All 10,059 decisions match. This checks transition fidelity on the supplied proxy inputs, not equality to actual QQQ/SPY signals. Missing credit history is explicitly disabled before May 2007; it is not invented.

10,059 daily rows, 1986-11-03–2026-10-08; 480 monthly samples. No duplicate or missing exchange sessions. Held positions are continuous. Independently recomputed daily returns differ by at most 0.0000005 (six-decimal rounding); reconstructed NAV differs by at most 0.00005 (four-decimal rounding). Monthly dates and NAVs exactly equal the final daily observation of each month. NAV ratios, not cumulative rounded return columns, drive the app.

Source headline: 27.769658% CAGR and -47.289764% daily closing-NAV drawdown since 1986-11-03; generator reports 1,241 calendar days longest underwater and 29.90%/-40.7% since the 1994 rebase. These are source calculations, not the UI's benchmark-aligned interval. The 1994 column rebases the existing path; it does not restart the state machine.

## Application treatment

Separate standalone option, alongside the earlier supplied monthly A-RVol import. Full daily source retained, including partial November 1986 and October 2026. Benchmark comparisons use December 1986–September 2026 complete months, anchoring capital at the last November observation. Selected ranges restart capital at the preceding month-end NAV; they do not restart the original signal machine. Daily curves and drawdown use actual source observations; benchmark comparisons use monthly returns only, with no densified daily benchmark. Rolling five-year returns use complete monthly windows. Source holdings before/after execution are not relabeled as decision dates.

Tax and incremental commissions are disabled. The source provides combined overnight/intraday sleeve returns on switch days, not separate sale values/security prices needed for reliable tax lots. No account tax estimate is inferred from daily state changes alone. No blending with monthly deep-history sleeves.

## Modeled inputs and limitations

Fully synthetic QLD/TQQQ throughout; no actual funds spliced. NDX price index excludes dividends. Leverage financing uses contemporaneous IRX/252 and 0.95% annual fee; trade-day carry is assigned to the ending position. Cash is modeled T-bill income, not BIL. S&P trend uses total return less 0.07% annual fee, price index before 1988. HYG/LQD use adjusted closes. These proxies need not generate the same signals or returns as live ETF inputs. Historical underperformance versus actual fund returns is not a guarantee of conservative risk.

Next-close execution before 2001-01-02; next-open thereafter, with 226 open switch days. NDX opening levels are not tradable fund quotes. IRX contains 46 missing observations in the entire raw file and the supplied generator forward-carries yields; source daily return reconstruction has no missing values. NDX and equity quotes are not forward-filled by the app. The reviewed generator contains a general NDX forward-fill, but these frozen NDX inputs have no missing prices or sessions. No forward-looking fill is introduced.

Raw source headers are retained verbatim as provenance, not instructions or app branding. The supplied manifest's IRX row has malformed CSV punctuation, so hashes are checked against its literal fields rather than blindly parsing the entire manifest as a clean CSV.

## Reproduce offline

Run in a temporary directory. Copy `inputs/` to `data_cache/` and run `generator.py --outdir out5`; then run `supplied_audit.py` in that directory. Do not re-download or use the generator's optional interpretation switches. Supplied scripts are reference/audit tools only; the app never executes them. All inputs end 2026-10-08 except IRX, whose extra 2026-10-09 row is outside the equity calendar and unused.
