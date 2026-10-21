# Today / Compare performance and display changes

Branch: `vercel-migration`; no merge. Streamlit, `src/haa`, strategy rules,
tax/fee/return algorithms, database settings, login and cron are unchanged.

## Measured public-data timings

Measured locally on 20 Oct 2026 with the real existing Yahoo/FRED loaders,
not mock data. Constructed portfolios only; no private holdings were read.
These are not Vercel timings and exclude browser/auth/network round trips.

Daily Compare example: two portfolios sharing Century Momentum, Inflation
Compass Standard and USD A-RVol V3, 2,569 common sessions. Download/load 5.08s.
Identical retained inputs; alternate before/after order, three runs each:

| Engine path | Run 1 | Run 2 | Run 3 | Median |
| --- | ---: | ---: | ---: | ---: |
| Original orchestration | 15.99s | 14.44s | 17.24s | 15.99s |
| Optimized orchestration | 4.92s | 4.95s | 5.17s | 4.95s |

Median reduction: 69.05%, above the user's approximately 20% threshold.
Keep the daily optimization. Monthly portfolios retain the original inner
rebasing: skipping it changed raw NAV at floating-point precision, not just
monthly returns. The redundant outer full-window run is skipped for both.
Narrower requested windows still rebase; gaps and benchmark checks remain.

Today, same three public strategies and constructed saved settings:

| Path | Total |
| --- | ---: |
| Original, including closed provisional previews | 6.18s |
| New first load, current signals only | 4.48s |
| First warm repeat | 1.64s |
| Fully warm repeat | 0.53s |

Every sleeve was available. Public downloads were 2.68s of the new cold run.
These provider-dependent samples are not a guaranteed cold-load SLA.
Original deployed monthly **model** comparison (CM / IC / HAA-Simple) reported
input 6.582171s, engine 2.120691s, total 9.960609s in its Timing and cache panel.
This is not the daily-portfolio optimization benchmark. Existing model-mode
A-RVol refusal is unchanged. No saved portfolios were created for timing.

## Caches and privacy

- `input_cache`: complete original loader output, including source metadata,
  missing observations and adjusted opens, cached in existing public
  `results_cache` / bounded worker memory for one five-minute bucket. Not a
  splice of the cron's per-symbol rows: that older cache lacks the complete
  selected-model/source metadata needed here. No schema or cron changes.
- Snapshot JSON uses Python float values, not rounded pandas JSON strings.
  Date indices and dtypes are restored. Empty/degraded/failed retrievals are
  not promoted to a valid snapshot. Expired buckets load again.
- Public decision memoization is bounded, keyed by exact observations, source
  revision, class, arguments, UTC date and completed cutoff. Deep copies include
  nested weight dictionaries. The original strategy produces all decisions.
- Existing data-versioned result cache stays in use. Compare timing now includes
  download/cache, signal, backtest and presentation spans when performed.
  Logs contain phase durations only, not capital, holdings, names or saved IDs.
- Today always reads the signed-in user's current saved default/capital/FX.
  Only public per-strategy pieces are cached. Private composition is never
  cached. Input/cache failures remain disclosed; no substituted series.

## Layout and formatting

Today shows Monthly action first, then one per-sleeve table: sleeve, weight,
hold now, amount(s) in native currency, status. A combined line appears only
for genuinely shared funds, without merging currencies. Whole-word wrapping
and horizontal scrolling replace mid-word breaks. Missing capital/FX does not
invent amounts. Buy-and-hold provenance/warnings and original full-precision
CSV are available generically using the existing provenance helper.

The browser first requests `/api/today?preview=false`; opening the provisional
section requests `preview=true`. Existing unparameterized API behavior retains
previews for compatibility. Refresh invalidates in-flight preview responses.

Compare selections are always-visible checkbox lists. Existing progress,
timeout and no-duplicate guards remain; failed runs have an explicit Retry.
The existing 300-second function maximum remains unchanged (Hobby/Fluid limit).
No start/poll job system was introduced: measured engine time is well below it.

Shared browser-only formatting handles numeric displays, percentages, monetary
separators and dates (19 Oct 2026). Raw engine/API objects, CSV downloads,
editable prices/units/FX inputs and editable portfolio JSON are not rounded or
rewritten. Raw diagnostic error text is preserved, not reformatted.

## Verification policy

Compare monthly-return columns alone allow absolute error <=1e-12, relative
tolerance zero; their two-decimal percentages must still match exactly.
Other comparison frames/fields stay bit-exact, as do memoized decisions outside
Compare. Three full recursive comparison cases cover monthly and two A-RVol
daily blends. Tests also cover displayed tables, tolerance scope, mutation
isolation, float/metadata/date snapshot round trips, expiration, degraded and
failed downloads, lazy previews and relevant UI behavior.

Final local verification: 477 original tests, 370 API tests, 111 web tests;
all passed. Next production static build and TypeScript checking passed.
Existing Streamlit serialization and Starlette/httpx deprecation warnings only.
`git diff main -- app.py src requirements.txt pyproject.toml` is empty.
