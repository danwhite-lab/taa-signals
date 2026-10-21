"use client";

import { useEffect, useRef, useState } from "react";
import { api, type SavedPortfolio, type Workspace } from "../../lib/api";
import { supabaseBrowser } from "../../lib/supabaseBrowser";
import { date, number, percent } from "../../lib/format";
import styles from "./portfolio.module.css";

function numeric(value: unknown): number | null {
  if (typeof value !== "number" && !(typeof value === "string" && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value.trim()))) return null;
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function PortfolioSummary({ name, json, isDefault, defaultOnSave }: { name: string; json: string; isDefault: boolean; defaultOnSave: boolean }) {
  let payload: Record<string, unknown> | null = null;
  try {
    const parsed: unknown = JSON.parse(json);
    if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) payload = parsed as Record<string, unknown>;
  } catch { /* Invalid drafts stay editable; never display an old saved summary. */ }
  const sleeves = Array.isArray(payload?.sleeves) ? payload.sleeves.map(value => {
    const row = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
    return { name: typeof row.model === "string" && row.model.trim() ? row.model : "Unavailable", weight: numeric(row.weight) };
  }) : null;
  const capital = numeric(payload?.total_ils), fx = numeric(payload?.ils_per_usd);
  const total = sleeves?.every(row => row.weight !== null) ? sleeves.reduce((sum, row) => sum + row.weight!, 0) : null;
  const weight = (value: number | null) => value !== null && Number.isFinite(value) ? percent(value / 100) : "Unavailable";
  return <section className={styles.summary} aria-label="Portfolio summary">
    <h2>{name.trim() || "Name not entered"}</h2>
    {(isDefault || defaultOnSave) && <span className={styles.badge}>{isDefault ? "Default" : "Default on save"}</span>}
    {!payload && <p role="alert">Summary unavailable: enter valid Portfolio JSON below. Your draft has not been changed.</p>}
    <dl className={styles.metadata}>
      <div><dt>Total capital (ILS)</dt><dd>{capital === null ? "Unavailable" : `₪${number(capital, true)}`}</dd></div>
      <div><dt>ILS per USD rate</dt><dd>{fx === null ? "Unavailable" : number(fx)}</dd></div>
    </dl>
    {sleeves ? <div className={styles.tableScroll}><table className={styles.sleeves} aria-label="Portfolio sleeves">
      <thead><tr><th scope="col">Sleeve name</th><th scope="col">Weight</th></tr></thead>
      <tbody>{sleeves.map((row, index) => <tr key={index}><td>{row.name}</td><td>{weight(row.weight)}</td></tr>)}</tbody>
      <tfoot><tr><th scope="row">Total</th><td>{weight(total)}</td></tr></tfoot>
    </table></div> : <p>Sleeve summary unavailable: enter a sleeve list in Portfolio JSON.</p>}
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
    if (!dirty || window.confirm("Discard unsaved portfolio edits?")) choose(item);
  }
  async function save() {
    let payload: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(json);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object" || !name.trim()) throw new Error();
      payload = { ...parsed, name: name.trim() };
    } catch { setError("Enter a name and valid portfolio JSON. No save was attempted."); return; }
    await act(async () => {
      const saved = await api<SavedPortfolio>("/api/portfolios", { method: "POST", body: JSON.stringify({
        payload, id: selected?.id ?? null, expected_updated_at: selected?.updated_at ?? null, is_default: makeDefault,
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
    {selected && <PortfolioSummary name={name} json={json} isDefault={selected.is_default} defaultOnSave={makeDefault}/>}
    <section><h2>{selected ? "Edit saved portfolio" : "Save a portfolio"}</h2>
      {selected && <p role="status">Loaded: {selected.name}</p>}
      <p>Minimal migration form: paste version-1 portfolio JSON exported from the existing app. It retains its exact strategy names, weights, capital and FX. No holdings are created or changed.</p>
      <label>Portfolio name<input value={name} maxLength={80} disabled={busy || uncertain} onChange={event => setName(event.target.value)} /></label>
      <details className={styles.advanced} key={selected?.id ?? "new"}><summary>Advanced: edit JSON</summary>
        <label>Portfolio JSON<textarea rows={12} value={json} disabled={busy || uncertain} onChange={event => setJson(event.target.value)} /></label>
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
