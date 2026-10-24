"use client";
import type { ReactNode } from "react";
import text from "../content/backtest.json";

export type FeeAssumptions = { fees_enabled: boolean; ils_fee_percent: number; ils_minimum_fee: number; usd_flat_fee: number };
export const defaultFees: FeeAssumptions = { fees_enabled: true, ils_fee_percent: .05, ils_minimum_fee: 2, usd_flat_fee: 5 };

export function AssumptionRow({ children }: { children: ReactNode }) {
  return <div className="assumption-row">{children}</div>;
}

export function Toggle({ checked, onChange, disabled, children }: { checked: boolean; onChange: (value: boolean) => void; disabled?: boolean; children: ReactNode }) {
  return <label className="toggle-label"><input className="toggle-switch" type="checkbox" role="switch" checked={checked} disabled={disabled} onChange={e => onChange(e.target.checked)} />{children}</label>;
}

export function AmountAndDates({ initial, start, end, dca, contribution }: {
  initial: ReactNode; start: ReactNode; end: ReactNode; dca?: ReactNode; contribution?: ReactNode;
}) {
  return <section className="amount-dates"><h3>Amount and dates</h3>
    <div className="amount-date-grid">{initial}{contribution}{start}{end}</div>
    {dca && <div className="dca-row">{dca}</div>}
  </section>;
}

export function DateField({ label, hint, children }: { label: string; hint: string; children: ReactNode }) {
  return <div className="date-field"><label>{label}{children}</label><small className="assumption-hint">{hint}</small></div>;
}

export function CostsAndTax({ children }: { children: ReactNode }) {
  return <section className="costs-tax"><h3>Costs and tax</h3><div className="costs-panel">{children}</div></section>;
}

export function TaxControls({ enabled, rate, onEnabled, onRate, label = text.taxEnabled, rateLabel = text.taxRate, disabled = false, hideRate = false, step, leading }:
  { enabled: boolean; rate: number; onEnabled: (value: boolean) => void; onRate: (value: number) => void;
    label?: string; rateLabel?: string; disabled?: boolean; hideRate?: boolean; step?: number; leading?: ReactNode }) {
  return <AssumptionRow>
    {leading}
    <Toggle checked={enabled} disabled={disabled} onChange={onEnabled}>{label}</Toggle>
    {!hideRate && <label>{rateLabel}<input type="number" min="0" max="100" step={step} disabled={!enabled || disabled} value={rate} onChange={e => onRate(e.target.valueAsNumber)} /></label>}
  </AssumptionRow>;
}

export function Fees({ value, onChange, children }: { value: FeeAssumptions; onChange: (patch: Partial<FeeAssumptions>) => void; children?: ReactNode }) {
  return <CostsAndTax><div className="fee-controls">
    <AssumptionRow>
      <Toggle checked={value.fees_enabled} onChange={fees_enabled => onChange({ fees_enabled })}>Trading fees</Toggle>
      <label>TASE fee %<input aria-label={text.ilsFeePercent} type="number" min="0" max="10" step="0.01" disabled={!value.fees_enabled} value={value.ils_fee_percent} onChange={e => onChange({ ils_fee_percent: e.target.valueAsNumber })} /></label>
      <label>TASE minimum fee<input aria-label={text.ilsMinimumFee} type="number" min="0" step="0.01" disabled={!value.fees_enabled} value={value.ils_minimum_fee} onChange={e => onChange({ ils_minimum_fee: e.target.valueAsNumber })} /></label>
      <label>USD flat fee<input aria-label={text.usdFlatFee} type="number" min="0" step="0.01" disabled={!value.fees_enabled} value={value.usd_flat_fee} onChange={e => onChange({ usd_flat_fee: e.target.valueAsNumber })} /></label>
    </AssumptionRow>
    {children}
    <details><summary>How fees work</summary><p>{text.feeHelp}</p></details>
  </div></CostsAndTax>;
}
