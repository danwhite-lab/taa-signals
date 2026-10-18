"""Verbatim Signals presentation port from app.py (not imported or executed).

Only UI collection and Pandas Styler rendering are adapted. Strategy branches,
text, table inputs and Python formatting remain the original presentation.
"""
import pandas as pd
from haa.portfolio import execution_security_label
from haa.strategies import (BAAG4Aggressive, CenturyMomentum, CenturyMomentumIsrael, GEM, GGCEMLinkOriginal, GrowthInflationConcentrated, GrowthInflationConcentratedIsrael, GrowthInflationDiversified, HAA4, HAA4Leveraged2x, HAAClassicLeveragedNoQQQ, HAAClassicNoQQQ, HAASimpleIsrael, HAASimpleLeveraged2x, InflationCompassFast, InflationCompassStandard, InflationCompassSteady, OrthogonalAlpha, VAAG4)
from .signals_wire import table

class Presentation:
    def __init__(self):
        self.result = {"heading": "Why this allocation", "paragraphs": [], "captions": [], "tables": []}
    def subheader(self, text):
        self.result["heading"] = text
    def write(self, text):
        self.result["paragraphs"].append(text)
    def caption(self, text):
        self.result["captions"].append(text)
    def dataframe(self, frame, formats=None, hide_index=False, **kwargs):
        self.result["tables"].append(table(frame, formats=formats, index=not hide_index))

def display_allocation(weights: dict[str, float], currency: str) -> str:
    """Format an executable allocation with broker-facing security labels."""
    return ", ".join(f"{execution_security_label(asset, currency)} {weight:.0%}" for asset, weight in weights.items())

