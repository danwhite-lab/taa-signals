# Saved portfolio transfer settings

Saved portfolios contain only a name and weighted sleeves. They do not carry
`total_ils`, `ils_per_usd`, or `transfer_rule`. Capital and currency assumptions
belong to the page that runs a calculation, and the sleeve transfer rule is
chosen for each Backtest run.

Older saved JSON files may still contain those fields. They remain accepted so
existing portfolios load normally, but are ignored. Loading a portfolio resets
the Backtest transfer setting to **None** and leaves the amount currently typed
on the form unchanged.
