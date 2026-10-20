# Vercel migration skeleton

This is an opt-in migration preview on `vercel-migration`. Nothing in
`app.py`, strategy/data/engine code, the Streamlit dependency manifests, the existing dashboard,
or its hosting configuration is changed. Do not merge or point the live domain
at this skeleton. Browser login and private saved-data endpoints are available (setup below). A fixed-universe live-data
and backtest diagnostic is available, alongside the authenticated single-strategy
Backtest page described below. Step 7 adds Portfolio and Deep History / Proxy
to that same page and API (details at the end of this document).
Step 5 additionally brings the five approved Rebalance Holdings feature files
over byte-identically from main; no further edits to those source files are made.

## What runs

- `web/`: Next.js App Router, TypeScript, React, plain CSS, exact package versions
  and an npm lockfile. The page fetches `/api/strategies` in the browser and lists
  the Python catalogue labels/currencies, with loading, error and retry states.
- `api/index.py`: a FastAPI ASGI `app`, exposing `GET /api/strategies`,
  `GET /api/rules`, `GET /api/price-check`, authenticated `GET /api/signals`, and
  the authenticated single-strategy `/api/backtest` routes described below.
  It adds the existing repository `src/` to `sys.path`, then imports the real
  `haa.model_catalog.MODEL_CATALOG`. No strategy/data/backtest code is duplicated.
  Step 5 also exposes the private `/api/rebalance*` routes listed below.
  JSON preserves every catalogue metadata field except the non-JSON Python class
  reference `model_class`. Private saved-data routes are separately authenticated.
- `vercel.json`: builds Next.js to `web/out`, serves those static assets, and
  rewrites `/api/*` to the Python function. The function includes `src/haa` and
  the unchanged `app.py` rule-text source. `cleanUrls` stays disabled: it breaks
  the rewrite's `.py` destination. Next.js exports directory indexes so static
  pages work at `/rules/` and `/price-check/` without changing API routing. The diagnostic function
  has a 300-second maximum duration; account/plan limits still apply.
- `api/requirements.txt`: pinned API/engine runtime dependencies. Tasekit uses the
  same pinned Git commit as the existing engine. Uvicorn supports local testing.
  Plotly is intentionally absent: browser charts use native SVG. The direct
  dependencies are pinned; the Python transitive dependencies are not fully locked.
- `.vercelignore`: Vercel-only exclusions keep the existing root Streamlit
  `requirements.txt` and `pyproject.toml` out of this deployment. Python discovery
  uses `api/requirements.txt` instead. The original files remain untouched for the
  live app. Secrets, tests and frontend build/dependency folders are also excluded.
  `.python-version` selects supported Python 3.12 for the Vercel function.

The Next.js build is a **static export**, not an SSR deployment. API requests
remain live Python function calls, not build-time catalogue snapshots. This
simple single-project setup does not require Vercel's experimental multi-service
feature. Next.js server actions, SSR, server-side login/session handling and
dynamic Next.js route handlers are not enabled by this skeleton; revisit the
deployment design before adding features that need them. The existing bundled
engine data remains in the repository; this endpoint does not load it.