def rationale(signal_strategy, signal, signal_execution_currency, signal_momentum_assets):
    display = Presentation()
    display.subheader('Why this allocation')
    if isinstance(signal_strategy, (HAA4, HAA4Leveraged2x)):
        if signal['regime'] == 'risk-off':
            holding = signal['selected_asset'] if isinstance(signal_strategy, HAA4Leveraged2x) else signal['defensive_winner']
            display.write(f'TIP 13612U momentum is not positive, so the model holds 100% of the higher-momentum defensive asset: {holding}.')
        elif signal['replaced_offensive_assets']:
            mapped = f" Final holdings: {signal['mapped_holding_assets']}." if isinstance(signal_strategy, HAA4Leveraged2x) else ''
            display.write(f"TIP 13612U momentum is positive, so the model selected {signal['selected_offensive_assets']}. The non-positive sleeve(s) {signal['replaced_offensive_assets']} were replaced with {signal['defensive_winner']}.{mapped}")
        else:
            holdings = signal['mapped_holding_assets'] if isinstance(signal_strategy, HAA4Leveraged2x) else signal['selected_offensive_assets']
            display.write(f'TIP 13612U momentum is positive and both selected offensive assets are positive, so the model holds {holdings} at 50% each.')
    elif isinstance(signal_strategy, (InflationCompassFast, InflationCompassStandard, InflationCompassSteady)):
        display.write(f"Growth is {('up' if signal['growth_up'] else 'down')} and inflation is {('on' if signal['inflation_on'] else 'off')}, producing the {signal['regime'].replace('-', ' ')} allocation.")
    elif isinstance(signal_strategy, (GrowthInflationConcentrated, GrowthInflationDiversified)):
        display.write(f"Growth is {('high' if signal['growth_up'] else 'low')} because SPY is {('above' if signal['growth_up'] else 'at or below')} its 200-day SMA. Inflation is {('high' if signal['inflation_on'] else 'low')} because the sector ratio is {('above' if signal['inflation_on'] else 'at or below')} its 200-day SMA, producing the {signal['regime']} allocation.")
        if isinstance(signal_strategy, GrowthInflationConcentratedIsrael):
            display.caption('The regime is calculated from U.S. market data; the displayed allocation is the corresponding TASE-listed ILS execution security.')
    elif isinstance(signal_strategy, VAAG4):
        if signal['regime'] == 'risk-on':
            display.write(f"All four offensive assets have positive 13612W momentum, so VAA holds the highest-scoring offensive asset: {signal['offensive_winner']}.")
        else:
            display.write(f"{signal['breadth_bad_count']} offensive asset(s) have non-positive 13612W momentum. With B=1, breadth protection is active and VAA holds the best defensive asset: {signal['defensive_winner']}.")
    elif isinstance(signal_strategy, BAAG4Aggressive):
        if signal['regime'] == 'risk-on':
            display.write(f"All four canaries have positive 13612W momentum, so BAA holds the highest-ranked offensive asset: {signal['selected_asset']}.")
        elif signal['bil_replacements']:
            display.write(f"{signal['breadth_bad_count']} canary asset(s) have non-positive 13612W momentum, so BAA selected the top three defensive assets. {signal['bil_replacements']} ranked below BIL and were replaced with BIL.")
        else:
            display.write(f"{signal['breadth_bad_count']} canary asset(s) have non-positive 13612W momentum, so BAA holds the top three defensive assets: {signal['selected_asset']}.")
    elif isinstance(signal_strategy, GEM):
        source_holding = signal.get('signal_selected_asset', signal['selected_asset'])
        if signal['regime'] == 'risk-off':
            display.write("SPY's completed 12-month return is at or below BIL's, so GEM holds aggregate bonds.")
        elif source_holding == 'SPY':
            display.write("SPY's completed 12-month return is above BIL's and at least VEU's, so GEM holds U.S. equities.")
        else:
            display.write("SPY's completed 12-month return is above BIL's, but VEU has the higher relative return, so GEM holds international equities.")
    elif isinstance(signal_strategy, GGCEMLinkOriginal):
        source = signal.get('macro_source')
        if signal['risk_on']:
            display.write(f"{source} set a risk-on regime. The model then selected the stronger 12-month equity leg: {signal.get('signal_selected_asset', signal['selected_asset'])}.")
        else:
            display.write(f"{source} set a risk-off regime. The model then selected the stronger 12-month defensive leg: {signal.get('signal_selected_asset', signal['selected_asset'])}.")
    elif isinstance(signal_strategy, OrthogonalAlpha):
        if signal['satellite_asset'] == 'BTAL':
            display.write("BTAL's blended 1/3/6/12-month momentum is strictly greater than BIL's, so the 50% satellite holds BTAL alongside the permanent 25% QLD / 25% BTAL core.")
        else:
            display.write("BTAL's blended 1/3/6/12-month momentum is at or below BIL's, so the 50% satellite holds QLD alongside the permanent 25% QLD / 25% BTAL core.")
    elif isinstance(signal_strategy, (CenturyMomentum, CenturyMomentumIsrael)):
        comparison = 'above' if signal['trend_up'] else 'at or below'
        display.write(f"{signal_strategy.equity_asset}'s completed month-end close is {comparison} its 10-month SMA, so Century Momentum holds {execution_security_label(signal['selected_asset'], signal_execution_currency)}.")
    elif isinstance(signal_strategy, (HAAClassicNoQQQ, HAAClassicLeveragedNoQQQ)) and signal['regime'] == 'risk-on':
        if isinstance(signal_strategy, HAAClassicLeveragedNoQQQ):
            display.write(f"TIP 13612U momentum is strictly positive, so the model selects the four highest-momentum 1x underlyings ({signal['selected_underlying_assets']}) and holds their mapped 2x ETFs ({signal['mapped_holding_assets']}).")
        else:
            display.write(f"TIP 13612U momentum is strictly positive, so the model selects the four highest-momentum offensive assets: {signal['selected_assets']}.")
    elif isinstance(signal_strategy, (HAAClassicNoQQQ, HAAClassicLeveragedNoQQQ)):
        if isinstance(signal_strategy, HAAClassicLeveragedNoQQQ):
            display.write(f"TIP 13612U momentum is not positive, so the model compares 1x IEF and BIL momentum and holds the mapped defensive asset: {signal['selected_asset']}.")
        else:
            display.write(f"TIP 13612U momentum is not positive, so the model selects the higher-momentum defensive asset: {signal['selected_asset']}.")
    elif isinstance(signal_strategy, HAASimpleIsrael) and signal['regime'] == 'risk-on':
        display.write('TIP and CSPX_IL 13612U momentum are both strictly positive, so the model selects CSPX — 1159250.')
    elif isinstance(signal_strategy, HAASimpleIsrael):
        selected_security = execution_security_label(signal['selected_asset'], signal_execution_currency)
        display.write(f'At least one of TIP or CSPX_IL 13612U momentum is not positive, so the model selects the higher-momentum Israeli defensive security: {selected_security}.')
    elif signal['regime'] == 'risk-on':
        holding = 'SSO' if isinstance(signal_strategy, HAASimpleLeveraged2x) else 'SPY'
        display.write(f'SPY and TIP 13612U momentum are both strictly positive, so the model selects {holding}.')
    else:
        display.write(f"At least one of SPY or TIP 13612U momentum is not positive, so the model selects the higher-momentum defensive asset: {signal['selected_asset']}.")
    if isinstance(signal_strategy, (InflationCompassFast, InflationCompassStandard, InflationCompassSteady)):
        window = signal_strategy.momentum_window
        compass_inputs = pd.DataFrame([{'SPY close': signal['SPY_price'], 'SPY 200-day SMA': signal['SPY_200d_sma'], 'Growth up': signal['growth_up'], 'T5YIE date (lagged)': signal['t5yie_lag_date'], 'T5YIE (lagged)': signal['t5yie_lagged'], f'T5YIE {window}-day date': signal['t5yie_momentum_date'], f'T5YIE {window}-day value': signal['t5yie_momentum_value'], 'Breakeven momentum': signal['breakeven_momentum'], 'Inflation indicator': signal['inflation_indicator'], f'{window}-day indicator slope': signal['indicator_momentum_slope'], 'Asset momentum': signal['asset_momentum'], 'Inflation on': signal['inflation_on']}])
        display.dataframe(compass_inputs, use_container_width=True, hide_index=True, formats={'SPY close': '{:.4f}', 'SPY 200-day SMA': '{:.4f}', 'T5YIE (lagged)': '{:.4f}', f'T5YIE {window}-day value': '{:.4f}', 'Inflation indicator': '{:.6f}', f'{window}-day indicator slope': '{:.8f}'})
        display.caption(f'T5YIE is read from the prior available trading-day observation. Both confirmation windows use {window} valid trading observations.')
    elif isinstance(signal_strategy, (GrowthInflationConcentrated, GrowthInflationDiversified)):
        timing_inputs = pd.DataFrame([{'SPY close': signal['SPY_price'], 'SPY 200-day SMA': signal['SPY_200d_sma'], 'Growth state': 'High' if signal['growth_up'] else 'Low', 'Inflation-positive basket': signal['positive_sector_basket'], 'Inflation-negative basket': signal['negative_sector_basket'], 'Inflation ratio': signal['inflation_ratio'], 'Inflation ratio 200-day SMA': signal['inflation_ratio_200d_sma'], 'Inflation state': 'High' if signal['inflation_on'] else 'Low'}])
        display.dataframe(timing_inputs, use_container_width=True, hide_index=True, formats={'SPY close': '{:.4f}', 'SPY 200-day SMA': '{:.4f}', 'Inflation-positive basket': '{:.4f}', 'Inflation-negative basket': '{:.4f}', 'Inflation ratio': '{:.6f}', 'Inflation ratio 200-day SMA': '{:.6f}'})
        display.caption('The inflation ratio is the equal-weighted inflation-positive sector basket divided by the equal-weighted inflation-negative sector basket. Both states use completed daily data at month-end.')
    elif isinstance(signal_strategy, VAAG4):
        vaa_inputs = pd.DataFrame([{'Bad offensive assets': signal['breadth_bad_count'], 'Breadth threshold (B)': signal['breadth_threshold'], 'Top offensive': signal['offensive_winner'], 'Top defensive': signal['defensive_winner'], **{f'{asset} 13612W': signal[f'{asset}_13612w'] for asset in signal_strategy.data_assets}}])
        display.dataframe(vaa_inputs, use_container_width=True, hide_index=True, formats={column: '{:.6f}' for column in vaa_inputs.columns if column.endswith('13612W')})
        display.caption('13612W = (12×1-month return + 4×3-month return + 2×6-month return + 12-month return) / 4. Momentum equal to zero is non-positive.')
    elif isinstance(signal_strategy, BAAG4Aggressive):
        baa_inputs = pd.DataFrame([{'Non-positive canaries': signal['breadth_bad_count'], 'Selected defensive assets': signal['selected_defensive_assets'] or '—', 'BIL replacements': signal['bil_replacements'] or '—', **{f'{asset} 13612W': signal[f'{asset}_13612w'] for asset in signal_strategy.canary_assets}, **{f'{asset} SMA(12)': signal[f'{asset}_sma12'] for asset in signal_strategy.signal_assets}}])
        display.dataframe(baa_inputs, use_container_width=True, hide_index=True, formats={column: '{:.6f}' for column in baa_inputs.columns if column.endswith('13612W') or column.endswith('SMA(12)')})
        display.caption('BAA ranks by current month-end price ÷ the average of the current and prior twelve month-ends − 1. Its canaries use 13612W; any value at or below zero activates defense.')
    elif isinstance(signal_strategy, GEM):
        gem_inputs = pd.DataFrame([{'SPY 12-month return': signal['SPY_12m_return'], 'VEU 12-month return': signal['VEU_12m_return'], 'AGG 12-month return': signal['AGG_12m_return'], 'BIL 12-month return': signal['BIL_12m_return'], 'Published holding': signal.get('signal_selected_asset', signal['selected_asset'])}])
        display.dataframe(gem_inputs, use_container_width=True, hide_index=True, formats={column: '{:.2%}' for column in gem_inputs.columns if column.endswith('return')})
        display.caption('GEM compares completed 12-month returns. SPY must strictly exceed BIL; an exact SPY/VEU tie selects SPY.')
    elif isinstance(signal_strategy, GGCEMLinkOriginal):
        ggcem_inputs = pd.DataFrame([{'CLI diffusion (prior month)': signal['oecd_cli_diffusion'], 'Regime source': signal['macro_source'], 'Risk-on': signal['risk_on'], 'SPY 12-month return': signal['SPY_12m_return'], 'VEU 12-month return': signal['VEU_12m_return'], 'IEF 12-month return': signal['IEF_12m_return'], 'BIL 12-month return': signal['BIL_12m_return']}])
        display.dataframe(ggcem_inputs, use_container_width=True, hide_index=True, formats={column: '{:.2%}' for column in ggcem_inputs.columns if 'return' in column or 'diffusion' in column})
        display.caption('Risk-on requires OECD diffusion strictly above 50%. The prior-month reading applies the publication lag; if unavailable, SPY-versus-BIL is the visible failsafe.')
    elif isinstance(signal_strategy, OrthogonalAlpha):
        alpha_inputs = pd.DataFrame([{'BTAL blended momentum': signal['BTAL_13612u'], 'BIL blended momentum': signal['BIL_13612u'], 'Satellite': signal['satellite_asset'], 'Core': 'QLD 25% / BTAL 25%', 'Target allocation': display_allocation(signal['target_weights'], signal_execution_currency)}])
        display.dataframe(alpha_inputs, use_container_width=True, hide_index=True, formats={'BTAL blended momentum': '{:.6f}', 'BIL blended momentum': '{:.6f}'})
        display.caption('Blended momentum = (1-month return + 3-month return + 6-month return + 12-month return) / 4. A tie allocates the satellite to QLD.')
    elif isinstance(signal_strategy, (CenturyMomentum, CenturyMomentumIsrael)):
        equity_asset = signal_strategy.equity_asset
        century_inputs = pd.DataFrame([{f'{equity_asset} close': signal[f'{equity_asset}_price'], f'{equity_asset} 10-month SMA': signal[f'{equity_asset}_10m_sma'], 'Trend state': f'Above SMA — hold {equity_asset}' if signal['trend_up'] else f'At/below SMA — hold {signal_strategy.defensive_asset}'}])
        display.dataframe(century_inputs, use_container_width=True, hide_index=True, formats={f'{equity_asset} close': '{:.4f}', f'{equity_asset} 10-month SMA': '{:.4f}'})
        display.caption(f'The SMA uses the ten completed month-end closes including the current signal close. A tie selects {signal_strategy.defensive_asset}; the decision takes effect on the next available trading day.')
    else:
        price_columns = [f'{asset}_price' for asset in signal_momentum_assets if f'{asset}_price' in signal.index]
        momentum_columns = [f'{asset}_13612u' for asset in signal_momentum_assets if f'{asset}_13612u' in signal.index]
        inputs = pd.DataFrame({'month-end price': {column.removesuffix('_price'): signal[column] for column in price_columns}, '13612U momentum': {column.removesuffix('_13612u'): signal[column] for column in momentum_columns}}).T
        display.dataframe(inputs, use_container_width=True, formats='{:.6f}')
        display.caption('13612U = (1-month return + 3-month return + 6-month return + 12-month return) / 4. The leveraged model uses SPY and TIP—not SSO momentum—to determine its gate.')
    return display.result
