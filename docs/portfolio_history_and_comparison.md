# Portfolio history and comparisons

Backtest performance tables are always visible. Date rows show actual first and
last observations, not requested dates that could not be filled. Monthly-only
tests show month-end observations; daily tests show trading-session observations.

Deep History loads compatible saved portfolios from browser storage or device
JSON without changing the default live portfolio. Only exact supported strategy
variants map automatically to bundled USD proxies. Israel, leveraged and other
unsupported variants are rejected rather than silently replaced. Saved ILS
capital is converted using the saved FX rate.

Long synthetic A-RVol can be blended with other proxy sleeves. Its month-end NAV
ratios are preserved exactly, including the effect of its daily trades. The blend
resets sleeve weights monthly, supports monthly DCA, and uses only shared complete
months. Other sleeves lack daily observations, so blended risk statistics are
monthly only. No interpolated daily returns are generated. Internal trade values
are unavailable; tax and extra trading fees are disabled for any such blend.
Standalone synthetic tests retain the original daily NAV engine. The older
daily-signal/monthly-return import remains standalone only.

Compare loads multiple portfolios saved in the browser and restarts each with
equal USD capital on the same executable dates. Each keeps independent costs and
tax state. Two explicit methods are available:

- Monthly sleeve weight resets: the existing monthly-only portfolio engine.
- Initial weights / daily valuation: funded security books marked daily, no
  inter-sleeve transfers; daily sleeves trade at next open and monthly sleeves at
  next close. Required for A-RVol and available for monthly-only portfolios.

The daily method requires actual daily prices and adjusted benchmark opens, not
Deep History inputs. Comparisons currently require USD sleeves and a shared
benchmark; currency conversion is not assumed. Missing sessions, unequal periods,
and inconsistent benchmark histories fail closed. Browser defaults and saved
portfolio records remain unchanged.
