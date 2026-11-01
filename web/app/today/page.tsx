"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import Markdown from "react-markdown";
import text from "../../content/today.json";
import { authorizedResponse, ApiError } from "../../lib/api";
import * as fmt from "../../lib/format";
import HistorySources, { type HistorySleeve } from "./history-sources";
import styles from "./today.module.css";

type Allocation = { name: string; security_number: string | null; weight_text: string | null };
type Signal = { label: string | null; weight_text: string | null; holding_display: Allocation[]; regime: string | null; status_code: "ok" | "check_data" | "unavailable"; holding: string | null; status: string | null; error_code: string | null };
type Comparison = { id: string; Fund: string; "Target %": number | null; "Actual %": number | null; "Gap (₪)": number | null; Status: string; price_as_of?: string | null; price_fresh?: boolean };
type Preview = { label: string | null; allocation: string | null; allocation_display?: Allocation[]; kind?: keyof typeof text.previewKinds | null; change: "yes" | "no" | null; price_as_of: string | null; reason: string | null; error_code: string | null };
type Today = { has_default: boolean; has_holdings: boolean; caption: string | null; issues: string[]; signals: Signal[]; comparison: Comparison[] | null; moves: string[] | null; pot_total: number | null;
  monthly_action: "changed" | "unchanged" | "unavailable"; latest_caption: string | null; stale: boolean;
  previews: Preview[]; preview_caption: string | null; warnings: string[];
  public_sleeves: HistorySleeve[]; timing: unknown };

const issue = (key: string | null) => key ? (text.errors as Record<string, string>)[key] ?? text.unavailable : null;
const requestError = (status: number) => (text.requestErrors as Record<string, string>)[String(status)] ?? `${text.httpError} (${status}). ${text.unchanged}`;
const sleeveName = (label: string | null) => label ? (text.shortNames as Record<string, string>)[label] ?? label : text.unavailable;
const names = (parts: Allocation[] | undefined) => parts?.map((part, i) => <div key={i}>{part.name}{part.weight_text && ` ${part.weight_text}`}</div>);
const numbers = (parts: Allocation[] | undefined) => parts?.length ? parts.map((part, i) => <div key={i}>{part.security_number ?? text.noSecurityNumber}</div>) : text.noSecurityNumber;

