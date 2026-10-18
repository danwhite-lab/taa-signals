"use client";

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import text from "../../content/backtest.json";
import { backtestRequest, backtestDownload } from "../../lib/backtestApi";

type Row = Record<string, unknown>;
type Table = { columns: string[]; rows: Row[]; display_rows?: Row[]; total_rows?: number; shown_rows?: number; truncated?: boolean };
type Model = { label: string; strategy: string; variant: string | null; implementation: string };
type Form = { label: string; start: string; end: string; initial: number; fee_type: "percentage" | "fixed"; fee_value: number;
  tax_enabled: boolean; tax_rate: number; monthly_contribution: number; reference_replay: boolean };
type Options = { models: Model[]; label: string; currency: string; bounds: { start_min: string; start_max: string; end_min: string; end_max: string };
  defaults: Form; captions: string[]; warnings: string[]; data_validation: Table; reference_replay_available: boolean; dca_caption: string; reference_caption: string };
type Chart = { series: { label: string; svg_points: string }[]; minimum: number; maximum: number; start: string; end: string; caption: string };
type Results = { label: string; currency: string; settings: Row; engine_parameters: Row; summary: Table; periods: Table; tax_events: Table;
  annual: Table; monthly: Table; value_chart: Chart; drawdown_chart: Chart; calculated_at: string; cache: { key: string; hit: string | null };
  captions: string[]; warnings: string[]; data_origin: string; timing: Row; calculation_timing: Row;
  downloads: { kind: string; label: string; filename: string; bytes: number }[] };

function show(value: unknown) {
  return value === null || value === undefined ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
}

function DataTable({ value, label }: { value: Table; label: string }) {
  return <div className="signal-table-scroll">
    {value.total_rows !== undefined && <p>{text.tablePreview}: {value.shown_rows} / {value.total_rows}</p>}
    <table aria-label={label}><thead><tr>{value.columns.map(column => <th key={column}>{column}</th>)}</tr></thead>
      <tbody>{(value.display_rows ?? value.rows).map((row, index) => <tr key={index}>
        {value.columns.map(column => <td key={column}>{show(row[column])}</td>)}
      </tr>)}</tbody></table>{!value.rows.length && <p>{text.empty}</p>}
  </div>;
}

function Lines({ value, title }: { value: Chart; title: string }) {
  const colors = ["#17645f", "#6488a3", "#b58a52"];
  return <section><h2>{title}</h2><svg viewBox="0 0 900 290" role="img" aria-label={title}>
    <line x1="55" y1="30" x2="55" y2="250" stroke="#dce2e8" /><line x1="55" y1="250" x2="870" y2="250" stroke="#dce2e8" />
    <text x="0" y="28" fontSize="12">{value.maximum}</text><text x="0" y="250" fontSize="12">{value.minimum}</text>
    <text x="55" y="277" fontSize="12">{value.start}</text><text x="870" y="277" fontSize="12" textAnchor="end">{value.end}</text>
    {value.series.map((series, index) => <polyline key={series.label} points={series.svg_points} fill="none" stroke={colors[index % colors.length]} strokeWidth="1.7" />)}
  </svg><ul aria-label={text.legend}>{value.series.map((series, index) => <li key={series.label} style={{ color: colors[index % colors.length] }}>{series.label}</li>)}</ul>
    <p>{value.caption}</p></section>;
}

const initialForm: Form = { label: "HAA-Simple", start: "", end: "", initial: 100000, fee_type: "percentage", fee_value: 0,
  tax_enabled: true, tax_rate: 25, monthly_contribution: 1000, reference_replay: false };

