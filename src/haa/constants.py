ASSETS = ("SPY", "TIP", "IEF", "BIL")
ISRAEL_SIMPLE_ASSETS = ("TIP", "CSPX_IL", "IEF_IL", "AYALON_KASPIT")
TA125_SMART_MOMENTUM_ASSET = "TA125_SMART_MOMENTUM"
LEVERAGED_ASSETS = ("SSO",)
# IEF belongs to Classic HAA's eight-asset risk-on ranking as well as its
# defensive pair; BIL is defensive-only. QQQ is intentionally absent.
CLASSIC_OFFENSIVE_ASSETS = ("IEF", "SPY", "IWM", "PDBC", "TLT", "VEA", "VNQ", "VWO")
CLASSIC_DEFENSIVE_ASSETS = ("IEF", "BIL")
CLASSIC_DATA_ASSETS = ("TIP", "BIL", *CLASSIC_OFFENSIVE_ASSETS)
# HAA's leveraged flavour calculates every momentum score on these 1x
# underlyings, then maps the selected holding to its 2x substitute. PDBC and
# BIL remain unleveraged because no substitute is part of this flavour.
CLASSIC_LEVERAGED_SUBSTITUTIONS = {
    "IEF": "UST",
    "SPY": "SSO",
    "IWM": "UWM",
    "PDBC": "PDBC",
    "TLT": "UBT",
    "VEA": "EFO",
    "VNQ": "URE",
    "VWO": "EET",
    "BIL": "BIL",
}
CLASSIC_LEVERAGED_HOLDINGS = ("UST", "SSO", "UWM", "PDBC", "UBT", "EFO", "URE", "EET", "BIL")
CLASSIC_LEVERAGED_DATA_ASSETS = tuple(dict.fromkeys((*CLASSIC_DATA_ASSETS, *CLASSIC_LEVERAGED_HOLDINGS)))
# Published Keller & Keuning HAA-4: IEF is deliberately shared by the
# offensive and defensive universes.  The data tuple is de-duplicated.
HAA4_OFFENSIVE_ASSETS = ("SPY", "VEA", "VNQ", "IEF")
HAA4_DEFENSIVE_ASSETS = ("IEF", "BIL")
HAA4_DATA_ASSETS = ("TIP", "BIL", "SPY", "VEA", "VNQ", "IEF")
# HAA-4 Leveraged 2x makes every decision using the published, unleveraged
# HAA-4 universe. These ETFs are execution vehicles only; BIL deliberately
# remains unleveraged.
HAA4_LEVERAGED_SUBSTITUTIONS = {
    "SPY": "SSO",
    "VEA": "EFO",
    "VNQ": "URE",
    "IEF": "UST",
    "BIL": "BIL",
}
HAA4_LEVERAGED_HOLDINGS = ("SSO", "EFO", "URE", "UST", "BIL")
HAA4_LEVERAGED_DATA_ASSETS = tuple(dict.fromkeys((*HAA4_DATA_ASSETS, *HAA4_LEVERAGED_HOLDINGS)))
# Inflation Compass uses FRED's daily five-year breakeven as a signal-only
# macro input; all other symbols are Yahoo-priced tradable ETFs.
FRED_ASSETS = ("T5YIE",)
INFLATION_COMPASS_MARKET_ASSETS = ("SPY", "XLE", "XLK", "XLU", "XLP", "IEF", "XLI", "XLF", "XLB", "XLV")
INFLATION_COMPASS_DATA_ASSETS = (*INFLATION_COMPASS_MARKET_ASSETS, *FRED_ASSETS)
# Growth-Inflation Sector Timing uses only liquid ETF prices. Its sector ratio
# deliberately includes XLY, unlike Inflation Compass's confirmation basket.
GROWTH_INFLATION_ASSETS = ("SPY", "XLE", "XLB", "XLI", "XLF", "XLU", "XLV", "XLP", "XLY", "XLK")
GROWTH_INFLATION_ISRAEL_EXECUTION_ASSETS = ("XLE_IL", "XLK_IL", "XLV_IL", "XLP_IL")
GROWTH_INFLATION_ISRAEL_DATA_ASSETS = (*GROWTH_INFLATION_ASSETS, *GROWTH_INFLATION_ISRAEL_EXECUTION_ASSETS)
VAA_OFFENSIVE_ASSETS = ("SPY", "EFA", "EEM", "AGG")
VAA_DEFENSIVE_ASSETS = ("LQD", "IEF", "SHY")
VAA_G4_DATA_ASSETS = (*VAA_OFFENSIVE_ASSETS, *VAA_DEFENSIVE_ASSETS)
# Keller's published Bold Asset Allocation, G4 aggressive variant. SPY is a
# canary only; it is deliberately absent from the investable universe.
BAA_G4_CANARY_ASSETS = ("SPY", "VEA", "VWO", "BND")
BAA_G4_OFFENSIVE_ASSETS = ("QQQ", "VWO", "VEA", "BND")
BAA_DEFENSIVE_ASSETS = ("TIP", "DBC", "BIL", "IEF", "TLT", "LQD", "BND")
BAA_G4_DATA_ASSETS = tuple(dict.fromkeys((*BAA_G4_CANARY_ASSETS, *BAA_G4_OFFENSIVE_ASSETS, *BAA_DEFENSIVE_ASSETS)))
# Carlson's Orthogonal Alpha holds a permanent QLD/BTAL core and switches its
# satellite between those same instruments using BTAL relative to T-bills.
ORTHOGONAL_ALPHA_DATA_ASSETS = ("QLD", "BTAL", "BIL", "SPY")
CENTURY_MOMENTUM_DATA_ASSETS = ("SPMO", "IEF", "SPY")
CENTURY_MOMENTUM_ISRAEL_DATA_ASSETS = ("SPMO_IL", "IEF_IL")
STRATEGY_NAME = "HAA-Simple"
MOMENTUM_LOOKBACKS = (1, 3, 6, 12)
DEFAULT_TAX_RATE = 0.25
