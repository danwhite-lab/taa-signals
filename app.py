from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent / "src"))
from haa.constants import ASSETS, DEFAULT_TAX_RATE, FRED_ASSETS, ISRAEL_SIMPLE_ASSETS, OECD_CLI_DIFFUSION_ASSET, TA125_SMART_MOMENTUM_ASSET
# Comparison logic stays outside the UI so it can enforce a shared period.
from haa.comparison import ModelInput, compare_models
from haa.data import combine_replacements, common_monthly_period, date_ranges, default_ticker_map, download_fred_series, download_latest_yahoo_close, download_oecd_cli_diffusion, download_yahoo_prices, parse_ticker_map, read_uploaded_csv, to_month_end, upload_asset_from_filename
from haa.deep_history import DEEP_HISTORY_SPECS, deep_history_model_input
from haa.engine import run_backtest
from haa.metrics import annual_returns, performance_metrics
from haa.model_catalog import MODEL_CATALOG, definition_for_label, implementations, resolve, strategies as catalog_strategies, variants
from haa.portfolio import aggregate_holdings_by_currency, convert_currency, execution_security_label, funding_plan, total_weight
from haa.portfolio_backtest import run_portfolio_backtest
from haa.signals import first_trading_day_after, latest_actionable_signal, latest_preview_signal, month_to_date_snapshot
from haa.strategies import BAAG4Aggressive, BAAG4AggressiveIsrael, CenturyMomentum, CenturyMomentumIsrael, GEM, GEMIsrael, GGCEMLinkOriginal, GGCEMLinkOriginalIsrael, GrowthInflationConcentrated, GrowthInflationConcentratedIsrael, GrowthInflationDiversified, HAA4, HAA4Israel, HAA4Leveraged2x, HAAClassicLeveragedNoQQQ, HAAClassicNoQQQ, HAASimple, HAASimpleIsrael, HAASimpleLeveraged2x, InflationCompassFast, InflationCompassStandard, InflationCompassSteady, OrthogonalAlpha, TA125SmartMomentum, VAAG4
from haa.tase_data import ISRAEL_DEFAULT_TASE_SUBSTITUTIONS, TASE_ISRAEL_ASSET_IDS, TaseDataError, download_tase_israel_prices, download_tase_security_prices
from haa.validation import ValidationInput, profile_for, run_deterministic_validation

MODEL_OPTIONS = {item.label: item.model_class for item in MODEL_CATALOG}
BACKTEST_MODEL_OPTIONS = {label: model_class for label, model_class in MODEL_OPTIONS.items() if getattr(model_class, "backtest_available", True)}
MODEL_RULES = {
    "Century Momentum Israel": """**Century Momentum Israel:** At each completed month-end, compare MTF Tracking S&P 500 Momentum (4D) (5140850) with its 10-month simple moving average, calculated from the ten completed TASE month-end closes including the current signal close. If it is strictly above the average, hold 100% MTF Tracking S&P 500 Momentum (4D) (5140850); if it is equal to or below the average, hold 100% iShares $ Treasury Bond 7–10yr UCITS (1159268). The decision takes effect from the following available TASE trading day. This ILS execution variant uses actual TASE fund histories only; it does not synthesize a longer history.""",
    "Century Momentum": """**Century Momentum:** At each completed month-end, compare SPMO's close with its 10-month simple moving average, calculated from the ten completed month-end closes including the current signal close. If SPMO is strictly above the average, hold 100% SPMO; if it is equal to or below the average, hold 100% IEF. The decision takes effect from the following available trading day. The backtest deliberately starts with SPMO's actual ETF history; it does not splice in the non-investable academic Fama-French momentum-decile history.""",
    "Growth-Inflation Concentrated Israel": """**Growth-Inflation Concentrated Israel:** Uses the original strategy's completed U.S. daily signals—SPY versus its 200-day SMA for growth and the inflation-positive/negative sector ratio versus its 200-day SMA for inflation—but executes each selected regime through TASE-listed instruments in ILS: reflation → KSM ETF S&P Energy (1145903); goldilocks → iShares S&P 500 IT UCITS (1159193); stagflation → MTF סל S&P Health Care (4D) (1150390); deflation → MTF S&P Consumer Staples (1150366). Decisions are made at month-end and take effect on the following available TASE trading day.""",
    "Orthogonal Alpha (BTAL/QLD)": """**Orthogonal Alpha (BTAL/QLD):** Thomas Carlson's monthly core-satellite allocation holds a permanent 25% QLD and 25% BTAL core. The remaining 50% satellite compares BTAL and BIL using equal-weighted 1-, 3-, 6-, and 12-month returns. If BTAL's blended momentum is strictly greater than BIL's, the satellite holds BTAL (25% QLD / 75% BTAL); otherwise, including a tie, it holds QLD (75% QLD / 25% BTAL). The month-end decision takes effect from the next trading day.""",
    "VAA-G4 (T1/B1)": """**VAA-G4 (T1/B1):** At each completed month-end, calculate 13612W for SPY, EFA, EEM, AGG, LQD, IEF, and SHY: `(12×R1 + 4×R3 + 2×R6 + R12) / 4`. If any offensive asset (SPY, EFA, EEM, AGG) has non-positive momentum, VAA holds 100% of the best defensive asset (LQD, IEF, SHY). Otherwise it holds 100% of the highest-momentum offensive asset. It is deliberately aggressive: `B=1` means one weak offensive asset activates full defense.""",
    "BAA-G4 (Aggressive)": """**BAA-G4 (Aggressive):** At each completed month-end, calculate 13612W canary momentum for SPY, VEA, VWO, and BND: `(12×R1 + 4×R3 + 2×R6 + R12) / 4`. If every canary is strictly positive, hold 100% of the highest-ranked asset from QQQ, VWO, VEA, and BND. If any canary is zero or negative, rank TIP, DBC, BIL, IEF, TLT, LQD, and BND; select the top three equally, then replace each selected asset whose 13-month SMA relative momentum is below BIL's with BIL. Relative momentum is current price divided by the average of the current and prior twelve completed month-ends, minus one. The decision takes effect on the following available trading day. DBC is the published commodity ETF; PDBC is not substituted.""",
    "BAA-G4 (Aggressive) Israel": """**BAA-G4 (Aggressive) Israel:** Uses the unchanged published BAA-G4 USD signals and displays the selected holdings through TASE-listed ILS proxies: QQQ→1186063, VWO→1159169, VEA→VXUS proxy 5142476, BND→BNDW proxy 1159102, TIP→1159060, DBC→GLDM 1147875, BIL→Keren Kaspit 5136866, IEF/TLT→IEF 1159268, and LQD→1159185. SPY remains the published signal-only canary. Its backtest uses U.S. proxy returns—VXUS, BNDW, and GLDM—rather than TASE fund returns, ILS currency performance, or Israeli-fund costs.""",
    "GEM": """**GEM (Global Equities Momentum):** At each completed month-end, calculate 12-month returns for SPY, VEU, AGG, and BIL. If SPY's return is strictly greater than BIL's, hold 100% SPY when SPY's return is at least VEU's; otherwise hold 100% VEU. If SPY is at or below BIL, hold 100% AGG. The decision takes effect on the following available trading day.""",
    "GEM Israel": """**GEM Israel:** Uses the unchanged published GEM USD signals and displays holdings through CSPX (1159250), the ACWX proxy (5142476), and the BNDW proxy (1159102). BIL remains a signal-only asset. Its backtest uses U.S. ACWX and BNDW returns, not TASE fund, ILS-currency, or Israeli-fund-cost performance.""",
    "GGCEM Link Original": """**GGCEM Link Original:** At each completed month-end, use the prior month's OECD Composite Leading Indicator diffusion: strictly more than half of available individual-country CLIs rising is risk-on; 50% or below is risk-off. In risk-on, hold the higher 12-month-return asset of SPY and VEU. In risk-off, hold the higher 12-month-return asset of IEF and BIL. If OECD data is unavailable, the disclosed failsafe uses SPY's 12-month return versus BIL to set the regime. The decision takes effect on the next available trading day.""",
    "GGCEM Link Original Israel": """**GGCEM Link Original Israel:** Uses the unchanged GGCEM USD regime and momentum signals while displaying SPY through CSPX (1159250), VEU through ACWX (5142476), IEF through 1159268, and BIL through Keren Kaspit (5136866). Its backtest uses U.S. return proxies, not TASE fund, ILS-currency, or Israeli-fund-cost performance.""",
    "Growth-Inflation Concentrated": """**Growth-Inflation Concentrated:** At each completed month-end, growth is high when SPY is above its 200-day SMA. Inflation is high when the equal-weighted XLE/XLB/XLI/XLF basket divided by the equal-weighted XLU/XLV/XLP/XLY basket is above its 200-day SMA. The four fixed allocations are: high growth/high inflation → XLE; high growth/low inflation → XLK; low growth/high inflation → XLV; low growth/low inflation → XLP. Inflation Compass is the later successor: it keeps this quadrant idea but makes five-year breakeven inflation its primary signal and uses sector relative strength as confirmation.""",
    "Growth-Inflation Diversified": """**Growth-Inflation Diversified:** Uses the same SPY and sector-ratio 200-day signals as the Concentrated variant, but holds fixed 50/50 pairs: high growth/high inflation → XLE/XLI; high growth/low inflation → XLK/XLY; low growth/high inflation → XLE/XLB; low growth/low inflation → XLV/XLP. The pairs are fixed; no sectors are dynamically ranked. Inflation Compass is the later successor: it keeps this quadrant idea but makes five-year breakeven inflation its primary signal and uses sector relative strength as confirmation.""",
    "TA-125 Smart Momentum": """**TA-125 Smart Momentum:** An Israeli equity momentum strategy implemented through Migdal MTF TA-125 Smart Momentum (fund 5134713). The underlying TA-125 Smart Momentum index dynamically adjusts TA-125 stock weights according to momentum and trend strength, including the relationship between 50-day and 200-day moving averages. The fund is held continuously rather than tactically traded, so selection and reweighting happen inside the index without investor-level trading on each rebalance.""",
    "HAA-Simple": """**HAA-Simple:** At each month-end, calculate equal-weighted 13612U momentum for SPY and TIP. If both are strictly positive, hold 100% SPY. Otherwise, compare IEF and BIL 13612U momentum and hold 100% of the higher-momentum asset. The decision earns the following month's return only.""",
    "HAA 4": """**HAA 4:** TIP is the sole canary. If TIP's equal-weighted 13612U momentum is zero or negative, hold 100% of the higher-momentum asset from IEF and BIL. If TIP is strictly positive, rank SPY, VEA, VNQ, and IEF by 13612U and select the top two at 50% each. Then replace each selected asset whose own momentum is zero or negative with the higher-momentum IEF/BIL defensive asset. This can produce a mixed offensive/defensive allocation. IEF is eligible in both universes.""",
    "HAA 4 Israel": """**HAA 4 Israel:** Uses the published HAA-4 USD signal logic: TIP is the canary; SPY, VEA, VNQ, and IEF are ranked by 13612U; and IEF/BIL provide defensive replacement. Holdings map to CSPX (1159250), IBI MSCI AC World ex USA (5142476), IBI DJ US Real Estate (5131834), IEF (1159268), and Keren Kaspit (5136866). Its backtest uses VXUS as the U.S. return proxy for the ex-US execution fund, so it is not actual TASE or ILS performance.""",
    "HAA 4 Leveraged 2x": """**HAA 4 Leveraged 2x:** HAA-4's TIP gate, Top-2 ranking, and sleeve-level defensive replacement all use unleveraged TIP, SPY, VEA, VNQ, IEF, and BIL momentum. Only after that decision are holdings mapped: SPY→SSO, VEA→EFO, VNQ→URE, IEF→UST, and BIL→BIL. If TIP is zero or negative, the defensive winner is held at 100%; otherwise each selected non-positive sleeve is replaced by that defensive winner. EFO and URE are practical execution proxies, not exact tracker matches for VEA and VNQ.

**Risk:** high-drawdown leveraged satellite, not a core holding. These ETFs target 2× daily returns, so results over a month or longer can materially differ from 2× the underlying return.""",
    "Inflation Compass Steady (80-day)": """**Inflation Compass Steady (80-day):** On the final NYSE trading day of each month, growth is on when SPY is above its 200-day SMA. Inflation is on when the prior trading day's T5YIE is above 2% and either exceeds its value 80 valid trading observations earlier or the 80-day linear-regression slope of the published inflation-sector indicator is positive. The indicator compounds daily rebalanced positive-basket returns (50% XLE; one-sixth each XLI/XLF/XLB) divided by daily rebalanced negative-basket returns (one-third each XLU/XLV/XLP). Holdings are XLE, XLK, XLU, or 50/50 XLP/IEF by the resulting regime. No CPI fallback is used, so the model begins in 2003.

**Risk:** concentrated sector allocation. T5YIE is market-implied and may be distorted in stressed markets; signals are informational only.""",
    "Inflation Compass Standard": """**Inflation Compass Standard:** The published 60-trading-day version of Inflation Compass. On the final NYSE trading day of each month, growth is on when SPY is above its 200-day SMA. Inflation is on when the prior trading day's T5YIE is above 2% and either exceeds its value 60 valid trading observations earlier or the 60-day linear-regression slope of the published inflation-sector indicator is positive. The indicator compounds daily rebalanced positive-basket returns (50% XLE; one-sixth each XLI/XLF/XLB) divided by daily rebalanced negative-basket returns (one-third each XLU/XLV/XLP). Holdings are XLE, XLK, XLU, or 50/50 XLP/IEF by the resulting regime. No CPI fallback is used, so the model begins in 2003.

**Risk:** concentrated sector allocation. T5YIE is market-implied and may be distorted in stressed markets; signals are informational only.""",
    "Inflation Compass Fast (40-day)": """**Inflation Compass Fast (40-day):** A faster 40-trading-day version of Inflation Compass. On the final NYSE trading day of each month, growth is on when SPY is above its 200-day SMA. Inflation is on when the prior trading day's T5YIE is above 2% and either exceeds its value 40 valid trading observations earlier or the 40-day linear-regression slope of the published inflation-sector indicator is positive. The indicator compounds daily rebalanced positive-basket returns (50% XLE; one-sixth each XLI/XLF/XLB) divided by daily rebalanced negative-basket returns (one-third each XLU/XLV/XLP). Holdings are XLE, XLK, XLU, or 50/50 XLP/IEF by the resulting regime. No CPI fallback is used, so the model begins in 2003.

**Risk:** shorter confirmation windows can enter and exit inflationary regimes earlier, but can also increase whipsaw and trading activity.""",
    "HAA-Simple Leveraged 2x (SSO)": """**HAA-Simple Leveraged 2x (SSO):** Calculate equal-weighted 13612U using unleveraged SPY and TIP. If both are strictly positive, hold 100% SSO. Otherwise, compare IEF and BIL momentum and hold the higher-momentum defensive asset. SSO momentum never controls the gate; IEF and BIL remain unleveraged.

**Risk:** high-drawdown satellite, not a core holding. A monthly signal cannot prevent losses from a fast intramonth crash.""",
    "HAA-Simple Israel": """**HAA-Simple Israel:** TIP is a U.S. signal-only canary. Use equal-weighted 13612U momentum for TIP, TASE-listed CSPX (1159250), iShares $ Treasury Bond 7–10yr UCITS (1159268), and Ayalon Kaspit (5136866). If TIP and CSPX are strictly positive, hold 100% CSPX. Otherwise compare 1159268 and Ayalon Kaspit and hold the higher-momentum asset; an exact tie selects 1159268. All instruments require real 12-month history. This ILS local-investability variant includes USD/ILS exposure; MAKAM 800 is not a holding series.""",
    "HAA Classic (No QQQ)": """**HAA Classic (No QQQ):** TIP is the sole canary. If TIP's equal-weighted 13612U momentum is strictly positive, rank IEF, SPY, IWM, PDBC, TLT, VEA, VNQ, and VWO by 13612U and hold the top four at 25% each. If TIP is zero or negative, compare IEF and BIL momentum and hold the higher-momentum asset. QQQ is intentionally excluded; no leverage is used.""",
    "HAA Classic Leveraged 2x (No QQQ)": """**HAA Classic Leveraged 2x (No QQQ):** TIP is the sole canary and all momentum scores use unleveraged ETFs. If TIP's equal-weighted 13612U momentum is strictly positive, rank IEF, SPY, IWM, PDBC, TLT, VEA, VNQ, and VWO, select the top four, and allocate 25% to each mapped holding: IEF→UST, SPY→SSO, IWM→UWM, PDBC→PDBC, TLT→UBT, VEA→EFO, VNQ→URE, and VWO→EET. If TIP is zero or negative, compare 1× IEF and BIL momentum; hold UST if IEF wins or BIL otherwise. QQQ is excluded.

**Risk:** high-drawdown leveraged satellite, not a core holding. A monthly signal cannot prevent losses from a fast intramonth crash.""",
}
ALL_MODEL_ASSETS = tuple(dict.fromkeys(asset for model_class in MODEL_OPTIONS.values() for asset in getattr(model_class, "data_assets", ASSETS)))
TASE_ASSETS = tuple(TASE_ISRAEL_ASSET_IDS)
YAHOO_ASSETS = tuple(asset for asset in ALL_MODEL_ASSETS if asset not in (*TASE_ASSETS, *FRED_ASSETS, OECD_CLI_DIFFUSION_ASSET))

