"use client";

import { useEffect, useState } from "react";
import Markdown from "react-markdown";
import { api } from "../../lib/api";

type Row = Record<string, unknown>;
export type SignalTable = { columns: string[]; rows: Row[]; display_rows?: Row[] };
type Model = { label: string; strategy: string; variant: string | null; implementation: string };
export type SignalsPayload = {
  mode: "daily" | "monthly" | "buy_and_hold"; heading: string; captions: string[]; warnings: string[];
  current: { available: boolean; reason: string | null; signal_date?: string; regime?: string;
    allocation?: string; instruction?: string; effective_start?: string; effective_text?: string;
    table?: SignalTable; information?: string };
  preview: null | { heading: string; decision: Row | null; reason: string | null; unavailable_text: string;
    price_as_of: string; allocation?: string; regime?: string; changed?: boolean; warning?: string; caption?: string };
  rationale: null | { heading: string; paragraphs: string[]; tables: SignalTable[]; captions: string[] };
  history: null | { table: SignalTable; csv: string; filename: string; download_label: string; count: number };
  data: null | { sources: SignalTable; ranges: SignalTable; provenance?: SignalTable;
    completed_through: string; captions: string[]; warnings: string[] };
  cache?: { hit: string | null; warnings: string[] }; fallback_warnings?: string[];
  data_origin?: string; timing?: Row; disclaimer: string;
};

function cell(value: unknown) {
  return value === null || value === undefined ? "—" : typeof value === "object" ? JSON.stringify(value) : String(value);
}

export function SignalTableView({ value, label }: { value: SignalTable; label: string }) {
  return <div className="signal-table-scroll"><table aria-label={label}><thead><tr>
    {value.columns.map(column => <th key={column} scope="col">{column}</th>)}
  </tr></thead><tbody>{(value.display_rows ?? value.rows).map((row, index) => <tr key={index}>
    {value.columns.map(column => <td key={column}>{cell(row[column])}</td>)}
  </tr>)}</tbody></table>{!value.rows.length && <p>No rows available.</p>}</div>;
}

