# Plain gold and Harel bond holdings

Gold also offers **GLD (USD)** as a separate Buy and Hold implementation.
It continuously holds GLD using the existing Yahoo Finance price adapter and
actual available GLD ETF history only. No futures or pre-ETF extension is
spliced in, and fund expenses embedded in prices are not deducted again.
The TASE 1147875 implementation remains separate and unchanged.

Under **Buy and Hold**, select **Gold / TASE 1147875** or
**Israeli Government Bonds / Harel 5131792**. Each holds its one fund continuously
in ILS, without a timing signal, rotation, annual reset or blend engine.

Gold uses actual security 1147875 adjusted TASE prices when available; NAV or
closing-price fallback is labelled and is not certified distribution-adjusted
total return. Harel 5131792 uses its actual Maya redemption prices.
The existing public adapter requests five years of history. Its earliest
returned observation is a coverage limit, not a claim about the fund's inception.

There is no automatic GLD/GLDM, futures, index 602 or pre-fund extension. No
additional fund-expense deduction is applied to prices already reflecting fund
expenses. Failed retrieval does not trigger a stand-in. An uploaded CSV replaces
the whole role history and is explicitly marked **Unverified replacement /
possible stand-in** in the UI, source download and standalone monthly audit.
Source dates or any pre-fund reconstruction in that replacement are unverified;
they must not be read as real-fund coverage.

Existing backtest timing, deposit handling, transaction fees, average-cost
realized-sale tax and no-final-liquidation conventions are unchanged. Monthly
reports use the existing buy-and-hold execution path, not a new daily engine.

Security identifiers are documented in official filings:
[gold 1147875](https://mayafiles.tase.co.il/RHtm/1208001-1209000/H1208195.htm),
[Harel government bonds 5131792](https://mayafiles.tase.co.il/RHtm/1454001-1455000/H1454615.htm).
