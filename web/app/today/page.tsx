"use client";

import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import text from "../../content/today.json";
import { authorizedResponse, ApiError } from "../../lib/api";

type Signal = { label: string | null; weight_text: string | null; holding: string | null; status: string | null; error_code: string | null };
type HoldingGroup = { currency: string; rows: { holding: string; weight_text: string; amount_text: string }[] };
type Preview = { label: string | null; allocation: string | null; change: "yes" | "no" | null; price_as_of: string | null; reason: string | null; error_code: string | null };
type Today = { has_default: boolean; caption: string | null; issues: string[]; signals: Signal[]; holdings: HoldingGroup[] | null;
  monthly_action: "changed" | "unchanged" | "unavailable"; latest_caption: string | null; stale: boolean;
  previews: Preview[]; preview_caption: string | null; warnings: string[]; public_sleeves: unknown[]; timing: unknown };

const issue = (key: string | null) => key ? (text.errors as Record<string, string>)[key] ?? text.unavailable : null;
const requestError = (status: number) => (text.requestErrors as Record<string, string>)[String(status)] ?? `${text.httpError} (${status}). ${text.unchanged}`;

export default function TodayPage() {
  const [value, setValue] = useState<Today | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inFlight = useRef(false);
  async function load() {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(""); setValue(null);
    try {
      const response = await authorizedResponse("/api/today");
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
      <section><h2>{text.sleeveSignals}</h2><div className="signal-table-scroll"><table aria-label={text.sleeveSignals}>
        <thead><tr><th>{text.sleeve}</th><th>{text.weight}</th><th>{text.currentHolding}</th><th>{text.status}</th></tr></thead>
        <tbody>{value.signals.map((row, i) => <tr key={i}><td>{row.label ?? text.unavailable}</td><td>{row.weight_text ?? text.dash}</td>
          <td>{row.holding ?? text.unavailable}</td><td>{issue(row.error_code) ?? row.status ?? text.dash}</td></tr>)}</tbody></table></div></section>
      {value.holdings ? <section><h2>{text.holdNow}</h2>{value.holdings.map(group => <div className="signal-table-scroll" key={group.currency}>
        <table aria-label={`${text.holdNow} ${group.currency}`}><thead><tr><th>{text.holding}</th><th>{text.portfolioWeight}</th><th>{text.allocation} ({group.currency})</th></tr></thead>
          <tbody>{group.rows.map((row, i) => <tr key={i}><td>{row.holding}</td><td>{row.weight_text}</td><td>{row.amount_text}</td></tr>)}</tbody></table></div>)}</section> : <p className="signal-warning">{text.combinedWarning}</p>}
      <section><h2>{text.monthlyAction}</h2><p className={`today-action today-action-${value.monthly_action}`}>{text.actions[value.monthly_action]}</p>
        {value.latest_caption && <p>{value.latest_caption}</p>}{value.stale && <p className="signal-warning">{text.staleWarning}</p>}</section>
      <details><summary>{text.preview}</summary><div className="signal-warning"><Markdown>{text.previewWarning}</Markdown></div>
        <div className="signal-table-scroll"><table aria-label={text.preview}><thead><tr><th>{text.sleeve}</th><th>{text.projectedAllocation}</th><th>{text.change}</th><th>{text.priceThrough}</th></tr></thead>
          <tbody>{value.previews.map((row, i) => <tr key={i}><td>{row.label ?? text.unavailable}</td><td>{row.allocation ?? issue(row.error_code) ?? row.reason ?? text.unavailable}</td>
            <td>{row.change === null ? text.dash : text[row.change]}</td><td>{row.price_as_of ?? text.dash}</td></tr>)}</tbody></table></div>
        {value.preview_caption && <p>{value.preview_caption}</p>}</details>
      {value.warnings.map((warning, i) => <p key={i} className="signal-source-note">{warning}</p>)}
      <footer>{text.footer}</footer>
    </>)}
  </main>;
}
