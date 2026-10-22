"use client";
import type { ReactNode } from "react";
import text from "../content/backtest.json";

export type FeeAssumptions = { fees_enabled: boolean; ils_fee_percent: number; ils_minimum_fee: number; usd_flat_fee: number };
export const defaultFees: FeeAssumptions = { fees_enabled: true, ils_fee_percent: .05, ils_minimum_fee: 2, usd_flat_fee: 5 };

export function AssumptionRow({ children }: { children: ReactNode }) {
  return <div className="assumption-row">{children}</div>;
}

export function TaxControls({ enabled, rate, onEnabled, onRate, label = text.taxEnabled, rateLabel = text.taxRate, disabled = false, hideRate = false, step }:
  { enabled: boolean; rate: number; onEnabled: (value: boolean) => void; onRate: (value: number) => void;
    label?: string; rateLabel?: string; disabled?: boolean; hideRate?: boolean; step?: number }) {
  return <AssumptionRow>
    <label className="toggle-label"><input type="checkbox" checked={enabled} disabled={disabled} onChange={e => onEnabled(e.target.checked)} />{label}</label>
    {!hideRate && <label>{rateLabel}<input type="number" min="0" max="100" step={step} disabled={!enabled || disabled} value={rate} onChange={e => onRate(e.target.valueAsNumber)} /></label>}
  </AssumptionRow>;
}

export function Fees({ value, onChange, children }: { value: FeeAssumptions; onChange: (patch: Partial<FeeAssumptions>) => void; children?: ReactNode }) {
  return <div className="fee-controls">
    <AssumptionRow>
      <label className="toggle-label"><input type="checkbox" checked={value.fees_enabled} onChange={e => onChange({ fees_enabled: e.target.checked })} />{text.feesEnabled}</label>
      <label>{text.ilsFeePercent}<input type="number" min="0" max="10" step="0.01" disabled={!value.fees_enabled} value={value.ils_fee_percent} onChange={e => onChange({ ils_fee_percent: e.target.valueAsNumber })} /></label>
      <label>{text.ilsMinimumFee}<input type="number" min="0" step="0.01" disabled={!value.fees_enabled} value={value.ils_minimum_fee} onChange={e => onChange({ ils_minimum_fee: e.target.valueAsNumber })} /></label>
      <label>{text.usdFlatFee}<input type="number" min="0" step="0.01" disabled={!value.fees_enabled} value={value.usd_flat_fee} onChange={e => onChange({ usd_flat_fee: e.target.valueAsNumber })} /></label>
    </AssumptionRow>
    {children}
    <details><summary>How fees work</summary><p>{text.feeHelp}</p></details>
  </div>;
}
