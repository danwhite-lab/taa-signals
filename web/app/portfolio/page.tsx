"use client";

import { useEffect, useRef, useState } from "react";
import { api, type SavedPortfolio, type Workspace } from "../../lib/api";
import { supabaseBrowser } from "../../lib/supabaseBrowser";
import { date, percent } from "../../lib/format";
import styles from "./portfolio.module.css";
import words from "../../content/portfolio.json";
import transferWords from "../../content/backtest-multi.json";
import { byLabel, savedOrder } from "../../lib/ui-order";

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

function transferRule(payload: Record<string, unknown> | null): Record<string, unknown> | null {
  if (payload?.transfer_rule === undefined) return { mode: "none" };
  const value = payload.transfer_rule;
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function transferError(payload: Record<string, unknown> | null): string | null {
  const rule = transferRule(payload);
  if (!rule || !['none','annual_target','rvol_cap'].includes(String(rule.mode))) return 'Choose a valid sleeve transfer rule.';
  if (rule.mode !== 'rvol_cap') return null;
  const rows = Array.isArray(payload?.sleeves) ? payload.sleeves : [];
  const cap = numeric(rule.cap_percent), target = numeric(rule.target_percent);
  if (typeof rule.sleeve_model !== 'string' || !rule.sleeve_model.includes('RVol')
    || rows.filter(row => row?.model === rule.sleeve_model).length !== 1)
    return 'Select an existing RVol sleeve to cap. The stored selection is not changed automatically.';
  if (cap === null || target === null || cap < 1 || cap > 99 || target < 1 || target > 98 || target >= cap)
    return 'Enter an RVol cap from 1–99% and a reset target from 1–98%, below the cap.';
  return null;
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

function PortfolioSummary({ name, json, isDefault, defaultOnSave, disabled, models, modelModes, modelsError, reloadModels, changeName, changePayload }:
  { name: string; json: string; isDefault: boolean; defaultOnSave: boolean; disabled: boolean; models: string[] | null; modelModes: Record<string, string | undefined>; modelsError: string;
    reloadModels: () => void; changeName: (name: string) => void; changePayload: (payload: Record<string, unknown>) => void }) {
  const payload = parseDraft(json);
  const [adding, setAdding] = useState("");
  const [ruleExpanded, setRuleExpanded] = useState(false);
  const sleeves = Array.isArray(payload?.sleeves) ? payload.sleeves.map(value => {
    const row = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
    return { name: typeof row.model === "string" && row.model.trim() ? row.model : "Unavailable", weight: numeric(row.weight) };
  }) : null;
  const capital = numeric(payload?.total_ils), fx = numeric(payload?.ils_per_usd);
  const total = totalWeight(payload);
  const weight = (value: number | null) => value !== null && Number.isFinite(value) ? percent(value / 100) : "Unavailable";
  const available = models?.filter(model => !sleeves?.some(row => row.name === model)).sort(byLabel) ?? [];
  const rule = transferRule(payload);
  const ruleMode = typeof rule?.mode === 'string' ? rule.mode : '';
  const ruleError = payload ? transferError(payload) : null;
  const rvolModels = sleeves?.filter(row => row.name.includes('RVol')).map(row => row.name) ?? [];
  const uncertainModels = !payload || !sleeves || models === null || !!modelsError
    || sleeves.some(row => !models.includes(row.name) || !["daily", "internal", "external"].includes(modelModes[row.name] ?? ""));
  const hasDaily = sleeves?.some(row => modelModes[row.name] === "daily");
  const invalidRule = !payload || !!ruleError;
  const panelOpen = ruleExpanded || invalidRule;
  const ruleName = invalidRule ? words.invalidRule : words.ruleNames[ruleMode as keyof typeof words.ruleNames];
  function editRule(patch: Record<string, unknown>) {
    if (payload) changePayload({ ...payload, transfer_rule: { ...(rule ?? {}), ...patch } });
  }
  function editSleeves(next: unknown[]) { if (payload) changePayload({ ...payload, sleeves: next }); }
  return <section className={styles.summary} aria-label="Portfolio summary">
    <h2>{name.trim() || "Name not entered"}</h2>
    {(isDefault || defaultOnSave) && <span className={styles.badge}>{isDefault ? "Default" : "Default on save"}</span>}
    {!payload && <p role="alert">Summary unavailable: enter valid Portfolio JSON below. Your draft has not been changed.</p>}
    <div className={styles.settings} role="group" aria-label={words.settings}>
    <label>Portfolio name<input value={name} maxLength={80} disabled={disabled} onChange={event => changeName(event.target.value)} /></label>
    <div className={styles.modelSetting}>    {modelsError ? <p role="alert">{modelsError} <button className="btn btn-secondary" type="button" disabled={disabled} onClick={reloadModels}>Retry model list</button></p> : models === null && <p role="status">Loading available models…</p>}
    <div className={styles.addSleeve}>
      <label>Model to add<select aria-label="Model to add" disabled={disabled || !payload || !sleeves || !models}
        value={available.includes(adding) ? adding : ""} onChange={event => setAdding(event.target.value)}>
        <option value="">Choose a model</option>{available.map(model => <option key={model} value={model}>{model}</option>)}
      </select></label>
      <button className="btn btn-secondary" type="button" aria-label="Add sleeve" disabled={disabled || !sleeves || !available.includes(adding)} onClick={() => {
        editSleeves([...(payload!.sleeves as unknown[]), { model: adding, weight: 0 }]); setAdding("");
      }}>+</button>
    </div>
    </div>
      <label>Total capital (ILS)<NumberField label="Total capital (ILS)" value={capital} disabled={disabled || !payload}
        onChange={value => payload && changePayload({ ...payload, total_ils: value })} /></label>
      <label className={styles.fxSetting}>ILS per USD rate<NumberField label="ILS per USD rate" value={fx} disabled={disabled || !payload}
        onChange={value => payload && changePayload({ ...payload, ils_per_usd: value })} /></label>
      <button className={`btn btn-secondary ${styles.transferButton}`} type="button" disabled={disabled} aria-expanded={panelOpen}
        aria-controls="portfolio-transfer-panel" onClick={() => { if (!invalidRule) setRuleExpanded(open => !open); }}>
        {words.transferButton}: {ruleName}
      </button>
    </div>
    {panelOpen && <fieldset id="portfolio-transfer-panel" className={styles.transfer} disabled={disabled || !payload}>
      <legend>{transferWords.rule}</legend>
      <label>{transferWords.rule}<select value={ruleMode} onChange={event => {
        if (event.target.value === 'rvol_cap') editRule({ mode:'rvol_cap', sleeve_model: rule?.sleeve_model ?? null,
          cap_percent: rule?.cap_percent ?? 15, target_percent: rule?.target_percent ?? 10 });
        else editRule({ mode:event.target.value });
      }}>
        {!Object.hasOwn(transferWords.rules, ruleMode) && <option value={ruleMode}>Choose a valid rule</option>}
        {Object.entries(transferWords.rules).map(([key,label]) => <option key={key} value={key}>{label}</option>)}
      </select></label>
      {ruleMode === 'rvol_cap' && <>
        <label>{transferWords.capSleeve}<select value={typeof rule?.sleeve_model === 'string' ? rule.sleeve_model : ''}
          onChange={event => editRule({ sleeve_model:event.target.value || null })}>
          <option value="">Choose an RVol sleeve</option>
          {typeof rule?.sleeve_model === 'string' && !rvolModels.includes(rule.sleeve_model) && <option value={rule.sleeve_model}>Stored sleeve unavailable — choose another</option>}
          {[...new Set(rvolModels)].map(model => <option key={model} value={model}>{model}</option>)}
        </select></label>
        <label>{transferWords.cap}<NumberField label={transferWords.cap} value={numeric(rule?.cap_percent)} disabled={disabled || !payload}
          onChange={value => editRule({ cap_percent:value })}/></label>
        <label>{transferWords.target}<NumberField label={transferWords.target} value={numeric(rule?.target_percent)} disabled={disabled || !payload}
          onChange={value => editRule({ target_percent:value })}/></label>
      </>}
      {!uncertainModels && !hasDaily && ["rvol_cap", "annual_target"].includes(ruleMode) && <p>{words.retainedRule}</p>}
      {ruleError && <p role="alert">{ruleError}</p>}
    </fieldset>}
    {sleeves ? <div className={styles.tableScroll}><table className={styles.sleeves} aria-label="Portfolio sleeves">
      <thead><tr><th scope="col">Sleeve name</th><th scope="col">Weight</th><th scope="col">Remove</th></tr></thead>
      <tbody>{sleeves.map((row, index) => <tr key={index}><td>{row.name}</td><td>
        <NumberField label={`Weight for ${row.name} (row ${index + 1})`} value={row.weight} decimals={2} disabled={disabled}
          onChange={value => editSleeves((payload!.sleeves as unknown[]).map((original, i) => i === index ? { ...(original as object), weight: value } : original))} />
      </td><td><button className="btn btn-destructive" type="button" aria-label={`Remove ${row.name} (row ${index + 1})`} disabled={disabled}
        onClick={() => editSleeves((payload!.sleeves as unknown[]).filter((_, i) => i !== index))}>-</button></td></tr>)}</tbody>
      <tfoot><tr><th scope="row">Total</th><td>{weight(total)}</td><td /></tr></tfoot>
    </table></div> : <p>Sleeve summary unavailable: enter a sleeve list in Portfolio JSON.</p>}
    {total !== null && Math.abs(total - 100) > 1e-9 && <p role="alert" className={styles.warning}>Weights total {weight(total)}, not 100%. You may save after confirmation, but signals and backtests require 100%. Weights are not normalized.</p>}

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
  const [modelModes, setModelModes] = useState<Record<string, string | undefined>>({});
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
      const config = await api<{ models: { label: string; signal_mode?: string }[] }>("/api/backtest/config?mode=portfolio");
      setModels([...new Set(config.models.map(model => model.label))]);
      setModelModes(Object.fromEntries(config.models.map(model => [model.label, model.signal_mode])));
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
    if (!Array.isArray(rows) || !rows.length || rows.some(row => numeric(row?.weight) === null || numeric(row.weight)! <= 0)) {
      setError(words.invalidWeights); return;
    }
    if ([payload.total_ils, payload.ils_per_usd].some(value => value != null && (numeric(value) === null || numeric(value)! <= 0))) {
      setError(words.invalidOptionalDefaults); return;
    }
    if (new Set(rows.map(row => row.model)).size !== rows.length) { setError("Each model may appear only once. No save was attempted."); return; }
    const ruleError = transferError(payload);
    if (ruleError) { setError(ruleError + ' No save was attempted.'); return; }
    if (payload.transfer_rule === undefined) payload = { ...payload, transfer_rule: { mode:'none' } };
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
    <div className="actions"><button className="btn btn-secondary" disabled={busy} onClick={() => {
      if ((!dirty && !preferenceDirty) || window.confirm("Discard unsaved edits and reload saved data?")) void act(load);
    }}>Reload saved data</button>
      <button className="btn btn-secondary" disabled={busy} onClick={() => void act(async () => {
        const { error } = await supabaseBrowser().auth.signOut();
        if (error) throw error; window.location.replace("/login/");
      })}>Sign out</button></div>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {uncertain && <p>Saving is paused until you reload, so a stale device or uncertain response cannot overwrite saved data.</p>}
    <section><h2>Your library</h2>
      {busy && <p role="status">Loading saved data…</p>}
      {!busy && !portfolios.length && !error && <p>No saved portfolios loaded.</p>}
      <button className="btn btn-primary" disabled={busy || uncertain} onClick={() => requestChoose(null)}>New portfolio</button>
      <ul className="saved-list" aria-label="Saved portfolios">{savedOrder(portfolios).map(item => <li key={item.id}><button className={`btn list-row${selected?.id === item.id ? " is-selected" : ""}`} aria-label={item.name} disabled={busy || uncertain} aria-pressed={selected?.id === item.id}
        onClick={() => requestChoose(item)}>
        <span className="row-name" title={item.name}>{item.name}</span>{item.is_default && <span className="list-tag">Default</span>}<small className="list-date">Updated {date(item.updated_at)}</small></button></li>)}</ul>
    </section>
    {(selected || json) && <PortfolioSummary key={selected?.id ?? 'new'} name={name} json={json} isDefault={selected?.is_default ?? false}
      defaultOnSave={makeDefault} disabled={busy || uncertain} models={models} modelModes={modelModes} modelsError={modelsError} reloadModels={() => void loadModels()}
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
      <div className="actions"><button className="btn btn-secondary" disabled={busy || uncertain || !workspace} onClick={() => void save()}>Save portfolio</button>
        {selected && <button className="btn btn-destructive" disabled={busy || uncertain} onClick={() => void remove()}>Delete portfolio</button>}</div>
    </section>
    <section><h2>Synced workspace</h2><p>Loaded revision: {workspace?.revision ?? "Not loaded"}. Shared holdings and unmigrated settings stay intact.</p>
      <label>Workspace portfolio name<input value={preferredName} maxLength={80} disabled={busy || uncertain}
        onChange={event => setPreferredName(event.target.value)} /></label>
      <button className="btn btn-secondary" disabled={busy || uncertain || !workspace} onClick={() => void act(async () => {
        if (!workspace) return;
        setWorkspace(await api<Workspace>("/api/workspace", { method: "PUT", body: JSON.stringify({
          revision: workspace.revision, payload: { portfolio_name: preferredName },
        }) })); setMessage("Workspace saved.");
      }, true)}>Save workspace preference</button>
    </section>
  </main>;
}
