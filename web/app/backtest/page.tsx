"use client";

import { asModel } from "../../components/MyFunds";
import type { ModelOption, RegisteredFund } from "../../lib/picker-display";
import SearchPicker from "../../components/SearchPicker";

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import DisplayTable from "../../components/DisplayTable";
import * as fmt from "../../lib/format";
import usdWords from "../../content/usd-equivalents.json";
import text from "../../content/backtest.json";
import multiText from "../../content/backtest-multi.json";
import MultiForm from "./multi-form";
import {UsdToggle,UsdBanner,fitDates,type UsdInfo} from "../../components/UsdEquivalents";
import Fees, { defaultFees, type FeeAssumptions } from "./fee-assumptions";
import { AmountAndDates, DateField, Toggle, TaxControls } from "../../components/BacktestAssumptions";
import { backtestRequest, backtestDownload } from "../../lib/backtestApi";

type Row = Record<string, unknown>;
type Table = { columns: string[]; rows: Row[]; display_rows?: Row[]; total_rows?: number; shown_rows?: number; truncated?: boolean };
type Model = ModelOption;
type Form = { usd_equivalents: boolean; label: string; start: string; end: string; initial: number; fee_type: "percentage" | "fixed"; fee_value: number;
  tax_enabled: boolean; tax_rate: number; monthly_contribution: number; reference_replay: boolean } & FeeAssumptions;
type Options = { models: Model[]; label: string; currency: string; bounds: { start_min: string; start_max: string; end_min: string; end_max: string };
  defaults: Form; captions: string[]; warnings: string[]; data_validation: Table; reference_replay_available: boolean; dca_caption: string; reference_caption: string };
type Chart = { series: { label: string; svg_points: string }[]; minimum: number; maximum: number; start: string; end: string; caption: string };
type Results = { model_name?: string; usd_equivalents?: UsdInfo; label: string; currency: string; settings: Row; engine_parameters: Row; summary: Table; periods: Table; tax_events: Table;
  fees?: { currency: string; enabled: boolean; pre_tax: number; after_tax: number } | null;
  annual: Table; monthly: Table; value_chart: Chart; drawdown_chart: Chart; calculated_at: string; cache: { key: string; hit: string | null };
  captions: string[]; warnings: string[]; data_origin: string; timing: Row; calculation_timing: Row;
  downloads: { kind: string; label: string; filename: string; bytes?: number }[];
  extra_tables?: { label: string; value: Table }[]; extra_charts?: { label: string; value: Chart }[];
  rolling?: { years: number; label: string; table: Table; chart: Chart }[];
  cards?: { label: string; value: string; delta?: string }[]; value_title?: string; drawdown_title?: string; summary_title?: string; data_validation?: Table };
let modelsCache: Model[] | null = null;
const optionsCache = new Map<string, Options>();

function DataTable({value,label}:{value:Table;label?:string}) { return <DisplayTable value={value} label={label}/>; }

function Lines({ value, title }: { value: Chart; title: string }) {
  const colors = ["#17645f", "#6488a3", "#b58a52"];
  return <section className="backtest-result-chart"><h2>{title}</h2>
    <ul className="backtest-chart-legend" aria-label={text.legend}>{value.series.map((series, index) => <li key={series.label}>
      <span aria-hidden="true" style={{ backgroundColor: colors[index % colors.length] }} />{series.label}
    </li>)}</ul>
    <svg viewBox="0 0 900 290" role="img" aria-label={title}>
    <line x1="55" y1="30" x2="55" y2="250" stroke="#dce2e8" /><line x1="55" y1="250" x2="870" y2="250" stroke="#dce2e8" />
    <text x="0" y="28" fontSize="12">{fmt.axis(value.maximum,title)}</text><text x="0" y="250" fontSize="12">{fmt.axis(value.minimum,title)}</text>
    <text x="55" y="277" fontSize="12">{fmt.date(value.start)}</text><text x="870" y="277" fontSize="12" textAnchor="end">{fmt.date(value.end)}</text>
    {value.series.map((series, index) => <polyline key={series.label} points={series.svg_points} fill="none" stroke={colors[index % colors.length]} strokeWidth="1.7" />)}
    </svg>
    <p>{value.caption}</p></section>;
}