References: [Next.js static export](https://nextjs.org/docs/app/guides/static-exports),
[Vercel file-based Python ASGI functions](https://vercel.com/docs/functions/runtimes/python/api-directory),
and [Vercel build/function configuration](https://vercel.com/docs/project-configuration/vercel-json).

## Run locally

Use Python 3.12, Node.js 24 LTS and npm. From the repository root:

```sh
python3.12 -m venv api/.venv
api/.venv/bin/python -m pip install -r api/requirements-dev.txt
api/.venv/bin/python -m uvicorn api.index:app --host 127.0.0.1 --port 8000
```

In a second terminal, from the same root:

```sh
npm --prefix web ci
npm --prefix web run dev
```

Visit `http://localhost:3000`. In development only, Next.js proxies `/api/*` to
`http://127.0.0.1:8000/api/*`, so the browser still uses one origin. No CORS
wildcard or API URL baked into browser code is needed. Login needs environment and callback setup below.
`http://127.0.0.1:8000/api/strategies` also works directly. Do not use
`next start` for the exported production build; Vercel serves `web/out`.

## Verify

```sh
api/.venv/bin/python -m pytest api/tests -q
npm --prefix web run typecheck
npm --prefix web test
npm --prefix web run build
```

The original Python suite still uses its existing Streamlit/dev environment and
command (`PYTHONPATH=src python -m pytest tests -q`). It does not require FastAPI;
API tests are kept under `api/tests` and run separately. Before publishing, check
`git diff main -- app.py src requirements.txt pyproject.toml` is empty.
The typecheck script generates Next.js route declarations first, so it works on
a fresh checkout without a previous dev server or build. `next-env.d.ts` is
generated by Next.js and is intentionally not committed.

## Deploy as ONE separate Vercel project

1. Publish `vercel-migration` when approved. Keep it unmerged. Do not modify the
   existing Streamlit hosting project or its domain.
2. Create a separate Vercel project connected to this repository. Build the
   `vercel-migration` branch, not `main` (which intentionally has no migration
   skeleton). For an initial branch deployment via CLI, check out this branch,
   run `vercel link` to the new project, then `vercel` for a preview, **not**
   `vercel --prod`. Linking/deploying requires your Vercel account.
3. Root Directory must be the **repository root (`.`)**, not `web/` or `api/`.
   Framework Preset: **Other** (`framework: null` is deliberate). Node.js: **24.x**.
   Keep Python **3.12**. Use the checked-in build settings:
   - Install: `npm --prefix web ci`
   - Build: `npm --prefix web run build`
   - Output: `web/out`
4. Set the environment variables and callback below. Keep preview protection;
   never put real credentials in committed files.
5. Verify `https://<preview>/api/strategies` returns JSON, then open
   `https://<preview>/` and check that strategy names load. Unknown `/api/*` routes
   should return a JSON 404, not frontend HTML.

Local builds and HTTP tests do not prove the Vercel cloud deployment. Review its
first build log for `api/requirements.txt`, successful Python dependency installs,
function bundle limits, and inclusion of `src/haa`. General-purpose financial
backtests may need more time/memory and persistent storage than serverless
functions provide; this diagnostic is not a general backtest service.
No cloud deployment or account changes
are performed just by adding these files.

## Rules preview and shared methodology

`/rules/` is a lightweight, client-rendered methodology page. It fetches only
`/api/rules`, not prices, portfolio/account data or backtests. The shared top bar
lists the exact eight current app pages; Today, Rules, Signals, Backtest, Rebalance Holdings
and the minimal Portfolio page are enabled.
Catalogue/diagnostic URLs remain available directly behind the browser login gate.

The existing `app.py` is unchanged and remains the one source for `MODEL_RULES`
and its static implementation/data notes. The API parses that trusted repository
file using Python's AST and evaluates only the existing `MODEL_RULES`
declarations and catalogue-derived rule augmentation. It never imports or runs
the Streamlit application, authentication, data downloads or UI. The selected
block allows only the existing `getattr` metadata call and uses no builtins.
It is not supplied by a request. This narrow compatibility reader avoids copying
the prose or changing the live app; future source refactoring must preserve the
declarations or update this reader and its parity tests. Source-read failures
are explicit API errors, not empty invented text.

`app.py` is bundled server-side for this purpose, not exposed as a static asset.
The API returns all 45 catalogue implementations with exact Markdown, original
strategy risk warnings and the common static notes. React Markdown renders the
API response without executing raw HTML. Four existing implementations lack
`MODEL_RULES` entries: the three Israel Inflation Compass variants and
Momentum-Correlation Triplet. These remain clearly marked as missing, with no
substituted methodology. Coverage/audit tables and dynamic results from the
Streamlit Rules page are intentionally not migrated.

## Live price and A-RVol diagnostic

Open `/price-check`, then press **Run live checks** once. It calls
`GET /api/price-check`. The page shows all returned fields as plain text, including
HTTP response bodies and browser/network exceptions if the request itself fails.
It does not auto-poll or start expensive diagnostics on every page visit.

The fixed checks are SPY, QQQ and VXUS through the existing
`haa.data.download_yahoo_prices` function (yfinance, maximum available history),
and CSPX_IL/1159250, RVOL_3X_IL/1187079 and TA125_SMART_MOMENTUM/5134713 through
`haa.tase_data.TasePriceSource.fetch_asset`. The latter deliberately retains the
app's asset-specific routes: in particular 1187079 uses its existing published
EOD series rather than substituting a different endpoint. Each result reports
success, latest series price/date, loader/field, elapsed seconds and any exact
exception text/type, chained traceback, provider log messages and warnings.
Failures do not stop the remaining checks. No source is replaced or silently
retried. History prices retain the engine/provider units and adjustment choices;
they are not re-labelled as live broker quotes or converted using a guessed
agorot divisor.

One original **USD A-RVol Shifter V3 Cash-Only** benchmark is calculated or retrieved from the results cache. This selects
the existing daily V3 implementation; it is not a claim that all strategy
variants have been ranked by runtime. It uses a complete same-refresh price cache under 36 hours old, or downloads the complete seven-series set with an explicit fallback warning
using `download_yahoo_daily_bars`, calls the unmodified strategy's `decisions`,
then `haa.engine.run_backtest` with the matching adjusted opening prices. The
window is the available real history up to the strategy's completed-session
cutoff. No CSV, synthetic or proxy fallback is used. The displayed diagnostic
parameters are hypothetical: initial capital 10,000 USD, zero trade costs and
deposits, tax enabled at 25%, with existing engine accounting. These are not
the user's saved account settings or a performance recommendation.

Data, signal and engine seconds are separate; outer seconds include the whole
operation. Successful runs also return signal/NAV-row counts and actual dates.
A failed data or signal step returns its error and leaves engine seconds null,
never claiming that a backtest completed. Cached signal/engine times describe the original calculation; outer time measures this request. A Vercel hard timeout cannot return Python's
per-check report; the page instead exposes the actual HTTP/platform error body.
This diagnostic is public unless deployment protection is enabled and can incur
function compute usage. It has no arbitrary ticker, URL or strategy parameters.

## Google login and private saves: manual setup required

The browser stays a static export: pinned `@supabase/supabase-js` uses Google
PKCE with persistent browser storage and browser-owned refresh tokens. There are
no cookies, SSR sessions, server actions or new login system. The callback
explicitly exchanges the code once and removes it from the URL. `/login/` and
`/auth/callback/` are public; `AuthGate` withholds other page components until
a browser session exists. Account changes remount private page state. Browser
state is not server authorization: every private API request verifies its Bearer
token through the existing `verified_session`/Supabase `get_user` helper.

Configure these **names**, with actual values only in private Vercel settings:

- Build/browser: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`.
- Python: `SUPABASE_URL`, `SUPABASE_PUBLISHABLE_KEY` (same project/public key).
- Python cache only: `SUPABASE_SERVICE_ROLE_KEY`.
- Vercel scheduler: a strong `CRON_SECRET`.

Local Next dev reads `web/.env.local`; the Python process needs its own environment.
The committed `.env.example` files contain names only. `NEXT_PUBLIC_` values are
baked into the static export, so rebuild when changing them. Never prefix the
server service key with `NEXT_PUBLIC_`, send it to a browser, or use it on a user save.

Allow this exact Supabase redirect (and a separate localhost callback for local
testing), not a broad wildcard across all Vercel previews:

`https://signalboard-git-vercel-migration-danwhite-labs-projects.vercel.app/auth/callback/`

Keep Google provider configuration and existing database ownership/RLS policies.
Check that authenticated users can select/insert/update their own `user_settings`
and select/delete their own `portfolios`, and can invoke `save_private_portfolio`.
Do not loosen policies to fix an error. This change does **not** alter or execute
SQL for either existing table or the RPC, and has not used any real account data
in tests. Real OAuth and cross-device smoke testing remain a user setup step.

Private endpoints (all return `Cache-Control: no-store, private`):

- `GET /api/me`: verified user ID/email only, never tokens.
- `GET /api/workspace`, `PUT /api/workspace`: `{revision, payload}`. PUT patches
  recognized preference fields, preserving unmigrated settings/holdings. Writes
  use the existing compare-and-swap revision check; conflicts return 409.
  Holdings changes require a new `last_operation_id` and reuse
  `save_holdings_workspace`, including its read-back after an uncertain response.
  An identical retry returns the saved row without applying units/cash twice.
- `GET /api/portfolios`, `POST /api/portfolios`: existing list/RPC helpers. POST
  accepts `{payload, id?, expected_updated_at?, is_default?}`. An update must
  include the loaded timestamp; the RPC atomically checks conflicts/defaults.
- `DELETE /api/portfolios/{id}?expected_updated_at=...`: delete filtered by
  verified user, ID and timestamp in a single request. No stale blind delete.

No private route accepts a user ID from the caller. Only the public key plus that
verified user's access token reaches the existing user-scoped storage helpers.
Validation/provider errors do not echo submitted values or tokens. The minimal
Portfolio page lists names/defaults/update dates and the workspace revision;
supports imported version-1 JSON saves/edits/deletes/default selection; and saves
one workspace name preference. It deliberately does not recreate the portfolio
builder, holdings editor or backtest pages. Blank forms are not prefilled with
invented holdings/capital/FX. After a conflict or uncertain mutation, the draft
stays visible but further mutations pause until an explicit reload. Reload
discards the draft. Unchecking the default checkbox preserves current defaults,
matching the existing RPC; it is not a clear-default action.

## Server-only caches and daily refresh

Review and run **only** `supabase/cache_tables.sql` manually in Supabase SQL Editor.
It creates two new tables with RLS, no browser policies, explicit revocation from
public/anon/authenticated, and grants only to service_role. It is transactional
and intentionally fails rather than replacing existing tables. No SQL was run
by this implementation. The server service key is used only in `server/cache.py`.
`server/` is bundled into the one `api/index.py` function, avoiding accidental
extra Vercel Python functions for helper modules.

Daily refresh: `GET /api/cron/refresh-prices`, `15 3 * * *` (03:15 UTC). It rejects
missing/wrong Bearer `CRON_SECRET` before fetching or accessing caches. Four
workers use the **existing** Yahoo adjusted-close/open loader and TASE adapter.
The universe is the catalogue's price assets plus the existing default Yahoo
map, and all explicit TASE asset mappings. No macro/FRED/OECD series are cached;
those are not prices. TASE rows retain their source/field/security ID and original
provider units, not guessed broker quotes. No proxy extension or filling is added.
Each symbol reports success/date/time or its provider error (configured secrets
redacted), and failed refreshes leave earlier stored rows untouched. Errors are
returned to the authenticated caller, never printed with credentials/account data.

**Vercel crons run only on production deployments, not branch previews.** Pushing
this branch configures the job but does not activate a daily job on its preview.
No production promotion is performed here. Enable a production deployment of the
separate migration project only when ready; do not redirect the Streamlit domain.
The full universe may exceed provider/rate/function limits despite four workers
and the existing 300-second limit. This is unverified in cloud. A hard timeout
can leave a partial refresh; the benchmark rejects mixed refresh IDs and loads
the complete live data instead, with a visible warning. A completed partial-failure
run returns `success: false`; inspect its per-symbol results, not just HTTP 200.

Price snapshots store raw unfilled observed rows, adjusted opens/closes for Yahoo,
and `as_of` plus `updated_at`. A-RVol uses only a complete same-refresh seven-symbol
Yahoo snapshot under 36 hours old. Missing observations remain missing; the
unchanged strategy/engine applies its original session/cutoff/execution rules.
If the snapshot is unavailable/invalid/too old, it downloads the entire live set
once, explicitly reports the fallback, and never silently stitches sources.

Results cache: SHA-256 of `{model, params, start, end, data_version}`. Data version
contains latest price date **and a hash of exact observed rows**; same-date history
revisions invalidate it. Params also include the engine/adapter source hash and
completed-session cutoff. A bounded warm-worker LRU avoids repeat database reads;
Supabase persists results across cold starts. A cache read/write failure produces
a warning and falls back to the unchanged calculation, with no double backtest in
one request. Engine failures are not cached. Warm-worker locking avoids duplicate
concurrent calculations there; separate cold workers may compute the same public
benchmark, safely upserting the same key. Private portfolio/account/user inputs
never enter either cache. **Only the currently existing fixed A-RVol diagnostic
has been integrated; there is no invented general backtest API or new strategy.**

Tests are offline and mocked: API tests block socket connections and remove
real environment credentials; frontend tests mock auth, fetch and private data.
They cover unauthorized access, revision races/conflicts, holdings response-loss
idempotency, timestamp saves/deletes, default forwarding, safe validation errors,
cron authorization/failures, cache hits/data revision misses/fallback, and browser
login/private-page gating/draft preservation. No login, SQL changes, price downloads,
or real user backtests run as part of tests.

Implementation references: [Supabase PKCE](https://supabase.com/docs/guides/auth/sessions/pkce-flow),
[server user verification](https://supabase.com/docs/reference/python/auth-getuser),
[explicit grants and RLS](https://supabase.com/docs/guides/api/securing-your-api),
[Vercel cron deployment rules](https://vercel.com/docs/cron-jobs).

## Signals page migration

`/signals/` is now enabled in the shared navigation, behind the existing AuthGate.
`GET /api/signals?label=HAA-Simple` verifies the same Bearer token as `/api/me`.
Unknown catalogue labels and invalid `as_of` dates return 400. No workspace,
holdings, account or user-specific information enters shared signal caches.
No SQL, settings, dependencies, Streamlit or `src/haa` files change for this page.

Only the chosen model's assets and its existing benchmark are loaded. Signals
use the existing `download_yahoo_prices` (not opening bars), default ticker map,
strict adjusted-US requirement for XNYS models, TASE adapter, FRED loader and OECD
diffusion loader. FRED/OECD remain live and are not added to the cron cache.
Retrieval failures retain the app's empty macro/TASE frames and warning wording;
no alternate feed, CSV, proxy or filled observation is introduced. The existing
GGCEM failsafe remains the existing strategy's decision, not API replacement logic.

Chosen data-cache option: **complete live inputs plus results caching**. The
current Yahoo cache does not retain the general Signals loader's price-field
fallback provenance, and TASE snapshots lack same-refresh markers. Rather than
change producer/row schemas or mix sources, Signals uses the complete existing
live-loader path and says so visibly on every response. This deliberately does
not extend `market_cache.py`, change `cron.py`, or redesign cache tables.

Results use the existing `ResultCache` with model label, parameters, data version,
engine/adapter code hash, source metadata and `as_of` behaviour. Data version
hashes every exact input observation, including live macro values. Default-now
keys also include the UTC date and the daily model's completed-session cutoff,
so a result cannot survive a daily completion boundary. Historical revisions on
the same date invalidate cached values. Failed inputs, failed computations and
unavailable signals are not cached. Cache failures are visible; they never rerun
the calculation twice in a request or substitute an older signal.

`as_of=YYYY-MM-DD` is optional, for verification. It is passed to existing helpers
as a date at midnight, **not the end of that day**. Daily models therefore use the
prior completed session according to their existing cutoff. Omitting it uses the
actual current UTC timestamp. Inputs are truncated at the supplied date; the
shared monthly helper receives completed-month observations, preventing a partial
historical month from being treated as final merely because wall-clock time is
later. Strategies accepting `as_of` receive it directly. Other daily-input monthly
strategies receive the eligible completed-month frame for official decisions and
the existing `include_current_month=True` preview call. No strategy is monkeypatched.
This freezes observation eligibility, not historical provider vintages/revisions.

Every number comes from existing strategy `decisions`, `monthly_strategy_input`,
`latest_actionable_signal`, `month_to_date_snapshot`, `latest_preview_signal`,
`execution_assets` and `first_trading_day_after`. JavaScript only selects catalogue
entries and renders Python-provided values/text. The three dropdowns retain a
compatible variant/implementation as the Streamlit selector does. Default is
HAA-Simple. Optional workspace persistence of the selection is intentionally
skipped: a fresh visit resets to HAA-Simple; no private workspace writes occur.

Daily models show the exact experimental/risk/timing captions and daily decision
table; buy-and-hold models show continuous holding without timing instructions,
including the TA-125 special case. Monthly models show current allocation,
instruction, effective start, provisional preview, rationale inputs, history and
source/date metadata. Unavailable engine reasons are shown verbatim, not replaced
with an earlier allocation. The disclaimer is present in all modes, including
daily/unavailable screens (the old daily Streamlit early stop skips its footer).

### Deliberate verbatim presentation duplication

`server/signals_presentation.py` ports the existing Signals Rationale block:
all per-strategy branches, paragraph/f-string text, captions, table field names,
input expressions and Python display formats. `display_allocation` is copied
verbatim, still using `execution_security_label`. Only Streamlit collection and
Pandas Styler rendering become JSON table collection; there is no new computation
dependency. An AST parity test verifies all literal/f-string chunks and the exact
allocation function against unchanged `app.py`. The running Signals code never
reads, imports, evaluates or executes `app.py`.

`server/signals.py` also deliberately ports the current-allocation/action labels,
No-prior-allocation handling, preview warning/caption, daily captions/table labels,
continuous-holding/TA-125 text, source/provenance warnings, history column/weight
formatting, filenames, pandas CSV generation, completed-month caption and disclaimer.
These presentation copies can drift if Streamlit wording changes; update parity
tests/port deliberately. Existing generic rationale fall-through wording is
retained even where a newer strategy could merit a dedicated explanation; this
migration does not invent or correct methodology. Missing Rules entries stay missing.

History rows are displayed newest first; downloaded CSV uses the original
ascending dataframe and `to_csv()` bytes/filename, not a browser reconstruction.
Full daily history plus CSV initially measured 5,440,285 JSON bytes for 4,196 V3
decisions. Redundant identical display-row copies are now omitted (all raw rows
remain), and gzip transport covers Signals and Backtest for clients accepting gzip.
Other API responses are not compressed by this adapter. The initial full response
compressed to 804,688 bytes even before removing duplication. These are local
measurements, not proof of deployed gateway behaviour; very long histories and
non-gzip clients still warrant a cloud check. No history is truncated or paginated.

### Verification and observed local timings

All tests remain offline with mocks. New tests directly compare API selections,
regimes, exact numeric weights, dates, effective starts, preview values, all history
rows and CSV bytes to independent calls into the same engine for HAA-Simple,
Inflation Compass Standard, HAA-Simple Israel, original USD A-RVol and Buy and Hold
SPY. Further coverage includes local/US-to-TASE daily modes, TA-125 continuous
holding, strict adjusted inputs, FRED/OECD failures, unchanged unavailable reasons,
no future-observation influence, cache hits/revisions, authentication, selector
behaviour, three rendered modes, warnings, CSV download and gzip round-trip.

Separate from tests, public-data local cold-result-cache runs (October 18, 2026)
used the existing loaders, with Supabase credentials removed from that process:

| Model | Live input load | Calculation/cache handling | End-to-end local call |
| --- | ---: | ---: | ---: |
| HAA-Simple | 1.371 s | 0.381 s | 1.760 s |
| Inflation Compass Standard | 1.996 s | 1.554 s | 3.555 s |
| HAA-Simple Israel | 1.564 s | 0.206 s | 1.770 s |
| A-RVol Shifter V3 Cash-Only | 0.675 s | 1.241 s | 1.995 s |
| Buy and Hold SPY | 0.649 s | 0.280 s | 0.933 s |

All five returned an available signal. These measure cold **result caches**, in
a warm local Python process, before HTTP/gateway/browser rendering. They do not
measure a cold Vercel interpreter, Supabase cache writes, cloud provider access or
worst-case delays. No sampled calculation approached the unchanged 300-second
limit locally; live provider stalls/throttling and large response limits remain
cloud risks. Do not treat these numbers as guaranteed Vercel timings.

Full verification commands remain the Verify section above: API pytest, npm
typecheck, npm test, npm build, and original `PYTHONPATH=src python -m pytest tests -q`.
The required protected-file check is `git diff main -- app.py src requirements.txt pyproject.toml`.

### Manual side-by-side checklist (not claimed as already completed)

Open Streamlit Signals beside the signed-in preview `/signals/` on the same day,
without an `as_of` query parameter. For each row below choose the exact matching
Strategy / Variant / Implementation. Compare input source/date metadata first;
Streamlit's data cache can be older than the preview's live download. If data
differs, refresh/align the observations before attributing a discrepancy to math.
Never force results to match by changing inputs or a strategy rule.

| Model | Check |
| --- | --- |
| HAA-Simple | Signal date, regime, instruction, target allocation, effective start, provisional preview values/date, history row count and downloaded CSV |
| Inflation Compass Standard | Same checks; also lagged T5YIE dates/values and all rationale input fields |
| HAA-Simple Israel | Same checks; verify TASE identifiers/source dates and broker-facing allocation labels |
| A-RVol Shifter V3 Cash-Only | Decision date, scheduled next-open date, target, Hold/Switch heading, state/regime, RVol/VR/trend/credit, history row count/CSV; preview must be absent |
| Buy and Hold SPY | Completed signal date/regime in history, 100% SPY continuous allocation, no timing instruction or preview, history row count/CSV |

Also confirm provisional previews are never labelled official; stale/missing input
reasons remain visible; warnings match; the footer disclaimer appears in every
mode; and the browser downloads Python's CSV unchanged. This change performs no
Google login, database settings changes, production promotion or manual account saves.

## Backtest page migration — Step 4, single strategy

`/backtest/` is now enabled in navigation, alongside Rules, Portfolio and Signals.
Portfolio backtesting and Deep History / Proxy remain disabled, labelled Coming
soon. There is no blend engine, proxy selector, custom ticker, saved backtest or
new database configuration. Streamlit, strategy/data/engine code under `src/haa`,
and the original dependency manifests remain untouched.

### Controls and accounting

Three catalogue selectors expose only `backtest_available` entries. Date limits,
data validation and captions come from the same existing loaders and preprocessing
as Streamlit. US daily execution obtains adjusted opens and closes together from
the existing Yahoo bars loader; it never substitutes closes for missing opens.
TASE inputs retain their existing loader rules. Source/fallback warnings remain
visible. Reference replay appears only for the US-signals / TASE implementations.

Initial capital defaults to 100,000 in the implementation's currency. Daniel's
requested after-tax view is ON at 25%; fees default to 0%. Percentage fees are
converted to fractions before the existing engine call; fixed fees are passed
unchanged. Monthly contributions are optional. The actual submitted settings and
engine arguments remain visible with results, including percentage/fraction labels.

The fee audit found **no minimum commission** in
`haa.backtest_options.order_fee`, `haa.engine._simulate_weighted_execution`,
`haa.daily_engine.run_daily_backtest` or
`haa.tase_daily_engine.run_tase_daily_backtest`. These implement percentage and/or
fixed fees, not `max(percentage fee, 2 NIS)`. Holdings' `minimum_ils` is a minimum
order size, not a commission. Existing monthly/daily fee conventions are preserved;
no brokerage fee rule was added. Every result shows:
**Minimum fee of 2 NIS is not modelled by this backtest**.

Tax uses the existing per-asset average-cost sale ledger, carried-forward losses
and proportional basis on partial disposals. It is not FIFO, has no final sale of
unsold holdings, and is not a legally validated Israeli broker calculation. No
flat 25% deduction, FX/indexation rule or new tax treatment was introduced.

`server/backtest_presentation.py` ports Streamlit's performance metrics, audit
column selection, captions, annual returns and CSV naming/formatting. It calls the
existing metrics and tax engine rather than importing/executing `app.py`. Some
unchanged captions describe capabilities of Streamlit; the page explicitly says
only Single strategy is available here. These presentation copies must be checked
deliberately when Streamlit wording changes. New page-owned labels/help live in
`web/content/backtest.json`; no CMS or dependency was added.

### API, cache and display limits

- `GET /api/backtest/options?label=...`: compatible catalogue entries, source
  metadata, source-derived bounds, replay eligibility and defaults.
- `POST /api/backtest`: validated settings in the body, not financial amounts in
  URLs. Runs existing decisions and `run_backtest`; returns metrics, curves,
  audit/tax/return previews, warnings, settings, timing and download manifest.
- `GET /api/backtest/download?key=...&kind=...`: exact Python-produced audit,
  tax-event or daily-NAV CSV from the result cache, not a browser reconstruction.

All three use the existing verified-user Bearer authentication and private response
headers. No user holdings or amounts are logged. Timings only (input load, signal,
engine) are logged and displayed. Invalid requests and failed runs return errors,
not partial results, and failures are not cached. An in-flight guard prevents
duplicate clicks. Gateway/time-limit errors show the brief's exact five-minute
message; the function's existing 300-second setting is unchanged.

The existing bounded memory/Supabase `ResultCache` is reused. Keys include all
parameters, adjusted price **and open** observations, metadata/warnings, engine
code version, UTC date and daily completed cutoff. Cache hits retain the original
calculation timestamp/timing; the current request timing separately reports zero
signal/engine work on a hit. Live inputs are still checked before cache lookup.
No SQL, database settings or tables were changed. If the full cached bundle is
unavailable on a cold instance, downloads return an explicit 404 asking for a new
run; they do not silently recalculate different data.

The main JSON response is guarded below 3,000,000 bytes. Tables preview at most
150 rows and say so. Charts show at most 700 evenly spaced display observations,
including first/last, with a reduction notice. Metrics, maxima, returns and all
CSV downloads use **unreduced** engine frames. Native SVG charts add no package.
Full CSV strings stay in the authenticated cache/download route rather than the
main JSON. Very large histories may still challenge cache or download limits;
there is no asynchronous job queue or split download service in this step.

### Verification and measured local runs

Offline tests compare independent existing-engine calls for HAA-Simple, Inflation
Compass Standard, HAA-Simple Israel, A-RVol Shifter V3 Cash-Only and Buy and Hold
SPY, each with tax OFF/ON at 25% and contributions OFF/ON. Final pre-/after-tax
values, benchmark, CAGR and drawdown agree within 1e-9; complete tax-event CSVs
and daily NAV CSVs match exactly. Additional tests cover both US-signals / TASE
replay settings, adjusted opens in cache keys, fee conversion, bounds/errors,
failure non-caching, missing/bad-token 401s, downloads, UI defaults/validation,
timeout/no partial result, duplicate-click prevention and content-file wording.
Mocks are confined to tests; no production example data is returned.

Verification: original Python suite **467 passed**, API suite **95 passed**, web
suite **29 passed**; TypeScript typecheck and production build passed. Existing
Python suites emit timestamp-attrs and Starlette/httpx deprecation warnings. The
protected-file diff against main is empty.

Separate public-data measurements on October 18, 2026 used full available real
history, default capital, 0% fees, 25% tax and no contributions. Supabase credentials
were removed from that process. These are cold **result-cache** runs in a warm
local interpreter, not Vercel cold starts, browser timings or remote-cache writes.

| Model | Input load | Signal | Engine | Local total | Main JSON bytes |
| --- | ---: | ---: | ---: | ---: | ---: |
| HAA-Simple | 1.256 s | 0.019 s | 0.111 s | 1.650 s | 140,007 |
| Inflation Compass Standard | 1.940 s | 0.113 s | 0.184 s | 3.004 s | 258,770 |
| HAA-Simple Israel | 1.537 s | 0.009 s | 0.016 s | 1.747 s | 35,763 |
| A-RVol Shifter V3 Cash-Only | 0.765 s | 0.234 s | 0.666 s | 2.886 s | 175,481 |
| Buy and Hold SPY | 0.826 s | 0.005 s | 0.202 s | 1.147 s | 119,845 |

Cumulative peak process memory was 234.17 MiB. A-RVol retained 4,195 daily result
rows; its display chart used 700 points and its separate full daily CSV measured
1,899,589 bytes. The largest main response was 258,770 bytes before gzip. These
measurements are representative rather than cloud guarantees: provider stalls,
cloud quotas, deployment protection and Supabase cache capacity remain unverified
in this local benchmark. No run approached five minutes locally.

### Backtest side-by-side manual checklist (not yet claimed complete)

For each of the five models above, open Streamlit and signed-in preview
`/backtest/` together. Select identical Strategy / Variant / Implementation,
currency, available start/end dates, initial value, fee type/value, tax ON 25%,
and contributions OFF; repeat with tax OFF and monthly contributions ON. Check
source observations and date bounds first (Streamlit may have older cached prices).
Compare final pre-/after-tax and benchmark values, CAGR, max fall, report row count,
first/last dates, complete tax-ledger count/last row/CSV, audit CSV, captions and
warnings. Include one full-history A-RVol run and a contribution-enabled run.
Confirm display reduction is labelled, downloads remain full, changing inputs
clears the old result, Run disables while running, and timeout yields no partial
report. Do not adjust methodology to force a match when source data differ.

No production promotion, manual account writes, database changes or merge are
part of this step. Frontend tests/build and engine parity checks do not substitute
for this signed-in cloud/browser comparison.

## Rebalance Holdings migration — Step 5

### Approved Step 0 and protected-file evidence

Main was fetched at `2dd0f9b75c0cd540fdf0910066453c5c67257fc0`. Its only
post-fork feature changes were the five files Daniel approved:

- `src/haa/rebalance_holdings.py`
- `src/haa/rebalance_page.py`
- `tests/test_rebalance_holdings.py`
- `tests/test_rebalance_ui.py`
- `docs/rebalance-holdings.md`

Only those files were restored from main, with no merge. Immediately afterward
`git diff main --` followed by those five paths was empty, and the original suite
passed **477 tests**, including the outside-rebalance tests. Those five files stay
byte-identical to main. The final protected check
`git diff main -- app.py src requirements.txt pyproject.toml` is also empty.
No other main file was brought over. No database/SQL/RLS/RPC, strategy, allocator,
price-rule, fee, tax, Streamlit hosting or domain change is part of this step.

### Page, orchestration and save path

`/rebalance-holdings/` is the fifth enabled page, behind the unchanged AuthGate.
It starts with New money and What to buy, followed by the always-open shared
holdings editor, the two labelled account totals, target/actual comparison, buy
list, conditional recording form, collapsed price/FX/sync details and collapsed
portfolio/signal dates. All new page-owned words are in
`web/content/rebalance.json`; no dependency or CMS was added.

The browser keeps drafts by security ID. Adding, marking for removal, editing
units/value/manual prices, changing Outside the rebalance, cash or FX never
autosaves an older snapshot. The last edited units/value cell supplies the entry
mode to the server; JavaScript performs no currency, unit, shortfall, target or
allocation calculation. Explicit preview and field blur request the server's
conversion preview. Displayed units/values have two decimals, while unchanged
stored US fractional-unit strings retain their full precision. Dates start blank,
not today. Quotes remain distinct from stored manual overrides.

`server/rebalance.py` calls the original `validate_account`, `security`,
`combined_targets`, `rebalance_targets`, `compare_holdings`, `make_buy_plan` and
`apply_purchases`. `server/rebalance_editor.py` mechanically copies the original
`_quote_cells` and `_preview_positions` bodies, changing only their import context;
an AST test verifies identical bodies. No allocator or financial conversion is
reimplemented. Presentation formatting and unchanged-cell precision preservation
are separate from allocation. Record preparation revalidates the full proposed
plan against freshly loaded holdings/targets/quote context before applying the
existing purchase function. It never saves or calls a broker.

All actual writes still use **PUT /api/workspace** and the existing
`save_holdings_workspace` helper. That route additionally checks holdings revision
increments exactly once, and rejects unsupported stored fields such as fetched
prices or pending plans. A fresh operation ID accompanies a changed notebook;
identical no-op accounts return the original saved record without a revision
increment. Manually entered dated prices/FX remain supported notebook fields.
An identical retry is acknowledged without a second mutation. The original
helper still reads back after an uncertain server response.

The browser makes one PUT only; if its response is uncertain, it reads back and
compares the **entire candidate account**, not just the operation ID. Confirmed
success alone shows Holdings saved. Conflicts and uncertainty preserve the draft
and pause further writes until explicit Reload, including when read-back confirms
an uncertain response. No prices, pending plans, confirmation drafts or tokens are
persisted by this page. No actual user account was read or written during tests
or the public-data benchmark.

### Endpoints, quotes and caches

All six routes verify the existing user Bearer token and return private no-store
headers. None accepts a caller-supplied user ID or uses the service-role key:

- `GET /api/rebalance?portfolio_id=...`: saved account, source-derived targets,
  quotes/FX, editor rows, totals, comparison and readiness.
- `POST /api/rebalance/refresh`: clears only this page's three quote/FX/target
  caches and returns a new snapshot; it does not save or poll.
- `POST /api/rebalance/security`: validates a custom actual security for staging.
- `POST /api/rebalance/editor`: validates and previews rows, preparing a candidate
  account; **no write**.
- `POST /api/rebalance/plan`: runs the original buy-only whole-unit allocator;
  **no write**.
- `POST /api/rebalance/record`: revalidates and applies actual confirmed units
  and spend to prepare a candidate account; **no write**. The browser then uses
  the single workspace PUT above.

`server/rebalance_quotes.py` mechanically ports the entire original market module,
replacing only Streamlit imports/decorators with a bounded 300-second deep-copy
memory cache (`server/rebalance_ttl.py`). Function-body AST checks plus behavioral
parity tests compare it with the original. API production imports no Streamlit.
All provider dependencies already existed in `api/requirements.txt`.

Unadjusted Yahoo Close with verified currency, listed-TASE agorot/100, the exact
three-fund MAYA identity/ISIN/type/currency allowlist, unverified raw-publication
path, completed-session XNYS/XTAE freshness, manual precedence and dated indicative
FX are unchanged. No price proxy, filling, publication-lag exception or guessed
divisor was introduced. Held included funds with stale/missing prices block
sizing; unpriced zero-unit targets may be skipped without redistributing weights.
Outside holdings use the original main exclusion/rescaling logic. Their missing
prices/FX can make the full total unavailable without blocking included holdings.
Costs still exclude automatically modelled commissions/spreads; actual paid ILS
can include fees charged to the budget when recording completed trades.

Signals use the ported original `load_portfolio_signals` and original shared
`portfolio_signal`, not provisional previews. Workspace `ticker_text` is parsed
when present, with source-setting errors blocking targets rather than silently
using defaults. If absent, defaults and the absence of uploaded replacements are
explicitly disclosed. Uploaded replacement series are not in GET /api/workspace
and cannot be recovered here; they are never guessed or silently recreated.

### Deliberate web differences and verification limits

There is no Streamlit five-second fragment or auto-polling. Requests occur on load,
field blur/explicit preview, explicit Refresh and user actions. Pending plans live
only in browser memory, not Streamlit session state or a database. Record checks
rebuild the original plan and compare its complete inputs/orders before applying
it. A quote refreshed on another Vercel worker, cache expiry, a completed session
or target change may invalidate an old plan; regenerate rather than accepting an
unverifiable price snapshot. There is no new queue or server-side private plan
store. Raw private-service/gateway failures are masked; draft and sync-paused
messages remain visible. Provider data/status remains available in price details.

The original Python suite passed 477 tests after Step 0. API tests compare exact
allocator outputs for empty/underweight/small-budget/minimum/decimal/USD/outside/
partial cases, stale held/FX blocking, whole-unit rejection, default-off behavior,
all-targets-outside behavior, exact recording, idempotency, duplicate/overspend/
stale/forged-plan rejection, server save CAS/revision/operation-ID checks and lost
responses. Quote tests compare original and ported functions for allowlist pass
and fail-closed cases, raw closes, dates/calendars, FX and manual precedence,
unverified funds and actionable targets with a frozen fixture clock. Cache tests
cover expiry and copy isolation. Web tests cover auth gating, staged draft edits,
last-edited-cell behavior, manual dates, conflicts, uncertain saves/read-back,
record acknowledgement/cancel, no-op preparation and content-file wording.
All automated tests use fake holdings and offline mocks, never production mocks.
Final suites: **477 original Python**, **171 API** and **43 web** tests passed;
TypeScript typecheck and production build passed. Existing timestamp-attrs and
Starlette/httpx warnings remain. No test connects to real account storage.

Separate public-data timing on October 19, 2026 used real SPY and TASE gold
1147875 signals/quotes plus real indicative FX, a synthetic empty notebook and no
Supabase environment credentials. Targets took **2.154 s**, quotes/FX **1.147 s**,
and plan sizing **0.000426 s**, for **3.301 s local total**. Both quotes were fresh
with actual observation date October 16, and FX was fresh. No amounts or real
holdings were printed, no prices invented and nothing saved. This is not a Vercel
cold-start, live MAYA verification, signed-in UI run or account-write benchmark.

Cloud deployment, actual Google sign-in, cross-device writes, live provider access
from Vercel and the following side-by-side checklist remain unverified here.

### Daniel's manual side-by-side checklist — do not record test buys

1. On the same day, open Streamlit beside the signed-in preview, selecting the
   same saved portfolio and source settings.
2. Compare rebalance and full account values; every fund's target %, actual % and
   status; each buy-list fund's whole units and estimated cost, and leftover cash.
   Repeat with new money zero and with a real planned deposit.
3. Mark CSPX Outside the rebalance in both apps. Confirm it stays visible but is
   excluded, remaining targets rescale and buy lists match.
4. Confirm a held fund without an automatic price blocks sizing until a correctly
   dated manual native per-unit price is entered, then compare again.
5. Open Record these buys and compare its rows to the buy list, then **Cancel**.
   Never record fictitious trades against real holdings.
6. Save an unchanged holdings set; confirm no error or unexpected revision bump.
   Edit then revert a value and check the save round-trip. Any uncertainty pauses
   saving: keep the draft, inspect sync details and explicitly reload.

## Today page migration — Step 6

### Read-only route and payload

`/today/` is enabled first in the existing navigation, behind the unchanged
AuthGate. The existing home page and all other page routes are unchanged.
**GET /api/today** uses the existing verified Bearer token and the same user-scoped
portfolio-list helper as GET /api/portfolios. It selects `is_default` server-side;
there is no caller user ID, model selector, portfolio ID or `as_of` parameter.
Query parameters are rejected. Missing/bad tokens return 401, POST returns 405,
and the route has private no-store response headers. No user workspace, holdings,
portfolio, SQL, settings, policy or RPC writes are made. The only permitted writes
are public result-cache entries through the already-existing ResultCache.

The response has `has_default`, the private portfolio `caption`, validation
`issues`, formatted `signals`, currency-separated `holdings`, a `monthly_action`
state, `latest_caption`/`stale`, provisional `previews`/`preview_caption`, visible
`warnings`, public per-model details in `public_sleeves`, and per-sleeve/request
`timing`. No default is a normal 200 setup state. Missing or malformed payload
fields, empty/invalid sleeves, unknown labels, invalid weights and missing capital
or saved FX produce unavailable affected sections, not substituted values or 500s.
Multiple defaults also produce an explicit unavailable selection rather than an
arbitrary choice. Provider/private-service failures remain errors, never a fake
empty portfolio. No amounts or portfolio details are logged.

The page fetches only on mount or explicit Refresh, guards concurrent refreshes,
and renders server-provided text/numbers. It has no save, edit, delete, allocation
math, date math, automatic polling or order action. New page-owned words are in
`web/content/today.json`; original captions/warnings are preserved verbatim.
It shows the sleeve table before combined holdings, following the brief's numbered
order. The existing Streamlit code actually places that table below Monthly action;
this is a presentation-only ordering difference, not a calculation change.

### Reused signal, preview, aggregation and saved-FX logic

`server/today.py` loads each model sequentially through
`server.signals.load_inputs`, truncates observations at the request's UTC clock,
and calls the unchanged `haa.portfolio_signals.portfolio_signal` directly. It
reuses `decision_record`, the shared presentation `display_allocation`, live-loader
metadata, degraded-failure warnings and the exact Signals `LIVE_NOTICE`. There is
no second data loader or signal implementation, no inferred price/proxy history
and no new dependency. As specified, these are the migrated Signals page's default
live sources; Streamlit-only workspace ticker overrides and uploaded replacement
series are not ported here. Compare with matching source settings.

The `next_portfolio_preview` helper is copied **verbatim** into a request-local
nested function in `preview_for`: its frame is closure-local, not mutable global
state shared by users. An AST test proves the entire original helper is identical.
Production never imports, reads or executes app.py. Buy-and-hold and daily sleeves
retain their distinct no-preview messages. Other previews use the original
month-to-date snapshot, daily-input `include_current_month=True` path, preview
status helper and unavailable reasons. A preview calculation failure leaves an
otherwise valid current signal visible, but the partial result is never cached.

Private composition is fresh on every request. It calls the original
`total_weight`, `aggregate_holdings_by_currency`, `execution_security_label` and
`convert_currency`; the amount expression is copied from Today. The exact
`abs(saved_total_weight - 100.0) < 1e-9` gate, trade-flag action precedence, newest
completed signal date, strictly-more-than-45-day warning, exact dictionary weight
comparison for Yes/No, and existing Python percent/thousands/two-decimal formats
are retained. Only the portfolio's **saved** `ils_per_usd` converts the amounts;
no live FX or invented fallback capital/rate is substituted. UTC dates are used
for the cache and stale boundary; no browser-local date calculation is introduced.

### Public-only cache and performance limits

The public function accepts only catalogue label, engine/adapter code hash and
clock. `cached_sleeve` accepts only public model definition and observed input
frames/metadata/warnings. ResultCache keys use:

`model + exact observed-row data_version + observation range + engine/adapter
code hash + UTC date + daily completed-session cutoff + source-metadata digest
+ presentation="today-v1"`.

Cached values contain only that strategy's public current decision/target weights,
preview, metadata/ranges and source warnings. Portfolio name, ID, membership list,
sleeve percentages, capital, saved FX and user/session data never enter the key or
cached value. Tests spy on cache arguments and inspect stored warm values using
distinct fake private markers/amounts. Private composition is never supplied to
ResultCache. The source/engine code hash includes the new server adapter.

Input retrieval failures, unavailable current signals, unavailable monthly
previews and computation failures are not cached. Continuous/daily no-preview
messages are expected states and may be cached with their valid current signal.
Cache failures degrade visibly and do not recompute twice. Public cache operations
are the only writes; no new schema/table or cron change is needed. The existing
300-second function duration is unchanged.

**A repeated visit is not guaranteed near-instant.** Every request still reloads
the public observations to detect revisions. A changed intraday or historical
price invalidates its key, as required; do not round away revisions or quietly
serve an older preview to manufacture hits. Even real cache hits include network
reload, hashing and JSON-copy cost. No input TTL cache, batching, extra workers or
background job was added. Any further latency redesign needs a separate decision.

### Tests and local timings

All tests are offline with synthetic prices/portfolios and mocked services.
Current signals for HAA-Simple, Orthogonal Alpha (multi-asset), Inflation Compass
Standard (daily inputs), Buy and Hold SPY, USD A-RVol daily and HAA-Simple Israel
match independent `portfolio_signal` calls on the original-style combined frame:
exact weights, full decision fields, dates, regimes and trade flags. Preview tests
compare the original isolated helper and direct engine path, including unavailable
reasons. Further checks cover mixed currencies/saved FX, exact weight tolerance,
Yes/No/em-dash, 45/46-day boundary, malformed saved data, no default, auth/no-store,
read-only routes, revisions/future data/cutoff keys, public-only cache contents,
failure non-caching, one computation after cache failure, content-file rendering,
collapsed preview and explicit Refresh. No real portfolio/account was accessed.

Verification: original suite **477 passed**, API suite **219 passed**, web suite
**50 passed**; TypeScript typecheck and production build passed. Existing
timestamp-attrs and Starlette/httpx warnings remain. Temporary missing test runtime
packages were restored without changing repository dependency files. The final
protected diff `git diff main -- app.py src requirements.txt pyproject.toml` is empty.

Separate public-feed measurements on October 19, 2026 used a hypothetical equal-
weight five-sleeve portfolio, no real saved records, no Supabase credentials and
no mocked provider. In a warm local Python process, complete live requests were:

| Model | First live load+calculation | Repeat live request |
| --- | ---: | ---: |
| Century Momentum | 1.510 s | 1.002 s |
| Inflation Compass Standard | 3.354 s | 2.972 s |
| Buy and Hold Gold GLD | 0.578 s | 0.598 s |
| Buy and Hold IEF | 0.661 s | 0.642 s |
| A-RVol Shifter V3 Cash-Only | 1.607 s | 1.316 s |
| **Whole composition** | **7.720 s** | **6.537 s** |

All current signals were available. Exact data-version hashes changed for **all
five** on the repeat, so these were legitimate cache misses, not a warm-hit speed
claim. A further prior-completed-observation cutoff run still saw provider revisions
in four models (one true hit); it is not used as a stable-data performance claim.

To measure genuine hits, the same production `cached_sleeve` helper was then called
twice on identical, real downloaded public frames retained in memory. No loader
was replaced or mocked. Those five real loads initially totalled **5.440 s**.
The following numbers measure **only the cache/calculation phase**, not another
full API request, network reload or private composition:

| Model | Cold result cache | Warm result cache |
| --- | ---: | ---: |
| Century Momentum | 0.344 s | 0.059 s |
| Inflation Compass Standard | 1.211 s | 0.244 s |
| Buy and Hold Gold GLD | 0.081 s | 0.014 s |
| Buy and Hold IEF | 0.065 s | 0.015 s |
| A-RVol Shifter V3 Cash-Only | 0.891 s | 0.158 s |
| **Total cache phase** | **2.591 s** | **0.490 s** |

All five second calls were genuine memory hits. These are local warm-interpreter
measurements, not Vercel cold-start, remote Supabase-cache latency or guaranteed
visit times. Cloud deployment, real Google sign-in, provider behaviour on Vercel
and the user side-by-side checklist below remain unverified.

### Daniel's manual Today checklist — no edits or test trades needed

1. On the same day, open Streamlit Today beside signed-in preview `/today/`, using
   the same saved default portfolio and matching data-source settings.
2. Compare every sleeve's weight, current holding and status, then each holding's
   portfolio weight and amount in each separate currency.
3. Compare Monthly action and Latest completed signal. If one shows the stale
   warning, both should for the same observations/date.
4. Expand both previews and compare projected allocation, Yes/No/em-dash, price
   date and every unavailable reason; previews must remain non-instructions.
5. Press Refresh once. With unchanged observations, figures should match; changed
   public observations legitimately invalidate cache entries.
6. If no default already exists, both should show the setup message. Do not clear
   a real default just to test this. Confirm Today offers no save/edit/order action.

## Backtest completion — Step 7 (Portfolio / Deep History)

### Scope and paths

Both modes are enabled on `/backtest/`. They extend the existing single-strategy
POST, result renderer, chart/table sampling, download manifest, compression and
ResultCache; no second financial engine or database path was introduced.
`server/backtest_multi.py` supplies validation/input orchestration;
`server/backtest_multi_presentation.py` ports the old result expressions and
formatting. All new component wording is in `web/content/backtest-multi.json`.
Tests check the main static captions/warnings against literal app.py text and
compare calculations/curves/audit/exports directly with the original engines.

- `GET /api/backtest/config?mode=portfolio|deep`: catalogue selectors, proxy
  options (single/blend), benchmark labels/caveats and the original DCA caption.
  No prices or backtests are loaded by this request.
- `POST /api/backtest/validate`: the proposed multi-mode request, validated
  without data retrieval or engine execution; returns `{valid, message}` or a
  safe 400. This is how the browser knows weights satisfy the exact original
  percentage tolerance; JavaScript does not calculate portfolio weights.
- `POST /api/backtest/load`: `{mode, portfolio_id}` or `{mode, payload}`.
  The former uses only the verified user's existing GET-portfolios helper;
  the latter validates a device JSON file (100,000-byte limit). Both use the
  unchanged portfolio_config helpers and return `{sleeves, initial, warnings}`.
  Saved capital is converted with **saved** FX, unavailable strategies are
  flagged, and incompatible proxy variants are rejected. Neither writes data.
- Existing `POST /api/backtest` accepts the original single request unchanged,
  or `{mode, sleeves:[{id, model, weight}], initial, start?, end?, fee_type,
  fee_value, tax_enabled, tax_rate, monthly_contribution, benchmark,
  sleeve_rebalance_mode, rebalance_sleeve?, rebalance_cap, rebalance_target}`.
  Weights/cap/target/tax-rate/percentage-fee inputs are percentages. Python
  converts them exactly as Streamlit does before calling the same engines.
- Existing `GET /api/backtest/download?key=...&kind=...` serves Python-generated
  CSVs from that result bundle. Source actual/early CSVs preserve bundled bytes.
  Missing cold-worker bundles return an explicit rerun-required 404, never a
  different recalculation. File names and source download labels match app.py.

All these routes use the existing verified-user dependency and private no-store
headers. No caller user ID is accepted, no saved-record mutations are made, and
the service key stays limited to the existing shared cache. The local root/
Streamlit dependency files and app.py/src remain unchanged. Main was checked at
`2dd0f9b75c0cd540fdf0910066453c5c67257fc0`; no additional main files were copied.
Vercel packaging now explicitly includes `data/deep_history/**` and
`web/content/**`, since these are runtime source data, not browser build assets.
The 300-second duration, cron, domains and database configuration are unchanged.

### Engine, fee, currency and presentation behaviour

Portfolio inputs use one union load through the existing Signals loaders,
including adjusted opens for mixed USD execution and the original shared
benchmark choice. Original decisions, monthly preprocessing, ModelInput and
run_portfolio_backtest are reused. Input order is retained for execution/ledger
parity; form-only row IDs are canonicalized without changing cap selection.
Mixed execution rejects incompatible currencies/calendars; no extra FX conversion
is inferred. Saved loading deliberately preserves the old helper's ILS-to-USD
conversion, rather than changing how that helper treats local implementations.

Deep History uses the unchanged specs, deep_history_model_input,
monthly_blend_input, load_deep_history, run_backtest and run_portfolio_backtest.
Per-strategy caveats, proxy warnings, benchmark help, unavailable-tax behaviour,
unsupported-extra-fee information, monthly/daily distinctions, rolling returns
and source exports are retained. Synthetic daily NAV has no invented daily
benchmark; monthly comparison and its separate daily drawdown remain separate.
The actual-fund provenance caption/table/CSV are retained for Portfolio mode.

**No minimum commission exists** in the Portfolio/mixed/proxy fee paths audited
here. Percentage and fixed order fees are unchanged; daily proxy extra fees
remain unsupported/not applied. Every result still displays:
`Minimum fee of 2 NIS is not modelled by this backtest`.
The engine's existing prohibition on sleeve transfers with monthly contributions
is shown before Run; it was not removed or worked around. Average-cost sale
ledgers, losses, no terminal liquidation and proxy tax approximations are unchanged.

Deliberate web differences: explicit Run only (including expensive preliminary
range discovery), no Streamlit rerun/auto-run, native SVG charts and collapsed
details rather than Streamlit tabs. Blank dates mean full common history; Python
confirms bounds on Run and rejects out-of-range dates. Display tables/curves use
the existing labelled preview limits, while metrics/exports use full engine rows.
Switching between modes starts a fresh multi-mode form rather than persisting
Streamlit session drafts. No workspace setting is written. Device portfolio JSON
loading **is ported**. Advanced Yahoo ticker overrides/replacement-price CSV uploads
remain unported, consistent with Step 4; the visible loader/source metadata never
claims those Streamlit-only overrides were recovered. No saved backtest feature
or brokerage fee rule was added.

### Cache shape and privacy evidence

Existing ResultCache SHA-256 envelope: `{model, params, start, end, data_version}`.
Params include sorted `{model, weight}` sleeves, the actual public execution order
(sale/loss ordering must not be assumed commutative), numeric run settings,
benchmark/transfer options, code hash, content hash, UTC date, each applicable
completed-session cutoff and source-metadata digest. Tags are
`backtest-portfolio-v1` and `backtest-deep-history-v1`.
Portfolio versions hash all exact close/open/macro observations. Proxy versions
hash the bundled files, including synthetic tax inputs. Same-date revisions,
settings, code/content changes and completion boundaries invalidate results.

No user/session identity, portfolio name/ID, original private row IDs, saved FX
field or saved portfolio payload enters keys or cached bundles. Numeric initial
capital explicitly submitted as a run setting is included, as in Step 4. An
offline test loads fake private markers through the real conversion helper,
spies on cache arguments and inspects stored bundles to prove the markers are
absent. Successful explicit results alone are cached; engine, invalid-bound and
oversized-response failures are not. Main JSON remains under the existing
3,000,000-byte guard; complete downloads are separate. No private values are logged.

### Today layout and deliberately missing follow-ups

Only the sleeve signal table gets `.today-sleeve-table`: fixed layout and normal
wrapping (including long tokens). Other table CSS/data/wording is unchanged.

Compared with app.py:

- **Yes:** `Next month portfolio preview (provisional)` expander exists.
- **No:** `Plain buy-and-hold assets: actual available fund history only...`
  caption is not on the new Today page. Follow-up: original static caption plus
  `haa.tase_data.plain_holding_provenance` for classification warnings.
- **No:** `Plain buy-and-hold history sources` expander and CSV are not on the new
  Today page. Follow-up: the same provenance function and Python `to_csv()` as
  the old page. Neither missing item was added to Today in this task.

### Verification and local timing

Offline suites: **477 original Python**, **272 API**, **69 web** tests passed;
TypeScript typecheck and production build passed. Existing timestamp-attrs and
Starlette/httpx warnings remain. Tests cover monthly two/three-sleeve portfolios,
A-RVol mixes and every transfer rule, percentage/fixed fees and contributions,
representative proxies, a synthetic blend, both benchmarks, exact source CSV
bytes, validation, auth/no-store, saved FX/no writes, cache revisions/privacy/
non-caching failures, controls and scoped Today CSS. Protected check:
`git diff main -- app.py src requirements.txt pyproject.toml` is empty.

Separate October 20 public-data measurements used hypothetical default capital,
zero fees, tax ON 25%, no contributions and no Supabase credentials/private reads.
Portfolio: Century Momentum 50 / Inflation Compass Standard 40 / USD A-RVol 10.
Deep History: Century Momentum 60 / GLD 20 / IEF 20, S&P proxy benchmark.

| Local call | Cold | Repeat | Repeat cache result |
| --- | ---: | ---: | --- |
| Portfolio, full input load + report | 8.259 s | 6.152 s | Miss: exact observed data changed |
| Deep History, full input load + report | 0.981 s | 0.193 s | Genuine memory hit |
| Portfolio cache/calculation phase on identical real frames | 2.319 s | 0.002642 s | Genuine memory hit |

The last row retains actual downloaded frames and profiles the real ResultCache
and report closure without mocking providers; it **excludes** another input load.
Do not describe 0.002642 s as a complete fresh portfolio request. Portfolio had
2,569 reporting rows and about 272 KB main JSON; proxy blend 333 rows and about
341 KB. `input_and_signal_seconds` intentionally combines retrieval, preprocessing,
decisions and version hashing; engine time is separately reported. These are warm
local interpreters/cold result caches, not Vercel cold starts or latency guarantees.

Not verified by these tests/measurements: cloud runtime/provider availability for
the new modes, real sign-in/saved-portfolio loading on Vercel, remote cache
persistence/download restoration, phone/laptop visual fit, or Daniel's side-by-side
comparison below. A Git build status, if checked, does not prove these workflows.

### Daniel's manual side-by-side checklist — not claimed complete

1. Same day: old Portfolio Backtest beside new `/backtest/` Portfolio. Match
   two/three sleeves, weights, dates, capital, fees, tax and transfer rule. Compare
   CAGR, total return, maximum drawdown, volatility, Sharpe, final value and warnings.
2. Load the same saved portfolio in both. Compare sleeves, weights and saved-FX
   converted capital. Loading must not change the saved record or default.
3. Repeat in Deep History with one proxy and one blend, matching benchmark and
   settings. Compare metrics, caveats, actual/early source CSVs and other exports.
4. Open Today on laptop and phone: Status should fit without sideways scrolling.
5. Confirm that no Backtest mode saves, edits or deletes a portfolio. Do not
   record fictitious trades or change your real portfolio for a test.

## Research migration - Step 8

### Scope and paths

Research is enabled at `/research/`; Compare was subsequently enabled in Step 9. No existing
Streamlit, strategy, portfolio, Today, fee, deployment-setting or database-setting
behaviour is changed. There are no new dependencies.

- `server/research.py`: catalogue gates, existing input loading/preprocessing,
  original validation invocation, bounded public result cache and CSV retrieval.
- `server/research_presentation.py`: original report tables, verdicts, evidence,
  Python CSVs and bounded native-SVG chart geometry.
- `web/content/research.json`: all page-owned wording, including verbatim old
  captions, explainers and interpretations (source-literal tests enforce this).
- `web/app/research/page.tsx`, `web/lib/researchApi.ts`: selectors, explicit Run,
  progress/error handling, results and authenticated downloads.
- `api/index.py`, `server/signals_wire.py`: authenticated routes and the existing
  compression convention. `web/components/top-navigation.tsx` enables Research.
- `api/tests/test_research.py`, `web/tests/research.test.tsx`: offline coverage;
  `api/tests/test_rules.py` updates the enabled-navigation assertion.

`GET /api/research/options?label=...` returns catalogue entries (including gates),
profile, public sources, derived full-history bounds and default capital. It
loads public inputs and production decisions to derive metadata, but never runs
validation or returns prices. `POST /api/research` accepts only `{label, initial}`
(default 100,000, minimum 1 in the implementation currency). It returns the gate,
profile/history, cards/evidence, bounded report tables/charts, CSV manifest,
warnings, cache information and separate input/validation timings.
`GET /api/research/download?key=...&kind=...` serves the cached Python CSV; a cold
worker without the bundle returns an explicit rerun-required 404, never reruns.

### Engine, behaviour and deliberate differences

Gates preserve their original order: missing profile and its class-declared
reason first; unavailable executable history second. Research uses the existing
Step 4 loaders and preprocessing, augmenting assets only with every declared
research proxy. Production decisions, monthly execution prices, daily prices
and monthly/daily proxy series go unchanged into the original `ValidationInput`.
Each cache miss calls `haa.validation.run_deterministic_validation` exactly once.
All scenarios, rolling windows, eras, quality checks, fixed-seed bootstrap and
grades are calculated by that unchanged engine, not financial JavaScript.

Deliberate presentation differences:

- Explicit Run only; no automatic validation when selecting a model or editing
  capital. An in-flight guard prevents duplicate requests.
- Six initially collapsed sections instead of Streamlit tabs; explainers remain
  collapsed. Charts are native SVG, with Python-derived geometry and statistics.
- The history caption always uses the full validation-input monthly frame. It
  cannot inherit dates left over from Backtest in the Streamlit session.
- Initial capital is the only numerical setting. No date, fee or tax controls.
- Custom Yahoo ticker overrides and replacement-price CSV uploads are unported.
- Changing the model or capital clears the old result. Timeout/gateway errors
  show the existing exact five-minute message and no partial report.

Two source/brief discrepancies were preserved rather than changing strategies:

1. Original USD BAA-G4 Aggressive declares **zero** proxy substitutions. The
   Israel version declares **three**, but its inherited applicable-test set does
   **not** enable `proxy_substitution`. Consequently the existing engine emits
   no BAA proxy-scenario rows. Tests cover both versions, verify all three
   declared proxy assets load, and preserve the actual engine output unchanged.
2. Every currently shipped researchable profile declares bootstrap. The
   no-bootstrap presentation branch is covered with a test-only immutable
   profile replacement; no production profile was changed or invented.

### Cache, privacy and limits

Every route uses the existing verified-user Bearer dependency and private
no-store headers. Missing/bad tokens return 401, wrong methods 405, unknown
labels/invalid inputs 400. No caller user ID, saved-record reads/writes, private
portfolio data, SQL/settings writes or order actions. Application timing logs
contain seconds only, never capital or holdings.

The bounded ResultCache uses a public-only envelope: model label, complete
profile contract/id, engine/server code hash, content hash, exact observations
of every loaded series including proxies, source metadata, full-history bounds,
UTC date, completed-session cutoff, initial capital and `research-v1`. Live
inputs are checked before cache lookup. A genuine hit performs zero validation
work for that request. Exceptions and oversized responses are not cached;
engine-reported unavailable scenarios remain valid evidence inside a completed
report, not swallowed request failures. Fake-private-marker tests check keys
and bundles; tests also fail if saved-record operations are attempted.

Tables preview at most 150 rows with a visible truncation notice. Chart samples
are bounded and labelled; box statistics are calculated from the complete
source rows. Main JSON has the existing 3,000,000-byte guard and an earlier
pre-cache size check. Full downloads use Python `to_csv(index=False)` and the
original strategy-based filenames, never browser reconstruction. The Monte
Carlo CSV is offered only when bootstrap results exist, as in Streamlit.

### Verification and measured local timing

Offline suites: **477 original Python**, **296 API**, **77 web** tests passed;
TypeScript typecheck and production build passed. Existing timestamp-attrs and
Starlette/httpx warnings remain. Tests cover original-engine parity for HAA,
Inflation Compass Standard and both BAA implementations, all report frames and
CSV bytes, gates, grade/evidence fallbacks, fixed-seed determinism, capital
scaling, cache invalidation/hits/privacy/failure handling, auth/routes, explicit
Run, duplicate guards, timeout, six collapsed sections and literal source text.
Protected check `git diff main -- app.py src requirements.txt pyproject.toml`
is empty; original validation tests are unchanged.

October 20 measurements used real public data, no Supabase credentials/private
reads, default hypothetical capital, warm interpreters and cold result caches:

| Model | Input load / preparation | Validation | Total cold result | Retained-frame hit | Main JSON bytes | Peak process MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HAA-Simple | 1.842545 s | 3.991432 s | 5.854996 s | 0.001690 s | 140,058 | 165.91 |
| Inflation Compass Standard | 2.895086 s | 8.182806 s | 11.101901 s | 0.001916 s | 153,208 | 188.58 |
| BAA-G4 (Aggressive) | 2.354035 s | 4.290544 s | 6.666002 s | 0.001730 s | 136,191 | 182.69 |

Input time includes public retrieval, preprocessing, production decisions and
version hashing. Each retained-frame repeat uses the same production cache path
on identical actually downloaded frames, with no mocks and zero validation work;
it **excludes another input load**, so it is not a complete fresh HTTP request.
Peak memory is process high-water RSS, not incremental engine allocation. These
are local warm-interpreter figures, not Vercel cold-start, remote-cache or
provider-latency guarantees. No run approached 300 seconds; the function setting
is unchanged.

Not verified: new Research cloud runtime/provider availability, signed-in browser
workflow, remote cache download restoration, phone/laptop visual fit, or Daniel's
side-by-side comparison. A successful Git/Vercel build alone does not prove them.

### Daniel's manual side-by-side checklist — not yet completed

1. Same day: Streamlit Research beside signed-in `/research/`. Select HAA-Simple
   in both, run the check, and compare overall grade, baseline CAGR and maximum
   drawdown, three-checks rows, scenario/rolling/subperiod row counts and
   statuses, fixed-seed Monte Carlo numbers (exact match expected), and
   data-quality rows. Download and compare all four CSVs.
2. Repeat with Inflation Compass Standard, including parameter-sweep rows.
3. Select an RVol Shifter variant and an Israel Inflation Compass variant in
   both apps: both must show the same explanation messages, not errors.
4. Change initial capital and rerun: final-value-style figures scale, growth
   rates and grades do not move.
5. Confirm Research saves nothing and offers no edit/order actions.

## Compare migration - Step 9

### Scope and paths

The final navigation page, `/compare/`, is enabled. Models mode compares selected
backtestable catalogue entries; Portfolios mode reads selected saved records
from the signed-in library. This page never edits a saved record or default.
Streamlit, strategy code, existing pages, settings/domains/cron, dependencies and
all deferred tidy-up items remain untouched.

- `server/compare.py`: input validation, catalogue/selection gates, union loading,
  original engine orchestration, public cache envelope and CSV retrieval.
- `server/compare_presentation.py`: original summary/turnover/allocation formulas,
  existing metric functions and row-format lists, Python CSVs and SVG series.
- `web/content/compare.json`: page-owned text and verbatim original captions.
- `web/app/compare/page.tsx`, `web/lib/compareApi.ts`: explicit Run, both selectors,
  settings, bounded previews, SVG charts and authenticated downloads.
- `api/index.py`: three new routes and no-store/safe-validation handling scoped
  to Compare; existing endpoint behaviour is unchanged.
- `web/components/top-navigation.tsx`, `api/tests/test_rules.py`: enable Compare
  and update the navigation assertion. No existing page component/CSS changes.
- `api/tests/test_compare.py`, `web/tests/compare.test.tsx`: offline coverage.

Routes: `GET /api/compare/options` returns catalogue labels/benchmarks/currencies,
private saved-portfolio selector summaries and independent defaults (initial
100,000, fee 0%, tax OFF, tax rate 25%). It downloads no prices and runs no
engine. `POST /api/compare` accepts mode, labels or saved IDs, monthly/daily
portfolio method, capital, percentage fee, tax settings and optional dates.
`GET /api/compare/download?key=...&kind=...` serves full cached Python CSVs:
`monthly-returns`, `after-tax-monthly-returns`, `portfolio-returns` and
`audit:<catalogue label>`. Missing bundles return an explicit rerun-required
404, never a recalculation. API financial errors are shown rather than hidden.

### Original engines and deliberate differences

Models loads the selected union with each model's own benchmark (no extra SPY
addition). Production decisions use the original daily/monthly decision input
and month-end market frame. `haa.comparison.compare_models` is called once; its
original independent runs, shared-period intersection and rebased reruns are
not replaced or optimised. Mixed benchmark/currency, daily execution and
single-strategy-only refusals remain unchanged.

Portfolios validates records with the existing saved-portfolio parser and uses
Step 7's union loader: shared SPY, model-specific monthly/decision frames and
adjusted opens when daily sleeves require them. `compare_portfolios` runs once
to discover the common executable window, then once with the requested dates,
inside one request. Monthly resets and initial-weights/daily valuation use the
original engines. USD-only, benchmark, A-RVol-monthly, gap, inconsistent-benchmark
and no-shared-history refusals are preserved. Saved FX is validated by the
existing parser but is not used to change Compare's user-entered USD capital.

All metrics use existing `performance_metrics`, `result_metrics` and
`annual_returns`. Allocation changes/year and turnover, latest dictionary
weights and audit filenames follow the original expressions. Portfolio test
date rows port the existing `add_test_dates` presentation expression literally.
Models drawdown uses curve/running maximum minus one; portfolio drawdown retains
the original running-maximum floor at initial capital. No financial JavaScript.

Deliberate differences:

- Explicit Run only, disabled while running; no price downloads/engine calls
  from edits or initial options. Mode/selection/method/settings edits clear the
  previous result. Tax defaults OFF independently of Backtest.
- Initially collapsed Performance / Drawdown / Details / Returns sections replace
  the four Streamlit tabs, retaining their internal content order; native SVG.
- Models defaults to the first two case-insensitively sorted eligible entries,
  not the last Backtest selection.
- Blank dates mean full common history; Run rejects out-of-range/inverted dates
  instead of silently clamping. Derived bounds/coverage appear with the result.
- No custom Yahoo overrides, uploaded price CSVs or device-JSON portfolio import.
- Saved names are only in the private no-store selector response. Compared
  portfolios use neutral `Portfolio 1`, `Portfolio 2`, etc., in **selection
  order**, not saved-library positions. This is explained on the page so no
  private name/ID needs reinserting into public cached results or CSVs.
- Portfolio monthly returns are displayed as well as downloadable (the old
  block exported them without rendering its constructed table).

### Cache, privacy and limits

All routes require the existing server-verified Bearer session and return private
no-store headers. The Supabase skill guided reuse of that verified-user/read-only
library path; no auth code, RLS, schema or project settings changed. Saved records
are read through the existing GET-portfolios helper. Unknown models/IDs or invalid
bodies return 400 without echoing submitted private values; missing/bad tokens
return 401 and wrong methods 405. Application logs contain timings only.

Bounded ResultCache tags are `compare-models-v1` and `compare-portfolios-v1`.
Keys contain sorted public model labels or per-portfolio public sleeve
compositions plus their exact execution order, all settings/capital, engine/server
code and content hashes, observed data version (including adjusted opens),
source metadata, UTC date and completed-session cutoffs. Never saved names,
library positions, record IDs, saved capital/FX, payloads, user IDs or tokens.
Tests read fake records through the real helper/parser path, spy on cache
arguments and inspect stored bundles; any saved-record write fails a test.
Renaming/changing saved capital/FX leaves the key unchanged, while changing the
public sleeve execution order invalidates it. Live inputs are checked before
lookup; hits perform zero comparison-engine work. Exceptions and oversized
responses are not cached.

The pre-cache 2.9 MB check and final 3,000,000-byte guard apply to main JSON.
Tables preview at most 150 rows with a visible notice; metrics and Python
`to_csv()` downloads use all rows and retain the original index/filenames.
Charts use the established labelled 700-observation display limit. Gateway/
timeout failures show the existing exact five-minute message without partial
results. No minimum-fee warning or rule was added to Compare or elsewhere.

### Verification and local timings

Offline suites: **477 original Python**, **331 API**, **91 web** tests passed;
TypeScript typecheck and production build passed. Existing timestamp-attrs and
Starlette/httpx warnings remain. Coverage includes direct engine parity, multi-
asset latest weights, tax on/off, nonzero fees, narrowed dates, turnover/change
rows, full indexed CSV bytes/filenames, monthly portfolios and daily A-RVol,
engine refusal messages, public cache/privacy/order/invalidation/failures/size,
auth/no-store/routes, both selection gates, verbatim captions, duplicate guard,
timeout, cleared results and collapsed sections.
`git diff main -- app.py src requirements.txt pyproject.toml` is empty.

October 20 real-data measurements used warm local interpreters/cold result
caches, no Supabase credentials/private reads, default hypothetical capital,
zero fees and tax ON at 25%. Models: HAA-Simple, Inflation Compass Standard,
HAA Classic (No QQQ), all SPY-benchmark (no substitutions needed). Monthly
portfolios: first two models at 60/40, all three at 40/30/30. Daily portfolios:
Century Momentum/IC Standard at 60/40 and CM/IC/USD A-RVol at 40/30/30. These
were constructed version-1 payloads, not saved user records or provider mocks.

| Mode | Input load / preparation | Engine | Total cold result | Retained-frame hit | Main JSON bytes | Peak process MiB |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Three monthly models | 3.917682 s | 0.762225 s | 4.715725 s | 0.001340 s | 146,342 | 223.14 |
| Two daily-valued portfolios, including A-RVol | 4.520215 s | 15.190148 s | 19.741281 s | 0.000625 s | 110,519 | 280.67 |
| Two monthly-reset portfolios | 4.086943 s | 2.982443 s | 7.089330 s | 0.000722 s | 72,386 | 222.53 |

Input time includes download, preprocessing, production decisions and version
hashing. Retained-frame repeats use the real cache path with identical actually
downloaded frames and zero engine work; they **exclude another input load** and
are not fresh HTTP-request timings. Peak memory is process high-water RSS, not
incremental engine allocation. These are not Vercel cold-start/provider-latency/
remote-cache guarantees. No run approached 300 seconds; that setting is unchanged.

Not verified: signed-in cloud runs, remote-cache CSV restoration, browser visual
fit on laptop/phone or the side-by-side checks below. A Git/Vercel build status
does not establish those workflows. No production cutover, merge or PR is part
of this task; the other deferred tidy-up items remain parked.

### Daniel's manual side-by-side checklist — not yet completed

1. Same day: Streamlit Compare beside signed-in `/compare/`. Models mode:
   HAA-Simple and Inflation Compass Standard, tax ON. Compare summary, equity
   and drawdown charts, annual/monthly returns and latest allocation. Download
   monthly returns and one audit CSV from both apps and compare bytes.
2. Add a third model, narrow the start date in both, and confirm shared windows.
3. Select one USD and one ILS model: both must show the same benchmark refusal.
4. Portfolios: the same two saved portfolios, monthly resets, tax off then on.
   Compare the full performance table including SPY and the returns CSVs.
5. Switch to daily valuation with an A-RVol sleeve: curves/closing caption must
   match. Then monthly resets with A-RVol: both must refuse identically.
6. Confirm Compare saves nothing and never changes a saved portfolio or default.
