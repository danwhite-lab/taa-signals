"use client";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import DisplayTable from "../../components/DisplayTable";
import * as fmt from "../../lib/format";
import text from "../../content/research.json";
import { researchRequest, researchDownload } from "../../lib/researchApi";

type Table = {columns: string[]; rows: Record<string, unknown>[]; shown_rows?: number; total_rows?: number};
type Profile = { caption: string; parameters: Table; notes: string };
type Model = { label: string; strategy: string; variant: string | null; implementation: string; gate: string; reason: string | null };
type Options = {models: Model[]; gate: string; reason: string | null; currency: string; profile: Profile | null;
  history: {caption: string} | null; data_validation: Table; warnings: string[]};
type Chart = {kind: string; marks: {x: number; y: number; width: number; height: number; color: string; tooltip: string; q1: number; median: number; q3: number; low: number; high: number; outliers: number[]}[];
  labels: {x: number; text: string; transform: string}[]; legend: {label: string; color: string}[]; zero_y: number; minimum: string; maximum: string; caption: string};
type Report = {gate: string; reason: string | null; initial: number; currency: string; profile: Profile; history: {caption: string};
  cards: {label: string; value: string}[]; grade: string; verdict: string; meaning: string; checks: Table;
  tables: Record<string, Table>; charts: Record<string, Chart | null>; has_bootstrap: boolean; warnings: string[];
  cache: {hit: string | null; key: string}; timing: unknown; calculation_timing: unknown;
  downloads: {kind: string; label: string; filename: string}[]};

function DataTable({value,label}:{value:Table;label?:string}) { return <DisplayTable value={value} label={label}/>; }

function Plot({value, title}: {value: Chart | null; title: string}) {
  if (!value) return null;
  return <section><h3>{title}</h3><svg viewBox="0 0 1000 450" role="img" aria-label={title}>
    <line x1="60" y1={value.zero_y} x2="940" y2={value.zero_y} stroke="#b8c5cc" />
    <text x="0" y="35" fontSize="12">{fmt.axis(value.maximum,title)}</text><text x="0" y="285" fontSize="12">{fmt.axis(value.minimum,title)}</text>
    {value.marks.map((m, i) => value.kind === "box" ? <g key={i}><title>{fmt.text(m.tooltip)}</title>
      <line x1={m.x} x2={m.x} y1={m.high} y2={m.low} stroke="#17645f" />
      <rect x={m.x-m.width/2} y={m.q3} width={m.width} height={m.q1-m.q3} fill="#d4e5e3" stroke="#17645f" />
      <line x1={m.x-m.width/2} x2={m.x+m.width/2} y1={m.median} y2={m.median} stroke="#17645f" />
      {m.outliers.map((y, j) => <circle key={j} cx={m.x} cy={y} r="2" fill="#17645f" />)}</g> :
      <rect key={i} x={m.x} y={m.y} width={m.width} height={m.height} fill={m.color}><title>{fmt.text(m.tooltip)}</title></rect>)}
    {value.labels.map((label, i) => <text key={i} x={label.x} y="305" transform={label.transform} textAnchor="end" fontSize="10">{label.text}</text>)}
  </svg><ul>{value.legend.map(item => <li key={item.label} style={{color:item.color}}>{item.label}</li>)}</ul><p>{value.caption}</p></section>;
}