export default function TodayPage() {
  const [value, setValue] = useState<Today | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  const [previewBusy,setPreviewBusy] = useState(false), [previewLoaded,setPreviewLoaded] = useState(false);
  const generation = useRef(0);
  const live = useRef(false);
  async function preview() {
    if(previewBusy || previewLoaded) return;
    const current=generation.current; setPreviewBusy(true);
    try {
      const response=await authorizedResponse(`/api/today?preview=true${live.current ? "&live=true" : ""}`);
      if(!response.ok) throw new Error(requestError(response.status));
      const next=await response.json() as Today;
      if(current===generation.current){setValue(previous=>previous && {...previous,previews:next.previews,preview_caption:next.preview_caption});setPreviewLoaded(true);}
    } catch {if(current===generation.current)setError(text.requestError);}
    finally {if(current===generation.current)setPreviewBusy(false);}
  }
  async function load(forceLive = false) {
    if (inFlight.current) return;
    live.current = forceLive;
    generation.current++;setPreviewLoaded(false);setPreviewBusy(false);
    inFlight.current = true; setBusy(true); setError(""); setValue(null);
    try {
      const response = await authorizedResponse(`/api/today?preview=false${forceLive ? "&live=true" : ""}`);
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
    <button className="btn btn-primary" disabled={busy} onClick={() => void load(true)}>{text.refresh}</button>
    {busy && <p role="status">{text.loading}</p>}{error && <p role="alert">{error}</p>}
    {value && (!value.has_default ? <div className="signal-info"><Markdown>{text.setup}</Markdown></div> : <>
      {value.caption && <p className="signal-caption">{value.caption}</p>}
      {value.issues.map((key, i) => <p role="alert" key={i}>{issue(key)}</p>)}
      <section><h2>{text.monthlyAction}</h2><p className={`today-action today-action-${value.monthly_action}`}>{text.actions[value.monthly_action]}</p>
        {value.latest_caption && <p>{fmt.text(value.latest_caption)}</p>}{value.stale && <p className="signal-warning">{text.staleWarning}</p>}</section>
      <section><h2>{text.sleeveSignals}</h2><div className="signal-table-scroll today-sleeve-table"><table aria-label={text.sleeveSignals}>
        <thead><tr><th>{text.sleeve}</th><th>{text.weight}</th><th>{text.holding}</th><th>{text.securityNumber}</th><th>{text.status}</th></tr></thead>
        <tbody>{value.signals.map((row, i) => <tr key={i}><td title={row.label ?? undefined}>{sleeveName(row.label)}</td><td>{row.weight_text ?? text.dash}</td>
          <td>{row.holding_display?.length ? names(row.holding_display) : text.unavailable}</td>
          <td>{numbers(row.holding_display)}</td>
          <td>{row.status_code === "ok" ? null : row.status_code === "check_data" ? text.checkData : <>{text.unavailable}<small className={styles.secondary}>{issue(row.error_code) ?? row.status}</small></>}{row.regime && <small className={styles.secondary}>{row.regime}</small>}</td></tr>)}</tbody></table></div></section>
      <section><h2>{text.whatToDo}</h2>{!value.has_holdings ? <p className="signal-warning"><Link href="/rebalance-holdings/">{text.noHoldings}</Link></p> : <>
        {value.moves?.map((move, index) => <p key={index}>{move}</p>)}
        {value.pot_total !== null && <p>{text.potTotal.replace("{amount}", fmt.number(value.pot_total, true))}</p>}
        {value.comparison && <div className="signal-table-scroll today-sleeve-table"><table aria-label={text.whatToDo}><thead><tr><th>{text.fund}</th><th>{text.securityNumber}</th><th>{text.target}</th><th>{text.now}</th><th>{text.gap}</th><th>{text.priceDate}</th></tr></thead><tbody>
          {value.comparison.map(row => <tr key={row.id}><td>{row.Fund}</td><td>{row.id.split(":")[1] ?? text.noSecurityNumber}</td><td>{row["Target %"] === null ? text.dash : fmt.percent(row["Target %"])}</td><td>{row["Actual %"] === null ? text.dash : fmt.percent(row["Actual %"])}</td><td>{row["Gap (₪)"] === null ? text.cannotPrice : fmt.number(row["Gap (₪)"], true)}</td><td>{row.price_as_of && !row.price_fresh ? fmt.date(row.price_as_of) : text.dash}</td></tr>)}
        </tbody></table></div>}</>}</section>
      <details onToggle={event=>{if(event.currentTarget.open)void preview();}}><summary>{text.preview}</summary><div className="signal-warning"><Markdown>{text.previewWarning}</Markdown></div>
        {previewBusy && <p role="status">{text.previewLoading}</p>}
        <div className="signal-table-scroll today-sleeve-table"><table aria-label={text.preview}><thead><tr><th>{text.sleeve}</th><th>{text.projectedAllocation}</th><th>{text.securityNumber}</th><th>{text.change}</th><th>{text.priceThrough}</th></tr></thead>
          <tbody>{value.previews.map((row, i) => <tr key={i}><td title={row.label ?? undefined}>{sleeveName(row.label)}</td><td>{row.allocation_display?.length ? names(row.allocation_display) : issue(row.error_code) ?? (row.kind ? text.previewKinds[row.kind] : row.reason) ?? text.unavailable}</td>
            <td>{numbers(row.allocation_display)}</td>
            <td>{row.change === null ? text.dash : text[row.change]}</td><td>{row.price_as_of ? fmt.date(row.price_as_of) : text.dash}</td></tr>)}</tbody></table></div>
        {value.preview_caption && <p>{fmt.text(value.preview_caption)}</p>}</details>
      <HistorySources sleeves={value.public_sleeves} />
      {value.warnings.map((warning, i) => <p key={i} className="signal-source-note">{warning}</p>)}
      <footer>{text.footer}</footer>
    </>)}
  </main>;
}
