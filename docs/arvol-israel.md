# A-RVol Shifter V3 Cash-Only — Israel

User-selected mappings (other Israel strategies are unchanged):

| US role | Local role | Security |
| --- | --- | --- |
| TQQQ | MTF Nasdaq-100 monthly-reset x3 | 1187079 |
| QLD | 50% MTF x3 + 50% Harel Nasdaq-100 | 1187079 + 1149038 |
| QQQ | Harel Nasdaq-100 | 1149038 |
| SPY | Tachlit S&P 500 | 1144385 |
| LQD | iShares USD corporate-bond UCITS | 1159185 |
| HYG | iShares USD high-yield UCITS | 1159078 |
| BIL/cash | Ayalon Kaspit, shekel cash | 5117700 |

This is a local ILS adaptation. Indicators use the four local signal securities;
V3 thresholds and the 252-observation annualizer remain unchanged. It is not a
daily-reset US leveraged ETF replica. Actual local history is required, with
266 warm-up observations and no proxy prehistory, filled session gaps or modeled
three-times USD/ILS exposure. NAV already includes fund expenses; the stated
1.38% expense is not deducted again. The stated drift and cost estimates are not
assumed backtest outcomes.

Signals use completed closes (conservative 20:00 Jerusalem cutoff), then execute
at the next TASE session's closing/NAV price. Check fund dealing deadlines with
the broker; this convention is not a guaranteed fill. The TASE session calendar
comes from the pinned exchange-calendars dependency, including its 2026 change.
The QLD substitute enters 50/50, drifts while held, and resets on the first
session of each new calendar year. State changes trim/buy only the required
securities, not automatically liquidating retained holdings. The audit shows
security trades and actual pre-tax weights as well as target weights.

Fees are charged per actual buy/sell side; the app's existing realized-tax model
tracks average security cost bases and loss carryforwards. The default tax is
25%. This is an approximation, not a legally validated Israeli tax return:
no FX/indexation, dividend withholding or terminal liquidation is added.
Mixed portfolio sleeve transfers retain the existing sleeve-level tax
approximation and do not offset losses between sleeves.

Single-strategy and same-currency ILS daily-valued portfolio Backtests support
drift, quarterly RVol caps and annual sleeve resets. Do not combine USD and ILS
sleeves without conversion. Portfolio Compare remains USD-only; generic monthly
Research and synthetic US Deep History do not represent this implementation.
Daily drawdowns use daily closing NAV, not intraday lows. No trades are placed.