export default function ResearchPage() {
  const [label, setLabel] = useState("HAA-Simple"), [initial, setInitial] = useState(100000);
  const [options, setOptions] = useState<Options | null>(null), [result, setResult] = useState<Report | null>(null);
  const [error, setError] = useState(""), [loading, setLoading] = useState(true), [running, setRunning] = useState(false);
  const [attempt, setAttempt] = useState(0), [elapsed, setElapsed] = useState(0), [changed, setChanged] = useState(false);
  const inFlight = useRef(false);
  const current = options?.models.find(model => model.label === label);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError(""); setResult(null);
    void researchRequest<Options>(`/api/research/options?label=${encodeURIComponent(label)}`, {signal:controller.signal})
      .then(value => { if (!controller.signal.aborted) setOptions(value); })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [label, attempt]);
  useEffect(() => {
    if (!running) return;
    const began = Date.now(); setElapsed(0);
    const timer = setInterval(() => setElapsed(Math.floor((Date.now()-began)/1000)), 1000);
    return () => clearInterval(timer);
  }, [running]);
  function clear() { if (result) setChanged(true); setResult(null); setError(""); }
  function choose(strategy: string, requestedVariant?: string) {
    const candidates = options?.models.filter(m => m.strategy === strategy) ?? [];
    const preferred = requestedVariant ?? current?.variant;
    const variant = candidates.some(m => m.variant === preferred) ? preferred : candidates[0]?.variant;
    const group = candidates.filter(m => m.variant === variant);
    const selected = group.find(m => m.implementation === current?.implementation) ?? group[0];
    if (selected) { setLabel(selected.label); clear(); }
  }
  async function run() {
    if (inFlight.current || loading || options?.gate !== "available") return;
    if (!Number.isFinite(initial) || initial < 1) { setError(text.invalid); return; }
    inFlight.current = true; setRunning(true); clear(); setChanged(false);
    const controller = new AbortController(); let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; controller.abort(); }, 305000);
    try { setResult(await researchRequest<Report>("/api/research", {method:"POST", body:JSON.stringify({label,initial}), signal:controller.signal})); }
    catch (failure) { setError(timedOut ? text.timeout : (failure as Error).message); }
    finally { clearTimeout(timer); inFlight.current = false; setRunning(false); }
  }
  const gated = !loading && options?.gate !== "available";
  const variants = [...new Set(options?.models.filter(m => m.strategy === current?.strategy).map(m => m.variant) ?? [])];
  function download(kind: string) { const item = result?.downloads.find(d => d.kind === kind); return item && <button className="btn btn-secondary" onClick={() => void researchDownload(result!.cache.key, kind, item.filename).catch(() => setError(text.downloadError))}>{item.label}</button>; }
  return <main className="backtest-page"><h1>{text.title}</h1>
    {options && <fieldset disabled={running} className="signal-selector">
      <label>{text.strategy}<select value={current?.strategy ?? ""} onChange={e => choose(e.target.value)}>{[...new Set(options.models.map(m => m.strategy))].sort().map(s => <option key={s}>{s}</option>)}</select></label>
      <label>{text.variant}<select value={current?.variant ?? ""} disabled={variants.length === 1 && variants[0] === null} onChange={e => choose(current?.strategy ?? "", e.target.value)}>{variants.map(v => <option key={v ?? "none"} value={v ?? ""}>{v ?? text.noVariants}</option>)}</select></label>
      <label>{text.implementation}<select value={label} onChange={e => {setLabel(e.target.value); clear();}}>{options.models.filter(m => m.strategy === current?.strategy && m.variant === current?.variant).map(m => <option key={m.label} value={m.label}>{m.implementation}</option>)}</select></label>
    </fieldset>}
    {loading && <p role="status">{text.loading}</p>}{error && <p role="alert">{error}</p>}
    {!loading && error && <button className="btn btn-secondary" onClick={() => setAttempt(v => v+1)}>{text.retry}</button>}
    {gated ? <p className="signal-info">{options?.reason}</p> : options?.profile && !loading && <>
      <p>{text.caption}</p><details><summary>{text.readTitle}</summary><Markdown>{text.readMarkdown.replace(/^ {4,}/gm, "")}</Markdown></details>
      <p>{options.profile.caption}</p><details><summary>{text.scope}</summary><DataTable value={options.profile.parameters} /><p>{options.profile.notes}</p></details>
      <h2>{text.quick}</h2><p>{result?.history.caption ?? options.history?.caption}</p><p>{text.info}</p>
      <label>{text.initial}<input type="number" min="1" disabled={running} value={initial} onChange={e => {setInitial(e.target.valueAsNumber); clear();}} /></label><p>{text.currency}: {options.currency}</p>
      <button className="btn btn-primary" disabled={running || loading} onClick={() => void run()}>{running ? text.running : text.run}</button>
      {running && <p role="status">{text.longRun} · {text.elapsed}: {elapsed}</p>}
      {!result && !running && <p>{text.before}</p>}{changed && <p>{text.changed}</p>}
      {options.warnings.map((w,i) => <p className="signal-warning" key={i}>{w}</p>)}
      <details><summary>{text.sources}</summary><DataTable value={options.data_validation} /></details>
    </>}
    {result?.gate === "available" && <section aria-label={text.completed}>
      <p>{text.completed}</p><p>{text.initial}: {fmt.number(result.initial,true)} · {text.currency}: {result.currency}</p><p>{result.cache.hit ? text.cached : text.calculated}</p>
      {result.warnings.map((w,i) => <p className="signal-warning" key={i}>{w}</p>)}
      <div className="backtest-grid">{result.cards.map(card => <section key={card.label}><h3>{card.label}</h3><p>{fmt.cell(card.value,card.label)}</p></section>)}</div>
      <h2>{text.checksTitle}</h2><DataTable value={result.checks} /><h2>{text.meansTitle}</h2><p>{result.meaning}</p><p>{text.limits}</p>
      {download("price-warnings")}
      <details><summary>{text.sections[0]}</summary><DataTable value={result.tables.scenarios} /><Plot value={result.charts.scenarios} title={text.scenarioChart} />{download("scenarios")}</details>
      <details><summary>{text.sections[1]}</summary><DataTable value={result.tables.execution} /><p>{text.executionCaption}</p></details>
      <details><summary>{text.sections[2]}</summary><h3>{text.rolling}</h3><DataTable value={result.tables.rolling} /><Plot value={result.charts.rolling} title={text.rollingChart} /><h3>{text.subperiods}</h3><DataTable value={result.tables.subperiods} /></details>
      <details><summary>{text.sections[3]}</summary><h3>{text.proxies}</h3><DataTable value={result.tables.proxies} /><p>{text.proxyCaption}</p><h3>{text.quality}</h3><p>{text.qualityCaption}</p><DataTable value={result.tables.data_quality} />{download("data_quality")}</details>
      <details><summary>{text.sections[4]}</summary><p>{text.bootstrapCaption}</p>{result.has_bootstrap ? <><DataTable value={result.tables.monte_carlo} /><Plot value={result.charts.monte_carlo} title={text.bootstrapChart} />{download("monte_carlo")}</> : <p>{text.noBootstrap}</p>}</details>
      <details><summary>{text.sections[5]}</summary><h3>{text.overall}</h3><p>{result.grade}</p><p>{text.scoreCaption}</p><details><summary>{text.scoreTitle}</summary><Markdown>{text.scoreMarkdown.replace(/^ {4,}/gm, "")}</Markdown></details><DataTable value={result.tables.scorecard} />{download("scorecard")}</details>
      <details><summary>{text.timing}</summary><pre>{fmt.json(result.timing)}</pre><h3>{text.originalTiming}</h3><pre>{fmt.json(result.calculation_timing)}</pre></details>
    </section>}
    {result && result.gate !== "available" && <p className="signal-info">{result.reason}</p>}
  </main>;
}
