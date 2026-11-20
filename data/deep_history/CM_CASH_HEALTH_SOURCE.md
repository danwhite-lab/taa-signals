# Century Momentum Move to Cash — health reference only

This reconstruction is **not used by signals, holdings, trading backtests, taxes,
or the deep-history strategy menu**. It extends only Strategy Health's earlier
completed-fall depth and recovery-time sample. Current metrics and SPY relative
return windows continue to use the existing real-fund backtest.

## Construction and sources

- Decisions are unchanged from `century_momentum_signals.csv`. Each signal is
  applied to the following calendar holding month, including signals dated on
  the penultimate/last trading day.
- A month allocated 100% SPMO retains exactly the supplied
  `century_momentum_monthly_returns.csv` return (including its rounded precision).
  Its pre-ETF risk-on reconstruction is supplied and unverified, not actual SPMO.
- Every 100% IEF month is replaced. **No bond defensive return is retained**.
- April 1928–May 2007: monthly RF (one-month US Treasury-bill return) from the
  [Kenneth French Data Library](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html),
  frozen in `cm_cash_health_tbill_proxy.csv`. RF is divided by 100 from percent
  to decimal. This is a disclosed pre-BIL cash proxy, not a claim BIL existed.
  RF for this period is attributed by the library to Ibbotson Associates.
- June 2007–July 2016: actual BIL adjusted-close returns from Yahoo Finance,
  frozen with prices and dated anchors in `cm_cash_health_bil.csv`. Each return
  is current/prior adjusted close minus 1, on actual last US sessions. Adjusted
  close incorporates distributions. BIL's official inception is
  [25 May 2007](https://www.ssga.com/us/en/individual/etfs/state-street-spdr-bloomberg-1-3-month-t-bill-etf-bil);
  June is the first complete monthly interval, with 31 May as its initial anchor.
  This return boundary never compares an RF price with a BIL price.
- The frozen reference stops July 2016, immediately before the existing cash
  backtest's August 2016 inception. Loading an earlier as-of date trims the
  reference strictly before that date; missing cash returns fail closed.
- Recovered falls in the early segment are measured independently of the real
  fund segment. No NAV splice or episode spanning the segment boundary is made.

Inputs retrieved 20 November 2026. Rebuild with
`scripts/build_cm_cash_health_inputs.py` using the downloaded official
[F-F Research Data Factors CSV ZIP](https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_Factors_CSV.zip)
and the script's documented BIL download. The runtime makes no extra requests.

SHA-256 checksums:

| Input | SHA-256 |
| --- | --- |
| Official factors ZIP | b03d39e4bb253dda0f14893db3b78e64b40b8d6549a0fc0fd4111dae84c98618 |
| Original CM signals | f06bc20433cbda6205596681619fc34ff091955d9c66980f69b3124e0e031010 |
| Original CM monthly returns | 2856b4ea8de53684fd36a2df9041405269d7f8e8507ebe22bdd49a4c9105f3e8 |
| Frozen RF CSV | 9426e58409727e6bb982b30bae039c33ad603ed698edfc61dd13aed217893029 |
| Frozen BIL CSV | 642882e600a3abf64bd52d8e10e202746a3fb68b06a18953e11881958ae62bf6 |