st.set_page_config(
    page_title="TAA Signals",
    page_icon="static/taa-signals-icon-512.png",
    layout="wide",
    initial_sidebar_state="collapsed",
)
components.html(
    """
    <script>
    const head = window.parent.document.head;
    const add = (selector, tag, attributes) => {
      let element = head.querySelector(selector);
      if (!element) {
        element = window.parent.document.createElement(tag);
        head.appendChild(element);
      }
      Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    };
    add('link[rel="apple-touch-icon"]', 'link', {
      rel: 'apple-touch-icon', sizes: '180x180',
      href: '/app/static/apple-touch-icon.png?v=1'
    });
    add('link[rel="manifest"]', 'link', {
      rel: 'manifest', href: '/app/static/manifest.json?v=1'
    });
    add('meta[name="apple-mobile-web-app-capable"]', 'meta', {
      name: 'apple-mobile-web-app-capable', content: 'yes'
    });
    add('meta[name="apple-mobile-web-app-status-bar-style"]', 'meta', {
      name: 'apple-mobile-web-app-status-bar-style', content: 'default'
    });
    add('meta[name="apple-mobile-web-app-title"]', 'meta', {
      name: 'apple-mobile-web-app-title', content: 'TAA Signals'
    });
    </script>
    """,
    height=0,
    width=0,
)
st.markdown("""
<style>
.block-container { max-width: 1440px; padding-top: 0.8rem !important; }
.st-key-primary-navigation {
  margin: 2.65rem 0 1.2rem;
  padding: 0.35rem 0.45rem;
  border: 1px solid rgba(49, 51, 63, 0.14);
  border-radius: 0.65rem;
  background: rgba(250, 250, 252, 0.72);
}
.st-key-primary-navigation [data-testid="stRadio"] > div { gap: 0.25rem; }
.st-key-primary-navigation label { margin: 0; padding: 0.35rem 0.7rem; border-radius: 0.4rem; }
.st-key-signals-model-selector,
.st-key-backtest-model-selector,
.st-key-rules-model-selector,
.st-key-backtest-configuration {
  margin: 0.25rem 0 1rem;
  padding: 0.9rem 1rem;
  border: 1px solid rgba(49, 51, 63, 0.12);
  border-radius: 0.65rem;
  background: rgba(250, 250, 252, 0.58);
}
.st-key-portfolio-investment-settings {
  max-width: 46rem;
  margin: 0.25rem 0 1rem;
}
.st-key-portfolio-sleeve-heading [data-testid="stHorizontalBlock"] {
  align-items: end;
  gap: 0.25rem;
}
.st-key-portfolio-sleeve-heading h3 { margin-bottom: 0; }
.st-key-portfolio-sleeve-heading [data-testid="stButton"] > button {
  min-width: 2rem;
  width: 2rem;
  height: 2rem;
  padding: 0;
  color: rgb(49, 51, 63);
  font-size: 1.25rem;
  font-weight: 650;
  line-height: 1;
}
@media (max-width: 640px) {
  .block-container { padding: 0.6rem 0.75rem 1.5rem !important; }
  .st-key-primary-navigation {
    width: 100%;
    margin-top: 2.4rem;
    padding: 0.25rem;
  }
  .st-key-primary-navigation [data-testid="stRadio"] > div {
    display: flex;
    flex-flow: row wrap;
    width: 100%;
    gap: 0.2rem;
  }
  .st-key-primary-navigation label {
    flex: 1 1 calc(33.33% - 0.2rem);
    min-width: calc(33.33% - 0.2rem);
    justify-content: center;
    padding: 0.38rem 0.2rem;
    font-size: 0.78rem;
    line-height: 1.1;
    white-space: nowrap;
  }
  .st-key-signals-model-selector [data-testid="stHorizontalBlock"],
  [class*="st-key-portfolio_"][class*="-sleeve-row"] [data-testid="stHorizontalBlock"] {
    flex-wrap: wrap;
    gap: 0.35rem;
  }
  .st-key-signals-model-selector [data-testid="stColumn"]:nth-child(-n+2) {
    flex: 1 1 calc(50% - 0.35rem) !important;
    min-width: calc(50% - 0.35rem) !important;
    width: calc(50% - 0.35rem) !important;
  }
  .st-key-signals-model-selector [data-testid="stColumn"]:nth-child(3) {
    flex: 1 1 100% !important;
    min-width: 100% !important;
    width: 100% !important;
  }
  [class*="st-key-portfolio_"][class*="-sleeve-row"] [data-testid="stColumn"]:nth-child(-n+2) {
    flex: 1 1 calc(50% - 0.35rem) !important;
    min-width: calc(50% - 0.35rem) !important;
    width: calc(50% - 0.35rem) !important;
  }
  [class*="st-key-portfolio_"][class*="-sleeve-row"] [data-testid="stColumn"]:nth-child(3) {
    flex: 1 1 calc(60% - 0.35rem) !important;
    min-width: calc(60% - 0.35rem) !important;
    width: calc(60% - 0.35rem) !important;
  }
  [class*="st-key-portfolio_"][class*="-sleeve-row"] [data-testid="stColumn"]:nth-child(4) {
    flex: 1 1 calc(40% - 0.35rem) !important;
    min-width: calc(40% - 0.35rem) !important;
    width: calc(40% - 0.35rem) !important;
  }
  .st-key-portfolio-sleeve-heading [data-testid="stColumn"]:nth-child(1) {
    flex: 0 1 auto !important;
    min-width: 0 !important;
    width: auto !important;
  }
  .st-key-portfolio-sleeve-heading [data-testid="stColumn"]:nth-child(2),
  .st-key-portfolio-sleeve-heading [data-testid="stColumn"]:nth-child(3) {
    flex: 0 0 2rem !important;
    min-width: 2rem !important;
    width: 2rem !important;
  }
  .st-key-portfolio-sleeve-heading [data-testid="stColumn"]:nth-child(4) {
    flex: 1 1 auto !important;
    min-width: 0 !important;
    width: auto !important;
  }
  [data-testid="stDataFrame"] { max-width: 100%; overflow-x: auto; }
  .st-key-user-settings { right: 8.35rem; }
}
</style>
""", unsafe_allow_html=True)

DEFAULT_TICKERS = "\n".join(f"{role}={ticker}" for role, ticker in default_ticker_map(YAHOO_ASSETS).items())
DEFAULT_MODEL = "HAA-Simple"
PORTFOLIO_STORAGE_KEY = "taa-signals.default-portfolio.v1"
PORTFOLIO_LIBRARY_STORAGE_KEY = "taa-signals.portfolio-library.v1"


def seed_model_selection(prefix: str, label: str) -> None:
    definition = definition_for_label(label)
    st.session_state.setdefault(f"{prefix}_strategy", definition.strategy)
    st.session_state.setdefault(f"{prefix}_variant", definition.variant)
    st.session_state.setdefault(f"{prefix}_implementation", definition.implementation)


def model_selector(prefix: str, heading: str | None = None, columns=None, implementation_dropdown: bool = False) -> str:
    if heading:
        st.subheader(heading)
    strategy_key, variant_key, implementation_key = (f"{prefix}_{name}" for name in ("strategy", "variant", "implementation"))
    available_strategies = catalog_strategies()
    if st.session_state.get(strategy_key) not in available_strategies:
        st.session_state[strategy_key] = available_strategies[0]
    if columns is None:
        with st.container(key=f"{prefix}-model-selector"):
            selected_strategy = st.selectbox("Strategy", available_strategies, key=strategy_key)
            available_variants = variants(selected_strategy)
            if st.session_state.get(variant_key) not in available_variants:
                st.session_state[variant_key] = available_variants[0]
            if available_variants == (None,):
                selected_variant = None
                st.session_state[variant_key] = None
                st.caption("No variants")
            else:
                selected_variant = st.selectbox("Variant", available_variants, key=variant_key)
            available_implementations = implementations(selected_strategy, selected_variant)
            if st.session_state.get(implementation_key) not in available_implementations:
                st.session_state[implementation_key] = available_implementations[0]
            if implementation_dropdown:
                st.selectbox("Implementation", available_implementations, key=implementation_key)
            else:
                st.segmented_control("Implementation", available_implementations, default=st.session_state[implementation_key], key=implementation_key, selection_mode="single")
    else:
        strategy_column, variant_column, implementation_column = columns
        with strategy_column:
            selected_strategy = st.selectbox("Strategy", available_strategies, key=strategy_key)
        available_variants = variants(selected_strategy)
        if st.session_state.get(variant_key) not in available_variants:
            st.session_state[variant_key] = available_variants[0]
        with variant_column:
            if available_variants == (None,):
                selected_variant = None
                st.session_state[variant_key] = None
                st.caption("No variant")
            else:
                selected_variant = st.selectbox("Variant", available_variants, key=variant_key)
        available_implementations = implementations(selected_strategy, selected_variant)
        if st.session_state.get(implementation_key) not in available_implementations:
            st.session_state[implementation_key] = available_implementations[0]
        with implementation_column:
            if implementation_dropdown:
                st.selectbox("Implementation", available_implementations, key=implementation_key)
            else:
                st.segmented_control("Implementation", available_implementations, default=st.session_state[implementation_key], key=implementation_key, selection_mode="single")
    return resolve(selected_strategy, selected_variant, st.session_state[implementation_key]).label


def execution_assets(decision: pd.Series, benchmark_asset: str) -> tuple[str, ...]:
    """Return individual holdings required to find an executable next date.

    Multi-asset strategies store their display label as a comma-separated
    string, but price lookup must receive the underlying asset symbols.
    """
    weights = decision.get("target_weights")
    holdings = tuple(weights) if isinstance(weights, dict) else (str(decision["selected_asset"]),)
    return tuple(dict.fromkeys((*holdings, benchmark_asset)))


