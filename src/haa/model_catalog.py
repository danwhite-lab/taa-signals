"""Authoritative UI catalogue for the app's existing stable implementations."""

from __future__ import annotations

from dataclasses import dataclass

from .strategies import (
    HAA4,
    HAA4Israel,
    HAA4Leveraged2x,
    HAAClassicLeveragedNoQQQ,
    HAAClassicNoQQQ,
    CenturyMomentum,
    CenturyMomentumIsrael,
    HAASimple,
    HAASimpleIsrael,
    HAASimpleLeveraged2x,
    InflationCompassFast,
    InflationCompassFastIsrael,
    InflationCompassStandard,
    InflationCompassStandardIsrael,
    InflationCompassSteady,
    InflationCompassSteadyIsrael,
    TA125SmartMomentum,
    GrowthInflationConcentrated,
    GrowthInflationConcentratedIsrael,
    GrowthInflationDiversified,
    GEM,
    GEMIsrael,
    GGCEMLinkOriginal,
    GGCEMLinkOriginalIsrael,
    OrthogonalAlpha,
    BAAG4Aggressive,
    BAAG4AggressiveIsrael,
    VAAG4,
    MomentumCorrelationTriplet,
)


@dataclass(frozen=True)
class ModelDefinition:
    strategy: str
    variant: str | None
    implementation: str
    label: str
    model_class: type
    execution_currency: str = "USD"
    strategy_mode: str = "externally_timed"
    signal_mode: str = "external"
    suggested_max_weight: float | None = None
    description: str | None = None


