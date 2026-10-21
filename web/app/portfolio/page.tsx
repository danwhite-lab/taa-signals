"use client";

import { useEffect, useRef, useState } from "react";
import { api, type SavedPortfolio, type Workspace } from "../../lib/api";
import { supabaseBrowser } from "../../lib/supabaseBrowser";
import { date, percent } from "../../lib/format";
import styles from "./portfolio.module.css";

function numeric(value: unknown): number | null {
  if (typeof value !== "number" && !(typeof value === "string" && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim()))) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function parseDraft(json: string): Record<string, unknown> | null {
  try {
    const parsed: unknown = JSON.parse(json);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed as Record<string, unknown>;
  } catch { /* Never replace an invalid JSON draft with stale saved numbers. */ }
  return null;
}

function totalWeight(payload: Record<string, unknown> | null): number | null {
  if (!Array.isArray(payload?.sleeves)) return null;
  const weights = payload.sleeves.map(row => numeric(row?.weight));
  return weights.every(value => value !== null) ? weights.reduce((sum, value) => sum + value!, 0) : null;
}

function NumberField({ label, value, disabled, decimals, onChange }: { label: string; value: number | null; disabled: boolean;
  decimals?: number; onChange: (value: number | null) => void }) {
  const format = (number: number | null) => number === null ? "" : decimals === undefined ? String(number) : number.toFixed(decimals);
  const [draft, setDraft] = useState(format(value));
  const [focused, setFocused] = useState(false);
  useEffect(() => { if (!focused) setDraft(format(value)); }, [value, focused, decimals]);
  return <input aria-label={label} type="number" min="0" step={decimals === undefined ? "any" : "0.01"}
    value={draft} disabled={disabled} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
    onChange={event => {
      setDraft(event.target.value);
      const next = event.target.valueAsNumber;
      onChange(Number.isFinite(next) ? decimals === undefined ? next : Number(next.toFixed(decimals)) : null);
    }} />;
}

function PortfolioSummary({ name, json, isDefault, defaultOnSave, disabled, models, modelsError, reloadModels, changeName, changePayload }:
  { name: string; json: string; isDefault: boolean; defaultOnSave: boolean; disabled: boolean; models: string[] | null; modelsError: string;
    reloadModels: () => void; changeName: (name: string) => void; changePayload: (payload: Record<string, unknown>) => void }) {
  const payload = parseDraft(json);
  const [adding, setAdding] = useState("");
  const sleeves = Array.isArray(payload?.sleeves) ? payload.sleeves.map(value => {
    const row = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
    return { name: typeof row.model === "string" && row.model.trim() ? row.model : "Unavailable", weight: numeric(row.weight) };
  }) : null;
  const capital = numeric(payload?.total_ils), fx = numeric(payload?.ils_per_usd);
  const total = totalWeight(payload);
  const weight = (value: number | null) => value !== null && Number.isFinite(value) ? percent(value / 100) : "Unavailable";
  const available = models?.filter(model => !sleeves?.some(row => row.name === model)) ?? [];
  function editSleeves(next: unknown[]) { if (payload) changePayload({ ...payload, sleeves: next }); }
  return <section className={styles.summary} aria-label="Portfolio summary">
    <h2>{name.trim() || "Name not entered"}</h2>
    {(isDefault || defaultOnSave) && <span className={styles.badge}>{isDefault ? "Default" : "Default on save"}</span>}
    {!payload && <p role="alert">Summary unavailable: enter valid Portfolio JSON below. Your draft has not been changed.</p>}
    <label>Portfolio name<input value={name} maxLength={80} disabled={disabled} onChange={event => changeName(event.target.value)} /></label>
    <div className={styles.metadata}>
      <label>Total capital (ILS)<NumberField label="Total capital (ILS)" value={capital} disabled={disabled || !payload}
        onChange={value => payload && changePayload({ ...payload, total_ils: value })} /></label>
      <label>ILS per USD rate<NumberField label="ILS per USD rate" value={fx} disabled={disabled || !payload}
        onChange={value => payload && changePayload({ ...payload, ils_per_usd: value })} /></label>
    </div>
    {sleeves ? <div className={styles.tableScroll}><table className={styles.sleeves} aria-label="Portfolio sleeves">
      <thead><tr><th scope="col">Sleeve name</th><th scope="col">Weight</th><th scope="col">Remove</th></tr></thead>
      <tbody>{sleeves.map((row, index) => <tr key={index}><td>{row.name}</td><td>
        <NumberField label={`Weight for ${row.name} (row ${index + 1})`} value={row.weight} decimals={2} disabled={disabled}
          onChange={value => editSleeves((payload!.sleeves as unknown[]).map((original, i) => i === index ? { ...(original as object), weight: value } : original))} />
      </td><td><button type="button" aria-label={`Remove ${row.name} (row ${index + 1})`} disabled={disabled}
        onClick={() => editSleeves((payload!.sleeves as unknown[]).filter((_, i) => i !== index))}>-</button></td></tr>)}</tbody>
      <tfoot><tr><th scope="row">Total</th><td>{weight(total)}</td><td /></tr></tfoot>
    </table></div> : <p>Sleeve summary unavailable: enter a sleeve list in Portfolio JSON.</p>}
    {total !== null && Math.abs(total - 100) > 1e-9 && <p role="alert" className={styles.warning}>Weights total {weight(total)}, not 100%. You may save after confirmation, but signals and backtests require 100%. Weights are not normalized.</p>}
    {modelsError ? <p role="alert">{modelsError} <button type="button" disabled={disabled} onClick={reloadModels}>Retry model list</button></p> : models === null && <p role="status">Loading available models…</p>}
    <div className={styles.addSleeve}>
      <label>Model to add<select aria-label="Model to add" disabled={disabled || !payload || !sleeves || !models}
        value={available.includes(adding) ? adding : ""} onChange={event => setAdding(event.target.value)}>
        <option value="">Choose a model</option>{available.map(model => <option key={model} value={model}>{model}</option>)}
      </select></label>
      <button type="button" aria-label="Add sleeve" disabled={disabled || !sleeves || !available.includes(adding)} onClick={() => {
        editSleeves([...(payload!.sleeves as unknown[]), { model: adding, weight: 0 }]); setAdding("");
      }}>+</button>
    </div>
    <p>New sleeves start at 0%. Enter a positive weight before saving; other weights are left unchanged.</p>
  </section>;
}

