"use client";
import { useState } from "react";
import words from "../content/holdings.json";
import text from "../content/rebalance.json";
import * as fmt from "../lib/format";

type Row = Record<string, string | boolean | null>;
type Quote = Record<string, unknown>;
const label = (key: string) => text.columns[key as keyof typeof text.columns] ?? key;

export default function HoldingEditorRow({ row, quote, busy, onEdit, onBlur, targets = [] }: {
  row: Row; quote?: Quote; busy: boolean;
  targets?: {id:string;label:string}[];
  onEdit: (key: string, field: string, value: string | boolean) => void; onBlur: () => void;
}) {
  const security = String(row.Security);
  const missing = !quote || quote.price == null || quote.price === "" || Boolean(quote.error);
  const stale = !missing && !quote?.fresh;
  const manual = row["Manual price per unit"] != null && row["Manual price per unit"] !== "";
  const [expanded, setExpanded] = useState(missing || stale || manual);
  function field(key: string, caption: string) {
    return <label className="holding-field"><span>{caption}</span>
      <input id={`holding-${encodeURIComponent(security)}-${encodeURIComponent(key)}`}
        aria-label={`${label(key)} ${security}`} type={key === "Price date" ? "date" : "text"}
        inputMode={key === "Price date" ? undefined : "decimal"} value={String(row[key] ?? "")}
        disabled={busy} onChange={event => onEdit(security, key, event.target.value)} onBlur={onBlur} />
    </label>;
  }
  function check(key: string, caption: string) {
    return <label className="holding-check"><input type="checkbox" aria-label={`${label(key)} ${security}`}
      checked={!!row[key]} disabled={busy} onChange={event => onEdit(security, key, event.target.checked)} /><span>{caption}</span></label>;
  }
  return <article className="holding-editor-row" role="listitem" aria-label={String(row.Fund)}>
    <div className="holding-main">
      <div className="holding-fund"><strong>{String(row.Fund).replace(/\s+[—–-]\s+\d+\s*$/, "")}</strong><small>{security.split(":").at(-1)} · {row.Currency}</small></div>
      {field("Value (₪ / $)", words.value)}
      {field("Units", words.units)}
      <div className="holding-price"><span className="holding-mobile-label">{words.price}</span>
        <span>{fmt.cell(quote?.price, "price")}</span><small>{fmt.cell(quote?.as_of, "as_of")}</small>
        {(missing || stale) && <details className="holding-price-status"><summary className="price-alert" title={String(quote?.status ?? quote?.error ?? text.unavailable)}>{missing ? words.missing : words.stale}</summary>
          <span>{String(quote?.status ?? quote?.error ?? text.unavailable)}</span></details>}
      </div>
      <div className="holding-membership">{check("Outside the rebalance", words.outside)}
        <label>{words.companion}<select aria-label={`${words.companion} ${security}`} disabled={busy}
          value={String(row["Companion of"] ?? "")} onChange={event=>onEdit(security,"Companion of",event.target.value)}>
          <option value="">{words.none}</option>
          {row["Companion of"] && !targets.some(t=>t.id===row["Companion of"]) && <option value={String(row["Companion of"])}>{words.unmatchedCompanion}</option>}
          {targets.filter(t=>t.id!==security).map(t=><option key={t.id} value={t.id}>{t.label}</option>)}
        </select></label>
      </div>
      <div className="holding-remove">
        <button type="button" className="btn btn-destructive" disabled={busy} aria-label={words.removeFund.replace("{fund}", String(row.Fund))}
          onClick={() => onEdit(security, "Remove", true)}>-</button>
      </div>
    </div>
    <details className="holding-price-editor" open={expanded} onToggle={event => setExpanded(event.currentTarget.open)}>
      <summary>{words.editPrice}</summary>
      <div className="holding-advanced">
        {field("Manual price per unit", label("Manual price per unit"))}
        <div>{field("Price date", label("Price date"))}
          <p className="holding-hint">{text.manualCaption}</p></div>
        {field("Minimum order (₪)", label("Minimum order (₪)"))}
      </div>
      <details className="holding-source"><summary>{words.source}</summary><p>{String(quote?.source ?? text.unavailable)}</p></details>
    </details>
  </article>;
}