MODEL_CATALOG: tuple[ModelDefinition, ...] = (
    ModelDefinition("HAA", "Simple", "Original", "HAA-Simple", HAASimple),
    ModelDefinition("HAA", "Simple", "Israel", "HAA-Simple Israel", HAASimpleIsrael, "ILS"),
    ModelDefinition("HAA", "Simple Leveraged 2x", "Original", "HAA-Simple Leveraged 2x (SSO)", HAASimpleLeveraged2x),
    ModelDefinition("HAA", "HAA 4", "Original", "HAA 4", HAA4),
    ModelDefinition("HAA", "HAA 4", "Israel", "HAA 4 Israel", HAA4Israel, "ILS", "externally_timed", "external", None, "Uses published HAA-4 USD signals and maps SPY to CSPX, VEA to IBI MSCI AC World ex USA, VNQ to IBI DJ US Real Estate, IEF to 1159268, and BIL to Keren Kaspit. Its backtest uses VXUS as the U.S. return proxy for the ex-US TASE fund, not TASE or ILS performance."),
    ModelDefinition("HAA", "HAA 4 Leveraged 2x", "Original", "HAA 4 Leveraged 2x", HAA4Leveraged2x),
    ModelDefinition("HAA", "Classic (No QQQ)", "Original", "HAA Classic (No QQQ)", HAAClassicNoQQQ),
    ModelDefinition("HAA", "Classic Leveraged 2x (No QQQ)", "Original", "HAA Classic Leveraged 2x (No QQQ)", HAAClassicLeveragedNoQQQ),
    ModelDefinition("Inflation Compass", "Standard", "Original", "Inflation Compass Standard", InflationCompassStandard),
    ModelDefinition("Inflation Compass", "Standard", "Israel", "Inflation Compass Standard Israel", InflationCompassStandardIsrael, "ILS"),
    ModelDefinition("Inflation Compass", "Fast (40-day)", "Original", "Inflation Compass Fast (40-day)", InflationCompassFast),
    ModelDefinition("Inflation Compass", "Fast (40-day)", "Israel", "Inflation Compass Fast (40-day) Israel", InflationCompassFastIsrael, "ILS"),
    ModelDefinition("Inflation Compass", "Steady (80-day)", "Original", "Inflation Compass Steady (80-day)", InflationCompassSteady),
    ModelDefinition("Inflation Compass", "Steady (80-day)", "Israel", "Inflation Compass Steady (80-day) Israel", InflationCompassSteadyIsrael, "ILS"),
    ModelDefinition("Buy and Hold", "TA-125 Smart Momentum", "Migdal MTF TA-125 Smart Momentum", "TA-125 Smart Momentum", TA125SmartMomentum, "ILS", "buy_and_hold", "internal", 0.20, "Israeli equity momentum held through fund 5134713. The underlying TA-125 Smart Momentum index adjusts TA-125 weights internally using momentum/trend strength, including its 50-day and 200-day moving-average relationship. Investors hold the fund continuously; there is no investor-level timing signal."),
    ModelDefinition("Century Momentum", "Standard", "Original", "Century Momentum", CenturyMomentum, "USD", "externally_timed", "external", None, "SPMO is held when its completed month-end close is above its 10-month moving average; otherwise the strategy holds IEF. Backtests use actual SPMO history only, without an academic pre-ETF splice."),
    ModelDefinition("Century Momentum", "Standard", "Israel", "Century Momentum Israel", CenturyMomentumIsrael, "ILS", "externally_timed", "external", None, "MTF Tracking S&P 500 Momentum (4D), 5140850, is held when its completed month-end close is above its 10-month moving average; otherwise the strategy holds iShares $ Treasury Bond 7–10yr UCITS, 1159268. Backtests use the actual TASE fund histories only."),
    ModelDefinition("Growth-Inflation Sector Timing", "Concentrated", "Original", "Growth-Inflation Concentrated", GrowthInflationConcentrated),
    ModelDefinition("Growth-Inflation Sector Timing", "Concentrated", "Israel", "Growth-Inflation Concentrated Israel", GrowthInflationConcentratedIsrael, "ILS", "externally_timed", "external", None, "Uses the original U.S. growth and sector-ratio signals, then executes the selected sector through TASE-listed Israeli ETFs in ILS."),
    ModelDefinition("Growth-Inflation Sector Timing", "Diversified", "Original", "Growth-Inflation Diversified", GrowthInflationDiversified),
    ModelDefinition("GEM", "Standard", "Original", "GEM", GEM),
    ModelDefinition("GEM", "Standard", "Israel", "GEM Israel", GEMIsrael, "ILS", "externally_timed", "external", None, "Uses published GEM USD signals and maps SPY to CSPX, VEU to ACWX (5142476), and AGG to BNDW (1159102). Its backtest uses ACWX and BNDW U.S. return proxies, not TASE fund or ILS performance."),
    ModelDefinition("GGCEM", "Link Original", "Original", "GGCEM Link Original", GGCEMLinkOriginal),
    ModelDefinition("GGCEM", "Link Original", "Israel", "GGCEM Link Original Israel", GGCEMLinkOriginalIsrael, "ILS", "externally_timed", "external", None, "Uses the published OECD CLI diffusion regime and maps SPY to CSPX (1159250), VEU to ACWX (5142476), IEF to IEF (1159268), and BIL to Keren Kaspit (5136866). Its backtest uses U.S. SPY, ACWX, IEF, and BIL returns, not TASE or ILS performance."),
    ModelDefinition("VAA", "G4 (T1/B1)", "Original", "VAA-G4 (T1/B1)", VAAG4),
    ModelDefinition("Momentum-Correlation Triplet", "Standard", "Original", "Momentum-Correlation Triplet", MomentumCorrelationTriplet),
    ModelDefinition("BAA", "G4 (Aggressive)", "Original", "BAA-G4 (Aggressive)", BAAG4Aggressive),
    ModelDefinition("BAA", "G4 (Aggressive)", "Israel", "BAA-G4 (Aggressive) Israel", BAAG4AggressiveIsrael, "ILS", "externally_timed", "external", None, "Uses published USD BAA-G4 signals and maps the selected holdings to the specified TASE-listed ILS securities. Its backtest uses the corresponding U.S. execution-proxy returns—VXUS, BNDW, and GLDM where needed—not TASE fund returns or ILS performance."),
    ModelDefinition("Orthogonal Alpha", None, "Standard", "Orthogonal Alpha (BTAL/QLD)", OrthogonalAlpha, "USD", "externally_timed", "external", None, "Thomas Carlson's monthly core-satellite model: a permanent 25% QLD / 25% BTAL core plus a 50% satellite that holds BTAL when BTAL's equal-weighted 1/3/6/12-month momentum exceeds BIL, otherwise QLD."),
)


def strategies() -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strategy for item in MODEL_CATALOG))


def variants(strategy: str) -> tuple[str | None, ...]:
    return tuple(dict.fromkeys(item.variant for item in MODEL_CATALOG if item.strategy == strategy))


def implementations(strategy: str, variant: str | None) -> tuple[str, ...]:
    return tuple(item.implementation for item in MODEL_CATALOG if item.strategy == strategy and item.variant == variant)


def resolve(strategy: str, variant: str | None, implementation: str) -> ModelDefinition:
    for item in MODEL_CATALOG:
        if (item.strategy, item.variant, item.implementation) == (strategy, variant, implementation):
            return item
    raise ValueError(f"Unknown model selection: {strategy} / {variant} / {implementation}")


def definition_for_label(label: str) -> ModelDefinition:
    for item in MODEL_CATALOG:
        if item.label == label:
            return item
    raise ValueError(f"Unknown model label: {label}")
