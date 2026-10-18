"use client";

import { useEffect, useRef, useState } from "react";
import { api, type SavedPortfolio, type Workspace } from "../../lib/api";
import { supabaseBrowser } from "../../lib/supabaseBrowser";

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
  async function load() {
    const [saved, list, user] = await Promise.all([api<Workspace>("/api/workspace"),
      api<SavedPortfolio[]>("/api/portfolios"), api<{ email: string }>("/api/me")]);
    setWorkspace(saved); setPortfolios(list); setEmail(user.email);
    setPreferredName(String(saved.payload.portfolio_name ?? ""));
    setSelected(null); setName(""); setJson(""); setMakeDefault(false); setUncertain(false);
  }
  useEffect(() => { void act(load); }, []); // Explicit load only; no overwriting unsaved drafts.
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
  return <main className="portfolio-page">
    <h1>Saved portfolios</h1>
    <p>{email}</p>
    <div className="actions"><button disabled={busy} onClick={() => void act(load)}>Reload saved data</button>
      <button disabled={busy} onClick={() => void act(async () => {
        const { error } = await supabaseBrowser().auth.signOut();
        if (error) throw error; window.location.replace("/login/");
      })}>Sign out</button></div>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {uncertain && <p>Saving is paused until you reload, so a stale device or uncertain response cannot overwrite saved data.</p>}
    <section><h2>Your library</h2>
      {!portfolios.length && <p>No saved portfolios loaded.</p>}
      <ul>{portfolios.map(item => <li key={item.id}><button disabled={busy || uncertain} onClick={() => choose(item)}>
        {item.name}{item.is_default ? " · Default" : ""}</button><small>Updated {item.updated_at}</small></li>)}</ul>
      <button disabled={busy || uncertain} onClick={() => choose(null)}>New portfolio</button>
    </section>
    <section><h2>{selected ? "Edit saved portfolio" : "Save a portfolio"}</h2>
      <p>Minimal migration form: paste version-1 portfolio JSON exported from the existing app. It retains its exact strategy names, weights, capital and FX. No holdings are created or changed.</p>
      <label>Portfolio name<input value={name} maxLength={80} disabled={busy || uncertain} onChange={event => setName(event.target.value)} /></label>
      <label>Portfolio JSON<textarea rows={12} value={json} disabled={busy || uncertain} onChange={event => setJson(event.target.value)} /></label>
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
