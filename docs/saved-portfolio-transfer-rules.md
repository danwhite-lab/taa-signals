# Saved portfolio transfer settings

Version-1 portfolio JSON may include `transfer_rule` alongside the existing
`name`, `sleeves`, `total_ils` and `ils_per_usd` fields. No database migration is
needed; the existing private JSON save and conflict checks are unchanged.

Examples:

```json
{"mode": "none"}
{"mode": "annual_target"}
{"mode": "rvol_cap", "sleeve_model": "A-RVol Shifter V3 Cash-Only", "cap_percent": 15, "target_percent": 10}
```

Cap and reset target are percentage points, matching the Backtest form. The
selected sleeve is stored by exact model label, not a transient row ID. Loading
resolves it to the cleaned Backtest sleeve ID; missing or ambiguous selections
are errors, never silently replaced with another RVol variant.

An absent rule means no transfers and resets the form's unused cap parameters
to the existing defaults (15 / 10), rather than retaining a previous portfolio's
settings. Portfolio editing and Advanced JSON stay in sync. Saving an old
portfolio explicitly records `{"mode":"none"}`; merely loading it writes nothing.

These settings select the existing transfer calculations, including their
mixed-frequency applicability and deposit restrictions. No engine rules change.
Deep History does not implement active transfer rules and rejects such a load
with an explicit direction to use Portfolio mode instead.
