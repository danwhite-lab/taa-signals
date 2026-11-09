"use client";

import { fundName as displayFundName } from "../lib/picker-display";
import { useEffect, useRef, useState } from "react";
import words from "../content/holdings.json";
import text from "../content/rebalance.json";
import * as fmt from "../lib/format";

type Row = Record<string, string | boolean | null>;
type Quote = Record<string, unknown>;
const label = (key: string) => text.columns[key as keyof typeof text.columns] ?? key;

export default function HoldingEditorRow({ row, quote, busy, onEdit, onBlur, targets = [], instruments = {}, portfolioName = "", allocation = "—", role: draftRole }: {
  row: Row; quote?: Quote; busy: boolean;
  role?: string;
  targets?: {id:string;label:string;weight?:string}[];
  instruments?: Record<string, {label:string; identifier:string}>;
  portfolioName?: string;
  allocation?: string;
  onEdit: (key: string, field: string, value: string | boolean) => void; onBlur: () => void;
}) {
  const security = String(row.Security);
  const role = draftRole ?? (row["Outside the rebalance"] ? "outside" : row["Companion of"] ? "companion" : "normal");
  const missing = !quote || quote.price == null || quote.price === "" || Boolean(quote.error);
  const stale = !missing && !quote?.fresh;
  const manual = row["Manual price per unit"] != null && row["Manual price per unit"] !== "";
  const target = targets.find(item => item.id === security);
  const [confirmRemoval, setConfirmRemoval] = useState(false);
  const removeButton = useRef<HTMLElement>(null);
  useEffect(() => setConfirmRemoval(false), [portfolioName, target?.id]);
  function fundName(id: string) {
    const identifier = instruments[id]?.identifier || id.split(":").at(-1) || id;
    const name = displayFundName(id, instruments[id]?.label ?? identifier);
    return name && name !== id && name !== identifier ? (name.includes(identifier) ? name : `${name} ${identifier}`) : identifier;
  }
  const anchor = String(row["Companion of"] || "");
  const planStatus = role === "companion" && anchor ? words.companionStatus.replace("{fund}", fundName(anchor))
    : target ? words.inPlan.replace("{weight}", target.weight || "—") : words.notInPlan;
  const hint = role === "outside" ? words.outsideHint : role === "companion" ? words.companionHint : !target ? words.notInPlanHint : undefined;
  const [menuOpen, setMenuOpen] = useState(false);
  const [holdingOpen, setHoldingOpen] = useState(false);
  const [priceEditorOpen, setPriceEditorOpen] = useState(false);
  function field(key: string, caption: string) {
    return <label className="compact-holding-field"><span>{caption}</span>
      <input id={`holding-${encodeURIComponent(security)}-${encodeURIComponent(key)}`}
        aria-label={`${label(key)} ${security}`} type={key === "Price date" ? "date" : "text"}
        inputMode={key === "Price date" ? undefined : "decimal"} value={String(row[key] ?? "")}
        disabled={busy} onChange={event => onEdit(security, key, event.target.value)} onBlur={onBlur} />
    </label>;
  }
  const currency = row.Currency === "ILS" ? "₪" : "$";
  const price = manual ? row["Manual price per unit"] : quote?.price;
  const priceDate = manual ? row["Price date"] : quote?.as_of;
  const detailsId = `holding-options-${encodeURIComponent(security)}`;
  return <>
    <tr className="compact-holding-row" aria-label={String(row.Fund)}>
      <th scope="row" title={[planStatus, hint].filter(Boolean).join(" · ")}>
        <span className="compact-fund-name">{displayFundName(security, String(row.Fund))}</span>
        <small>{instruments[security]?.identifier ?? security.split(":").at(-1)} · {security.split(":")[0]} · {row.Currency}</small>
      </th>
      <td className="numeric"><div className="compact-value-field"><span aria-hidden="true">{currency}</span>{field("Value (₪ / $)", `${words.value} (${currency})`)}</div></td>
      <td className="numeric">{field("Units", words.units)}</td>
      <td className="numeric" title={planStatus}>{allocation}</td>
      <td><select className="compact-role" aria-label={`${words.role} ${security}`} value={role} disabled={busy}
        onChange={event => { onEdit(security, "Role", event.target.value); if (event.target.value === "companion") setHoldingOpen(true); }}>
        {Object.entries(words.roles).map(([value,caption]) => <option key={value} value={value}
          disabled={value === "companion" && !targets.some(t => t.id !== security) && !anchor}>{caption}</option>)}
      </select></td>
      <td className="compact-row-actions">
        {(missing || stale) && <span className="price-alert" title={String(quote?.status ?? quote?.error ?? text.unavailable)} aria-label={missing ? words.missing : words.stale}>!</span>}
        <button type="button" className="compact-icon-button" disabled={busy} aria-label={words.detailsFund.replace("{fund}", String(row.Fund))}
          aria-expanded={holdingOpen} aria-controls={detailsId} onClick={() => setHoldingOpen(previous => !previous)}><span aria-hidden="true">{holdingOpen ? "⌃" : "⌄"}</span></button>
        <details className="compact-holding-menu" open={menuOpen} onKeyDown={event => { if (event.key === "Escape") { setMenuOpen(false); removeButton.current?.focus(); } }}>
          <summary ref={removeButton} aria-disabled={busy} aria-expanded={menuOpen} onClick={event => {event.preventDefault(); if (!busy) setMenuOpen(previous => !previous);}} aria-label={words.actionsFund.replace("{fund}", String(row.Fund))}>⋯</summary>
          <button type="button" className="compact-delete" hidden={!menuOpen} disabled={busy} aria-label={words.removeFund.replace("{fund}", String(row.Fund))}
            onClick={() => { setMenuOpen(false); if (target) {setConfirmRemoval(true); setHoldingOpen(true);} else onEdit(security, "Remove", true); }}>{words.remove}</button>
        </details>
      </td>
    </tr>
    <tr className="compact-holding-details" id={detailsId} hidden={!holdingOpen}><td colSpan={6}>
      {role === "companion" && <label className="compact-companion">{words.companion}<select aria-label={`${words.companion} ${security}`} disabled={busy}
        value={anchor} onChange={event => onEdit(security, "Companion of", event.target.value)}>
        <option value="">{words.none}</option>
        {anchor && !targets.some(t => t.id === anchor) && <option value={anchor}>{words.unmatchedCompanion.replace("{fund}", fundName(anchor))}</option>}
        {[...targets].filter(t => t.id !== security).sort((a,b) => (a.label || a.id).localeCompare(b.label || b.id, undefined, {sensitivity:"base"})).map(t => <option key={t.id} value={t.id}>{displayFundName(t.id, t.label || t.id)}</option>)}
      </select></label>}
      <div className="compact-price-summary" title={String(quote?.source ?? text.unavailable)}>
        <span>{words.price}: {price == null || price === "" ? text.unavailable : `${currency}${fmt.cell(price, "price")}`} · {manual ? text.manual : text.auto} · {fmt.cell(priceDate, "as_of")}</span>
        <button type="button" className="compact-edit-button" disabled={busy} aria-expanded={priceEditorOpen} aria-controls={`${detailsId}-price`} onClick={() => setPriceEditorOpen(previous => !previous)}>{words.editPrice}</button>
      </div>
      <div className="compact-price-fields" id={`${detailsId}-price`} hidden={!priceEditorOpen}>
        {field("Manual price per unit", words.unitPrice)}
        {field("Price date", words.priceDate)}
        {field("Minimum order (₪)", words.minimumOrder)}
      </div>
      {confirmRemoval && <div className="compact-remove-confirm" role="alert">
        <p>{words.removePlanConfirm.replace("{portfolio}", portfolioName)}</p>
        <button type="button" className="btn btn-destructive" disabled={busy} onClick={() => onEdit(security, "Remove", true)}>{words.removeAnyway}</button>
        <button type="button" className="btn btn-secondary" disabled={busy} onClick={() => {setConfirmRemoval(false); removeButton.current?.focus();}}>{words.cancelRemoval}</button>
      </div>}
    </td></tr>
  </>;
}