export default function Portfolio() {
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [portfolios, setPortfolios] = useState<SavedPortfolio[]>([]);
  const [selected, setSelected] = useState<SavedPortfolio | null>(null);
  const [name, setName] = useState("");
  const [json, setJson] = useState("");
  const [makeDefault, setMakeDefault] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [uncertain, setUncertain] = useState(false);
  const [email, setEmail] = useState("");
  const [preferredName, setPreferredName] = useState("");
  const [models, setModels] = useState<string[] | null>(null);
  const [modelsError, setModelsError] = useState("");
  const inFlight = useRef(false);
  const dirty = name !== (selected?.name ?? "") || json !== (selected ? JSON.stringify(selected.payload, null, 2) : "")
    || makeDefault !== (selected?.is_default ?? false);
  const preferenceDirty = preferredName !== String(workspace?.payload.portfolio_name ?? "");
  async function load() {
    const [saved, , user] = await Promise.all([api<Workspace>("/api/workspace"),
      api<SavedPortfolio[]>("/api/portfolios").then(list => { setPortfolios(list); return list; }), api<{ email: string }>("/api/me")]);
    setWorkspace(saved); setEmail(user.email);
    setPreferredName(String(saved.payload.portfolio_name ?? ""));
    setSelected(null); setName(""); setJson(""); setMakeDefault(false); setUncertain(false);
  }
  useEffect(() => { void act(load); }, []); // Initial read; refresh remains explicit after mount.
  async function loadModels() {
    setModelsError("");
    try {
      const config = await api<{ models: { label: string }[] }>("/api/backtest/config?mode=portfolio");
      setModels([...new Set(config.models.map(model => model.label))]);
    } catch { setModelsError("Available models could not be loaded. Existing drafts are unchanged."); }
  }
  useEffect(() => { void loadModels(); }, []);
  async function act(operation: () => Promise<void>, mutation = false) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(""); setMessage("");
    try { await operation(); }
    catch { setError("Operation not confirmed. Reload saved data before continuing; your draft is unchanged.");
      if (mutation) setUncertain(true); }
    finally { setBusy(false); inFlight.current = false; }
  }
  function choose(item: SavedPortfolio | null) {
    setSelected(item); setName(item?.name ?? "");
    setJson(item ? JSON.stringify(item.payload, null, 2) : "");
    setMakeDefault(item?.is_default ?? false); setMessage(""); setError("");
  }
  function requestChoose(item: SavedPortfolio | null) {
    if (!dirty || window.confirm("Discard unsaved portfolio edits?")) {
      choose(item);
      if (!item) setJson(JSON.stringify({ version: 1, name: "", total_ils: null, ils_per_usd: null, sleeves: [] }, null, 2));
    }
  }
  function changeName(next: string) {
    setName(next);
    const payload = parseDraft(json);
    if (payload) setJson(JSON.stringify({ ...payload, name: next }, null, 2));
  }
  function editJson(next: string) {
    setJson(next);
    const payload = parseDraft(next);
    if (payload) setName(typeof payload.name === 'string' ? payload.name : '');
  }
  async function save() {
    let payload: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(json);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object" || !name.trim()) throw new Error();
      payload = { ...parsed, name: name.trim() };
    } catch { setError("Enter a name and valid portfolio JSON. No save was attempted."); return; }
    const total = totalWeight(payload);
    const rows = payload.sleeves;
    if (!Array.isArray(rows) || !rows.length || rows.some(row => numeric(row?.weight) === null || numeric(row.weight)! <= 0)
      || numeric(payload.total_ils) === null || numeric(payload.total_ils)! <= 0 || numeric(payload.ils_per_usd) === null || numeric(payload.ils_per_usd)! <= 0) {
      setError("Enter positive sleeve weights, total capital and ILS per USD rate. No save was attempted."); return;
    }
    if (new Set(rows.map(row => row.model)).size !== rows.length) { setError("Each model may appear only once. No save was attempted."); return; }
    const unbalanced = total === null || Math.abs(total - 100) > 1e-9;
    if (unbalanced && !window.confirm("Save weights that do not total 100%? They will be saved unchanged. Signals and backtests require 100%.")) return;
    await act(async () => {
      const saved = await api<SavedPortfolio>("/api/portfolios", { method: "POST", body: JSON.stringify({
        payload, id: selected?.id ?? null, expected_updated_at: selected?.updated_at ?? null, is_default: makeDefault,
        ...(unbalanced ? { allow_non_100_weights: true } : {}),
      }) });
      const list = await api<SavedPortfolio[]>("/api/portfolios");
      setPortfolios(list); choose(saved); setMessage("Portfolio saved.");
    }, true);
  }
  async function remove() {
    if (!selected || !window.confirm("Delete this saved portfolio? This does not delete your shared holdings.")) return;
    await act(async () => {
      await api(`/api/portfolios/${encodeURIComponent(selected.id)}?expected_updated_at=${encodeURIComponent(selected.updated_at)}`, { method: "DELETE" });
      setPortfolios(await api<SavedPortfolio[]>("/api/portfolios")); choose(null); setMessage("Portfolio deleted.");
    }, true);
  }
  return <main className={`portfolio-page ${styles.page}`}>
    <h1>Saved portfolios</h1>
    <p>{email}</p>
    <div className="actions"><button disabled={busy} onClick={() => {
      if ((!dirty && !preferenceDirty) || window.confirm("Discard unsaved edits and reload saved data?")) void act(load);
    }}>Reload saved data</button>
      <button disabled={busy} onClick={() => void act(async () => {
        const { error } = await supabaseBrowser().auth.signOut();
        if (error) throw error; window.location.replace("/login/");
      })}>Sign out</button></div>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {uncertain && <p>Saving is paused until you reload, so a stale device or uncertain response cannot overwrite saved data.</p>}
    <section><h2>Your library</h2>
      {busy && <p role="status">Loading saved data…</p>}
      {!busy && !portfolios.length && !error && <p>No saved portfolios loaded.</p>}
      <ul>{portfolios.map(item => <li key={item.id}><button disabled={busy || uncertain} aria-pressed={selected?.id === item.id}
        style={selected?.id === item.id ? { backgroundColor: "#e5f2ed", color: "#1c5343", outline: "2px solid #326454", fontWeight: 700 } : undefined}
        onClick={() => requestChoose(item)}>
        {item.name}{item.is_default ? " · Default" : ""}</button><small>Updated {date(item.updated_at)}</small></li>)}</ul>
      <button disabled={busy || uncertain} onClick={() => requestChoose(null)}>New portfolio</button>
    </section>
    {(selected || json) && <PortfolioSummary key={selected?.id ?? 'new'} name={name} json={json} isDefault={selected?.is_default ?? false}
      defaultOnSave={makeDefault} disabled={busy || uncertain} models={models} modelsError={modelsError} reloadModels={() => void loadModels()}
      changeName={changeName} changePayload={payload => setJson(JSON.stringify(payload, null, 2))}/>}
    <section><h2>{selected ? "Edit saved portfolio" : "Save a portfolio"}</h2>
      {selected && <p role="status">Loaded: {selected.name}</p>}
      <p>Edit the fields above or use Advanced JSON. Values stay in sync; no holdings are created or changed.</p>
      {!selected && !json && <label>Portfolio name<input value={name} maxLength={80} disabled={busy || uncertain} onChange={event => changeName(event.target.value)} /></label>}
      <details className={styles.advanced} key={selected?.id ?? "new"}><summary>Advanced: edit JSON</summary>
        <label>Portfolio JSON<textarea rows={12} value={json} disabled={busy || uncertain} onChange={event => editJson(event.target.value)} /></label>
      </details>
      <label><input type="checkbox" checked={makeDefault} disabled={busy || uncertain}
        onChange={event => setMakeDefault(event.target.checked)} /> Make this the default when saving</label>
      <p>Leaving this unchecked preserves existing defaults; it does not clear a default portfolio.</p>
      <div className="actions"><button disabled={busy || uncertain || !workspace} onClick={() => void save()}>Save portfolio</button>
        {selected && <button disabled={busy || uncertain} onClick={() => void remove()}>Delete portfolio</button>}</div>
    </section>
    <section><h2>Synced workspace</h2><p>Loaded revision: {workspace?.revision ?? "Not loaded"}. Shared holdings and unmigrated settings stay intact.</p>
      <label>Workspace portfolio name<input value={preferredName} maxLength={80} disabled={busy || uncertain}
        onChange={event => setPreferredName(event.target.value)} /></label>
      <button disabled={busy || uncertain || !workspace} onClick={() => void act(async () => {
        if (!workspace) return;
        setWorkspace(await api<Workspace>("/api/workspace", { method: "PUT", body: JSON.stringify({
          revision: workspace.revision, payload: { portfolio_name: preferredName },
        }) })); setMessage("Workspace saved.");
      }, true)}>Save workspace preference</button>
    </section>
  </main>;
}