export function downloadHistory(csv: string, filename: string) {
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a"); link.href = url; link.download = filename;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

export function SignalsView({ value }: { value: SignalsPayload }) {
  const tabs = value.mode === "monthly" && value.current.available ? ["Overview", "Rationale", "History", "Data"] : ["History", "Data"];
  const [active, setActive] = useState(tabs[0]);
  const selected = tabs.includes(active) ? active : tabs[0];
  const current = value.current;
  return <>
    <h1>{value.heading}</h1>
    {value.captions.map((caption, index) => <p key={index} className="signal-caption">{caption}</p>)}
    {value.warnings.filter(Boolean).map((warning, index) => <div key={index} role="note" className="signal-warning"><Markdown>{warning}</Markdown></div>)}
    {(value.fallback_warnings ?? []).map((warning, index) => <p key={index} className="signal-source-note">{warning}</p>)}
    {(value.cache?.warnings ?? []).map((warning, index) => <p key={index} className="signal-source-note">{warning}</p>)}
    {!current.available && <p role="alert">{current.reason}</p>}
    {value.data?.warnings.map((warning, index) => <div key={index} role="note" className="signal-warning">{warning}</div>)}
    {current.table && <section><SignalTableView value={current.table} label="Current signal" /></section>}
    {current.information && <p className="signal-info">{current.information}</p>}
    {value.mode === "monthly" && current.available && <section className="current-allocation" aria-label="Current allocation">
      <p className="eyebrow">CURRENT ALLOCATION</p><h2>{current.allocation}</h2>
      <dl><div><dt>Signal date</dt><dd>{current.signal_date}</dd></div><div><dt>Regime</dt><dd>{current.regime}</dd></div></dl>
      <p>{current.instruction}</p>
    </section>}
    <div className="signal-tabs" role="tablist" aria-label="Signal detail views">
      {tabs.map(tab => <button key={tab} role="tab" aria-selected={tab === selected} id={`signal-tab-${tab}`}
        aria-controls={`signal-panel-${tab}`} onClick={() => setActive(tab)}>{tab}</button>)}
    </div>
    <section role="tabpanel" id={`signal-panel-${selected}`} aria-labelledby={`signal-tab-${selected}`}>
      {selected === "Overview" && <>
        <details><summary>Signal summary</summary><dl>
          <dt>signal date</dt><dd>{current.signal_date}</dd><dt>regime</dt><dd>{current.regime}</dd>
          <dt>instruction</dt><dd>{current.instruction}</dd><dt>target allocation</dt><dd>{current.allocation}</dd>
        </dl></details>
        {current.effective_text && <div className={current.effective_start ? "signal-info" : "signal-warning"}><Markdown>{current.effective_text}</Markdown></div>}
        {value.preview && <details><summary>{value.preview.heading}</summary>
          {value.preview.decision ? <>
            <div className="signal-warning"><Markdown>{value.preview.warning}</Markdown></div>
            <dl><dt>price data through</dt><dd>{value.preview.price_as_of}</dd><dt>projected regime</dt><dd>{value.preview.regime}</dd>
              <dt>projected allocation</dt><dd>{value.preview.allocation}</dd><dt>change vs current signal</dt><dd>{value.preview.changed ? "Yes" : "No"}</dd></dl>
            <p className="signal-caption">{value.preview.caption}</p>
          </> : <p>{value.preview.unavailable_text}</p>}
        </details>}
      </>}
      {selected === "Rationale" && value.rationale && <>
        <h2>{value.rationale.heading}</h2>
        {value.rationale.paragraphs.map((text, index) => <p key={index}>{text}</p>)}
        {value.rationale.tables.map((value, index) => <SignalTableView key={index} value={value} label={`Rationale inputs ${index + 1}`} />)}
        {value.rationale.captions.map((text, index) => <p key={index} className="signal-caption">{text}</p>)}
      </>}
      {selected === "History" && value.history && <>
        <p>{value.history.count} decisions · newest first</p>
        <button onClick={() => downloadHistory(value.history!.csv, value.history!.filename)}>{value.history.download_label}</button>
        <SignalTableView value={value.history.table} label="Signal history" />
      </>}
      {selected === "Data" && value.data && <>
        {value.data.captions.map((text, index) => <p key={index} className="signal-caption">{text}</p>)}
        <SignalTableView value={value.data.sources} label="Data sources" />
        {value.mode !== "daily" && <SignalTableView value={value.data.ranges} label="Available date ranges" />}
        {value.data.provenance && <SignalTableView value={value.data.provenance} label="Plain buy-and-hold history sources" />}
        <p>{value.data_origin}</p><p>Results cache: {value.cache?.hit ?? "Calculated this request"}</p>
        {value.timing && <pre>{JSON.stringify(value.timing, null, 2)}</pre>}
      </>}
    </section>
    <footer>{value.disclaimer}</footer>
  </>;
}

export default function SignalsPage() {
  const [models, setModels] = useState<Model[]>([]);
  const [label, setLabel] = useState("HAA-Simple");
  const [payload, setPayload] = useState<SignalsPayload | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    void api<Model[]>("/api/strategies").then(rows => { if (live) setModels(rows); })
      .catch((problem: Error) => { if (live) setError(problem.message); });
    return () => { live = false; };
  }, [attempt]);
  useEffect(() => {
    if (!models.length) return;
    const controller = new AbortController(); setPayload(null); setError("");
    const asOf = new URLSearchParams(window.location.search).get("as_of");
    void api<SignalsPayload>(`/api/signals?label=${encodeURIComponent(label)}${asOf ? `&as_of=${encodeURIComponent(asOf)}` : ""}`, { signal: controller.signal })
      .then(data => { if (!controller.signal.aborted) setPayload(data); })
      .catch((problem: Error) => { if (!controller.signal.aborted) setError(problem.message); });
    return () => controller.abort();
  }, [models, label, attempt]);
  const selected = models.find(model => model.label === label);
  const strategies = [...new Set(models.map(model => model.strategy))].sort((a, b) => a.toLowerCase().localeCompare(b.toLowerCase()));
  const variants = [...new Set(models.filter(model => model.strategy === selected?.strategy).map(model => model.variant))];
  const implementations = models.filter(model => model.strategy === selected?.strategy && model.variant === selected?.variant);
  function choose(strategy: string, requestedVariant?: string) {
    const candidates = models.filter(model => model.strategy === strategy);
    const preferred = requestedVariant ?? selected?.variant;
    const variant = candidates.some(model => model.variant === preferred) ? preferred : candidates[0].variant;
    const group = candidates.filter(model => model.variant === variant);
    setLabel((group.find(model => model.implementation === selected?.implementation) ?? group[0]).label);
  }
  return <main className="signals-page">
    <p className="eyebrow">Strategy signals</p>
    {selected && <div className="signal-selector">
      <label>Strategy<select value={selected.strategy} onChange={event => choose(event.target.value)}>
        {strategies.map(strategy => <option key={strategy}>{strategy}</option>)}</select></label>
      <label>Variant<select value={selected.variant ?? ""} disabled={variants.length === 1 && variants[0] === null}
        onChange={event => choose(selected.strategy, event.target.value)}>
        {variants.map(variant => <option key={variant ?? "none"} value={variant ?? ""}>{variant ?? "No variants"}</option>)}</select></label>
      <label>Implementation<select value={label} onChange={event => setLabel(event.target.value)}>
        {implementations.map(model => <option key={model.label} value={model.label}>{model.implementation}</option>)}</select></label>
    </div>}
    {error && <section role="alert"><h1>Signals could not be loaded</h1><p>{error}</p>
      <button onClick={() => setAttempt(value => value + 1)}>Try again</button></section>}
    {!payload && !error && <p role="status">Loading signals from the existing Python engine…</p>}
    {payload && <SignalsView key={label} value={payload} />}
    {!payload && <footer>Rules-based informational signal only; not investment advice. You are responsible for any trading decision and execution.</footer>}
  </main>;
}
