"use client";
import text from "../../content/backtest.json";

export type FeeAssumptions = { fees_enabled: boolean; ils_fee_percent: number; ils_minimum_fee: number; usd_flat_fee: number };
export const defaultFees: FeeAssumptions = { fees_enabled: true, ils_fee_percent: .05, ils_minimum_fee: 2, usd_flat_fee: 5 };

export default function Fees({ value, onChange }: { value: FeeAssumptions; onChange: (patch: Partial<FeeAssumptions>) => void }) {
  return <fieldset><legend>{text.tradingFees}</legend>
    <label>{text.feesEnabled}<input type="checkbox" checked={value.fees_enabled} onChange={e => onChange({ fees_enabled: e.target.checked })} /></label>
    <div className="backtest-grid">
      <label>{text.ilsFeePercent}<input type="number" min="0" max="10" step="0.01" disabled={!value.fees_enabled} value={value.ils_fee_percent} onChange={e => onChange({ ils_fee_percent: e.target.valueAsNumber })} /></label>
      <label>{text.ilsMinimumFee}<input type="number" min="0" step="0.01" disabled={!value.fees_enabled} value={value.ils_minimum_fee} onChange={e => onChange({ ils_minimum_fee: e.target.valueAsNumber })} /></label>
      <label>{text.usdFlatFee}<input type="number" min="0" step="0.01" disabled={!value.fees_enabled} value={value.usd_flat_fee} onChange={e => onChange({ usd_flat_fee: e.target.valueAsNumber })} /></label>
    </div>
    <p>{text.feeHelp}</p>
  </fieldset>;
}
