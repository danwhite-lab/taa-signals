# GEM deep-history inputs

User-supplied `Montly returns - GEM.csv` and `Signal History - GEM.csv`, received 2026-10-06. Bundled as `gem_monthly_returns.csv` and `gem_signals.csv`; source values are retained without added dividends, inflation adjustments or invented prehistory. These are supplied strategy-level proxy returns/signals, not independently reconstructed security-level returns. The files do not state currency or a detailed historical construction methodology; they are treated consistently with the user's other strategy exports, not claimed as independently verified official USD histories.

Validation: 488 monthly returns, March 1986–October 2026; 488 signals, February 1986–September 2026. No duplicate dates or calendar-month signals, internal month gaps or nonfinite returns. Each signal is aligned to the following holding month, normalizing penultimate/last-trading-day dates to calendar month-end. Allocations are 100% SPY, VEU or AGG and sum to 100%. First return: March 1986 +10.80%; September 2026 -0.10%; October 2026 +1.90%. January–February 1986 and November–December 2026 are unavailable, not zero-filled.

October 2026 is incomplete as of receipt. It is preserved in the raw input but excluded from current backtests because both independently supplied benchmarks end September 2026. Current usable GEM holding periods: March 1986–September 2026, 487 months. A future data update must explicitly review the incomplete October observation before extending benchmark coverage.

Monthly values have effective precision of 0.1 percentage points. Compounded annual/YTD values differ from the supplied Total column by at most 0.263 percentage points, consistent with rounding; no values have been adjusted to force agreement. Total is not an extra return observation.

The existing allocation-change realized-gain tax proxy is unchanged: component-level prices and tax lots are unavailable, so each component receives the strategy NAV. GEM is selectable alone or in custom-weight blends with other Deep History sleeves; common usable dates are used. Live GEM rules and prices are not changed by this import.
