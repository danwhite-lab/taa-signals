"use client";

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import text from "../../content/today.json";
import { authorizedResponse, ApiError } from "../../lib/api";
import * as fmt from "../../lib/format";
import DisplayTable, { DisplayTableValue } from "../../components/DisplayTable";

type Signal = { label: string | null; weight_text: string | null; holding: string | null; status: string | null; error_code: string | null; amounts?: {holding:string;amount:number;currency:string}[] };
type HoldingGroup = { currency: string; rows: { holding: string; weight_text: string; amount_text: string }[] };
type Preview = { label: string | null; allocation: string | null; change: "yes" | "no" | null; price_as_of: string | null; reason: string | null; error_code: string | null };
type Today = { has_default: boolean; caption: string | null; issues: string[]; signals: Signal[]; holdings: HoldingGroup[] | null;
  monthly_action: "changed" | "unchanged" | "unavailable"; latest_caption: string | null; stale: boolean;
  previews: Preview[]; preview_caption: string | null; warnings: string[]; shared_holdings?: {holding:string;amount:number;currency:string}[];
  public_sleeves: {model:string;history_note?:string;provenance?:DisplayTableValue;provenance_csv?:string}[]; timing: unknown };

const issue = (key: string | null) => key ? (text.errors as Record<string, string>)[key] ?? text.unavailable : null;
const requestError = (status: number) => (text.requestErrors as Record<string, string>)[String(status)] ?? `${text.httpError} (${status}). ${text.unchanged}`;

export default function TodayPage() {
  const [value, setValue] = useState<Today | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const [previewBusy,setPreviewBusy] = useState(false), [previewLoaded,setPreviewLoaded] = useState(false);
  const generation = useRef(0);
  async function preview() {
    if(previewBusy || previewLoaded) return;
    const current=generation.current; setPreviewBusy(true);
    try {
      const response=await authorizedResponse("/api/today?preview=true");
      if(!response.ok) throw new Error(requestError(response.status));
      const next=await response.json() as Today;
      if(current===generation.current){setValue(previous=>previous && {...previous,previews:next.previews,preview_caption:next.preview_caption});setPreviewLoaded(true);}
    } catch {if(current===generation.current)setError(text.requestError);}
    finally {if(current===generation.current)setPreviewBusy(false);}
  }
  function historyCsv(csv:string) {
    const url=URL.createObjectURL(new Blob([csv],{type:"text/csv"}));
    const link=document.createElement("a");link.href=url;link.download="plain_holdings_history_sources.csv";link.click();URL.revokeObjectURL(url);
  }
  async function load() {
    if (inFlight.current) return;
    generation.current++;setPreviewLoaded(false);setPreviewBusy(false);
    inFlight.current = true; setBusy(true); setError(""); setValue(null);
    try {
      const response = await authorizedResponse("/api/today?preview=false");
      if (!response.ok) {
        let message = requestError(response.status);
        // Only recognized server reasons are displayed; never echo raw bodies.
        try {
          const body = await response.json();
          if (typeof body.detail === "string" && Object.hasOwn(text.requestDetails, body.detail))
            message = (text.requestDetails as Record<string, string>)[body.detail];
        } catch { /* A platform error can be HTML, not JSON. Keep the HTTP reason. */ }
        setError(message); return;
      }
      try { setValue(await response.json() as Today); }
      catch { throw new ApiError(-1, text.invalidResponse); }
    } catch (failure) {
      setError(failure instanceof ApiError
        ? requestError(failure.status)
        : text.requestError);
    }
    finally { inFlight.current = false; setBusy(false); }
  }
  useEffect(() => { void load(); }, []);
  return <main className="today-page"><h1>{text.title}</h1>
    <button disabled={busy} onClick={() => void load()}>{text.refresh}</button>
    {busy && <p role="status">{text.loading}</p>}{error && <p role="alert">{error}</p>}
    {value && (!value.has_default ? <div className="signal-info"><Markdown>{text.setup}</Markdown></div> : <>
      {value.caption && <p className="signal-caption">{value.caption}</p>}
      {value.issues.map((key, i) => <p role="alert" key={i}>{issue(key)}</p>)}
      <section><h2>{text.monthlyAction}</h2><p className={`today-action today-action-${value.monthly_action}`}>{text.actions[value.monthly_action]}</p>
        {value.latest_caption && <p>{fmt.text(value.latest_caption)}</p>}{value.stale && <p className="signal-warning">{text.staleWarning}</p>}</section>
      <section><h2>{text.sleeveSignals}</h2><div className="signal-table-scroll today-sleeve-table"><table aria-label={text.sleeveSignals}>
        <thead><tr><th>{text.sleeve}</th><th>{text.weight}</th><th>{text.holdNow}</th><th>{text.amount}</th><th>{text.status}</th></tr></thead>
        <tbody>{value.signals.map((row, i) => <tr key={i}><td>{row.label ?? text.unavailable}</td><td>{row.weight_text ?? text.dash}</td>
          <td>{row.holding ? fmt.text(row.holding) : text.unavailable}</td><td>{row.amounts?.map((a,j)=><div key={j}>{a.holding}: {fmt.number(a.amount,true)} {a.currency}</div>) ?? text.dash}</td><td>{issue(row.error_code) ?? row.status ?? text.dash}</td></tr>)}</tbody></table></div></section>
      {!value.holdings && <p className="signal-warning">{text.combinedWarning}</p>}
      {!!value.shared_holdings?.length && <p>{text.shared}: {value.shared_holdings.map(a=>`${a.holding}: ${fmt.number(a.amount,true)} ${a.currency}`).join("; ")}</p>}
      {value.public_sleeves.filter(p=>p.provenance).map((p,i)=><details key={i}><summary>{text.historySources} · {p.model}</summary><p>{p.history_note}</p><DisplayTable value={p.provenance!}/><button onClick={()=>historyCsv(p.provenance_csv!)}>{text.historyCsv}</button></details>)}
      <details onToggle={event=>{if(event.currentTarget.open)void preview();}}><summary>{text.preview}</summary><div className="signal-warning"><Markdown>{text.previewWarning}</Markdown></div>
        {previewBusy && <p role="status">{text.previewLoading}</p>}
        <div className="signal-table-scroll"><table aria-label={text.preview}><thead><tr><th>{text.sleeve}</th><th>{text.projectedAllocation}</th><th>{text.change}</th><th>{text.priceThrough}</th></tr></thead>
          <tbody>{value.previews.map((row, i) => <tr key={i}><td>{row.label ?? text.unavailable}</td><td>{row.allocation ?? issue(row.error_code) ?? row.reason ?? text.unavailable}</td>
            <td>{row.change === null ? text.dash : text[row.change]}</td><td>{row.price_as_of ? fmt.date(row.price_as_of) : text.dash}</td></tr>)}</tbody></table></div>
        {value.preview_caption && <p>{fmt.text(value.preview_caption)}</p>}</details>
      {value.warnings.map((warning, i) => <p key={i} className="signal-source-note">{warning}</p>)}
      <details><summary>{text.timing}</summary><pre>{fmt.json(value.timing)}</pre></details>
      <footer>{text.footer}</footer>
    </>)}
  </main>;
}