def append_missing_default_tickers(text: str) -> str:
    """Retain custom sources while migrating saved sessions to new model assets."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    roles = {line.split("=", 1)[0].strip().upper() for line in lines if "=" in line}
    # Older sessions included Yahoo placeholders for Israeli assets.  Those
    # values must not quietly override the dedicated TASE/Maya adapter.
    lines = [line for line in lines if line.split("=", 1)[0].strip().upper() not in TASE_ASSETS]
    defaults = default_ticker_map(YAHOO_ASSETS)
    lines.extend(f"{asset}={defaults[asset]}" for asset in YAHOO_ASSETS if asset not in roles)
    return "\n".join(lines)


def substitution_ticker_map(
    base_tickers: dict[str, str], yahoo_substitutions: dict[str, str]
) -> dict[str, str]:
    """Return a second role-to-ticker map without changing the published run.

    Strategy classes continue to receive their canonical asset-role columns
    (for example ``SPY`` or ``IEF``). The selected-source comparison changes only the
    Yahoo series placed into those columns, so it can run the exact same rules
    beside the unmodified published inputs.
    """
    return {asset: yahoo_substitutions.get(asset, ticker) for asset, ticker in base_tickers.items()}


def portfolio_payload(sleeves: list[dict], total_ils: float, ils_per_usd: float, name: str) -> dict:
    """Return the small, browser-only configuration used by Today."""
    return {
        "version": 1,
        "name": name.strip() or "My portfolio",
        "sleeves": [
            {"id": int(sleeve["id"]), "weight": float(sleeve["weight"]), "model": sleeve["model"]}
            for sleeve in sleeves
        ],
        "total_ils": float(total_ils),
        "ils_per_usd": float(ils_per_usd),
    }


def apply_browser_portfolio(payload: object, *, as_default: bool = False) -> bool:
    """Validate an untrusted browser payload before placing it in session state."""
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return False
    sleeves = payload.get("sleeves")
    if not isinstance(sleeves, list) or not sleeves:
        return False
    cleaned_sleeves = []
    for position, sleeve in enumerate(sleeves, start=1):
        if not isinstance(sleeve, dict) or sleeve.get("model") not in MODEL_OPTIONS:
            return False
        try:
            weight = float(sleeve["weight"])
        except (KeyError, TypeError, ValueError):
            return False
        if not 0 <= weight <= 100:
            return False
        cleaned_sleeves.append({"id": position, "weight": weight, "model": sleeve["model"]})
    try:
        total_ils = max(0.0, float(payload.get("total_ils", 0.0)))
        ils_per_usd = float(payload.get("ils_per_usd", 3.7))
    except (TypeError, ValueError):
        return False
    if ils_per_usd <= 0:
        return False
    # Model selector and weight widgets retain their own session values. Clear
    # them before loading so the saved sleeve choices are not overwritten on
    # the next Streamlit render.
    for key in list(st.session_state):
        if key.startswith("portfolio_") and any(
            token in key for token in ("_strategy", "_variant", "_implementation", "_weight", "_model", "_currency_")
        ):
            del st.session_state[key]
    st.session_state["portfolio_sleeves"] = cleaned_sleeves
    st.session_state["portfolio_next_id"] = len(cleaned_sleeves) + 1
    st.session_state["portfolio_total_ils"] = total_ils
    st.session_state["portfolio_fx_rate"] = ils_per_usd
    st.session_state["portfolio_name"] = str(payload.get("name", "My portfolio"))[:80] or "My portfolio"
    for sleeve in cleaned_sleeves:
        definition = definition_for_label(sleeve["model"])
        prefix = f"portfolio_{sleeve['id']}"
        st.session_state[f"{prefix}_strategy"] = definition.strategy
        st.session_state[f"{prefix}_variant"] = definition.variant
        st.session_state[f"{prefix}_implementation"] = definition.implementation
        st.session_state[f"{prefix}_weight"] = sleeve["weight"]
    if as_default:
        st.session_state["browser_default_portfolio"] = portfolio_payload(cleaned_sleeves, total_ils, ils_per_usd, st.session_state["portfolio_name"])
    return True


def store_portfolio_in_browser(payload: dict | None) -> None:
    """Write or remove the default portfolio in this browser only."""
    payload_json = json.dumps(payload, separators=(",", ":")) if payload is not None else ""
    components.html(
        f"""
        <script>
        try {{
          const storage = window.parent.localStorage;
          const key = {json.dumps(PORTFOLIO_STORAGE_KEY)};
          const value = {json.dumps(payload_json)};
          if (value) storage.setItem(key, value); else storage.removeItem(key);
        }} catch (error) {{ console.warn("Portfolio storage is unavailable", error); }}
        </script>
        """,
        height=0,
        width=0,
    )


def store_portfolio_library_in_browser(portfolios: list[dict]) -> None:
    """Save the named portfolio library in this browser only."""
    payload_json = json.dumps({"version": 1, "portfolios": portfolios}, separators=(",", ":"))
    components.html(
        f"""
        <script>
        try {{ window.parent.localStorage.setItem({json.dumps(PORTFOLIO_LIBRARY_STORAGE_KEY)}, {json.dumps(payload_json)}); }}
        catch (error) {{ console.warn("Portfolio library storage is unavailable", error); }}
        </script>
        """,
        height=0,
        width=0,
    )


def apply_browser_portfolio_library(payload: object) -> bool:
    """Validate the browser-only named portfolio library without loading one."""
    if not isinstance(payload, dict) or payload.get("version") != 1 or not isinstance(payload.get("portfolios"), list):
        return False
    portfolios: list[dict] = []
    seen_names: set[str] = set()
    state_keys = ("portfolio_sleeves", "portfolio_next_id", "portfolio_total_ils", "portfolio_fx_rate", "portfolio_name", "browser_default_portfolio")
    for candidate in payload["portfolios"]:
        snapshot = {key: st.session_state[key] for key in state_keys if key in st.session_state}
        def restore_snapshot() -> None:
            for key in state_keys:
                if key in snapshot:
                    st.session_state[key] = snapshot[key]
                elif key in st.session_state:
                    del st.session_state[key]
        if not apply_browser_portfolio(candidate):
            restore_snapshot()
            return False
        cleaned = portfolio_payload(st.session_state["portfolio_sleeves"], st.session_state["portfolio_total_ils"], st.session_state["portfolio_fx_rate"], st.session_state["portfolio_name"])
        restore_snapshot()
        name_key = cleaned["name"].casefold()
        if name_key not in seen_names:
            portfolios.append(cleaned)
            seen_names.add(name_key)
    st.session_state["browser_portfolio_library"] = portfolios
    return True


def request_browser_portfolio() -> None:
    """Ask the browser for its saved portfolio through a one-time URL handoff."""
    if st.session_state.get("browser_portfolio_checked"):
        return
    components.html(
        f"""
        <script>
        try {{
          const parentWindow = window.parent;
          const url = new URL(parentWindow.location.href);
          const encode = (value) => btoa(unescape(encodeURIComponent(value)))
            .replace(/\\+/g, "-").replace(/\\//g, "_").replace(/=+$/, "");
          const saved = parentWindow.localStorage.getItem({json.dumps(PORTFOLIO_STORAGE_KEY)});
          const library = parentWindow.localStorage.getItem({json.dumps(PORTFOLIO_LIBRARY_STORAGE_KEY)});
          if (saved && !url.searchParams.has("portfolio_state")) url.searchParams.set("portfolio_state", encode(saved));
          if (library && !url.searchParams.has("portfolio_library_state")) url.searchParams.set("portfolio_library_state", encode(library));
          if (url.searchParams.has("portfolio_state") || url.searchParams.has("portfolio_library_state")) parentWindow.location.replace(url.toString());
        }} catch (error) {{ console.warn("Portfolio storage is unavailable", error); }}
        </script>
        """,
        height=0,
        width=0,
    )


for key, value in {
    "model_name": DEFAULT_MODEL,
    "signals_model_name": DEFAULT_MODEL,
    "page": "Today",
    "ticker_text": DEFAULT_TICKERS,
    "initial": 100_000.0,
    "cost_pct": 0.0,
    "tax_enabled": False,
    "tax_rate": DEFAULT_TAX_RATE,
    "compare_initial": 100_000.0,
    "compare_cost_pct": 0.0,
    "compare_tax_enabled": False,
    "compare_tax_rate": DEFAULT_TAX_RATE,
    "uploaded_replacements": {},
    "portfolio_sleeves": [{"id": 1, "weight": 100.0, "model": DEFAULT_MODEL}],
    "portfolio_next_id": 2,
    "portfolio_base_currency": "USD",
    "portfolio_name": "My portfolio",
    "browser_default_portfolio": None,
    "browser_portfolio_library": [],
    "browser_portfolio_checked": False,
    "backtest_mode": "Single strategy",
    "backtest_sleeves": [{"id": 1, "weight": 100.0, "model": DEFAULT_MODEL}],
    "backtest_next_id": 2,
    "deep_proxy_mode": "Single strategy",
    "deep_proxy_primary": "century_momentum",
    "deep_proxy_secondary": "inflation_compass",
    "deep_proxy_primary_weight": 70.0,
    "research_model_name": DEFAULT_MODEL,
}.items():
    st.session_state.setdefault(key, value)

# Browser storage is used only for named portfolios and the optional Today
# default. It never leaves the browser other than a short-lived handoff used
# to restore the Streamlit session after a reload.
encoded_browser_portfolio = st.query_params.get("portfolio_state")
encoded_browser_portfolio_library = st.query_params.get("portfolio_library_state")
if encoded_browser_portfolio and not st.session_state["browser_portfolio_checked"]:
    try:
        padded = str(encoded_browser_portfolio) + "=" * (-len(str(encoded_browser_portfolio)) % 4)
        decoded_browser_portfolio = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        apply_browser_portfolio(decoded_browser_portfolio, as_default=True)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    st.session_state["browser_portfolio_checked"] = True
    del st.query_params["portfolio_state"]
if encoded_browser_portfolio_library:
    try:
        padded = str(encoded_browser_portfolio_library) + "=" * (-len(str(encoded_browser_portfolio_library)) % 4)
        apply_browser_portfolio_library(json.loads(base64.urlsafe_b64decode(padded).decode("utf-8")))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        pass
    del st.query_params["portfolio_library_state"]
if encoded_browser_portfolio or encoded_browser_portfolio_library:
    st.session_state["browser_portfolio_checked"] = True
if not encoded_browser_portfolio and not encoded_browser_portfolio_library:
    request_browser_portfolio()

seed_model_selection("signals", st.session_state["signals_model_name"])
seed_model_selection("backtest", st.session_state["model_name"])
seed_model_selection("rules", st.session_state["model_name"])
seed_model_selection("research", st.session_state["research_model_name"])
st.session_state.setdefault("settings_cost_pct", st.session_state["cost_pct"] * 100)
st.session_state.setdefault("settings_tax_rate", st.session_state["tax_rate"] * 100)
if st.session_state["page"] == "Validation":
    st.session_state["page"] = "Research"
if st.session_state["page"] == "Compare Models":
    st.session_state["page"] = "Compare"
st.session_state["ticker_text"] = append_missing_default_tickers(st.session_state["ticker_text"])

with st.container(key="primary-navigation"):
    page = st.radio("Primary navigation", ("Today", "Signals", "Portfolio", "Backtest", "Research", "Compare", "Rules"), horizontal=True, label_visibility="collapsed", key="page")
title_column = st.container()

# Signals has its own selector.  Use its saved selection for the early data
# validation below; otherwise an unavailable *Backtest* selection can prevent
# the Signals selector from ever being rendered.
model_name = st.session_state["signals_model_name"] if page == "Signals" else st.session_state["model_name"]
ticker_text = st.session_state["ticker_text"]
initial = st.session_state["initial"]
cost_pct = st.session_state["cost_pct"]
tax_enabled = st.session_state["tax_enabled"]
tax_rate = st.session_state["tax_rate"]
uploads = []
backtest_configuration = None

if page == "Backtest":
    backtest_configuration = st.container(key="backtest-configuration")
    with backtest_configuration:
        st.header("Backtest configuration")
        st.caption("Choose a model and assumptions, then review the summary below. Advanced data controls are optional.")
        investment_column, cost_column = st.columns(2)
        with investment_column:
            st.number_input("Initial investment", min_value=1.0, key="initial", step=1_000.0)
        with cost_column:
            st.number_input("Transaction cost per entry/change (%)", min_value=0.0, max_value=10.0, step=0.01, key="settings_cost_pct")
        backtest_mode = st.radio("Backtest mode", ("Single strategy", "Portfolio", "Deep History / Proxy"), horizontal=True, key="backtest_mode")
        if backtest_mode == "Single strategy":
            model_name = model_selector("backtest", "Model")
            st.session_state["model_name"] = model_name
            st.toggle("Israeli capital-gains tax", key="tax_enabled")
            st.number_input("Tax rate (%)", min_value=0.0, max_value=100.0, step=0.1, disabled=not st.session_state["tax_enabled"], key="settings_tax_rate")
        elif backtest_mode == "Portfolio":
            st.subheader("Portfolio sleeves")
            st.caption("Each sleeve uses the same strategy selection as Portfolio. Sleeve weights reset to their targets at every month-end.")
            configured_sleeves = st.session_state["backtest_sleeves"]
            controls, add_column, remove_column = st.columns([7, 0.5, 0.5])
            with add_column:
                add_backtest_sleeve = st.button("+", key="backtest_add_sleeve", help="Add sleeve")
            with remove_column:
                remove_backtest_sleeve = st.button("-", key="backtest_remove_sleeve", help="Remove the last sleeve", disabled=len(configured_sleeves) == 1)
            updated_backtest_sleeves = []
            for sleeve in configured_sleeves:
                sleeve_id = sleeve["id"]
                prefix = f"backtest_sleeve_{sleeve_id}"
                seed_model_selection(prefix, sleeve.get("model", DEFAULT_MODEL))
                with st.container(key=f"{prefix}-row"):
                    strategy_column, variant_column, implementation_column, weight_column = st.columns([1.15, 1.3, 1.6, 0.7])
                    sleeve_model = model_selector(prefix, columns=(strategy_column, variant_column, implementation_column), implementation_dropdown=True)
                    with weight_column:
                        sleeve_weight = st.number_input("Weight (%)", min_value=0.0, max_value=100.0, value=float(sleeve["weight"]), step=1.0, key=f"{prefix}_weight")
                updated_backtest_sleeves.append({"id": sleeve_id, "weight": float(sleeve_weight), "model": sleeve_model})
            st.session_state["backtest_sleeves"] = updated_backtest_sleeves
            if add_backtest_sleeve:
                next_id = st.session_state["backtest_next_id"]
                st.session_state["backtest_next_id"] = next_id + 1
                st.session_state["backtest_sleeves"].append({"id": next_id, "weight": 0.0, "model": DEFAULT_MODEL})
                st.rerun()
            if remove_backtest_sleeve:
                st.session_state["backtest_sleeves"] = updated_backtest_sleeves[:-1]
                st.rerun()
            backtest_weight_total = total_weight(updated_backtest_sleeves)
            if abs(backtest_weight_total - 100.0) > 1e-9:
                st.warning(f"Sleeve weights total {backtest_weight_total:.2f}%. Set them to exactly 100% to run the portfolio backtest.")
            else:
                st.success("Sleeve weights total 100%.")
            st.toggle("Israeli capital-gains tax", key="tax_enabled")
            st.number_input("Tax rate (%)", min_value=0.0, max_value=100.0, step=0.1, disabled=not st.session_state["tax_enabled"], key="settings_tax_rate")
            st.caption("When enabled, tax applies to realized tactical sleeve sales and profitable sleeve reductions during monthly portfolio rebalancing. Unrealized gains are not taxed.")
        else:
            st.subheader("Proxy history configuration")
            st.caption("Bundled strategy-level monthly returns and signal histories extend beyond the available ETF/TASE price histories. Results are proxy backtests, not security-level historical returns.")
            deep_mode = st.radio("Proxy backtest type", ("Single strategy", "Portfolio blend"), horizontal=True, key="deep_proxy_mode")
            proxy_options = tuple(DEEP_HISTORY_SPECS)
            proxy_labels = {key: spec.label for key, spec in DEEP_HISTORY_SPECS.items()}
            if deep_mode == "Single strategy":
                st.selectbox("Proxy strategy", proxy_options, format_func=lambda key: proxy_labels[key], key="deep_proxy_primary")
            else:
                first_column, second_column, weight_column = st.columns((1.3, 1.3, 0.8))
                with first_column:
                    st.selectbox("First sleeve", proxy_options, format_func=lambda key: proxy_labels[key], key="deep_proxy_primary")
                with second_column:
                    st.selectbox("Second sleeve", proxy_options, format_func=lambda key: proxy_labels[key], key="deep_proxy_secondary")
                with weight_column:
                    st.number_input("First weight (%)", min_value=0.0, max_value=100.0, step=1.0, key="deep_proxy_primary_weight")
                first_weight = float(st.session_state["deep_proxy_primary_weight"])
                st.caption(f"Blend: {first_weight:.0f}% {proxy_labels[st.session_state['deep_proxy_primary']]} / {100 - first_weight:.0f}% {proxy_labels[st.session_state['deep_proxy_secondary']]}.")
            st.toggle("Israeli capital-gains tax", key="tax_enabled")
            st.number_input("Tax rate (%)", min_value=0.0, max_value=100.0, step=0.1, disabled=not st.session_state["tax_enabled"], key="settings_tax_rate")
            st.caption("Tax is applied using the existing realized-gain engine. Because these files contain strategy-level returns rather than security-level prices, tax realization at allocation changes is an explicit proxy approximation.")
        with st.expander("Advanced data controls", expanded=False):
            ticker_text = st.text_area("Yahoo Finance ticker sources", value=ticker_text, help="One asset role per line. Israeli roles CSPX_IL, IEF_IL, and AYALON_KASPIT always use public TASE/Maya data via tasekit; TIP and all other roles use Yahoo Finance.")
            uploads = st.file_uploader("Upload replacement CSV files", type="csv", accept_multiple_files=True, help=f"Upload one or more files named with one valid asset: {', '.join(ALL_MODEL_ASSETS)}.")
    st.session_state["ticker_text"] = ticker_text

st.session_state["cost_pct"] = st.session_state["settings_cost_pct"] / 100
st.session_state["tax_rate"] = st.session_state["settings_tax_rate"] / 100
tax_enabled = st.session_state["tax_enabled"]
tax_rate = st.session_state["tax_rate"]

if page == "Backtest" and backtest_mode == "Deep History / Proxy":
    proxy_mode = st.session_state["deep_proxy_mode"]
    proxy_specs = DEEP_HISTORY_SPECS
    try:
        if proxy_mode == "Single strategy":
            spec = proxy_specs[st.session_state["deep_proxy_primary"]]
            proxy_input = deep_history_model_input(spec)
            full_result = run_backtest(
                proxy_input.decisions,
                proxy_input.monthly_prices,
                initial,
                transaction_cost=cost_pct,
                tax_enabled=tax_enabled,
                tax_rate=tax_rate,
                benchmark_asset="SPY",
            )
            proxy_min = full_result.monthly.index.min().date()
            proxy_max = full_result.monthly.index.max().date()
            proxy_start = min(max(pd.Timestamp(st.session_state.get("deep_proxy_start", proxy_min)).date(), proxy_min), proxy_max)
            proxy_end = min(max(pd.Timestamp(st.session_state.get("deep_proxy_end", proxy_max)).date(), proxy_min), proxy_max)
            if proxy_start > proxy_end:
                proxy_start, proxy_end = proxy_min, proxy_max
            st.session_state["deep_proxy_start"] = proxy_start
            st.session_state["deep_proxy_end"] = proxy_end
            with backtest_configuration:
                st.caption(f"Available proxy holding periods: {proxy_min} to {proxy_max}.")
                proxy_start = st.date_input("Proxy backtest start", value=proxy_start, min_value=proxy_min, max_value=proxy_max, key="deep_proxy_start")
                proxy_end = st.date_input("Proxy backtest end", value=proxy_end, min_value=proxy_min, max_value=proxy_max, key="deep_proxy_end")
            result = run_backtest(
                proxy_input.decisions,
                proxy_input.monthly_prices,
                initial,
                transaction_cost=cost_pct,
                tax_enabled=tax_enabled,
                tax_rate=tax_rate,
                start=pd.Timestamp(proxy_start),
                end=pd.Timestamp(proxy_end),
                benchmark_asset="SPY",
            )
            title_column.title(f"{spec.label} — Deep History / Proxy")
            st.warning("Proxy result: the bundled CSV contains strategy-level returns and signals, not historical security prices. Capital-gains realization at allocation changes is therefore an approximation.")
            st.caption(f"Holding periods: {result.monthly.index.min().date()} through {result.monthly.index.max().date()}. No independent benchmark is implied by the synthetic SPY column.")
            proxy_label = f"{spec.label} proxy pre-tax"
            proxy_after_label = f"{spec.label} proxy after-tax"
            summary = pd.DataFrame({proxy_label: performance_metrics(result.monthly["pre_tax_value"], initial)})
            if tax_enabled:
                summary[proxy_after_label] = performance_metrics(result.monthly["after_tax_value"], initial)
            st.subheader("Results")
            result_columns = st.columns(4 if tax_enabled else 2)
            result_columns[0].metric("Proxy CAGR", f"{summary.loc['CAGR', proxy_label]:.2%}")
            if tax_enabled:
                result_columns[1].metric("After-tax CAGR", f"{summary.loc['CAGR', proxy_after_label]:.2%}", delta=f"{summary.loc['CAGR', proxy_after_label] - summary.loc['CAGR', proxy_label]:+.2%}")
                result_columns[2].metric("Pre-tax final value", f"{summary.loc['Final value', proxy_label]:,.0f}")
                result_columns[3].metric("After-tax final value", f"{summary.loc['Final value', proxy_after_label]:,.0f}")
            else:
                result_columns[1].metric("Final value", f"{summary.loc['Final value', proxy_label]:,.0f}")
            curves = pd.DataFrame({proxy_label: result.monthly["pre_tax_value"]})
            if tax_enabled:
                curves[proxy_after_label] = result.monthly["after_tax_value"]
            st.plotly_chart(px.line(curves, title="Proxy equity curve"), use_container_width=True)
            st.plotly_chart(px.line(curves.div(curves.cummax()).sub(1), title="Proxy drawdown"), use_container_width=True)
            with st.expander("Performance and tax details", expanded=False):
                proxy_percentage_rows = [row for row in ["CAGR", "Total return", "Maximum drawdown", "Annualized volatility", "Best month", "Worst month"] if row in summary.index]
                proxy_numeric_rows = [row for row in ["Final value", "Allocation changes", "Average changes/year"] if row in summary.index]
                st.dataframe(summary.style.format("{:.2%}", subset=pd.IndexSlice[proxy_percentage_rows, :]).format("{:.2f}", subset=pd.IndexSlice[proxy_numeric_rows, :]), use_container_width=True)
                st.caption(f"Realized-gain tax events recorded: {len(result.tax_events)}.")
            annual = annual_returns(result.monthly["pre_tax_monthly_return"]).to_frame(proxy_label)
            monthly_returns = result.monthly["pre_tax_monthly_return"].to_frame(proxy_label)
            if tax_enabled:
                annual[proxy_after_label] = annual_returns(result.monthly["after_tax_monthly_return"])
                monthly_returns[proxy_after_label] = result.monthly["after_tax_monthly_return"]
            with st.expander("Return history", expanded=False):
                annual_tab, monthly_tab = st.tabs(["Annual", "Monthly"])
                with annual_tab:
                    st.dataframe(annual.style.format("{:.2%}"), use_container_width=True)
                with monthly_tab:
                    st.dataframe(monthly_returns.style.format("{:.2%}"), use_container_width=True)
        else:
            first_key = st.session_state["deep_proxy_primary"]
            second_key = st.session_state["deep_proxy_secondary"]
            if first_key == second_key:
                raise ValueError("Choose two different proxy strategies for a blend.")
            first_weight = float(st.session_state["deep_proxy_primary_weight"]) / 100
            if not 0 < first_weight < 1:
                raise ValueError("The first proxy sleeve weight must be between 0% and 100%.")
            first_spec, second_spec = proxy_specs[first_key], proxy_specs[second_key]
            portfolio_inputs = {
                first_spec.label: (first_weight, deep_history_model_input(first_spec)),
                second_spec.label: (1 - first_weight, deep_history_model_input(second_spec)),
            }
            preliminary = run_portfolio_backtest(portfolio_inputs, initial, transaction_cost=cost_pct, tax_enabled=tax_enabled, tax_rate=tax_rate)
            proxy_min = preliminary.common_index.min().date()
            proxy_max = preliminary.common_index.max().date()
            proxy_start = min(max(pd.Timestamp(st.session_state.get("deep_proxy_start", proxy_min)).date(), proxy_min), proxy_max)
            proxy_end = min(max(pd.Timestamp(st.session_state.get("deep_proxy_end", proxy_max)).date(), proxy_min), proxy_max)
            if proxy_start > proxy_end:
                proxy_start, proxy_end = proxy_min, proxy_max
            st.session_state["deep_proxy_start"] = proxy_start
            st.session_state["deep_proxy_end"] = proxy_end
            with backtest_configuration:
                st.caption(f"Common proxy holding periods: {proxy_min} to {proxy_max}.")
                proxy_start = st.date_input("Proxy blend start", value=proxy_start, min_value=proxy_min, max_value=proxy_max, key="deep_proxy_start")
                proxy_end = st.date_input("Proxy blend end", value=proxy_end, min_value=proxy_min, max_value=proxy_max, key="deep_proxy_end")
            result = run_portfolio_backtest(
                portfolio_inputs,
                initial,
                transaction_cost=cost_pct,
                tax_enabled=tax_enabled,
                tax_rate=tax_rate,
                start=pd.Timestamp(proxy_start),
                end=pd.Timestamp(proxy_end),
            )
            title_column.title("Deep History / Proxy portfolio blend")
            st.warning("Proxy blend: strategy-level returns are combined over their shared history. Tax uses the existing realized-gain portfolio logic, with allocation-change realization treated as a proxy because security-level prices are unavailable.")
            st.caption(f"{first_weight:.0%} {first_spec.label} / {1 - first_weight:.0%} {second_spec.label}. Holding periods: {result.monthly.index.min().date()} through {result.monthly.index.max().date()}.")
            blend_label = "Proxy blend pre-tax"
            blend_after_label = "Proxy blend after-tax"
            summary = pd.DataFrame({blend_label: performance_metrics(result.monthly["pre_tax_value"], initial)})
            if tax_enabled:
                summary[blend_after_label] = performance_metrics(result.monthly["after_tax_value"], initial)
            st.subheader("Results")
            result_columns = st.columns(4 if tax_enabled else 2)
            result_columns[0].metric("Blend CAGR", f"{summary.loc['CAGR', blend_label]:.2%}")
            if tax_enabled:
                result_columns[1].metric("After-tax CAGR", f"{summary.loc['CAGR', blend_after_label]:.2%}", delta=f"{summary.loc['CAGR', blend_after_label] - summary.loc['CAGR', blend_label]:+.2%}")
                result_columns[2].metric("Pre-tax final value", f"{summary.loc['Final value', blend_label]:,.0f}")
                result_columns[3].metric("After-tax final value", f"{summary.loc['Final value', blend_after_label]:,.0f}")
            else:
                result_columns[1].metric("Final value", f"{summary.loc['Final value', blend_label]:,.0f}")
            curves = pd.DataFrame({blend_label: result.monthly["pre_tax_value"]})
            if tax_enabled:
                curves[blend_after_label] = result.monthly["after_tax_value"]
            st.plotly_chart(px.line(curves, title="Proxy blend equity curve"), use_container_width=True)
            st.plotly_chart(px.line(curves.div(curves.cummax()).sub(1), title="Proxy blend drawdown"), use_container_width=True)
            with st.expander("Performance and tax details", expanded=False):
                proxy_percentage_rows = [row for row in ["CAGR", "Total return", "Maximum drawdown", "Annualized volatility", "Best month", "Worst month"] if row in summary.index]
                proxy_numeric_rows = [row for row in ["Final value", "Allocation changes", "Average changes/year"] if row in summary.index]
                st.dataframe(summary.style.format("{:.2%}", subset=pd.IndexSlice[proxy_percentage_rows, :]).format("{:.2f}", subset=pd.IndexSlice[proxy_numeric_rows, :]), use_container_width=True)
                st.caption(f"Realized-gain tax events recorded: {len(result.tax_events)}.")
            annual = annual_returns(result.monthly["pre_tax_monthly_return"]).to_frame(blend_label)
            monthly_returns = result.monthly["pre_tax_monthly_return"].to_frame(blend_label)
            if tax_enabled:
                annual[blend_after_label] = annual_returns(result.monthly["after_tax_monthly_return"])
                monthly_returns[blend_after_label] = result.monthly["after_tax_monthly_return"]
            with st.expander("Return history", expanded=False):
                annual_tab, monthly_tab = st.tabs(["Annual", "Monthly"])
                with annual_tab:
                    st.dataframe(annual.style.format("{:.2%}"), use_container_width=True)
                with monthly_tab:
                    st.dataframe(monthly_returns.style.format("{:.2%}"), use_container_width=True)
    except (ValueError, KeyError, OSError) as exc:
        title_column.title("Deep History / Proxy backtest")
        st.error(str(exc))
    st.stop()

if page == "Rules":
    model_name = model_selector("rules", "Choose model")
if page == "Research":
    model_name = model_selector("research", "Model")
    st.session_state["research_model_name"] = model_name

backtest_mode = st.session_state["backtest_mode"]
strategy = MODEL_OPTIONS[model_name]()
model_definition = definition_for_label(model_name)
research_profile = profile_for(strategy)
if page in {"Backtest", "Rules"} and backtest_mode == "Single strategy" and not getattr(strategy, "backtest_available", True):
    title_column.title(strategy.name)
    st.info("Signals and Portfolio use the unchanged USD Compass inputs and map the final holdings to Israeli securities. Backtesting is unavailable until reliable historical prices for those Israeli execution securities are configured.")
    st.stop()
if page == "Research" and research_profile is None:
    title_column.title("Research")
    st.info(f"{strategy.name} does not yet declare a validation profile. Add one beside the strategy implementation before running research validation.")
    st.stop()
if page == "Research" and not getattr(strategy, "backtest_available", True):
    title_column.title("Research")
    st.info(f"{strategy.name} has a validation profile, but its executable historical-price data is not available for research backtests yet.")
    st.stop()
data_assets = getattr(strategy, "data_assets", ASSETS)
benchmark_asset = getattr(strategy, "benchmark_asset", "SPY")
benchmark_label = f"{benchmark_asset} buy-and-hold"

try:
    ticker_map = parse_ticker_map(ticker_text, YAHOO_ASSETS)
except (ValueError, TypeError) as exc:
    st.error(str(exc))
    st.stop()

substitution_mode = "Original"
yahoo_substitutions: dict[str, str] = {}
tase_substitutions: dict[str, str] = {}
if page == "Backtest" and backtest_mode == "Single strategy":
    substitutable_assets = tuple(asset for asset in data_assets if asset not in (*FRED_ASSETS, OECD_CLI_DIFFUSION_ASSET))
    with backtest_configuration:
        st.divider()
        substitution_mode = st.segmented_control(
            "Asset sources",
            ("Original", "Israeli defaults", "Custom"),
            default="Original",
            key="substitution_mode",
            help="Original preserves published inputs. Israeli defaults use available locally traded TASE implementations. Custom lets you select Yahoo Finance tickers or numeric TASE security IDs for individual asset roles.",
        )
        if substitution_mode == "Israeli defaults":
            for asset in substitutable_assets:
                security_id = ISRAEL_DEFAULT_TASE_SUBSTITUTIONS.get(asset)
                if security_id:
                    tase_substitutions[asset] = security_id
            mapped = [f"{asset} -> TASE {security_id}" for asset, security_id in tase_substitutions.items()]
            unmapped = [asset for asset in substitutable_assets if asset not in tase_substitutions]
            if mapped:
                st.success("Israeli defaults: " + ", ".join(mapped))
            if unmapped:
                st.info("No Israeli default is configured for: " + ", ".join(unmapped) + ". Those roles keep their original data.")
            st.caption("Defaults are practical local implementations, not claims of identical exposures or returns. Public TASE history can be materially shorter than Yahoo history.")
        elif substitution_mode == "Custom":
            st.caption(
                "Choose the data source for each role. A TASE entry is a numeric security ID, not an index code. The strategy rules remain unchanged, but the selected source replaces that role's price history."
            )
            for asset in substitutable_assets:
                source_column, kind_column, replacement_column = st.columns((1, 1.05, 1.4))
                with source_column:
                    baseline = ticker_map.get(asset, f"TASE {TASE_ISRAEL_ASSET_IDS.get(asset, asset)}")
                    st.text_input(f"{asset} original", value=baseline, disabled=True, key=f"published_ticker_{asset}")
                with kind_column:
                    source_kind = st.selectbox("Source", ("Original", "Yahoo Finance", "TASE security"), key=f"substitution_source_{model_name}_{asset}", label_visibility="collapsed")
                with replacement_column:
                    if source_kind == "Yahoo Finance":
                        replacement = st.text_input(f"{asset} Yahoo ticker", placeholder="Example: EFA", key=f"substitution_yahoo_{model_name}_{asset}").strip().upper()
                    elif source_kind == "TASE security":
                        replacement = st.text_input(f"{asset} TASE security ID", placeholder="Example: 1159250", key=f"substitution_tase_{model_name}_{asset}").strip()
                    else:
                        replacement = ""
                        st.caption("Keep original")
                if source_kind == "Yahoo Finance" and replacement:
                    yahoo_substitutions[asset] = replacement
                elif source_kind == "TASE security" and replacement:
                    tase_substitutions[asset] = replacement
            if tase_substitutions and any(not identifier.isdigit() for identifier in tase_substitutions.values()):
                st.error("Each custom TASE security ID must contain digits only.")
                st.stop()
            chosen = [*(f"{asset} -> Yahoo {ticker}" for asset, ticker in yahoo_substitutions.items()), *(f"{asset} -> TASE {identifier}" for asset, identifier in tase_substitutions.items())]
            if chosen:
                st.success("Custom sources: " + ", ".join(chosen))
            else:
                st.info("Select at least one Yahoo ticker or TASE security ID, or choose Original mode.")

@st.cache_data(ttl=3600, show_spinner="Downloading Yahoo Finance price history...")
def load_data(source_items: tuple[tuple[str, str], ...]):
    return download_yahoo_prices(dict(source_items))


@st.cache_data(ttl=6 * 60 * 60, show_spinner="Downloading FRED macro data...")
def load_fred_data():
    return download_fred_series(FRED_ASSETS)


@st.cache_data(ttl=6 * 60 * 60, show_spinner="Downloading OECD CLI macro data...")
def load_oecd_cli_data():
    return download_oecd_cli_diffusion()


def monthly_strategy_input(daily_prices: pd.DataFrame, market_assets: tuple[str, ...]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Build tradable month-ends plus forward-filled signal-only macro inputs."""
    monthly_market = to_month_end(daily_prices.loc[:, list(market_assets)])
    auxiliary = daily_prices.drop(columns=list(market_assets), errors="ignore")
    if auxiliary.empty:
        return monthly_market, monthly_market
    values = auxiliary.reindex(monthly_market.index, method="ffill")
    return monthly_market, monthly_market.join(values)


@st.cache_data(ttl=6 * 60 * 60, show_spinner="Downloading public TASE/Maya price history...")
def load_tase_data():
    """Cache successful public-source requests and avoid repeated TASE traffic."""
    return download_tase_israel_prices()


@st.cache_data(ttl=6 * 60 * 60, show_spinner="Downloading selected TASE security history...")
def load_tase_substitution_data(source_items: tuple[tuple[str, str], ...]):
    """Cache custom TASE security lookups by canonical role and security ID."""
    return download_tase_security_prices(dict(source_items))

try:
    downloaded = load_data(tuple(ticker_map.items()))
except Exception as exc:
    st.error(f"Yahoo Finance download failed: {exc}")
    st.stop()

substitution_downloaded: pd.DataFrame | None = None
if yahoo_substitutions:
    try:
        substitution_downloaded = load_data(
            tuple(substitution_ticker_map(ticker_map, yahoo_substitutions).items())
        )
    except Exception as exc:
        st.error(f"Selected-source Yahoo data download failed: {exc}")
        st.stop()

try:
    fred_prices = load_fred_data()
    fred_warning: str | None = None
except Exception as exc:
    # FRED is required only by Inflation Compass; keep existing models usable.
    fred_warning = str(exc)
    fred_prices = pd.DataFrame(columns=FRED_ASSETS, dtype=float)

try:
    oecd_prices = load_oecd_cli_data()
    oecd_warning: str | None = None
except Exception as exc:
    oecd_warning = str(exc)
    oecd_prices = pd.DataFrame(columns=[OECD_CLI_DIFFUSION_ASSET], dtype=float)

tase_warning: str | None = None
try:
    tase_prices, tase_metadata = load_tase_data()
except TaseDataError as exc:
    # Do not take down US models if the public TASE/Maya site is unavailable.
    # CSV uploads remain a deliberate, visible fallback for the Israel model.
    tase_warning = str(exc)
    tase_prices = pd.DataFrame(columns=TASE_ASSETS, dtype=float)
    tase_metadata = pd.DataFrame(
        {"source": "TASE/Maya via tasekit (unavailable)", "identifier": [TASE_ISRAEL_ASSET_IDS[asset] for asset in TASE_ASSETS], "price_field": "Unavailable"},
        index=pd.Index(TASE_ASSETS, name="asset"),
    )

substitution_tase_prices: pd.DataFrame | None = None
if tase_substitutions:
    try:
        substitution_tase_prices, _ = load_tase_substitution_data(tuple(tase_substitutions.items()))
    except TaseDataError as exc:
        st.error(f"TASE substitution data failed: {exc}")
        st.stop()

replacements = st.session_state["uploaded_replacements"].copy()
if page == "Backtest":
    replacements = {}
    for upload in uploads or []:
        try:
            asset = upload_asset_from_filename(upload.name, ALL_MODEL_ASSETS)
            if asset in replacements:
                raise ValueError(f"More than one upload targets {asset}; upload only one replacement file per canonical role.")
            replacements[asset] = read_uploaded_csv(upload.getvalue(), asset)
        except ValueError as exc:
            st.error(str(exc))
    st.session_state["uploaded_replacements"] = replacements
downloaded_all = downloaded.join(tase_prices, how="outer").join(fred_prices, how="outer").join(oecd_prices, how="outer")
all_prices = combine_replacements(downloaded_all, replacements, ALL_MODEL_ASSETS)
substitution_all_prices: pd.DataFrame | None = None
if substitution_downloaded is not None or substitution_tase_prices is not None:
    substitution_all_prices = all_prices.copy()
    for asset in yahoo_substitutions:
        # Assign by index rather than replacing the full frame: macro, TASE,
        # and uploaded CSV inputs remain identical in both comparison runs.
        substitution_all_prices[asset] = substitution_downloaded[asset]
    if substitution_tase_prices is not None:
        for asset in tase_substitutions:
            substitution_all_prices[asset] = substitution_tase_prices[asset]
source_metadata = pd.DataFrame(
    {
        "source": "Yahoo Finance",
        "identifier": [ticker_map[asset] for asset in YAHOO_ASSETS],
        "price_field": "Adj Close (Close fallback)",
    },
    index=pd.Index(YAHOO_ASSETS, name="asset"),
)
source_metadata = pd.concat([source_metadata, tase_metadata]).reindex(ALL_MODEL_ASSETS)
for asset in FRED_ASSETS:
    source_metadata.loc[asset] = {"source": "FRED", "identifier": asset, "price_field": "Daily observation"}
source_metadata.loc[OECD_CLI_DIFFUSION_ASSET] = {"source": "OECD SDMX", "identifier": "CLI diffusion (dynamic country panel)", "price_field": "Monthly observation; one-month lag"}
for asset in replacements:
    source_metadata.loc[asset] = {"source": "User CSV replacement", "identifier": asset, "price_field": "Adj Close or Close"}

if page == "Backtest" and backtest_mode == "Portfolio":
    percentage_rows = ["CAGR", "Total return", "Maximum drawdown", "Annualized volatility", "Best month", "Worst month", "Annual turnover"]
    ratio_rows = ["Sharpe", "Sortino", "Calmar"]
    numeric_rows = ["Final value", "Allocation changes", "Average changes/year"]
    portfolio_sleeves = st.session_state["backtest_sleeves"]
    portfolio_weight_total = total_weight(portfolio_sleeves)
    if abs(portfolio_weight_total - 100.0) > 1e-9 or any(float(sleeve["weight"]) <= 0 for sleeve in portfolio_sleeves):
        title_column.title("Portfolio backtest")
        st.info("Set one or more positive sleeve weights totaling exactly 100% to run the portfolio backtest.")
        st.stop()
    try:
        portfolio_inputs = {}
        for sleeve in portfolio_sleeves:
            sleeve_name = sleeve["model"]
            sleeve_key = f"{sleeve_name} ({sleeve['id']})"
            sleeve_strategy = MODEL_OPTIONS[sleeve_name]()
            if not getattr(sleeve_strategy, "backtest_available", True):
                raise ValueError(f"{sleeve_name} is not available for backtesting.")
            sleeve_assets = tuple(dict.fromkeys((*getattr(sleeve_strategy, "data_assets", ASSETS), "SPY")))
            sleeve_daily = all_prices.loc[:, sleeve_assets]
            sleeve_market_assets = getattr(sleeve_strategy, "market_data_assets", sleeve_assets)
            sleeve_monthly, sleeve_decision_monthly = monthly_strategy_input(sleeve_daily, sleeve_market_assets)
            sleeve_decision_prices = sleeve_daily if getattr(sleeve_strategy, "uses_daily_signals", False) else sleeve_decision_monthly
            portfolio_inputs[sleeve_key] = (float(sleeve["weight"]) / 100, ModelInput(
                sleeve_key, sleeve_strategy.decisions(sleeve_decision_prices), sleeve_monthly, sleeve_daily, "SPY"
            ))
        preliminary_portfolio = run_portfolio_backtest(
            portfolio_inputs, initial, transaction_cost=cost_pct, tax_enabled=tax_enabled, tax_rate=tax_rate
        )
    except (ValueError, KeyError) as exc:
        title_column.title("Portfolio backtest")
        st.error(str(exc))
        st.stop()

    portfolio_start_min = preliminary_portfolio.common_index.min().date()
    portfolio_end_max = preliminary_portfolio.common_index.max().date()
    saved_portfolio_start = st.session_state.get("portfolio_backtest_start", portfolio_start_min)
    saved_portfolio_end = st.session_state.get("portfolio_backtest_end", portfolio_end_max)
    portfolio_start = min(max(saved_portfolio_start, portfolio_start_min), portfolio_end_max)
    portfolio_end = min(max(saved_portfolio_end, portfolio_start_min), portfolio_end_max)
    if portfolio_start > portfolio_end:
        portfolio_start = portfolio_start_min
    with backtest_configuration:
        st.caption(f"Common executable holding periods: {portfolio_start_min} to {portfolio_end_max}. The start date reflects the shortest available sleeve history.")
        portfolio_start = st.date_input("Portfolio backtest start", value=portfolio_start, min_value=portfolio_start_min, max_value=portfolio_end_max)
        portfolio_end = st.date_input("Portfolio backtest end", value=portfolio_end, min_value=portfolio_start_min, max_value=portfolio_end_max)
    st.session_state.update({"portfolio_backtest_start": portfolio_start, "portfolio_backtest_end": portfolio_end})
    try:
        portfolio_result = run_portfolio_backtest(
            portfolio_inputs,
            initial,
            transaction_cost=cost_pct,
            tax_enabled=tax_enabled,
            tax_rate=tax_rate,
            start=pd.Timestamp(portfolio_start),
            end=pd.Timestamp(portfolio_end),
        )
    except ValueError as exc:
        title_column.title("Portfolio backtest")
        st.error(str(exc))
        st.stop()

    title_column.title("Portfolio backtest")
    st.caption("Monthly sleeve rebalancing resets sleeve weights to targets at each month-end and uses only shared available history.")
    st.caption(f"Holding periods: {portfolio_result.monthly.index.min().date()} through {portfolio_result.monthly.index.max().date()}. SPY is the buy-and-hold benchmark.")
    portfolio_label = "Portfolio pre-tax"
    portfolio_after_tax_label = "Portfolio after-tax"
    benchmark_label = "SPY buy-and-hold"
    summary = pd.DataFrame({
        portfolio_label: performance_metrics(portfolio_result.monthly["pre_tax_value"], initial),
        benchmark_label: performance_metrics(portfolio_result.monthly["benchmark_value"], initial),
    })
    if tax_enabled:
        summary.insert(1, portfolio_after_tax_label, performance_metrics(portfolio_result.monthly["after_tax_value"], initial))
    portfolio_percentage_rows = [row for row in percentage_rows if row in summary.index]
    portfolio_numeric_rows = [row for row in ratio_rows + numeric_rows if row in summary.index]
    styled_summary = summary.style.format("{:.2%}", subset=pd.IndexSlice[portfolio_percentage_rows, :]).format("{:.2f}", subset=pd.IndexSlice[portfolio_numeric_rows, :])
    st.subheader("Results")
    result_columns = st.columns(4 if tax_enabled else 3)
    result_columns[0].metric("Portfolio CAGR", f"{summary.loc['CAGR', portfolio_label]:.2%}")
    if tax_enabled:
        result_columns[1].metric("After-tax CAGR", f"{summary.loc['CAGR', portfolio_after_tax_label]:.2%}", delta=f"{summary.loc['CAGR', portfolio_after_tax_label] - summary.loc['CAGR', portfolio_label]:+.2%}")
        result_columns[2].metric("Pre-tax final value", f"{summary.loc['Final value', portfolio_label]:,.0f}")
        result_columns[3].metric("After-tax final value", f"{summary.loc['Final value', portfolio_after_tax_label]:,.0f}")
    else:
        result_columns[1].metric("Maximum drawdown", f"{summary.loc['Maximum drawdown', portfolio_label]:.2%}")
        result_columns[2].metric("Final value", f"{summary.loc['Final value', portfolio_label]:,.0f}")
    curves = pd.DataFrame({portfolio_label: portfolio_result.monthly["pre_tax_value"], benchmark_label: portfolio_result.monthly["benchmark_value"]})
    if tax_enabled:
        curves.insert(1, portfolio_after_tax_label, portfolio_result.monthly["after_tax_value"])
    st.plotly_chart(px.line(curves, title="Equity curve"), use_container_width=True)
    st.plotly_chart(px.line(curves.div(curves.cummax()).sub(1), title="Drawdown"), use_container_width=True)
    with st.expander("Full performance table", expanded=False):
        st.dataframe(styled_summary, use_container_width=True)
    st.subheader("Selected sleeves")
    sleeve_summary = pd.DataFrame([
        {"Sleeve": sleeve["model"], "Target weight": sleeve["weight"] / 100,
         "CAGR": performance_metrics((1 + portfolio_result.sleeve_returns[f"{sleeve['model']} ({sleeve['id']})"]).cumprod() * initial, initial).get("CAGR"),
         "Total return": performance_metrics((1 + portfolio_result.sleeve_returns[f"{sleeve['model']} ({sleeve['id']})"]).cumprod() * initial, initial).get("Total return")}
        for sleeve in portfolio_sleeves
    ])
    st.dataframe(sleeve_summary.style.format({"Target weight": "{:.2%}", "CAGR": "{:.2%}", "Total return": "{:.2%}"}), use_container_width=True, hide_index=True)
    annual = pd.DataFrame({portfolio_label: annual_returns(portfolio_result.monthly["pre_tax_monthly_return"]), benchmark_label: annual_returns(portfolio_result.monthly["benchmark_monthly_return"])})
    monthly_returns = pd.DataFrame({portfolio_label: portfolio_result.monthly["pre_tax_monthly_return"], benchmark_label: portfolio_result.monthly["benchmark_monthly_return"]})
    if tax_enabled:
        annual.insert(1, portfolio_after_tax_label, annual_returns(portfolio_result.monthly["after_tax_monthly_return"]))
        monthly_returns.insert(1, portfolio_after_tax_label, portfolio_result.monthly["after_tax_monthly_return"])
    with st.expander("Return history", expanded=False):
        history_tab, monthly_tab = st.tabs(["Annual", "Monthly"])
        with history_tab:
            st.dataframe(annual.style.format("{:.2%}"), use_container_width=True)
        with monthly_tab:
            st.dataframe(monthly_returns.style.format("{:.2%}"), use_container_width=True)
    st.stop()
prices = all_prices.loc[:, data_assets]
market_data_assets = getattr(strategy, "market_data_assets", data_assets)
monthly, monthly_decision_input = monthly_strategy_input(prices, market_data_assets)
substitution_prices: pd.DataFrame | None = None
substitution_monthly: pd.DataFrame | None = None
substitution_decision_input: pd.DataFrame | None = None
all_monthly = to_month_end(all_prices)
ranges = date_ranges(prices)
common_start, common_end = common_monthly_period(monthly)

if substitution_all_prices is not None:
    substitution_prices = substitution_all_prices.loc[:, data_assets]
    substitution_monthly, substitution_decision_input = monthly_strategy_input(substitution_prices, market_data_assets)
    substitution_common_start, substitution_common_end = common_monthly_period(substitution_monthly)
    if substitution_common_start is None or substitution_common_end is None:
        st.error("The substituted assets have no common month-end history. Choose replacements with overlapping price history.")
        st.stop()
    # Both versions must use the same completed holding periods. This prevents
    # a newer replacement ETF from giving either result a different sample.
    if common_start is not None and common_end is not None:
        common_start = max(common_start, substitution_common_start)
        common_end = min(common_end, substitution_common_end)

if common_start is None or common_end is None or common_start > common_end:
    if isinstance(strategy, HAASimpleIsrael) and tase_warning:
        st.error(f"HAA-Simple Israel has no common month-end observations because its public TASE/Maya data source is unavailable. {tase_warning}")
    else:
        st.error("The selected model assets have no common month-end observations. Check the data sources or upload compatible CSV histories.")
    st.stop()
start = st.session_state.get("start", common_start.date())
execution_end_limit = prices.index.max().date()
if substitution_prices is not None:
    execution_end_limit = min(execution_end_limit, substitution_prices.index.max().date())
end = st.session_state.get("end", execution_end_limit)
# A model can have a shorter history than the previously configured model.
# Keep saved backtest dates valid when returning to its configuration page.
start = min(max(start, common_start.date()), common_end.date())
end = min(max(end, common_start.date()), execution_end_limit)
if start > end:
    start = common_start.date()
if page == "Backtest":
    with backtest_configuration:
        st.caption(f"Common monthly data: {common_start.date()} to {common_end.date()}")
        with st.expander("Data & validation"):
            st.caption("Available adjusted-price history for the assets required by the selected model.")
            st.dataframe(ranges, use_container_width=True, hide_index=True)
            st.caption(f"Actual common monthly data period: {common_start.date()} through {common_end.date()}.")
        start = st.date_input("Backtest start (holding-period end)", value=start, min_value=common_start.date(), max_value=common_end.date())
        end = st.date_input("Backtest end (holding-period execution date)", value=end, min_value=common_start.date(), max_value=execution_end_limit)
    st.session_state.update({"start": start, "end": end})

decision_prices = prices if getattr(strategy, "uses_daily_signals", False) else monthly_decision_input
decisions = strategy.decisions(decision_prices)
if decisions.empty:
    st.error(f"Insufficient history for {strategy.name}.")
    st.stop()
substitution_decisions: pd.DataFrame | None = None
if substitution_prices is not None and substitution_monthly is not None and substitution_decision_input is not None:
    substitution_signal_prices = substitution_prices if getattr(strategy, "uses_daily_signals", False) else substitution_decision_input
    substitution_decisions = strategy.decisions(substitution_signal_prices)
    if substitution_decisions.empty:
        st.error(f"Insufficient history for the substituted {strategy.name} run.")
        st.stop()
first_signal = decisions.index.min()
try:
    result = run_backtest(decisions, monthly, initial, cost_pct, tax_enabled, tax_rate, pd.Timestamp(start), pd.Timestamp(end), daily_prices=prices, benchmark_asset=benchmark_asset)
except ValueError as exc:
    st.error(str(exc))
    st.stop()
substitution_result = None
if substitution_decisions is not None and substitution_monthly is not None and substitution_prices is not None:
    try:
        substitution_result = run_backtest(
            substitution_decisions,
            substitution_monthly,
            initial,
            cost_pct,
            tax_enabled,
            tax_rate,
            pd.Timestamp(start),
            pd.Timestamp(end),
            daily_prices=substitution_prices,
            benchmark_asset=benchmark_asset,
        )
    except ValueError as exc:
        st.error(f"The substituted run could not be compared: {exc}")
        st.stop()

# Shared result-table formatting used by both Backtest and Compare Models.
percentage_rows = ["CAGR", "Total return", "Maximum drawdown", "Annualized volatility", "Best month", "Worst month", "Annual turnover"]
ratio_rows = ["Sharpe", "Sortino", "Calmar"]
numeric_rows = ["Final value", "Allocation changes", "Average changes/year"]

if page == "Research":
    title_column.title("Research")
    title_column.caption("Stress-test the selected strategy to see whether its historical result remains broadly credible when timing, costs, parameters, periods, data, and return sequences change. Validation runs are research-only and never modify live strategy rules.")
    with st.expander("How to read this page", expanded=False):
        st.markdown("""- **Summary** compares the published backtest with every completed stress-test scenario.
- **Parameters & Execution** asks whether nearby settings, small timing changes, costs, tax, or minor input-price changes materially alter the result.
- **Periods** shows whether the strategy worked across rolling 5-, 10-, and 20-year windows and named market eras, rather than only across one favourable start date.
- **Proxies & Data** checks practical implementation substitutes where declared and flags missing, stale, invalid, or potentially look-ahead-biased data.
- **Monte Carlo** reorders blocks of the strategy's actual monthly returns into many plausible paths. It is scenario analysis, not a forecast.
- **Robustness Scorecard** condenses the completed evidence. A stronger grade means the worst completed tests stayed closer to the published baseline; it is not an investment recommendation.

The useful question is not which strategy has the highest historical CAGR. It is whether a strategy remains reasonably similar when realistic assumptions change.""")
    st.info(f"Profile: **{research_profile.profile_id}** · Data confidence: **{research_profile.data_confidence.title()}**")
    with st.expander("Published baseline and declared research scope"):
        parameters = pd.DataFrame([
            {
                "Parameter": item.key,
                "Published value": item.published_value,
                "Research candidates": ", ".join(map(str, item.candidate_values)) or "None — immutable",
                "Description": item.description,
            }
            for item in research_profile.published_parameters
        ])
        st.dataframe(parameters, use_container_width=True, hide_index=True)
        st.caption(research_profile.notes or "Only the tests declared by this profile are run.")

    proxy_monthly_prices = {}
    proxy_daily_prices = {}
    for proxy in research_profile.proxy_substitutions:
        if proxy.proxy_asset in all_prices:
            proxy_monthly_prices[proxy.proxy_asset] = to_month_end(all_prices.loc[:, [proxy.proxy_asset]])[proxy.proxy_asset]
            proxy_daily_prices[proxy.proxy_asset] = all_prices[proxy.proxy_asset]
    research_input = ValidationInput(
        model_name,
        decisions,
        monthly,
        prices,
        benchmark_asset,
        research_profile,
        proxy_monthly_prices,
        proxy_daily_prices,
        strategy,
        decision_prices,
    )
    history_start, history_end = result.monthly.index.min(), result.monthly.index.max()
    history_years = len(result.monthly) / 12
    st.subheader("Quick confidence check")
    st.caption(
        f"History examined: {history_start:%B %Y}–{history_end:%B %Y} ({history_years:.1f} years). "
        "This is the shared period with usable data for every asset this model needs."
    )
    st.info("This checks whether the historical result stays broadly similar after realistic timing delays, costs, and different periods. It is not a prediction or a guarantee.")
    if st.button("Run confidence check", type="primary", key="run_full_validation"):
        with st.spinner("Running deterministic validation and block-bootstrap scenarios…"):
            st.session_state["research_report"] = run_deterministic_validation(research_input, initial)
        st.session_state["research_report_model"] = model_name
        st.session_state["research_report_completed"] = model_name

    report = st.session_state.get("research_report") if st.session_state.get("research_report_model") == model_name else None
    if report is None:
        st.caption("Run the confidence check to see a plain-English summary. Advanced technical results remain optional below.")
    else:
        if st.session_state.get("research_report_completed") == model_name:
            st.success("Confidence check completed for the currently selected model and data.")
        complete = report.scenarios.loc[report.scenarios["status"] == "complete"].copy()
        baseline_row = complete.loc[complete["test"] == "baseline"]
        overall = report.scorecard.loc[report.scorecard["Category"] == "Overall robustness"]
        grade = str(overall.iloc[0]["Grade"]) if not overall.empty else "Not assessed"
        plain_verdict = {
            "A": "Reasonably robust", "B+": "Reasonably robust", "B": "Reasonably robust",
            "C": "Mixed", "D": "Fragile", "Not assessed": "Not enough evidence yet",
        }.get(grade, "Mixed")
        verdict_column, cagr_column, drawdown_column = st.columns(3)
        verdict_column.metric("Historical confidence", plain_verdict)
        if not baseline_row.empty:
            baseline_metrics = baseline_row.iloc[0]
            cagr_column.metric("Historical CAGR", f"{baseline_metrics['CAGR']:.2%}")
            drawdown_column.metric("Historical max drawdown", f"{baseline_metrics['Maximum drawdown']:.2%}")
        else:
            cagr_column.metric("Historical CAGR", "Unavailable")
            drawdown_column.metric("Historical max drawdown", "Unavailable")
        evidence = report.scorecard.set_index("Category")["Evidence"] if not report.scorecard.empty else pd.Series(dtype=str)
        simple_rows = [
            {"Check": "Trading delays", "What it asks": "Would small delays in trading materially change the result?", "Result": evidence.get("Execution robustness", "Not assessed")},
            {"Check": "Trading costs", "What it asks": "Would realistic costs materially reduce the result?", "Result": evidence.get("Costs and tax resilience", "Not assessed")},
            {"Check": "Different periods", "What it asks": "Did it work across different historical windows, not only one lucky start?", "Result": evidence.get("Rolling-period resilience", "Not assessed")},
        ]
        st.subheader("The three checks that matter most")
        st.dataframe(pd.DataFrame(simple_rows), use_container_width=True, hide_index=True)
        st.subheader("What this means for me")
        if plain_verdict == "Reasonably robust":
            st.write("The available historical tests did not show a large dependence on one exact timing or assumption. That supports further consideration, but does not predict future returns.")
        elif plain_verdict == "Mixed":
            st.write("Some historical checks were less convincing. Treat the strategy as an idea to diversify with, rather than evidence that it will reliably perform on its own.")
        elif plain_verdict == "Fragile":
            st.write("The historical result changed materially in at least some realistic checks. Be cautious about relying on the published backtest alone.")
        else:
            st.write("There is not enough completed evidence to give a useful robustness verdict. The date range and available scenarios are shown above.")
        st.caption("Limits: this uses the price and macro histories available to the app. It cannot know future market conditions, your exact execution, or data revisions that were not available in real time.")
        with st.expander("Advanced research details", expanded=False):
            summary_tab, execution_tab, periods_tab, proxy_data_tab, monte_carlo_tab, scorecard_tab = st.tabs(["Summary", "Parameters & Execution", "Periods", "Proxies & Data", "Monte Carlo", "Robustness Scorecard"])
            with summary_tab:
                st.dataframe(report.scenarios, use_container_width=True, hide_index=True)
                if not complete.empty:
                    st.plotly_chart(px.bar(complete, x="scenario", y="CAGR", color="test", title="CAGR across completed validation scenarios"), use_container_width=True)
                st.download_button("Download validation scenarios CSV", report.scenarios.to_csv(index=False).encode("utf-8"), f"{strategy.name.lower().replace(' ', '_')}_validation_scenarios.csv", "text/csv")
        with execution_tab:
            execution_tests = report.scenarios.loc[report.scenarios["test"].isin(["parameter_sweep", "execution_delay", "transaction_cost", "israeli_tax", "alternate_start", "rebalance_shift", "signal_perturbation"])]
            st.dataframe(execution_tests, use_container_width=True, hide_index=True)
            st.caption("Parameter and shifted-date scenarios recompute a copied research instance only. Daily-signal strategies remain explicitly unavailable for generic rebalance shifts, rather than treating a later trade as a shifted signal.")
        with periods_tab:
            st.subheader("Rolling periods")
            st.dataframe(report.rolling_periods, use_container_width=True, hide_index=True)
            if not report.rolling_periods.empty and "CAGR" in report.rolling_periods:
                completed_rolling = report.rolling_periods.loc[report.rolling_periods["status"] == "complete"]
                if not completed_rolling.empty:
                    st.plotly_chart(px.box(completed_rolling, x="scenario", y="CAGR", title="Distribution of rolling-period CAGR"), use_container_width=True)
            st.subheader("Named subperiods")
            st.dataframe(report.subperiods, use_container_width=True, hide_index=True)
        with proxy_data_tab:
            proxy_rows = report.scenarios.loc[report.scenarios["test"] == "proxy_substitution"]
            st.subheader("Declared execution proxies")
            st.dataframe(proxy_rows, use_container_width=True, hide_index=True)
            st.caption("A proxy result is available only when the proxy's actual monthly and daily history is available. It replaces the executed holding, not the strategy's published signal input.")
            st.subheader("Data quality and timing")
            st.caption("Raw gaps can reflect ordinary exchange holidays, different publication schedules, or pre-inception history. They are shown for transparency, but do not lower the robustness score unless a price required for an actual execution path is missing.")
            st.dataframe(report.data_quality, use_container_width=True, hide_index=True)
            st.download_button("Download data-quality CSV", report.data_quality.to_csv(index=False).encode("utf-8"), f"{strategy.name.lower().replace(' ', '_')}_data_quality.csv", "text/csv")
        with monte_carlo_tab:
            st.caption("Circular block bootstrap of realised monthly strategy returns. It preserves short return sequences from history, uses a fixed seed for reproducibility, and is scenario analysis—not a forecast.")
            if report.monte_carlo.empty:
                st.info("This strategy has no declared block-bootstrap analysis.")
            else:
                st.dataframe(report.monte_carlo, use_container_width=True, hide_index=True)
                complete_bootstrap = report.monte_carlo.loc[report.monte_carlo["status"] == "complete"]
                if not complete_bootstrap.empty:
                    bootstrap_chart = complete_bootstrap.melt(id_vars="horizon", value_vars=["CAGR p10", "CAGR median", "CAGR p90"], var_name="Outcome", value_name="CAGR")
                    st.plotly_chart(px.bar(bootstrap_chart, x="horizon", y="CAGR", color="Outcome", barmode="group", title="Bootstrap CAGR range by horizon"), use_container_width=True)
                st.download_button("Download Monte Carlo CSV", report.monte_carlo.to_csv(index=False).encode("utf-8"), f"{strategy.name.lower().replace(' ', '_')}_block_bootstrap.csv", "text/csv")
        with scorecard_tab:
            overall = report.scorecard.loc[report.scorecard["Category"] == "Overall robustness"]
            if not overall.empty:
                st.metric("Overall robustness", str(overall.iloc[0]["Grade"]))
            st.caption("This is an evidence summary, not an investment rating or forecast. Its fixed bands compare the worst completed scenario CAGR with the published baseline; unrun or unavailable tests are shown as not assessed.")
            with st.expander("How the final robustness score is calculated", expanded=False):
                st.markdown("""
                Each completed evidence category is graded from its weakest completed result relative to the published baseline CAGR:

                - **Good (3 points):** no more than 2 percentage points below the baseline.
                - **Moderate (2 points):** more than 2, but no more than 5 percentage points below.
                - **Weak (1 point):** more than 5 percentage points below, or a failed data-integrity check.
                - **Not assessed:** the test was not declared, could not run, or lacked enough history. It does not count for or against the result.

                The overall grade is the average of the assessed categories, and needs at least four assessed categories. A is 2.75–3.00 points, B+ is 2.40–2.74, B is 2.00–2.39, C is 1.50–1.99, and D is below 1.50.

                **Data confidence is different:** ordinary calendar, holiday, and pre-inception gaps are reported but are not penalised. It is marked down only when a price needed at an actual entry, exit, or benchmark comparison is missing or invalid, or when the timing check cannot rule out look-ahead.
                """)
            st.dataframe(report.scorecard, use_container_width=True, hide_index=True)
            st.download_button("Download robustness scorecard CSV", report.scorecard.to_csv(index=False).encode("utf-8"), f"{strategy.name.lower().replace(' ', '_')}_robustness_scorecard.csv", "text/csv")
    st.stop()

if page == "Backtest":
    title_column.title(strategy.name)
    st.caption("These settings configure this backtest only.")
    st.caption("Signals are evaluated at month-end and execute for the following holding period; no optimization or synthetic history.")
    if substitution_result is not None:
        st.caption(
            f"{substitution_mode} comparison: both runs use the same strategy rules, costs, tax settings, and shared available holding periods."
        )
    if hasattr(strategy, "risk_warning"):
        st.warning(strategy.risk_warning)
    st.caption(f"Holding periods: {result.monthly.index.min().date()} through {result.monthly.index.max().date()}. SPY benchmark uses these same monthly periods.")
    pre_tax_label = f"Published {strategy.name} pre-tax" if substitution_result is not None else f"{strategy.name} pre-tax"
    after_tax_label = f"Published {strategy.name} after-tax" if substitution_result is not None else f"{strategy.name} after-tax"
    substitution_pre_tax_label = "Substituted strategy pre-tax"
    substitution_after_tax_label = "Substituted strategy after-tax"
    comparison = {pre_tax_label: performance_metrics(result.monthly["pre_tax_value"], initial)}
    if tax_enabled:
        comparison[after_tax_label] = performance_metrics(result.monthly["after_tax_value"], initial)
    if substitution_result is not None:
        comparison[substitution_pre_tax_label] = performance_metrics(substitution_result.monthly["pre_tax_value"], initial)
        if tax_enabled:
            comparison[substitution_after_tax_label] = performance_metrics(substitution_result.monthly["after_tax_value"], initial)
    # Keep the benchmark at the far right; the after-tax strategy result sits
    # beside its pre-tax counterpart for direct capital-gains comparison.
    comparison[benchmark_label] = performance_metrics(result.monthly["benchmark_value"], initial)
    summary = pd.DataFrame(comparison)
    changes = int(result.monthly["allocation_change"].sum())
    years = len(result.monthly) / 12
    annual_turnover = result.monthly["turnover"].sum() / years if "turnover" in result.monthly and years else changes / years if years else 0
    summary.loc["Allocation changes", pre_tax_label] = changes
    summary.loc["Average changes/year", pre_tax_label] = changes / years if years else 0
    summary.loc["Annual turnover", pre_tax_label] = annual_turnover
    if substitution_result is not None:
        substitution_changes = int(substitution_result.monthly["allocation_change"].sum())
        substitution_years = len(substitution_result.monthly) / 12
        substitution_turnover = substitution_result.monthly["turnover"].sum() / substitution_years if "turnover" in substitution_result.monthly and substitution_years else substitution_changes / substitution_years if substitution_years else 0
        summary.loc["Allocation changes", substitution_pre_tax_label] = substitution_changes
        summary.loc["Average changes/year", substitution_pre_tax_label] = substitution_changes / substitution_years if substitution_years else 0
        summary.loc["Annual turnover", substitution_pre_tax_label] = substitution_turnover
    st.subheader("Results")
    styled_summary = summary.style.format("{:.2%}", subset=pd.IndexSlice[percentage_rows, :]).format("{:.2f}", subset=pd.IndexSlice[ratio_rows + numeric_rows, :])
    result_columns = st.columns(4)
    if substitution_result is None:
        result_columns[0].metric("CAGR", f"{summary.loc['CAGR', pre_tax_label]:.2%}")
        result_columns[1].metric("Maximum drawdown", f"{summary.loc['Maximum drawdown', pre_tax_label]:.2%}")
        result_columns[2].metric("Final value", f"{summary.loc['Final value', pre_tax_label]:,.0f}")
        result_columns[3].metric("Changes / year", f"{changes / years:.1f}" if years else "—")
    else:
        cagr_delta = summary.loc["CAGR", substitution_pre_tax_label] - summary.loc["CAGR", pre_tax_label]
        result_columns[0].metric("Published CAGR", f"{summary.loc['CAGR', pre_tax_label]:.2%}")
        result_columns[1].metric("Substituted CAGR", f"{summary.loc['CAGR', substitution_pre_tax_label]:.2%}", delta=f"{cagr_delta:+.2%}")
        result_columns[2].metric("Published maximum drawdown", f"{summary.loc['Maximum drawdown', pre_tax_label]:.2%}")
        result_columns[3].metric("Substituted maximum drawdown", f"{summary.loc['Maximum drawdown', substitution_pre_tax_label]:.2%}")
    curves = pd.DataFrame({pre_tax_label: result.monthly["pre_tax_value"]})
    if tax_enabled:
        curves[after_tax_label] = result.monthly["after_tax_value"]
    if substitution_result is not None:
        curves[substitution_pre_tax_label] = substitution_result.monthly["pre_tax_value"]
        if tax_enabled:
            curves[substitution_after_tax_label] = substitution_result.monthly["after_tax_value"]
    curves[benchmark_label] = result.monthly["benchmark_value"]
    st.plotly_chart(px.line(curves, title="Equity curve"), use_container_width=True)
    drawdowns = curves.div(curves.cummax()).sub(1)
    st.plotly_chart(px.line(drawdowns, title="Drawdown"), use_container_width=True)
    with st.expander("Full performance table", expanded=False):
        st.dataframe(styled_summary, use_container_width=True)
    annual = pd.DataFrame({pre_tax_label: annual_returns(result.monthly["pre_tax_monthly_return"])})
    if tax_enabled:
        annual[after_tax_label] = annual_returns(result.monthly["after_tax_monthly_return"])
    if substitution_result is not None:
        annual[substitution_pre_tax_label] = annual_returns(substitution_result.monthly["pre_tax_monthly_return"])
        if tax_enabled:
            annual[substitution_after_tax_label] = annual_returns(substitution_result.monthly["after_tax_monthly_return"])
    annual[benchmark_label] = annual_returns(result.monthly["benchmark_monthly_return"])
    monthly_returns = pd.DataFrame({pre_tax_label: result.monthly["pre_tax_monthly_return"]})
    if tax_enabled:
        monthly_returns[after_tax_label] = result.monthly["after_tax_monthly_return"]
    if substitution_result is not None:
        monthly_returns[substitution_pre_tax_label] = substitution_result.monthly["pre_tax_monthly_return"]
        if tax_enabled:
            monthly_returns[substitution_after_tax_label] = substitution_result.monthly["after_tax_monthly_return"]
    monthly_returns[benchmark_label] = result.monthly["benchmark_monthly_return"]
    with st.expander("Return history", expanded=False):
        annual_tab, monthly_tab = st.tabs(["Annual", "Monthly"])
        with annual_tab:
            st.dataframe(annual.style.format("{:.2%}"), use_container_width=True)
        with monthly_tab:
            st.dataframe(monthly_returns.style.format("{:.2%}"), use_container_width=True)


def current_portfolio_signal(model_label: str):
    """Reuse a model's normal signal path and return its executable weights."""
    sleeve_strategy = MODEL_OPTIONS[model_label]()
    sleeve_assets = getattr(sleeve_strategy, "data_assets", ASSETS)
    sleeve_prices = all_prices.loc[:, sleeve_assets]
    sleeve_market_assets = getattr(sleeve_strategy, "market_data_assets", sleeve_assets)
    sleeve_monthly, sleeve_monthly_input = monthly_strategy_input(sleeve_prices, sleeve_market_assets)
    sleeve_decision_prices = sleeve_prices if getattr(sleeve_strategy, "uses_daily_signals", False) else sleeve_monthly_input
    status = latest_actionable_signal(sleeve_strategy.decisions(sleeve_decision_prices), sleeve_monthly, sleeve_market_assets)
    if status.decision is None:
        return None, status.reason
    decision = status.decision
    weights = decision.get("target_weights", {decision["selected_asset"]: 1.0})
    return {"decision": decision, "weights": dict(weights), "strategy": sleeve_strategy}, None


def next_portfolio_preview(model_label: str):
    """Return one sleeve's non-actionable current-month estimate."""
    if definition_for_label(model_label).strategy_mode == "buy_and_hold":
        return None, "This sleeve is held continuously and has no next-month timing preview."
    strategy = MODEL_OPTIONS[model_label]()
    assets = getattr(strategy, "data_assets", ASSETS)
    prices = all_prices.loc[:, assets]
    market_assets = getattr(strategy, "market_data_assets", assets)
    monthly, _ = monthly_strategy_input(prices, market_assets)
    preview_monthly, price_as_of, reason = month_to_date_snapshot(monthly, prices, market_assets)
    if reason is not None or price_as_of is None:
        return None, reason or "No common current-month price row is available."
    if getattr(strategy, "uses_daily_signals", False):
        preview_decisions = strategy.decisions(prices.loc[:price_as_of], include_current_month=True)
    else:
        preview_input = preview_monthly.join(
            prices.drop(columns=list(market_assets), errors="ignore").reindex(preview_monthly.index, method="ffill")
        )
        preview_decisions = strategy.decisions(preview_input)
    status = latest_preview_signal(preview_decisions, price_as_of)
    if status.decision is None:
        return None, status.reason or "No preview is available."
    decision = status.decision
    weights = decision.get("target_weights", {decision["selected_asset"]: 1.0})
    return {"decision": decision, "weights": dict(weights), "price_as_of": status.price_as_of}, None


def display_allocation(weights: dict[str, float], currency: str) -> str:
    """Format an executable allocation with broker-facing security labels."""
    return ", ".join(f"{execution_security_label(asset, currency)} {weight:.0%}" for asset, weight in weights.items())


@st.cache_data(ttl=60 * 60 * 6, show_spinner=False)
def latest_usd_ils_quote() -> tuple[float, pd.Timestamp]:
    """Get a short-lived Portfolio-only USD/ILS quote from Yahoo Finance."""
    return download_latest_yahoo_close("USDILS=X")


def initialise_portfolio_fx_rate() -> tuple[pd.Timestamp | None, str | None]:
    """Seed the editable Portfolio FX field once without overwriting overrides."""
    if "portfolio_fx_rate" in st.session_state:
        return st.session_state.get("portfolio_fx_quote_timestamp"), st.session_state.get("portfolio_fx_error")
    try:
        rate, quote_timestamp = latest_usd_ils_quote()
        st.session_state["portfolio_fx_rate"] = rate
        st.session_state["portfolio_fx_quote_timestamp"] = quote_timestamp
        st.session_state["portfolio_fx_error"] = None
        return quote_timestamp, None
    except Exception as exc:
        st.session_state["portfolio_fx_rate"] = 3.7
        error = f"Could not retrieve the latest USD/ILS quote from Yahoo Finance ({exc}). Using the fallback rate; you can edit it below."
        st.session_state["portfolio_fx_error"] = error
        return None, error



if page == "Today":
    title_column.title("Today")
    saved_portfolio = st.session_state.get("browser_default_portfolio")
    if not saved_portfolio:
        st.info("Set up a portfolio, then choose **Use as my default portfolio** on the Portfolio page. It will be saved only in this browser.")
    else:
        saved_sleeves = st.session_state["portfolio_sleeves"]
        saved_total_weight = total_weight(saved_sleeves)
        title_column.caption(f"{saved_portfolio['name']} · saved in this browser")
        signal_rows, valid_sleeves, signal_dates, changed_models, current_weights_by_model = [], [], [], [], {}
        for sleeve in saved_sleeves:
            currency = definition_for_label(sleeve["model"]).execution_currency
            signal, error = current_portfolio_signal(sleeve["model"])
            row = {"Sleeve": sleeve["model"], "Weight": sleeve["weight"] / 100, "Current holding": "Unavailable", "Status": error or ""}
            if signal is not None:
                decision = signal["decision"]
                row["Current holding"] = display_allocation(signal["weights"], currency)
                row["Status"] = f"Ready · {decision['regime']}"
                signal_dates.append(pd.Timestamp(decision.name))
                if bool(decision.get("trade", False)):
                    changed_models.append(sleeve["model"])
                current_weights_by_model[sleeve["model"]] = signal["weights"]
                valid_sleeves.append({"name": sleeve["model"], "weight": sleeve["weight"], "currency": currency, "target_weights": signal["weights"]})
            signal_rows.append(row)
        if len(valid_sleeves) == len(saved_sleeves) and abs(saved_total_weight - 100.0) < 1e-9:
            st.subheader("What to hold now")
            grouped_holdings = aggregate_holdings_by_currency(valid_sleeves)
            for currency, holdings in grouped_holdings.items():
                holding_rows = []
                for asset, values in sorted(holdings.items()):
                    ils_allocation = saved_portfolio["total_ils"] * values["weight"]
                    holding_rows.append({"Holding": execution_security_label(asset, currency), "Portfolio weight": values["weight"], f"Allocation ({currency})": convert_currency(ils_allocation, "ILS", currency, saved_portfolio["ils_per_usd"])})
                st.dataframe(pd.DataFrame(holding_rows).style.format({"Portfolio weight": "{:.2%}", f"Allocation ({currency})": "{:,.2f}"}), use_container_width=True, hide_index=True)
        else:
            st.warning("Combined holdings are unavailable until every saved sleeve has a valid signal and the sleeve weights total 100%.")
        st.subheader("Monthly action")
        if changed_models:
            st.warning("Action required: review the changed sleeve signals below before your next trade.")
        elif len(valid_sleeves) == len(saved_sleeves) and abs(saved_total_weight - 100.0) < 1e-9:
            st.success("No changes required at the most recent completed signal.")
        else:
            st.info("No action can be determined until every sleeve has a valid signal.")
        if signal_dates:
            newest_signal_date = max(signal_dates)
            st.caption(f"Latest completed signal: {newest_signal_date:%Y-%m-%d}")
            if (pd.Timestamp.now().normalize() - newest_signal_date.normalize()).days > 45:
                st.warning("This signal may be stale. Check that the data sources are up to date before acting.")
        st.subheader("Sleeve signals")
        st.dataframe(pd.DataFrame(signal_rows).style.format({"Weight": "{:.2%}"}), use_container_width=True, hide_index=True)
        with st.expander("Next month portfolio preview (provisional)", expanded=False):
            st.warning("**Provisional only — not a trading instruction.** This estimates the next completed month-end decision from current-month prices. It can change before month-end.")
            preview_rows, preview_dates = [], []
            for sleeve in saved_sleeves:
                currency = definition_for_label(sleeve["model"]).execution_currency
                preview, error = next_portfolio_preview(sleeve["model"])
                row = {"Sleeve": sleeve["model"], "Projected allocation": "Unavailable", "Change vs current": "—", "Price data through": "—"}
                if preview is not None:
                    row["Projected allocation"] = display_allocation(preview["weights"], currency)
                    row["Change vs current"] = "Yes" if preview["weights"] != current_weights_by_model.get(sleeve["model"]) else "No"
                    row["Price data through"] = preview["price_as_of"].date().isoformat()
                    preview_dates.append(preview["price_as_of"])
                else:
                    row["Projected allocation"] = error or "Unavailable"
                preview_rows.append(row)
            st.dataframe(pd.DataFrame(preview_rows), use_container_width=True, hide_index=True)
            if preview_dates:
                st.caption(f"Uses the latest common eligible price data for each sleeve (latest: {max(preview_dates):%Y-%m-%d}). The official portfolio remains the completed-month signal above.")
        st.caption("Edit this portfolio or choose a different default on the Portfolio page.")


if page == "Portfolio":
    title_column.title("Portfolio")
    title_column.caption("Combine existing actionable strategy signals from your brokerage's total ILS account value. Currency amounts are informational; no conversion or trade is executed by the app.")
    library = st.session_state["browser_portfolio_library"]
    if library:
        library_by_name = {portfolio["name"]: portfolio for portfolio in library}
        picker_column, load_column, delete_column, library_spacer = st.columns([2.3, 0.8, 0.8, 5.1])
        with picker_column:
            selected_saved_name = st.selectbox("Saved portfolios", tuple(library_by_name), key="portfolio_library_selection")
        with load_column:
            load_saved = st.button("Load", key="portfolio_load_saved")
        with delete_column:
            delete_saved = st.button("Delete", key="portfolio_delete_saved")
        if load_saved:
            apply_browser_portfolio(library_by_name[selected_saved_name])
            st.rerun()
        if delete_saved:
            st.session_state["browser_portfolio_library"] = [portfolio for portfolio in library if portfolio["name"] != selected_saved_name]
            store_portfolio_library_in_browser(st.session_state["browser_portfolio_library"])
            st.rerun()
    else:
        st.caption("Save named portfolios in this browser, then load or delete them here. They are not uploaded anywhere.")
    fx_quote_timestamp, fx_error = initialise_portfolio_fx_rate()
    with st.container(key="portfolio-investment-settings"):
        name_column, base_column, rate_column = st.columns([1.15, 1, 1])
        with name_column:
            portfolio_name = st.text_input("Portfolio name", key="portfolio_name", max_chars=80)
        with base_column:
            total_ils = st.number_input("Total available capital (ILS)", min_value=0.0, value=100_000.0, step=1_000.0, key="portfolio_total_ils")
        with rate_column:
            ils_per_usd = st.number_input("ILS per 1 USD (editable)", min_value=0.0001, step=0.01, format="%.4f", key="portfolio_fx_rate")
    if fx_error:
        st.info(fx_error)
    elif fx_quote_timestamp is not None:
        st.caption(
            f"Latest USD/ILS from Yahoo Finance (quote time: {fx_quote_timestamp:%Y-%m-%d %H:%M UTC}; cached for up to 6 hours). "
            "Edit the rate above to use a manual override for this session."
        )

    sleeves = st.session_state["portfolio_sleeves"]
    with st.container(key="portfolio-sleeve-heading"):
        sleeve_title_column, sleeve_add_column, sleeve_remove_column, sleeve_spacer = st.columns([2.4, 0.35, 0.35, 9])
        with sleeve_title_column:
            st.subheader("Strategy sleeves")
        with sleeve_add_column:
            add_sleeve = st.button("+", key="portfolio_add_sleeve", help="Add sleeve")
        with sleeve_remove_column:
            remove_sleeve = st.button("-", key="portfolio_remove_sleeve", help="Remove the last sleeve", disabled=len(sleeves) == 1)
    updated_sleeves = []
    for sleeve in sleeves:
        sleeve_id = sleeve["id"]
        prefix = f"portfolio_{sleeve_id}"
        previous_model = sleeve.get("model", st.session_state.get(f"{prefix}_model", DEFAULT_MODEL))
        seed_model_selection(prefix, previous_model)
        with st.container(key=f"{prefix}-sleeve-row"):
            strategy_column, variant_column, implementation_column, weight_column, currency_column = st.columns([1.1, 1.25, 1.45, 0.65, 0.55])
            model_label = model_selector(prefix, columns=(strategy_column, variant_column, implementation_column), implementation_dropdown=True)
            with weight_column:
                weight = st.number_input("Weight (%)", min_value=0.0, max_value=100.0, step=1.0, value=float(sleeve["weight"]), key=f"{prefix}_weight")
            execution_currency = definition_for_label(model_label).execution_currency
            with currency_column:
                st.selectbox("Currency", (execution_currency,), key=f"{prefix}_currency_{execution_currency}", disabled=True)
            st.session_state[f"{prefix}_model"] = model_label
            updated_sleeves.append({"id": sleeve_id, "weight": float(weight), "model": model_label, "currency": execution_currency})
    st.session_state["portfolio_sleeves"] = updated_sleeves
    if add_sleeve:
        next_id = st.session_state["portfolio_next_id"]
        st.session_state["portfolio_next_id"] = next_id + 1
        st.session_state["portfolio_sleeves"].append({"id": next_id, "weight": 0.0, "model": DEFAULT_MODEL})
        st.rerun()
    if remove_sleeve:
        st.session_state["portfolio_sleeves"] = updated_sleeves[:-1]
        st.rerun()

    sleeve_total = total_weight(updated_sleeves)
    plan = funding_plan(updated_sleeves, total_ils, ils_per_usd)
    for sleeve in updated_sleeves:
        definition = definition_for_label(sleeve["model"])
        if definition.suggested_max_weight is not None and sleeve["weight"] > definition.suggested_max_weight * 100:
            st.info(f"{sleeve['model']} is above its suggested {definition.suggested_max_weight:.0%} portfolio maximum. This is guidance only; the allocation remains available.")
    if abs(sleeve_total - 100.0) > 1e-9:
        st.warning(f"Sleeve weights total {sleeve_total:.2f}%. Set them to exactly 100% before using the combined allocation.")
    else:
        st.success("Sleeve weights total 100%.")

    save_column, default_column, clear_column, save_spacer = st.columns([1.35, 2.0, 1.5, 5.15])
    with save_column:
        save_named = st.button("Save portfolio")
    with default_column:
        save_as_default = st.button("Use as Today default", type="primary")
    with clear_column:
        clear_default = st.button("Clear saved default", disabled=st.session_state.get("browser_default_portfolio") is None)
    valid_portfolio = abs(sleeve_total - 100.0) <= 1e-9 and all(sleeve["weight"] > 0 for sleeve in updated_sleeves)
    current_payload = portfolio_payload(updated_sleeves, total_ils, ils_per_usd, portfolio_name)
    if save_named:
        if not valid_portfolio:
            st.error("Set one or more positive sleeve weights totaling exactly 100% before saving a portfolio.")
        else:
            updated_library = [portfolio for portfolio in st.session_state["browser_portfolio_library"] if portfolio["name"].casefold() != current_payload["name"].casefold()]
            updated_library.append(current_payload)
            st.session_state["browser_portfolio_library"] = updated_library
            store_portfolio_library_in_browser(updated_library)
            st.success(f"Saved {current_payload['name']} in this browser.")
    if save_as_default:
        if not valid_portfolio:
            st.error("Set one or more positive sleeve weights totaling exactly 100% before saving this default portfolio.")
        else:
            updated_library = [portfolio for portfolio in st.session_state["browser_portfolio_library"] if portfolio["name"].casefold() != current_payload["name"].casefold()]
            updated_library.append(current_payload)
            st.session_state["browser_portfolio_library"] = updated_library
            store_portfolio_library_in_browser(updated_library)
            st.session_state["browser_default_portfolio"] = current_payload
            st.session_state["browser_portfolio_checked"] = True
            store_portfolio_in_browser(current_payload)
            st.success("Saved in this browser and set as Today’s default portfolio.")
    if clear_default:
        st.session_state["browser_default_portfolio"] = None
        store_portfolio_in_browser(None)
        st.success("Removed the saved default portfolio from this browser.")

    st.subheader("Funding and FX")
    total_ils_column, total_usd_column = st.columns(2)
    with total_ils_column:
        st.metric("Total portfolio value (ILS)", f"{plan['total_ils']:,.2f}")
    with total_usd_column:
        st.metric("Total portfolio value (USD)", f"{plan['total_usd']:,.2f}")
    funding_rows = [
        {
            "Execution currency": currency,
            "Required allocation": plan["required"][currency],
            "ILS equivalent": convert_currency(plan["required"][currency], currency, "ILS", ils_per_usd),
        }
        for currency in ("USD", "ILS")
    ]
    st.dataframe(
        pd.DataFrame(funding_rows).style.format({"Required allocation": "{:,.2f}", "ILS equivalent": "{:,.2f}"}),
        use_container_width=True,
        hide_index=True,
    )
    if plan["total_ils"] == 0:
        st.info("Enter your total available ILS capital to calculate sleeve funding requirements.")
    else:
        st.caption("Required native-currency amounts show what the selected sleeves need. Your broker determines whether any conversion is needed to fund those purchases.")

    sleeve_rows, sleeve_detail_rows, valid_sleeves = [], [], []
    allocations_by_id = {int(item["id"]): item for item in plan["sleeves"]}
    for sleeve in updated_sleeves:
        definition = definition_for_label(sleeve["model"])
        signal, error = current_portfolio_signal(sleeve["model"])
        allocation = allocations_by_id[sleeve["id"]]
        base_row = {
            "Model": sleeve["model"],
            "Weight": sleeve["weight"] / 100,
            "Allocation": allocation["allocation_native"],
            "Current holding": None,
            "Status": None,
        }
        detail_row = {
            "Model": sleeve["model"], "Strategy": definition.strategy,
            "Variant": definition.variant or "—", "Implementation": definition.implementation,
            "Currency": sleeve["currency"], "Weight": sleeve["weight"] / 100,
            "Target allocation (ILS)": allocation["allocation_ils"],
            "Native allocation": allocation["allocation_native"],
        }
        if error:
            base_row.update({"Current holding": "Unavailable", "Status": error})
            detail_row.update({"Current holding": "Unavailable", "Status": error})
        else:
            target = display_allocation(signal["weights"], sleeve["currency"])
            base_row.update({"Current holding": target, "Status": f"Ready · {signal['decision']['regime']}"})
            detail_row.update({"Current holding": target, "Status": f"Ready · {signal['decision']['regime']}"})
            valid_sleeves.append({"name": sleeve["model"], "weight": sleeve["weight"], "currency": sleeve["currency"], "target_weights": signal["weights"]})
        sleeve_rows.append(base_row)
        sleeve_detail_rows.append(detail_row)
    st.subheader("Current sleeve signals")
    sleeve_table = pd.DataFrame(sleeve_rows)
    st.dataframe(sleeve_table.style.format({"Weight": "{:.2%}", "Allocation": "{:,.2f}"}), use_container_width=True, hide_index=True)
    with st.expander("Sleeve configuration details", expanded=False):
        st.dataframe(pd.DataFrame(sleeve_detail_rows).style.format({"Weight": "{:.2%}", "Target allocation (ILS)": "{:,.2f}", "Native allocation": "{:,.2f}"}), use_container_width=True, hide_index=True)

    st.subheader("Combined actionable holdings")
    if len(valid_sleeves) != len(updated_sleeves):
        st.info("Combined holdings are unavailable until every sleeve has a valid current signal.")
        unavailable = [f"{row['Model']}: {row['Status']}" for row in sleeve_rows if row["Current holding"] == "Unavailable"]
        st.caption(" · ".join(unavailable))
    elif abs(sleeve_total - 100.0) > 1e-9:
        st.info("Combined holdings are unavailable until sleeve weights total exactly 100%.")
    else:
        grouped_holdings = aggregate_holdings_by_currency(valid_sleeves)
        for currency, holdings in grouped_holdings.items():
            st.markdown(f"**{currency} holdings**")
            holding_rows, holding_detail_rows = [], []
            for asset, values in sorted(holdings.items()):
                ils_allocation = plan["total_ils"] * values["weight"]
                holding_row = {
                    "Holding": execution_security_label(asset, currency),
                    "Combined weight": values["weight"],
                    f"Allocation ({currency})": convert_currency(ils_allocation, "ILS", currency, ils_per_usd),
                    "ILS equivalent": ils_allocation,
                }
                holding_rows.append(holding_row)
                holding_detail_rows.append({**holding_row, "Contributing sleeves": ", ".join(values["sleeves"])})
            st.dataframe(pd.DataFrame(holding_rows).style.format({"Combined weight": "{:.2%}", f"Allocation ({currency})": "{:,.2f}", "ILS equivalent": "{:,.2f}"}), use_container_width=True, hide_index=True)
            with st.expander(f"{currency} holding sources", expanded=False):
                st.dataframe(pd.DataFrame(holding_detail_rows), use_container_width=True, hide_index=True)

if page == "Compare":
    title_column.title("Compare")
    st.caption("Each selected model is independently backtested, then restarted over the exact shared completed holding periods. Comparison settings below are independent of the Backtest page. This is informational only and does not recommend one model.")
    default_model = model_name if model_name in BACKTEST_MODEL_OPTIONS else next(iter(BACKTEST_MODEL_OPTIONS))
    default_comparison = [default_model, next(name for name in BACKTEST_MODEL_OPTIONS if name != default_model)]
    selected_models = st.multiselect("Models", tuple(BACKTEST_MODEL_OPTIONS), default=default_comparison, key="compare_models")
    if len(selected_models) < 2:
        st.info("Select at least two models to compare.")
    else:
        try:
            comparison_inputs = {}
            comparison_bounds = []
            for selected_name in selected_models:
                selected_strategy = BACKTEST_MODEL_OPTIONS[selected_name]()
                selected_assets = getattr(selected_strategy, "data_assets", ASSETS)
                selected_daily = all_prices.loc[:, selected_assets]
                selected_market_assets = getattr(selected_strategy, "market_data_assets", selected_assets)
                selected_monthly = to_month_end(selected_daily.loc[:, list(selected_market_assets)])
                selected_decision_prices = selected_daily if getattr(selected_strategy, "uses_daily_signals", False) else selected_monthly
                comparison_inputs[selected_name] = ModelInput(selected_name, selected_strategy.decisions(selected_decision_prices), selected_monthly, selected_daily, getattr(selected_strategy, "benchmark_asset", "SPY"))
                first_date, last_date = common_monthly_period(selected_monthly)
                if first_date is None or last_date is None:
                    raise ValueError(f"{selected_name} has no common monthly data.")
                comparison_bounds.append((first_date, last_date))
            if len({model.benchmark_asset for model in comparison_inputs.values()}) != 1:
                raise ValueError("Compare only models with the same buy-and-hold benchmark. HAA-Simple Israel uses CSPX_IL; the other current models use SPY.")
            comparison_start_min = max(first for first, _ in comparison_bounds).date()
            comparison_end_max = min(last for _, last in comparison_bounds).date()
            compare_start = min(max(st.session_state.get("compare_start", comparison_start_min), comparison_start_min), comparison_end_max)
            compare_end = min(max(st.session_state.get("compare_end", comparison_end_max), comparison_start_min), comparison_end_max)
            if compare_start > compare_end:
                compare_start = comparison_start_min
            with st.expander("Comparison configuration", expanded=True):
                config_left, config_right = st.columns(2)
                with config_left:
                    compare_initial = st.number_input("Initial investment", min_value=1.0, value=100_000.0, step=1_000.0, key="comparison_initial")
                    compare_cost_pct = st.number_input("Transaction cost per entry/change (%)", min_value=0.0, max_value=10.0, value=0.0, step=0.01, key="comparison_cost_pct") / 100
                    compare_tax_enabled = st.toggle("Israeli capital-gains tax", value=False, key="comparison_tax_enabled")
                    compare_tax_rate = st.number_input("Tax rate (%)", min_value=0.0, max_value=100.0, value=DEFAULT_TAX_RATE * 100, step=0.1, key="comparison_tax_rate", disabled=not compare_tax_enabled) / 100
                with config_right:
                    st.caption(f"Shared source-data window: {comparison_start_min} through {comparison_end_max}")
                    compare_start = st.date_input("Comparison start (holding-period end)", value=compare_start, min_value=comparison_start_min, max_value=comparison_end_max, key="compare_start")
                    compare_end = st.date_input("Comparison end (holding-period end)", value=compare_end, min_value=comparison_start_min, max_value=comparison_end_max, key="compare_end")
                    if compare_start > compare_end:
                        st.error("Comparison start must not be after comparison end.")
                        st.stop()
            model_comparison = compare_models(
                comparison_inputs,
                compare_initial,
                compare_cost_pct,
                compare_tax_enabled,
                compare_tax_rate,
                pd.Timestamp(compare_start),
                pd.Timestamp(compare_end),
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.subheader("Comparable period")
            st.dataframe(model_comparison.available_periods, use_container_width=True)
            st.success(f"All results below use **{model_comparison.common_index.min().date()} through {model_comparison.common_index.max().date()}** ({len(model_comparison.common_index)} complete monthly holding periods).")
            comparison_pre = {name: performance_metrics(backtest.monthly["pre_tax_value"], compare_initial) for name, backtest in model_comparison.results.items()}
            first_comparison = next(iter(model_comparison.results.values()))
            comparison_benchmark_label = f"{next(iter(comparison_inputs.values())).benchmark_asset} buy-and-hold"
            comparison_pre[comparison_benchmark_label] = performance_metrics(first_comparison.monthly["benchmark_value"], compare_initial)
            comparison_summary = pd.DataFrame(comparison_pre)
            comparison_years = len(model_comparison.common_index) / 12
            for name, backtest in model_comparison.results.items():
                changes = int(backtest.monthly["allocation_change"].sum())
                turnover = backtest.monthly["turnover"].sum() / comparison_years if "turnover" in backtest.monthly and comparison_years else changes / comparison_years if comparison_years else 0
                comparison_summary.loc["Allocation changes", name] = changes
                comparison_summary.loc["Average changes/year", name] = changes / comparison_years if comparison_years else 0
                comparison_summary.loc["Annual turnover", name] = turnover
            st.subheader("Pre-tax results")
            st.dataframe(comparison_summary.style.format("{:.2%}", subset=pd.IndexSlice[percentage_rows, :]).format("{:.2f}", subset=pd.IndexSlice[ratio_rows + numeric_rows, :]), use_container_width=True)

            pre_curves = pd.DataFrame({name: backtest.monthly["pre_tax_value"] for name, backtest in model_comparison.results.items()})
            pre_curves[comparison_benchmark_label] = first_comparison.monthly["benchmark_value"]
            st.plotly_chart(px.line(pre_curves, title="Pre-tax equity curves"), use_container_width=True)
            st.plotly_chart(px.line(pre_curves.div(pre_curves.cummax()).sub(1), title="Monthly drawdown"), use_container_width=True)
            annual_comparison = pd.DataFrame({name: annual_returns(backtest.monthly["pre_tax_monthly_return"]) for name, backtest in model_comparison.results.items()})
            annual_comparison[comparison_benchmark_label] = annual_returns(first_comparison.monthly["benchmark_monthly_return"])
            st.subheader("Annual returns")
            st.dataframe(annual_comparison.style.format("{:.2%}"), use_container_width=True)
            monthly_comparison = pd.DataFrame({name: backtest.monthly["pre_tax_monthly_return"] for name, backtest in model_comparison.results.items()})
            monthly_comparison[comparison_benchmark_label] = first_comparison.monthly["benchmark_monthly_return"]
            st.subheader("Monthly returns")
            st.dataframe(monthly_comparison.style.format("{:.2%}"), use_container_width=True)
            st.download_button("Download common-period monthly returns CSV", monthly_comparison.to_csv().encode("utf-8"), "haa_model_comparison_monthly_returns.csv", "text/csv", key="comparison_monthly_download")

            if compare_tax_enabled:
                after_summary = pd.DataFrame({name: performance_metrics(backtest.monthly["after_tax_value"], compare_initial) for name, backtest in model_comparison.results.items()})
                st.subheader("After-tax results")
                st.dataframe(after_summary.style.format("{:.2%}", subset=pd.IndexSlice[["CAGR", "Total return", "Maximum drawdown", "Annualized volatility", "Best month", "Worst month"], :]).format("{:.2f}", subset=pd.IndexSlice[ratio_rows + ["Final value"], :]), use_container_width=True)
                after_curves = pd.DataFrame({name: backtest.monthly["after_tax_value"] for name, backtest in model_comparison.results.items()})
                st.plotly_chart(px.line(after_curves, title="After-tax equity curves"), use_container_width=True)
                after_annual = pd.DataFrame({name: annual_returns(backtest.monthly["after_tax_monthly_return"]) for name, backtest in model_comparison.results.items()})
                st.subheader("After-tax annual returns")
                st.dataframe(after_annual.style.format("{:.2%}"), use_container_width=True)
                after_monthly = pd.DataFrame({name: backtest.monthly["after_tax_monthly_return"] for name, backtest in model_comparison.results.items()})
                st.subheader("After-tax monthly returns")
                st.dataframe(after_monthly.style.format("{:.2%}"), use_container_width=True)
                st.download_button("Download common-period after-tax monthly returns CSV", after_monthly.to_csv().encode("utf-8"), "haa_model_comparison_after_tax_monthly_returns.csv", "text/csv", key="comparison_after_tax_monthly_download")

            st.subheader("Latest allocation in the shared period")
            allocation_rows = []
            for name, backtest in model_comparison.results.items():
                latest = backtest.monthly.iloc[-1]
                weights = latest.get("target_weights")
                allocation = ", ".join(f"{asset} {weight:.0%}" for asset, weight in weights.items()) if isinstance(weights, dict) else latest["selected_asset"]
                allocation_rows.append({"model": name, "signal_date": latest["signal_date"], "regime": latest["regime"], "target allocation": allocation})
            st.dataframe(pd.DataFrame(allocation_rows).set_index("model"), use_container_width=True)
            st.subheader("Model audit downloads")
            for name, backtest in model_comparison.results.items():
                st.download_button(f"Download {name} common-period audit CSV", backtest.audit.to_csv().encode("utf-8"), f"{name.lower().replace(' ', '_').replace('(', '').replace(')', '')}_comparison_audit.csv", "text/csv", key=f"comparison_audit_{name}")

if page == "Signals":
    with st.container(key="signals-model-selector"):
        signal_model_name = model_selector("signals", columns=st.columns([1.1, 1.25, 1.45]), implementation_dropdown=True)
    st.session_state["signals_model_name"] = signal_model_name
    signal_strategy = MODEL_OPTIONS[signal_model_name]()
    signal_definition = definition_for_label(signal_model_name)
    signal_execution_currency = signal_definition.execution_currency
    signal_data_assets = getattr(signal_strategy, "data_assets", ASSETS)
    signal_momentum_assets = getattr(signal_strategy, "signal_assets", signal_data_assets)
    signal_prices = all_prices.loc[:, signal_data_assets]
    signal_market_assets = getattr(signal_strategy, "market_data_assets", signal_data_assets)
    signal_monthly, signal_monthly_input = monthly_strategy_input(signal_prices, signal_market_assets)
    signal_decision_prices = signal_prices if getattr(signal_strategy, "uses_daily_signals", False) else signal_monthly_input
    signal_decisions = signal_strategy.decisions(signal_decision_prices)
    signal_status = latest_actionable_signal(signal_decisions, signal_monthly, signal_market_assets)
    preview_status = None
    if signal_definition.strategy_mode != "buy_and_hold":
        preview_monthly, preview_price_as_of, preview_reason = month_to_date_snapshot(
            signal_monthly, signal_prices, signal_market_assets
        )
        if preview_reason is not None:
            preview_status = latest_preview_signal(pd.DataFrame(), preview_price_as_of)
        elif getattr(signal_strategy, "uses_daily_signals", False):
            preview_decisions = signal_strategy.decisions(
                signal_prices.loc[:preview_price_as_of], include_current_month=True
            )
            preview_status = latest_preview_signal(preview_decisions, preview_price_as_of)
        else:
            preview_input = preview_monthly.join(
                signal_prices.drop(columns=list(signal_market_assets), errors="ignore").reindex(preview_monthly.index, method="ffill")
            )
            preview_decisions = signal_strategy.decisions(preview_input)
            preview_status = latest_preview_signal(preview_decisions, preview_price_as_of)
    if signal_definition.strategy_mode == "buy_and_hold":
        title_column.title("TA-125 Smart Momentum")
        title_column.caption("Internally managed momentum strategy · Israeli equity / momentum growth sleeve")
        if signal_status.decision is None:
            st.error(signal_status.reason)
        else:
            st.dataframe(pd.DataFrame([{
                "Current allocation": "100% TA-125 Smart Momentum (5134713)",
                "External signal": "None — Buy & Hold",
                "Internal strategy": "Momentum weighting handled by the underlying index",
            }]), use_container_width=True, hide_index=True)
            st.info("This fund is held continuously. The TA-125 Smart Momentum index performs its own momentum selection and reweighting; the app does not produce BUY, SELL, or CASH timing instructions.")
            st.caption("Fund 5134713 uses public TASE/Maya history only. No synthetic or pre-fund history is used; Backtest and Compare begin at the actual available fund history.")
    elif signal_status.decision is None:
        title_column.title("Signal")
        title_column.caption(f"Model: {signal_model_name} · Completed month-end signal")
        st.error(signal_status.reason)
    else:
        signal = signal_status.decision
        signal_date = pd.Timestamp(signal.name)
        effective_start = first_trading_day_after(signal_prices, signal_date, execution_assets(signal, getattr(signal_strategy, "benchmark_asset", "SPY")))
        previous = signal["previous_asset"] if pd.notna(signal["previous_asset"]) else "No prior allocation"
        weights = signal.get("target_weights", {signal["selected_asset"]: 1.0})
        if getattr(signal_strategy, "is_multi_asset", False):
            action = "Hold allocation" if not bool(signal["trade"]) else ("Establish allocation" if previous == "No prior allocation" else "Rebalance allocation")
            target_allocation = display_allocation(weights, signal_execution_currency)
        else:
            selected_security = execution_security_label(signal["selected_asset"], signal_execution_currency)
            previous_security = execution_security_label(str(previous), signal_execution_currency) if previous != "No prior allocation" else previous
            action = "Hold" if not bool(signal["trade"]) else (f"Buy {selected_security}" if previous == "No prior allocation" else f"Switch {previous_security} → {selected_security}")
            target_allocation = f"100% {selected_security}"
        title_column.title(f"Signal - {target_allocation}")
        title_column.caption(f"Model: {signal_model_name} · Completed month-end signal")
        signal_summary = pd.DataFrame([{
            "signal date": signal_date.date().isoformat(),
            "regime": str(signal["regime"]).replace("-", " ").title(),
            "instruction": action,
            "target allocation": target_allocation,
        }])
        st.dataframe(signal_summary.style.set_properties(**{"background-color": "#fff3cd"}), use_container_width=True, hide_index=True)
        if effective_start is not None:
            st.info(f"Effective holding period: **{effective_start.date()}** until the next month-end decision.")
        else:
            st.warning("No later trading observation is available yet, so an effective start date cannot be shown.")
        with st.expander("Next month preview (provisional)", expanded=False):
            if preview_status is None or preview_status.decision is None:
                st.info("No preview is available yet because a common current-month price row is not available.")
            else:
                preview = preview_status.decision
                preview_weights = preview.get("target_weights", {preview["selected_asset"]: 1.0})
                if getattr(signal_strategy, "is_multi_asset", False):
                    preview_allocation = display_allocation(preview_weights, signal_execution_currency)
                else:
                    preview_allocation = f"100% {execution_security_label(preview['selected_asset'], signal_execution_currency)}"
                current_weights = weights if isinstance(weights, dict) else {signal["selected_asset"]: 1.0}
                changed = preview_weights != current_weights
                st.warning(
                    "**Provisional only — not a trading instruction.** This estimates the next month-end decision "
                    f"from prices available through **{preview_status.price_as_of.date()}**. It can change before month-end."
                )
                st.dataframe(pd.DataFrame([{
                    "price data through": preview_status.price_as_of.date().isoformat(),
                    "projected regime": str(preview["regime"]).replace("-", " ").title(),
                    "projected allocation": preview_allocation,
                    "change vs current signal": "Yes" if changed else "No",
                }]), use_container_width=True, hide_index=True)
                st.caption("The official signal remains the completed month-end decision above. This preview uses the latest common trading-day close in the current month and does not assume a future close.")
        st.subheader("Why this allocation")
        if isinstance(signal_strategy, (HAA4, HAA4Leveraged2x)):
            if signal["regime"] == "risk-off":
                holding = signal["selected_asset"] if isinstance(signal_strategy, HAA4Leveraged2x) else signal["defensive_winner"]
                st.write(f"TIP 13612U momentum is not positive, so the model holds 100% of the higher-momentum defensive asset: {holding}.")
            elif signal["replaced_offensive_assets"]:
                mapped = f" Final holdings: {signal['mapped_holding_assets']}." if isinstance(signal_strategy, HAA4Leveraged2x) else ""
                st.write(f"TIP 13612U momentum is positive, so the model selected {signal['selected_offensive_assets']}. The non-positive sleeve(s) {signal['replaced_offensive_assets']} were replaced with {signal['defensive_winner']}.{mapped}")
            else:
                holdings = signal["mapped_holding_assets"] if isinstance(signal_strategy, HAA4Leveraged2x) else signal["selected_offensive_assets"]
                st.write(f"TIP 13612U momentum is positive and both selected offensive assets are positive, so the model holds {holdings} at 50% each.")
        elif isinstance(signal_strategy, (InflationCompassFast, InflationCompassStandard, InflationCompassSteady)):
            st.write(f"Growth is {'up' if signal['growth_up'] else 'down'} and inflation is {'on' if signal['inflation_on'] else 'off'}, producing the {signal['regime'].replace('-', ' ')} allocation.")
        elif isinstance(signal_strategy, (GrowthInflationConcentrated, GrowthInflationDiversified)):
            st.write(f"Growth is {'high' if signal['growth_up'] else 'low'} because SPY is {'above' if signal['growth_up'] else 'at or below'} its 200-day SMA. Inflation is {'high' if signal['inflation_on'] else 'low'} because the sector ratio is {'above' if signal['inflation_on'] else 'at or below'} its 200-day SMA, producing the {signal['regime']} allocation.")
            if isinstance(signal_strategy, GrowthInflationConcentratedIsrael):
                st.caption("The regime is calculated from U.S. market data; the displayed allocation is the corresponding TASE-listed ILS execution security.")
        elif isinstance(signal_strategy, VAAG4):
            if signal["regime"] == "risk-on":
                st.write(f"All four offensive assets have positive 13612W momentum, so VAA holds the highest-scoring offensive asset: {signal['offensive_winner']}.")
            else:
                st.write(f"{signal['breadth_bad_count']} offensive asset(s) have non-positive 13612W momentum. With B=1, breadth protection is active and VAA holds the best defensive asset: {signal['defensive_winner']}.")
        elif isinstance(signal_strategy, BAAG4Aggressive):
            if signal["regime"] == "risk-on":
                st.write(f"All four canaries have positive 13612W momentum, so BAA holds the highest-ranked offensive asset: {signal['selected_asset']}.")
            elif signal["bil_replacements"]:
                st.write(f"{signal['breadth_bad_count']} canary asset(s) have non-positive 13612W momentum, so BAA selected the top three defensive assets. {signal['bil_replacements']} ranked below BIL and were replaced with BIL.")
            else:
                st.write(f"{signal['breadth_bad_count']} canary asset(s) have non-positive 13612W momentum, so BAA holds the top three defensive assets: {signal['selected_asset']}.")
        elif isinstance(signal_strategy, GEM):
            source_holding = signal.get("signal_selected_asset", signal["selected_asset"])
            if signal["regime"] == "risk-off":
                st.write("SPY's completed 12-month return is at or below BIL's, so GEM holds aggregate bonds.")
            elif source_holding == "SPY":
                st.write("SPY's completed 12-month return is above BIL's and at least VEU's, so GEM holds U.S. equities.")
            else:
                st.write("SPY's completed 12-month return is above BIL's, but VEU has the higher relative return, so GEM holds international equities.")
        elif isinstance(signal_strategy, GGCEMLinkOriginal):
            source = signal.get("macro_source")
            if signal["risk_on"]:
                st.write(f"{source} set a risk-on regime. The model then selected the stronger 12-month equity leg: {signal.get('signal_selected_asset', signal['selected_asset'])}.")
            else:
                st.write(f"{source} set a risk-off regime. The model then selected the stronger 12-month defensive leg: {signal.get('signal_selected_asset', signal['selected_asset'])}.")
        elif isinstance(signal_strategy, OrthogonalAlpha):
            if signal["satellite_asset"] == "BTAL":
                st.write("BTAL's blended 1/3/6/12-month momentum is strictly greater than BIL's, so the 50% satellite holds BTAL alongside the permanent 25% QLD / 25% BTAL core.")
            else:
                st.write("BTAL's blended 1/3/6/12-month momentum is at or below BIL's, so the 50% satellite holds QLD alongside the permanent 25% QLD / 25% BTAL core.")
        elif isinstance(signal_strategy, (CenturyMomentum, CenturyMomentumIsrael)):
            comparison = "above" if signal["trend_up"] else "at or below"
            st.write(f"{signal_strategy.equity_asset}'s completed month-end close is {comparison} its 10-month SMA, so Century Momentum holds {execution_security_label(signal['selected_asset'], signal_execution_currency)}.")
        elif isinstance(signal_strategy, (HAAClassicNoQQQ, HAAClassicLeveragedNoQQQ)) and signal["regime"] == "risk-on":
            if isinstance(signal_strategy, HAAClassicLeveragedNoQQQ):
                st.write(f"TIP 13612U momentum is strictly positive, so the model selects the four highest-momentum 1x underlyings ({signal['selected_underlying_assets']}) and holds their mapped 2x ETFs ({signal['mapped_holding_assets']}).")
            else:
                st.write(f"TIP 13612U momentum is strictly positive, so the model selects the four highest-momentum offensive assets: {signal['selected_assets']}.")
        elif isinstance(signal_strategy, (HAAClassicNoQQQ, HAAClassicLeveragedNoQQQ)):
            if isinstance(signal_strategy, HAAClassicLeveragedNoQQQ):
                st.write(f"TIP 13612U momentum is not positive, so the model compares 1x IEF and BIL momentum and holds the mapped defensive asset: {signal['selected_asset']}.")
            else:
                st.write(f"TIP 13612U momentum is not positive, so the model selects the higher-momentum defensive asset: {signal['selected_asset']}.")
        elif isinstance(signal_strategy, HAASimpleIsrael) and signal["regime"] == "risk-on":
            st.write("TIP and CSPX_IL 13612U momentum are both strictly positive, so the model selects CSPX — 1159250.")
        elif isinstance(signal_strategy, HAASimpleIsrael):
            selected_security = execution_security_label(signal["selected_asset"], signal_execution_currency)
            st.write(f"At least one of TIP or CSPX_IL 13612U momentum is not positive, so the model selects the higher-momentum Israeli defensive security: {selected_security}.")
        elif signal["regime"] == "risk-on":
            holding = "SSO" if isinstance(signal_strategy, HAASimpleLeveraged2x) else "SPY"
            st.write(f"SPY and TIP 13612U momentum are both strictly positive, so the model selects {holding}.")
        else:
            st.write(f"At least one of SPY or TIP 13612U momentum is not positive, so the model selects the higher-momentum defensive asset: {signal['selected_asset']}.")
        if isinstance(signal_strategy, (InflationCompassFast, InflationCompassStandard, InflationCompassSteady)):
            window = signal_strategy.momentum_window
            compass_inputs = pd.DataFrame([{
                "SPY close": signal["SPY_price"],
                "SPY 200-day SMA": signal["SPY_200d_sma"],
                "Growth up": signal["growth_up"],
                "T5YIE date (lagged)": signal["t5yie_lag_date"],
                "T5YIE (lagged)": signal["t5yie_lagged"],
                f"T5YIE {window}-day date": signal["t5yie_momentum_date"],
                f"T5YIE {window}-day value": signal["t5yie_momentum_value"],
                "Breakeven momentum": signal["breakeven_momentum"],
                "Inflation indicator": signal["inflation_indicator"],
                f"{window}-day indicator slope": signal["indicator_momentum_slope"],
                "Asset momentum": signal["asset_momentum"],
                "Inflation on": signal["inflation_on"],
            }])
            st.dataframe(compass_inputs.style.format({"SPY close": "{:.4f}", "SPY 200-day SMA": "{:.4f}", "T5YIE (lagged)": "{:.4f}", f"T5YIE {window}-day value": "{:.4f}", "Inflation indicator": "{:.6f}", f"{window}-day indicator slope": "{:.8f}"}), use_container_width=True, hide_index=True)
            st.caption(f"T5YIE is read from the prior available trading-day observation. Both confirmation windows use {window} valid trading observations.")
        elif isinstance(signal_strategy, (GrowthInflationConcentrated, GrowthInflationDiversified)):
            timing_inputs = pd.DataFrame([{
                "SPY close": signal["SPY_price"],
                "SPY 200-day SMA": signal["SPY_200d_sma"],
                "Growth state": "High" if signal["growth_up"] else "Low",
                "Inflation-positive basket": signal["positive_sector_basket"],
                "Inflation-negative basket": signal["negative_sector_basket"],
                "Inflation ratio": signal["inflation_ratio"],
                "Inflation ratio 200-day SMA": signal["inflation_ratio_200d_sma"],
                "Inflation state": "High" if signal["inflation_on"] else "Low",
            }])
            st.dataframe(timing_inputs.style.format({"SPY close": "{:.4f}", "SPY 200-day SMA": "{:.4f}", "Inflation-positive basket": "{:.4f}", "Inflation-negative basket": "{:.4f}", "Inflation ratio": "{:.6f}", "Inflation ratio 200-day SMA": "{:.6f}"}), use_container_width=True, hide_index=True)
            st.caption("The inflation ratio is the equal-weighted inflation-positive sector basket divided by the equal-weighted inflation-negative sector basket. Both states use completed daily data at month-end.")
        elif isinstance(signal_strategy, VAAG4):
            vaa_inputs = pd.DataFrame([{
                "Bad offensive assets": signal["breadth_bad_count"],
                "Breadth threshold (B)": signal["breadth_threshold"],
                "Top offensive": signal["offensive_winner"],
                "Top defensive": signal["defensive_winner"],
                **{f"{asset} 13612W": signal[f"{asset}_13612w"] for asset in signal_strategy.data_assets},
            }])
            st.dataframe(vaa_inputs.style.format({column: "{:.6f}" for column in vaa_inputs.columns if column.endswith("13612W")}), use_container_width=True, hide_index=True)
            st.caption("13612W = (12×1-month return + 4×3-month return + 2×6-month return + 12-month return) / 4. Momentum equal to zero is non-positive.")
        elif isinstance(signal_strategy, BAAG4Aggressive):
            baa_inputs = pd.DataFrame([{
                "Non-positive canaries": signal["breadth_bad_count"],
                "Selected defensive assets": signal["selected_defensive_assets"] or "—",
                "BIL replacements": signal["bil_replacements"] or "—",
                **{f"{asset} 13612W": signal[f"{asset}_13612w"] for asset in signal_strategy.canary_assets},
                **{f"{asset} SMA(12)": signal[f"{asset}_sma12"] for asset in signal_strategy.signal_assets},
            }])
            st.dataframe(baa_inputs.style.format({column: "{:.6f}" for column in baa_inputs.columns if column.endswith("13612W") or column.endswith("SMA(12)")}), use_container_width=True, hide_index=True)
            st.caption("BAA ranks by current month-end price ÷ the average of the current and prior twelve month-ends − 1. Its canaries use 13612W; any value at or below zero activates defense.")
        elif isinstance(signal_strategy, GEM):
            gem_inputs = pd.DataFrame([{
                "SPY 12-month return": signal["SPY_12m_return"],
                "VEU 12-month return": signal["VEU_12m_return"],
                "AGG 12-month return": signal["AGG_12m_return"],
                "BIL 12-month return": signal["BIL_12m_return"],
                "Published holding": signal.get("signal_selected_asset", signal["selected_asset"]),
            }])
            st.dataframe(gem_inputs.style.format({column: "{:.2%}" for column in gem_inputs.columns if column.endswith("return")}), use_container_width=True, hide_index=True)
            st.caption("GEM compares completed 12-month returns. SPY must strictly exceed BIL; an exact SPY/VEU tie selects SPY.")
        elif isinstance(signal_strategy, GGCEMLinkOriginal):
            ggcem_inputs = pd.DataFrame([{
                "CLI diffusion (prior month)": signal["oecd_cli_diffusion"],
                "Regime source": signal["macro_source"],
                "Risk-on": signal["risk_on"],
                "SPY 12-month return": signal["SPY_12m_return"],
                "VEU 12-month return": signal["VEU_12m_return"],
                "IEF 12-month return": signal["IEF_12m_return"],
                "BIL 12-month return": signal["BIL_12m_return"],
            }])
            st.dataframe(ggcem_inputs.style.format({column: "{:.2%}" for column in ggcem_inputs.columns if "return" in column or "diffusion" in column}), use_container_width=True, hide_index=True)
            st.caption("Risk-on requires OECD diffusion strictly above 50%. The prior-month reading applies the publication lag; if unavailable, SPY-versus-BIL is the visible failsafe.")
        elif isinstance(signal_strategy, OrthogonalAlpha):
            alpha_inputs = pd.DataFrame([{
                "BTAL blended momentum": signal["BTAL_13612u"],
                "BIL blended momentum": signal["BIL_13612u"],
                "Satellite": signal["satellite_asset"],
                "Core": "QLD 25% / BTAL 25%",
                "Target allocation": display_allocation(signal["target_weights"], signal_execution_currency),
            }])
            st.dataframe(alpha_inputs.style.format({"BTAL blended momentum": "{:.6f}", "BIL blended momentum": "{:.6f}"}), use_container_width=True, hide_index=True)
            st.caption("Blended momentum = (1-month return + 3-month return + 6-month return + 12-month return) / 4. A tie allocates the satellite to QLD.")
        elif isinstance(signal_strategy, (CenturyMomentum, CenturyMomentumIsrael)):
            equity_asset = signal_strategy.equity_asset
            century_inputs = pd.DataFrame([{
                f"{equity_asset} close": signal[f"{equity_asset}_price"],
                f"{equity_asset} 10-month SMA": signal[f"{equity_asset}_10m_sma"],
                "Trend state": f"Above SMA — hold {equity_asset}" if signal["trend_up"] else f"At/below SMA — hold {signal_strategy.defensive_asset}",
            }])
            st.dataframe(century_inputs.style.format({f"{equity_asset} close": "{:.4f}", f"{equity_asset} 10-month SMA": "{:.4f}"}), use_container_width=True, hide_index=True)
            st.caption(f"The SMA uses the ten completed month-end closes including the current signal close. A tie selects {signal_strategy.defensive_asset}; the decision takes effect on the next available trading day.")
        else:
            price_columns = [f"{asset}_price" for asset in signal_momentum_assets if f"{asset}_price" in signal.index]
            momentum_columns = [f"{asset}_13612u" for asset in signal_momentum_assets if f"{asset}_13612u" in signal.index]
            inputs = pd.DataFrame({
                "month-end price": {column.removesuffix("_price"): signal[column] for column in price_columns},
                "13612U momentum": {column.removesuffix("_13612u"): signal[column] for column in momentum_columns},
            }).T
            st.dataframe(inputs.style.format("{:.6f}"), use_container_width=True)
            st.caption("13612U = (1-month return + 3-month return + 6-month return + 12-month return) / 4. The leveraged model uses SPY and TIP—not SSO momentum—to determine its gate.")
    history_columns = ["regime", "selected_asset", "previous_asset", "trade"]
    if "target_weights" in signal_decisions:
        history_columns.insert(2, "target_weights")
    if signal_decisions.empty:
        history = pd.DataFrame(columns=[*history_columns, "effective_start"])
        history.index.name = "signal_date"
    else:
        history = signal_decisions.loc[:, history_columns].copy()
        history["effective_start"] = [first_trading_day_after(signal_prices, date, execution_assets(history.loc[date], getattr(signal_strategy, "benchmark_asset", "SPY"))) for date in history.index]
        if "target_weights" in history:
            history["target_weights"] = history["target_weights"].map(lambda weights: ", ".join(f"{asset} {weight:.0%}" for asset, weight in weights.items()))
        history.index = pd.to_datetime(history.index).strftime("%Y-%m-%d")
        history = history.rename_axis("signal_date")
    with st.expander("Signal history"):
        st.dataframe(history.sort_index(ascending=False), use_container_width=True)
        st.download_button("Download signal history CSV", history.to_csv().encode("utf-8"), f"{signal_strategy.name.lower().replace(' ', '_').replace('(', '').replace(')', '')}_signal_history.csv", "text/csv")
    with st.expander("Data status"):
        st.caption("This signal uses completed month-end data only. Backtest settings do not affect it.")
        if isinstance(signal_strategy, HAASimpleIsrael) and tase_warning:
            st.warning(f"Public TASE/Maya retrieval issue: {tase_warning}")
        if isinstance(signal_strategy, (InflationCompassFast, InflationCompassStandard, InflationCompassSteady)) and fred_warning:
            st.warning(f"FRED retrieval issue: {fred_warning}")
        if isinstance(signal_strategy, GGCEMLinkOriginal) and oecd_warning:
            st.warning(f"OECD CLI retrieval issue: {oecd_warning}. This signal is using the disclosed SPY/BIL failsafe.")
        st.dataframe(source_metadata.loc[list(signal_data_assets)], use_container_width=True)
        raw_ranges = date_ranges(signal_prices)
        st.dataframe(raw_ranges, use_container_width=True)
        st.caption(f"Latest eligible completed month: {signal_status.completed_through.date()}. A partial current month is never presented as a final signal.")
    st.caption("Rules-based informational signal only; not investment advice. You are responsible for any trading decision and execution.")

if page == "Rules":
    title_column.title("Rules")
    st.subheader("Model rules")
    st.markdown(MODEL_RULES[model_name])
    if model_definition.strategy_mode == "buy_and_hold":
        st.info("Internally managed momentum strategy: the fund is held continuously and the underlying index manages momentum weighting. Unlike externally timed strategies, it has no app-generated BUY, SELL, or CASH signal.")
        st.write("**Market:** Israel  \\n+**Fund:** Migdal MTF TA-125 Smart Momentum (5134713)  \\n+**Underlying index:** TA-125 Smart Momentum  \\n+**Implementation:** Buy & Hold  \\n+**Signal frequency:** None  \\n+**Review frequency:** Annual  \\n+**Evidence status:** Limited / developing  \\n+**Suggested portfolio maximum:** 20% (guidance only)")

    with st.expander("Implementation and data notes", expanded=False):
        st.markdown("""**13612U:** `(1-month return + 3-month return + 6-month return + 12-month return) / 4`. Each return is `price at signal date / price at its historical month-end - 1`. This implementation therefore requires 12 earlier observations of each asset it actually needs and uses no later prices.

**Data:** TIP and all non-Israel assets use Yahoo Finance. HAA-Simple Israel retrieves CSPX_IL (1159250), IEF_IL (1159268), and AYALON_KASPIT (5136866) from public TASE/Maya endpoints through tasekit; the ETF adapter uses adjusted close when available, then published NAV, then end-of-day close, while the mutual fund uses its published Maya redemption price. Public endpoints may change or be blocked, so this source is for personal research and CSV replacement remains available. Enter `ASSET=YAHOO_TICKER` mappings only for Yahoo-sourced roles in the sidebar. Uploaded CSV data replaces an asset’s entire history; use one uploader and name files with their target role, e.g. `SSO.csv`. No missing ETF or fund history is fabricated.

**Tax:** applies only when an existing position is sold due to an allocation change. It tracks cost basis and loss carryforward, never taxes the final unrealized position, and is independent of the strategy module.""")
    st.write(f"First valid signal date: **{first_signal.date()}**")
    with st.expander("Data coverage", expanded=False):
        if isinstance(strategy, HAASimpleIsrael) and tase_warning:
            st.warning(f"Public TASE/Maya retrieval issue: {tase_warning}")
        if isinstance(strategy, (InflationCompassFast, InflationCompassStandard, InflationCompassSteady)) and fred_warning:
            st.warning(f"FRED retrieval issue: {fred_warning}")
        if isinstance(strategy, GGCEMLinkOriginal) and oecd_warning:
            st.warning(f"OECD CLI retrieval issue: {oecd_warning}. The strategy falls back to the disclosed SPY/BIL regime gate.")
        st.dataframe(source_metadata.loc[list(data_assets)].join(date_ranges(prices)), use_container_width=True)
        missing = monthly[monthly.isna().any(axis=1)]
        st.write(f"Months with at least one missing canonical price: **{len(missing)}**")
    audit_momentum_assets = getattr(strategy, "signal_assets", data_assets)
    audit_columns = [f"{asset}_price" for asset in data_assets]
    if not isinstance(strategy, (BAAG4Aggressive, CenturyMomentum, CenturyMomentumIsrael, GEM, GrowthInflationConcentrated, GrowthInflationDiversified, VAAG4, OrthogonalAlpha)):
        audit_columns += [f"{asset}_13612u" for asset in audit_momentum_assets]
    if isinstance(strategy, (HAAClassicNoQQQ, HAAClassicLeveragedNoQQQ, HAA4, HAA4Leveraged2x)):
        audit_columns += [f"{asset}_rank" for asset in strategy.offensive_assets] + ["selected_assets", "target_weights", "previous_weights"]
        if isinstance(strategy, (HAA4, HAA4Leveraged2x)):
            audit_columns += ["defensive_winner", "selected_offensive_assets", "replaced_offensive_assets"]
        if isinstance(strategy, HAA4Leveraged2x):
            audit_columns += ["selected_underlying_assets", "mapped_holding_assets"]
    if isinstance(strategy, (InflationCompassFast, InflationCompassStandard, InflationCompassSteady)):
        audit_columns += ["SPY_200d_sma", "t5yie_lag_date", "t5yie_lagged", "t5yie_momentum_date", "t5yie_momentum_value", "positive_basket_growth", "negative_basket_growth", "inflation_indicator", "indicator_momentum_slope", "growth_up", "inflation_level", "breakeven_momentum", "asset_momentum", "inflation_on", "target_weights", "previous_weights"]
        if isinstance(strategy, HAAClassicLeveragedNoQQQ):
            audit_columns += ["selected_underlying_assets", "mapped_holding_assets"]
    if isinstance(strategy, (GrowthInflationConcentrated, GrowthInflationDiversified)):
        audit_columns += ["SPY_200d_sma", "positive_sector_basket", "negative_sector_basket", "inflation_ratio", "inflation_ratio_200d_sma", "growth_up", "inflation_on", "target_weights", "previous_weights"]
    if isinstance(strategy, VAAG4):
        audit_columns += [f"{asset}_13612w" for asset in data_assets] + ["breadth_bad_count", "breadth_threshold", "offensive_winner", "defensive_winner", "target_weights", "previous_weights"]
    if isinstance(strategy, BAAG4Aggressive):
        audit_columns += [f"{asset}_13612w" for asset in strategy.canary_assets] + [f"{asset}_sma12" for asset in data_assets] + ["breadth_bad_count", "selected_defensive_assets", "bil_replacements", "target_weights", "previous_weights"]
    if isinstance(strategy, GEM):
        audit_columns += [f"{asset}_12m_return" for asset in strategy.signal_assets] + ["signal_selected_asset"]
    if isinstance(strategy, GGCEMLinkOriginal):
        audit_columns += [f"{asset}_12m_return" for asset in strategy.signal_assets] + ["oecd_cli_diffusion", "macro_source", "risk_on", "signal_selected_asset"]
    if isinstance(strategy, OrthogonalAlpha):
        audit_columns += ["BTAL_13612u", "BIL_13612u", "satellite_asset", "target_weights", "previous_weights"]
    if isinstance(strategy, (CenturyMomentum, CenturyMomentumIsrael)):
        audit_columns += [f"{strategy.equity_asset}_10m_sma", "trend_up"]
    audit_columns += ["regime", "selected_asset", "previous_asset", "trade", "execution_date", "holding_end", "holding_period_return"]
    audit = result.audit[[column for column in audit_columns if column in result.audit.columns]]
    with st.expander("Monthly audit table"):
        st.dataframe(audit.style.format("{:.6f}", subset=[c for c in audit.columns if c.endswith("13612u") or c.endswith("return")]), use_container_width=True)
        st.download_button("Download audit CSV", audit.to_csv().encode("utf-8"), f"{strategy.name.lower().replace(' ', '_').replace('(', '').replace(')', '')}_monthly_audit.csv", "text/csv")
    with st.expander("Raw and monthly data used", expanded=False):
        raw_tab, monthly_tab = st.tabs(["Daily", "Month-end"])
        with raw_tab:
            st.dataframe(prices, use_container_width=True)
        with monthly_tab:
            st.dataframe(monthly, use_container_width=True)
    st.caption("Automated validation: run `pytest` locally; tests cover strategy selection, timing, benchmark dates, tax realization, conditional early risk-on execution, and a hand-calculated 13612U example.")
