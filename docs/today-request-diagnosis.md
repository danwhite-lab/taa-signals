# Today request failure — 19 October 2026

Diagnosed before changing request handling. Reproduced by opening Today in the
existing signed-in browser on the deployed Vercel site. Runtime request logs
showed `GET /api/today` returning **400**, with Supabase `/auth/v1/user` returning
**200**. Vercel's request detail showed search parameters `path=today`, injected
by the existing `/api/:path*` rewrite. Function execution was 377 ms; edge cache
status was BYPASS.

The route rejected any query parameter before reading saved portfolios or
loading prices. Its exact response, also reproduced in a failing local regression
test before the fix, was:

```json
{"detail":"Today reads your saved default portfolio; query parameters are not supported."}
```

This failure was not an expired session, missing authentication environment
settings, missing default portfolio, price download, timeout or cache failure.
The saved-portfolio page also loaded successfully. This does not imply every
downstream fund feed is available; the failed request never reached those feeds.

Smallest fix: accept exactly the routing pair `path=today` (or no query), while
continuing to reject all actual options, mismatches and duplicate parameters.
No rewrite, authentication, database, price, cache, strategy or Streamlit changes.
Today now maps HTTP failures to safe specific messages, distinguishes network
failures and invalid JSON, and never displays raw provider response bodies. A
successful no-default result still shows the normal portfolio setup guidance;
individual data failures keep their existing sleeve-level reasons.

Tests use only fake portfolios and mocked providers. No account values, tokens
or private portfolio payloads were added to diagnostics or fixtures.
