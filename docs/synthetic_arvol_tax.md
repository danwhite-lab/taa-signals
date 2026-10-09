# Synthetic A-RVol realized-gain estimate

This is a simplified USD scenario model, not a historical Israeli account tax
calculation. Live strategy rules and supplied source files are unchanged.

The source NAV and NDX/IRX frozen input hashes are checked before use. Every
unrounded daily modeled return must reproduce the source NAV within its
four-decimal export rounding interval. Exact supplied NAV ratios remain the
pre-tax return source. The minute NAV-rounding residual is assigned to the
post-open segment on modern switch days; pre-2001 close executions assign the
entire day's exact return before the sale. Reconstruction factors are cached
by content hashes, not by path alone.

From 2001, sale proceeds include the old position's modeled overnight movement;
tax is paid before buying the new position and earning its modeled intraday
return. Before 2001, the documented next-close fallback applies. These are modeled
leveraged exposure fills, not actual ETF quotations. Financing and the source's
0.95% annual fund expense are already embedded in the return factors; additional
broker commissions are unsupported and never silently added.

Funded average-cost books carry gains/losses across switches. DCA increases cost
basis, not taxable income. Selected subranges start fresh cost bases and empty
loss carryforwards at the preceding month-end anchor; the original signal path
is retained. Standalone tests retain both daily pre-tax and after-tax NAV.

Blends reset sleeve weights at the start of each reporting month using prior
month-end NAV. These calendar dates are proxy accounting dates, not invented
exchange fills. Daily A-RVol switches keep their original execution dates.
DCA is added at those boundaries before resets. Surplus sales
realize gains with proportional cost basis; taxes reduce the amount available
for purchases. Reallocation iterates to self-financing target weights; every
tax-funded reduction is recorded as a sale, never a silent basis adjustment.
A-RVol internal transactions are processed daily; other supplied sleeves use
monthly allocations and strategy-return proxies, not invented security prices.
Portfolio reporting remains monthly because those other sleeves lack daily data.

Cash is treated as an accumulating synthetic instrument; its modeled gains are
realized when sold. This is **not** an interest-withholding model. Cost bases and
loss carryforwards stay separate per sleeve. No cross-sleeve loss netting, FX or
inflation/indexation adjustments, dividend taxation, annual tax settlement or
terminal liquidation is modeled. The benchmark remains pre-tax. Tax ledgers and
modeled portfolio transactions can be downloaded from Deep History.