const resultTabs = ["overview", "charts", "statistics", "history"] as const;

function BacktestResults({ result, onDownloadError }: { result: Results; onDownloadError: () => void }) {
  const [tab, setTab] = useState<(typeof resultTabs)[number]>("overview");
  const [rollingYears, setRollingYears] = useState<number>();
  const rollingChart = result.rolling?.find(item => item.years === rollingYears)
    ?? result.rolling?.find(item => item.years === 5)
    ?? result.rolling?.at(-1);

  // These labels are emitted by the current API for history and provenance tables.
  const historyLabels = new Set<string>([multiText.dailySignals, multiText.plainSources]);
  const historyTables = result.extra_tables?.filter(item => historyLabels.has(item.label));
  const statisticsTables = result.extra_tables?.filter(item => !historyLabels.has(item.label));
  const sectionCaptions = new Set<string>([
    ...(historyTables?.some(item => item.label === multiText.dailySignals) ? [multiText.sourceCaption] : []),
    ...(statisticsTables?.some(item => item.label === multiText.selected) ? [multiText.sleeveFeeCaption] : []),
  ]);
  const panel = (id: (typeof resultTabs)[number]) => ({
    role: "tabpanel",
    id: `backtest-result-panel-${id}`,
    "aria-labelledby": `backtest-result-tab-${id}`,
    tabIndex: 0,
    hidden: tab !== id,
  });

  return <section className="backtest-results" aria-label={text.results}>
    <header className="backtest-results-heading">
      <h2>{result.model_name ?? result.label}</h2>
      <p>{text.testedPeriod.replace("{start}", fmt.date(result.value_chart.start)).replace("{end}", fmt.date(result.value_chart.end))}</p>
    </header>
    <UsdBanner value={result.usd_equivalents} />
    {result.warnings.map((value, index) => <p key={index} className="signal-warning">{value}</p>)}

    <div className="backtest-result-tabs" role="tablist" aria-label={text.results}>
      {resultTabs.map((value, index) => <button
        key={value} id={`backtest-result-tab-${value}`} type="button" role="tab"
        aria-controls={`backtest-result-panel-${value}`} aria-selected={tab === value}
        tabIndex={tab === value ? 0 : -1} onClick={() => setTab(value)}
        onKeyDown={event => {
          let next: number;
          if (event.key === "ArrowRight") next = (index + 1) % resultTabs.length;
          else if (event.key === "ArrowLeft") next = (index + resultTabs.length - 1) % resultTabs.length;
          else if (event.key === "Home") next = 0;
          else if (event.key === "End") next = resultTabs.length - 1;
          else return;
          event.preventDefault();
          setTab(resultTabs[next]);
          document.getElementById(`backtest-result-tab-${resultTabs[next]}`)?.focus();
        }}
      >{multiText.resultTabs[value]}</button>)}
    </div>

    <div className="backtest-result-panel" {...panel("overview")}>
      {!!result.cards?.length && <div className="backtest-result-cards">
        {result.cards.map(card => <section key={card.label}>
          <h3>{card.label}</h3>
          <p>{fmt.cell(card.value, card.label)}</p>
          {card.delta && <p>{card.delta}</p>}
        </section>)}
      </div>}
      <section><h2>{result.summary_title ?? text.summary}</h2>
        <DataTable value={result.summary} label={result.summary_title ?? text.summary} />
      </section>
      {result.fees && <section aria-label={text.totalFees}><h3>{text.totalFees} ({result.fees.currency})</h3>
        <p>{text.preTaxFees}: {result.fees.pre_tax.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>
        {!!result.settings.tax_enabled && <p>{text.afterTaxFees}: {result.fees.after_tax.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</p>}
        <p>{text.feeSimulations}</p></section>}
      <details className="backtest-result-detail"><summary>{text.settings}</summary><p>{text.currency}: {result.currency}</p>
        <h3>{text.configuredSettings}</h3><dl>{Object.entries(result.settings).map(([key, value]) => <div key={key}><dt>{(text.settingLabels as Record<string, string>)[key] ?? key}</dt><dd>{fmt.configuration(value,key,result.settings.fee_type==="percentage")}</dd></div>)}</dl>
        <h3>{text.engineSettings}</h3><dl>{Object.entries(result.engine_parameters).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{fmt.cell(value,key)}</dd></div>)}</dl></details>
      <footer>{text.disclaimer}</footer>
    </div>

    <div className="backtest-result-panel" {...panel("charts")}>
      <Lines value={result.value_chart} title={result.value_title ?? text.performance} />
      <Lines value={result.drawdown_chart} title={result.drawdown_title ?? text.drawdown} />
      {result.extra_charts?.map(item => <Lines key={item.label} value={item.value} title={item.label} />)}
      {!!result.rolling?.length && <details className="backtest-result-detail">
        <summary>{multiText.rolling}</summary>
        <p>{multiText.rollingCaption}</p>
        <label>{multiText.rollingPeriod}<select value={rollingChart?.years} onChange={event => setRollingYears(Number(event.target.value))}>
          {result.rolling.map(item => <option key={item.years} value={item.years}>{item.label}</option>)}
        </select></label>
        {rollingChart && <Lines value={rollingChart.chart} title={rollingChart.label} />}
      </details>}
    </div>

    <div className="backtest-result-panel" {...panel("statistics")}>
      <details className="backtest-result-detail" open><summary>{text.periods}</summary>
        <DataTable value={result.periods} label={text.periods} />
      </details>
      <details className="backtest-result-detail"><summary>{text.returns}</summary>
        <h3>{text.annual}</h3><DataTable value={result.annual} label={text.annual} />
        <h3>{text.monthly}</h3><DataTable value={result.monthly} label={text.monthly} />
      </details>
      {statisticsTables?.map(item => <details className="backtest-result-detail" key={item.label}>
        <summary>{item.label}</summary>
        {item.label === multiText.selected && sectionCaptions.has(multiText.sleeveFeeCaption) && <p>{multiText.sleeveFeeCaption}</p>}
        <DataTable value={item.value} label={item.label} />
      </details>)}
      {!!result.rolling?.length && <details className="backtest-result-detail">
        <summary>{multiText.rolling}</summary>
        {result.rolling.map(item => <details className="backtest-result-detail" key={item.years}>
          <summary>{item.label}</summary><DataTable value={item.table} label={item.label} />
        </details>)}
      </details>}
    </div>

    <div className="backtest-result-panel" {...panel("history")}>
      <details className="backtest-result-detail"><summary>{text.howRan}</summary>
        {result.captions.map((value, index) => !sectionCaptions.has(value) && <div key={index}><Markdown>{value}</Markdown></div>)}
      </details>
      <details className="backtest-result-detail"><summary>{text.ledger}</summary>
        <DataTable value={result.tax_events} label={text.ledger} />
      </details>
      {historyTables?.map(item => <details className="backtest-result-detail" key={item.label}>
        <summary>{item.label}</summary>
        {item.label === multiText.dailySignals && sectionCaptions.has(multiText.sourceCaption) && <p>{multiText.sourceCaption}</p>}
        <DataTable value={item.value} label={item.label} />
      </details>)}
      {result.data_validation && <details className="backtest-result-detail"><summary>{text.validation}</summary>
        {!result.warnings.includes(result.data_origin) && !result.captions.includes(result.data_origin) && <p>{result.data_origin}</p>}
        <DataTable value={result.data_validation} label={text.sources} />
      </details>}
      <section><h2>{text.downloads}</h2>
        <p>{text.fullDownloadNote}</p>
        <ul className="backtest-result-downloads">
          {result.downloads.map(item => <li key={item.kind}>
            <div><span>{item.filename}</span>{typeof item.bytes === "number" && Number.isFinite(item.bytes) &&
              <small>{multiText.downloadBytes.replace("{bytes}", item.bytes.toLocaleString())}</small>}</div>
            <button className="btn btn-secondary" type="button"
              onClick={() => void backtestDownload(result.cache.key, item.kind, item.filename).catch(onDownloadError)}>{item.label}</button>
          </li>)}
        </ul>
      </section>
      <p>{result.cache.hit ? text.cached : text.calculatedNow} · {text.calculated}: {result.calculated_at}</p>
      <details className="backtest-result-detail"><summary>{text.timing}</summary>
        <pre>{fmt.json(result.timing)}</pre><h3>{text.originalTiming}</h3><pre>{fmt.json(result.calculation_timing)}</pre>
      </details>
    </div>
  </section>;
}

const initialForm: Form = { ...defaultFees, usd_equivalents:false, label: "", start: "", end: "", initial: 100000, fee_type: "percentage", fee_value: 0,
  tax_enabled: true, tax_rate: 25, monthly_contribution: 1000, reference_replay: false };

export default function BacktestPage() {
  const [mode, setMode] = useState<"single" | "portfolio" | "deep">("portfolio");
  const [form, setForm] = useState<Form>(initialForm);
  const [dca, setDca] = useState(false);
  const [options, setOptions] = useState<Options | null>(null);
  const [models, setModels] = useState<Model[] | null>(modelsCache);
  const [result, setResult] = useState<Results | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [loadingModels, setLoadingModels] = useState(!modelsCache);
  const [running, setRunning] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [changed, setChanged] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const inFlight = useRef(false);
  const optionsLabel = useRef("");
  const current = models?.find(model => model.label === form.label);
  useEffect(() => {
    if (mode !== "single" || modelsCache) return;
    const controller = new AbortController();
    void backtestRequest<{models: Model[]}>("/api/backtest/models", {signal: controller.signal})
      .then(value => { if (!controller.signal.aborted) { modelsCache=value.models.filter(model => !model.label.startsWith("MY-FUND-")); setModels(value.models); } })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoadingModels(false); });
    return () => controller.abort();
  }, [attempt, mode]);
  useEffect(() => {
    if (mode !== "single" || !form.label) { setLoading(false); return; }
    const preserve = optionsLabel.current === form.label;
    const applyOptions = (value: Options) => {setOptions(value); optionsLabel.current=form.label; setForm(previous=>({...previous,...(preserve?fitDates(previous,value.bounds):{start:value.bounds.start_min,end:value.bounds.end_max}),reference_replay:false}));};
    const cached = form.usd_equivalents ? null : optionsCache.get(form.label);
    if (cached) {setLoading(false); setError(""); applyOptions(cached); return;}
    const controller = new AbortController(); setLoading(true); setOptions(null); setError(""); setResult(null);
    void backtestRequest<Options>(`/api/backtest/options?label=${encodeURIComponent(form.label)}${form.usd_equivalents ? "&usd_equivalents=true" : ""}`, { signal: controller.signal })
      .then(value => {
        if (controller.signal.aborted) return;
        if(!form.usd_equivalents)optionsCache.set(form.label,value); applyOptions(value);
      }).catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [form.label, form.usd_equivalents, mode]);
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
  async function run() {
    if (inFlight.current || !options) return;
    const b = options.bounds;
    if (![form.initial, form.fee_value, form.tax_rate, form.monthly_contribution, form.ils_fee_percent, form.ils_minimum_fee, form.usd_flat_fee].every(Number.isFinite)
      || form.ils_fee_percent < 0 || form.ils_fee_percent > 10 || form.ils_minimum_fee < 0 || form.usd_flat_fee < 0
      || form.initial < 1 || form.fee_value < 0 || (form.fee_type === "percentage" && form.fee_value > 10)
      || form.tax_rate < 0 || form.tax_rate > 100 || form.monthly_contribution < 0
      || form.start < b.start_min || form.start > b.start_max || form.end < b.end_min || form.end > b.end_max || form.start > form.end) {
      setError(text.validationError); setResult(null); return;
    }
    await execute({ ...form, monthly_contribution: dca ? form.monthly_contribution : 0 });
  }
  async function execute(body: Record<string, unknown>) {
    if (inFlight.current) return;
    inFlight.current = true; setRunning(true); setError(""); setResult(null); setChanged(false);
    const controller = new AbortController(); let timedOut = false;
    const timeout = setTimeout(() => { timedOut = true; controller.abort(); }, 305000);
    try {
      const value = await backtestRequest<Results>("/api/backtest", { method: "POST", signal: controller.signal,
        body: JSON.stringify(body) });
      setResult(value);
    } catch (failure) { setError(timedOut ? text.timeout : (failure as Error).message); }
    finally { clearTimeout(timeout); inFlight.current = false; setRunning(false); }
  }
  return <main className="backtest-page"><p className="eyebrow">{text.eyebrow}</p><h1>{text.title}</h1>
    {mode === "single" && <UsdToggle checked={form.usd_equivalents} disabled={running} onChange={usd_equivalents=>update({usd_equivalents})}/> }
    {mode !== "single" && <MultiForm key={mode} mode={mode} running={running} onRun={execute} onChange={() => update({})}
      modeControl={<Toggle checked={mode === "deep"} disabled={running} onChange={enabled => {
        setMode(enabled ? "deep" : "portfolio");
        update({});
      }}>{text.extendedHistory}</Toggle>} />}
    {loadingModels && mode === "single" && <p role="status">{text.loading}</p>}
    {error && <section role="alert"><h2>{text.errorHeading}</h2><p>{error}</p>{!models && <button className="btn btn-secondary" onClick={() => setAttempt(value => value + 1)}>{text.retry}</button>}</section>}
    {mode === "single" && models && <SearchPicker onFundChange={fund => setModels(current => [...(current ?? []).filter(model => model.label !== fund.model), asModel(fund)])} models={models} value={form.label} disabled={running}
      onSelect={label => update({ label })} />}
    {mode === "single" && options && current && <>
      <fieldset disabled={running} className="backtest-controls"><legend>{text.single}</legend>
        <p className="assumption-hint">{text.currency}: {options.currency}</p>
        <AmountAndDates initial={<label>{text.initial}{form.usd_equivalents && ` (${usdWords.unit})`}<input type="number" min="1" value={form.initial} onChange={event => update({ initial: event.target.valueAsNumber })} /></label>} start={<DateField label="Start" hint={text.start}><input aria-label={text.start} type="date" min={options.bounds.start_min} max={options.bounds.start_max} value={form.start} onChange={event => update({ start: event.target.value })} /></DateField>} end={<DateField label="End" hint={text.end}><input aria-label={text.end} type="date" min={options.bounds.end_min} max={options.bounds.end_max} value={form.end} onChange={event => update({ end: event.target.value })} /></DateField>}
          dca={<><Toggle checked={dca} onChange={value => { setDca(value); update({}); }}>{text.dcaEnabled}</Toggle>{dca && <label>{text.dcaAmount}{form.usd_equivalents && ` (${usdWords.unit})`}<input type="number" min="0" value={form.monthly_contribution} onChange={event => update({ monthly_contribution: event.target.valueAsNumber })} /></label>}</>} />
        <Fees value={form} onChange={update}>
          <TaxControls enabled={form.tax_enabled} rate={form.tax_rate} step={.1} onEnabled={tax_enabled => update({tax_enabled})} onRate={tax_rate => update({tax_rate})} />
        </Fees>
        {dca && <p>{options.dca_caption}</p>}
        {options.reference_replay_available && <><label>{text.reference}<input type="checkbox" checked={form.reference_replay} onChange={event => update({ reference_replay: event.target.checked })} /></label><p>{options.reference_caption}</p></>}
      </fieldset>
      {options.captions.map((value, index) => <p key={index}>{value}</p>)}
      {options.warnings.map((value, index) => <p key={index} className="signal-warning">{value}</p>)}
      <details><summary>{text.validation}</summary><DataTable value={options.data_validation} label={text.sources} /></details>
      <button className="btn btn-primary" type="button" disabled={running || loading} onClick={() => void run()}>{running ? text.running : text.run}</button>
    </>}
    {running && <div role="status"><p>{text.longRun}</p><p>{text.elapsed}: {elapsed}</p></div>}
    {changed && <p>{text.changed}</p>}
    {result ? <BacktestResults result={result} onDownloadError={() => setError(text.downloadError)} />
      : <footer>{text.disclaimer}</footer>}
  </main>;
}