export default function BacktestPage() {
  const [form, setForm] = useState<Form>(initialForm);
  const [dca, setDca] = useState(false);
  const [options, setOptions] = useState<Options | null>(null);
  const [result, setResult] = useState<Results | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [changed, setChanged] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef(false);
  const current = options?.models.find(model => model.label === form.label);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setOptions(null); setError(""); setResult(null);
    void backtestRequest<Options>(`/api/backtest/options?label=${encodeURIComponent(form.label)}`, { signal: controller.signal })
      .then(value => {
        if (controller.signal.aborted) return;
        setOptions(value); setForm(previous => ({ ...previous, start: value.bounds.start_min, end: value.bounds.end_max, reference_replay: false }));
      }).catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [form.label, attempt]);
  useEffect(() => {
    if (!running) return;
    const started = Date.now(); setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(timer);
  }, [running]);
  function update(patch: Partial<Form>) {
    setForm(previous => ({ ...previous, ...patch }));
    if (result) setChanged(true);
    setResult(null); setError("");
  }
  function choose(strategy: string, requestedVariant?: string) {
    if (!options) return;
    const candidates = options.models.filter(model => model.strategy === strategy);
    const preferred = requestedVariant ?? current?.variant;
    const variant = candidates.some(model => model.variant === preferred) ? preferred : candidates[0].variant;
    const group = candidates.filter(model => model.variant === variant);
    update({ label: (group.find(model => model.implementation === current?.implementation) ?? group[0]).label });
  }
  async function run() {
    if (inFlight.current || !options) return;
    const b = options.bounds;
    if (![form.initial, form.fee_value, form.tax_rate, form.monthly_contribution].every(Number.isFinite)
      || form.initial < 1 || form.fee_value < 0 || (form.fee_type === "percentage" && form.fee_value > 10)
      || form.tax_rate < 0 || form.tax_rate > 100 || form.monthly_contribution < 0
      || form.start < b.start_min || form.start > b.start_max || form.end < b.end_min || form.end > b.end_max || form.start > form.end) {
      setError(text.validationError); setResult(null); return;
    }
    inFlight.current = true; setRunning(true); setError(""); setResult(null); setChanged(false);
    const controller = new AbortController(); let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 305000);
    try {
      const value = await backtestRequest<Results>("/api/backtest", { method: "POST", signal: controller.signal,
        body: JSON.stringify({ ...form, monthly_contribution: dca ? form.monthly_contribution : 0 }) });
      setResult(value);
    } catch (failure) { setError(timedOut ? text.timeout : (failure as Error).message); }
    finally { clearTimeout(timeout); inFlight.current = false; setRunning(false); }
  }
  const strategies = [...new Set(options?.models.map(model => model.strategy) ?? [])].sort();
  const variants = [...new Set(options?.models.filter(model => model.strategy === current?.strategy).map(model => model.variant) ?? [])];
  const implementations = options?.models.filter(model => model.strategy === current?.strategy && model.variant === current?.variant) ?? [];
  return <main className="backtest-page"><p className="eyebrow">{text.eyebrow}</p><h1>{text.title}</h1>
    <label>{text.mode}<select value="single" onChange={() => {}}><option value="single">{text.single}</option><option disabled>{text.portfolio}</option><option disabled>{text.deep}</option></select></label>
    {loading && <p role="status">{text.loading}</p>}
    {error && <section role="alert"><h2>{text.errorHeading}</h2><p>{error}</p>{!options && <button onClick={() => setAttempt(value => value + 1)}>{text.retry}</button>}</section>}
    {options && current && <>
      <fieldset disabled={running} className="backtest-controls"><legend>{text.single}</legend>
        <div className="signal-selector">
          <label>{text.strategy}<select value={current.strategy} onChange={event => choose(event.target.value)}>{strategies.map(value => <option key={value}>{value}</option>)}</select></label>
          <label>{text.variant}<select value={current.variant ?? ""} disabled={variants.length === 1 && variants[0] === null}
            onChange={event => choose(current.strategy, event.target.value)}>{variants.map(value => <option key={value ?? "none"} value={value ?? ""}>{value ?? text.noVariants}</option>)}</select></label>
          <label>{text.implementation}<select value={form.label} onChange={event => update({ label: event.target.value })}>{implementations.map(value => <option key={value.label} value={value.label}>{value.implementation}</option>)}</select></label>
        </div>
        <p>{text.currency}: {options.currency}</p>
        <div className="backtest-grid"><label>{text.initial}<input type="number" min="1" value={form.initial} onChange={event => update({ initial: event.target.valueAsNumber })} /></label>
          <label>{text.feeType}<select value={form.fee_type} onChange={event => update({ fee_type: event.target.value as Form["fee_type"], fee_value: event.target.value === "fixed" ? 5 : 0 })}>
            <option value="percentage">{text.percentage}</option><option value="fixed">{text.fixed}</option></select></label>
          <label>{form.fee_type === "percentage" ? text.feePercent : text.feeFixed}<input type="number" min="0" step="0.01" value={form.fee_value} onChange={event => update({ fee_value: event.target.valueAsNumber })} /></label>
          <label>{text.taxEnabled}<input type="checkbox" checked={form.tax_enabled} onChange={event => update({ tax_enabled: event.target.checked })} /></label>
          <label>{text.taxRate}<input type="number" min="0" max="100" step="0.1" disabled={!form.tax_enabled} value={form.tax_rate} onChange={event => update({ tax_rate: event.target.valueAsNumber })} /></label>
          <label>{text.dcaEnabled}<input type="checkbox" checked={dca} onChange={event => { setDca(event.target.checked); update({}); }} /></label>
          {dca && <label>{text.dcaAmount}<input type="number" min="0" value={form.monthly_contribution} onChange={event => update({ monthly_contribution: event.target.valueAsNumber })} /></label>}
          <label>{text.start}<input type="date" min={options.bounds.start_min} max={options.bounds.start_max} value={form.start} onChange={event => update({ start: event.target.value })} /></label>
          <label>{text.end}<input type="date" min={options.bounds.end_min} max={options.bounds.end_max} value={form.end} onChange={event => update({ end: event.target.value })} /></label>
        </div>
        {dca && <p>{options.dca_caption}</p>}
        {options.reference_replay_available && <><label>{text.reference}<input type="checkbox" checked={form.reference_replay} onChange={event => update({ reference_replay: event.target.checked })} /></label><p>{options.reference_caption}</p></>}
      </fieldset>
      {options.captions.map((value, index) => <p key={index}>{value}</p>)}
      {options.warnings.map((value, index) => <p key={index} className="signal-warning">{value}</p>)}
      <details><summary>{text.validation}</summary><DataTable value={options.data_validation} label={text.sources} /></details>
      <button type="button" disabled={running || loading} onClick={() => void run()}>{running ? text.running : text.run}</button>
    </>}
    {running && <div role="status"><p>{text.longRun}</p><p>{text.elapsed}: {elapsed}</p></div>}
    {changed && <p>{text.changed}</p>}
    {result && <div aria-label={text.results}>
      <h2>{result.label}</h2><p>{result.cache.hit ? text.cached : text.calculatedNow} · {text.calculated}: {result.calculated_at}</p>
      <section><h2>{text.settings}</h2><p>{text.currency}: {result.currency}</p>
        <h3>{text.configuredSettings}</h3><dl>{Object.entries(result.settings).map(([key, value]) => <div key={key}><dt>{(text.settingLabels as Record<string, string>)[key] ?? key}</dt><dd>{show(value)}</dd></div>)}</dl>
        <h3>{text.engineSettings}</h3><dl>{Object.entries(result.engine_parameters).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{show(value)}</dd></div>)}</dl></section>
      <p>{text.legacyCaptions}</p>
      {result.captions.map((value, index) => <div key={index}><Markdown>{value}</Markdown></div>)}
      {result.warnings.map((value, index) => <p key={index} className="signal-warning">{value}</p>)}
      <section><h2>{text.summary}</h2><DataTable value={result.summary} label={text.summary} /></section>
      <Lines value={result.value_chart} title={text.performance} /><Lines value={result.drawdown_chart} title={text.drawdown} />
      <p>{text.fullDownloadNote}</p>
      <details><summary>{text.periods}</summary><DataTable value={result.periods} label={text.periods} /></details>
      <details><summary>{text.ledger}</summary><DataTable value={result.tax_events} label={text.ledger} /></details>
      <details><summary>{text.returns}</summary><DataTable value={result.annual} label={text.annual} /><DataTable value={result.monthly} label={text.monthly} /></details>
      <section><h2>{text.downloads}</h2><div className="actions">{result.downloads.map(item => <button key={item.kind}
        onClick={() => void backtestDownload(result.cache.key, item.kind, item.filename).catch(() => setError(text.downloadError))}>{item.label}</button>)}</div></section>
      <details><summary>{text.timing}</summary><pre>{JSON.stringify(result.timing, null, 2)}</pre><h3>{text.originalTiming}</h3><pre>{JSON.stringify(result.calculation_timing, null, 2)}</pre></details>
    </div>}
    <footer>{text.disclaimer}</footer>
  </main>;
}
