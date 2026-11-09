"use client";

import { asModel } from "../../components/MyFunds";
import SearchPicker, { ChoiceLabel } from "../../components/SearchPicker";

import { useEffect, useRef, useState } from "react";
import { registryMessage } from "../../lib/my-funds-errors";
import { api, type SavedPortfolio, type Workspace } from "../../lib/api";
import { supabaseBrowser } from "../../lib/supabaseBrowser";
import { date, percent } from "../../lib/format";
import styles from "./portfolio.module.css";
import words from "../../content/portfolio.json";
import pickerWords from "../../content/pickers.json";
import { isKnownModel, modelChoice, type ModelOption, type RegisteredFund } from "../../lib/picker-display";
import { savedOrder } from "../../lib/ui-order";

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

function PortfolioSummary({ name, json, disabled, models, modelsError, reloadModels, openModels, onFundChange, changePayload }:
  { name: string; json: string; disabled: boolean; models: ModelOption[] | null; onFundChange: (fund: RegisteredFund) => void; modelsError: string;
    reloadModels: () => void; openModels: () => void; changePayload: (payload: Record<string, unknown>) => void }) {
  const payload = parseDraft(json);
  const [editing, setEditing] = useState<number | null>(null);
  const [editModel, setEditModel] = useState("");
  const [editWeight, setEditWeight] = useState<number | null>(null);
  const sleeves = Array.isArray(payload?.sleeves) ? payload.sleeves.map(value => {
    const row = value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : {};
    return { name: typeof row.model === "string" && row.model.trim() ? row.model : "Unavailable", weight: numeric(row.weight) };
  }) : null;
  const total = totalWeight(payload);
  const weight = (value: number | null) => value !== null && Number.isFinite(value) ? percent(value / 100) : "Unavailable";
  const editOptions = editing === null ? [] : (models?.filter(model => model.label === sleeves?.[editing]?.name || !sleeves?.some((row, index) => index !== editing && row.name === model.label)) ?? []);
  function editSleeves(next: unknown[]) { if (payload) changePayload({ ...payload, sleeves: next }); }
  return <div className={styles.summary} role="region" aria-label="Portfolio summary">
    <h2>{name.trim() || "Name not entered"}</h2>
    {!payload && <p role="alert">{words.summaryUnavailable}</p>}
    {sleeves ? <div className={styles.tableScroll}><table role="table" className={styles.sleeves} aria-label="Portfolio sleeves">
      <thead role="rowgroup"><tr role="row"><th role="columnheader" scope="col">Sleeve name</th><th role="columnheader" scope="col">Weight</th><th role="columnheader" scope="col">Actions</th></tr></thead>
      <tbody role="rowgroup">{sleeves.map((row, index) => <><tr role="row" className={styles.sleeveRow} key={index}><td role="cell"><ChoiceLabel choice={(models ? models.some(model => model.label === row.name) : isKnownModel(row.name))
        ? modelChoice(models?.find(model => model.label === row.name) ?? { label: row.name }) : { key: row.name, name: row.name, secondary: pickerWords.unavailable }} /></td><td role="cell" className={styles.weightCell}>
        <NumberField label={`Weight for ${row.name} (row ${index + 1})`} value={row.weight} decimals={2} disabled={disabled}
          onChange={value => editSleeves((payload!.sleeves as unknown[]).map((original, i) => i === index ? { ...(original as object), weight: value } : original))} />
      </td><td role="cell"><div className={styles.rowActions}><button className="btn btn-secondary" type="button" aria-label={`${words.edit} ${row.name} (row ${index + 1})`} disabled={disabled}
        onClick={() => { setEditing(index); setEditModel(row.name); setEditWeight(row.weight); }}>{words.edit}</button><button className="btn btn-destructive" type="button" aria-label={`Remove ${row.name} (row ${index + 1})`} disabled={disabled}
        onClick={() => editSleeves((payload!.sleeves as unknown[]).filter((_, i) => i !== index))}>-</button></div></td></tr>{editing === index && <tr role="row" className={styles.editor}><td role="cell" colSpan={3}><fieldset disabled={disabled}><legend>{words.editSleeve}</legend><SearchPicker value={editModel} models={editOptions} onFundChange={onFundChange} excludeFunds={sleeves.filter((_, i) => i !== index).map(s => s.name)} disabled={disabled}
        onOpen={openModels} loading={models === null} error={modelsError} retry={reloadModels} retryLabel={words.retry} onSelect={setEditModel} /><NumberField label={words.editWeight} value={editWeight} decimals={2} disabled={disabled} onChange={setEditWeight}/><div className={styles.rowActions}><button className="btn btn-primary" type="button" onClick={() => { editSleeves((payload!.sleeves as unknown[]).map((original, i) => i === index ? { ...(original as object), model: editModel, weight: editWeight } : original)); setEditing(null); }}>{words.apply}</button><button className="btn btn-secondary" type="button" onClick={() => setEditing(null)}>{words.cancel}</button></div></fieldset></td></tr>}</>)}</tbody>
      <tfoot role="rowgroup"><tr role="row"><th role="rowheader" scope="row">Total</th><td role="cell">{weight(total)}</td><td role="cell" /></tr></tfoot>
    </table></div> : <p>{words.sleevesUnavailable}</p>}
    {total !== null && Math.abs(total - 100) > 1e-9 && <p role="alert" className={styles.warning}>Weights total {weight(total)}, not 100%. You may save after confirmation, but signals and backtests require 100%. Weights are not normalized.</p>}

  </div>;
}

function AddSleeve({ json, disabled, models, modelsError, reloadModels, openModels, onFundChange, changePayload }:
  { json: string; disabled: boolean; models: ModelOption[] | null; onFundChange: (fund: RegisteredFund) => void; modelsError: string;
    reloadModels: () => void; openModels: () => void; changePayload: (payload: Record<string, unknown>) => void }) {
  const payload = parseDraft(json);
  const [adding, setAdding] = useState("");
  const sleeves = Array.isArray(payload?.sleeves) ? payload.sleeves : null;
  const available = models?.filter(model => !sleeves?.some(row => row?.model === model.label)) ?? [];
  return (
    <div className={styles.modelSetting}>
      <SearchPicker caption={words.addSleeve} disabled={disabled || !payload || !sleeves}
        models={available} onFundChange={onFundChange} excludeFunds={sleeves?.map(row => row.model)} value={available.some(model => model.label === adding && !model.fund?.archived) ? adding : ""} onSelect={setAdding}
        onOpen={openModels} loading={models === null} error={modelsError} retry={reloadModels} retryLabel={words.retry} />
      <button className="btn btn-secondary" type="button" aria-label={words.addSleeveButton} disabled={disabled || !sleeves || !available.some(model => model.label === adding && !model.fund?.archived)} onClick={() => {
        changePayload({ ...payload, sleeves: [...(payload!.sleeves as unknown[]), { model: adding, weight: 0 }] }); setAdding("");
      }}>+</button>
    </div>
  );
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
  const [editingName, setEditingName] = useState(false);
  const [models, setModels] = useState<ModelOption[] | null>(null);
  const [modelsError, setModelsError] = useState("");
  const inFlight = useRef(false);
  const dirty = name !== (selected?.name ?? "") || json !== (selected ? JSON.stringify(selected.payload, null, 2) : "")
    || makeDefault !== (selected?.is_default ?? false);
  async function load() {
    const [saved, , user] = await Promise.all([api<Workspace>("/api/workspace"),
      api<SavedPortfolio[]>("/api/portfolios").then(list => { setPortfolios(list); return list; }), api<{ email: string }>("/api/me")]);
    setWorkspace(saved); setEmail(user.email);
    setSelected(null); setName(""); setJson(""); setMakeDefault(false); setEditingName(false); setUncertain(false);
  }
  useEffect(() => { void act(load); }, []); // Initial read; refresh remains explicit after mount.
  const modelsInFlight = useRef(false);
  async function loadModels() {
    if (modelsInFlight.current) return;
    modelsInFlight.current = true;
    setModelsError("");
    try {
      const config = await api<{ models: { label: string; signal_mode?: string }[] }>("/api/backtest/config?mode=portfolio");
      setModels([...new Map(config.models.map(model => [model.label, model])).values()]);
    } catch { setModelsError(words.modelListError); }
    finally { modelsInFlight.current = false; }
  }
  function updateFund(fund: RegisteredFund) {
    setModels(current => [...(current ?? []).filter(model => model.label !== fund.model), asModel(fund)]);
  }
  async function act(operation: () => Promise<void>, mutation = false) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError(""); setMessage("");
    try { await operation(); }
    catch (failure) {
      const message = registryMessage((failure as Error)?.message);
      setError(message ?? "Operation not confirmed. Reload saved data before continuing; your draft is unchanged.");
      if (mutation && !message) setUncertain(true);
    }
    finally { setBusy(false); inFlight.current = false; }
  }
  function choose(item: SavedPortfolio | null) {
    setSelected(item); setName(item?.name ?? ""); setEditingName(false);
    setJson(item ? JSON.stringify(item.payload, null, 2) : "");
    setMakeDefault(item?.is_default ?? false); setMessage(""); setError("");
  }
  function requestChoose(item: SavedPortfolio | null) {
    if (!dirty || window.confirm("Discard unsaved portfolio edits?")) {
      choose(item);
      if (!item) {
        setJson(JSON.stringify({ version: 1, name: "", sleeves: [] }, null, 2));
        setEditingName(true);
      }
    }
  }
  function changeName(next: string) {
    setName(next);
    const payload = parseDraft(json);
    if (payload) setJson(JSON.stringify({ ...payload, name: next }, null, 2));
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
    <div className="actions"><button className="btn btn-secondary" disabled={busy} onClick={() => {
      if (!dirty || window.confirm("Discard unsaved edits and reload saved data?")) void act(load);
    }}>Reload saved data</button>
      <button className="btn btn-secondary" disabled={busy} onClick={() => void act(async () => {
        const { error } = await supabaseBrowser().auth.signOut();
        if (error) throw error; window.location.replace("/login/");
      })}>Sign out</button></div>
    {error && <p role="alert">{error}</p>}{message && <p role="status">{message}</p>}
    {uncertain && <p>Saving is paused until you reload, so a stale device or uncertain response cannot overwrite saved data.</p>}
    <section aria-label={words.settings}>
      <div className={styles.controls}>
        {busy && <p role="status">Loading saved data…</p>}
        {!busy && !portfolios.length && !error && <p>No saved portfolios loaded.</p>}
        <div className={styles.controlRow}>
          <label className={styles.portfolioPicker}>{words.savedPortfolios}
            <select value={selected?.id ?? ""} disabled={busy || uncertain} onChange={event => {
              const next = portfolios.find(item => item.id === event.target.value);
              if (next && next.id !== selected?.id) requestChoose(next);
            }}>
              <option value="" disabled>{words.choosePortfolio}</option>
              {savedOrder(portfolios).map(item => <option key={item.id} value={item.id}>{item.name}</option>)}
            </select>
          </label>
          <label className={styles.defaultControl}>
            <input type="checkbox" checked={makeDefault} disabled={busy || uncertain}
              onChange={event => setMakeDefault(event.target.checked)} />
            {words.defaultLabel}
          </label>
          {selected && <button className="btn btn-secondary" type="button" disabled={busy || uncertain}
            aria-expanded={editingName} onClick={() => setEditingName(value => !value)}>{words.renamePortfolio}</button>}
        </div>
        {selected && <p className={styles.portfolioMeta} role="status">
          <span className="visually-hidden">{words.loadedPortfolio.replace("{name}", selected.name)}</span>
          {selected.is_default && <span className="list-tag">{words.defaultLabel}</span>}
          {!selected.is_default && makeDefault && <span className="list-tag">{words.defaultOnSave}</span>}
          <small>{words.updatedPortfolio.replace("{date}", date(selected.updated_at))}</small>
        </p>}
        {!selected && makeDefault && <span className="list-tag">{words.defaultOnSave}</span>}
        {editingName && <label>{words.portfolioName}
          <input value={name} maxLength={80} disabled={busy || uncertain} autoFocus
            onChange={event => changeName(event.target.value)} />
        </label>}
        <div className="actions">
          <button className="btn btn-primary" type="button" disabled={busy || uncertain} onClick={() => requestChoose(null)}>{words.newPortfolio}</button>
          <button className="btn btn-secondary" type="button" disabled={busy || uncertain || !workspace} onClick={() => void save()}>
            {selected ? words.saveChanges : words.savePortfolio}
          </button>
          {selected && <button className="btn btn-destructive" type="button" disabled={busy || uncertain} onClick={() => void remove()}>
            {words.deletePortfolio}
          </button>}
          {(selected || json) && <AddSleeve key={selected?.id ?? "new"} json={json} disabled={busy || uncertain}
            models={models} onFundChange={updateFund} modelsError={modelsError} reloadModels={() => void loadModels()}
            openModels={() => { if (models === null && !modelsError) void loadModels(); }}
            changePayload={payload => setJson(JSON.stringify(payload, null, 2))} />}
        </div>
      </div>
      {(selected || json) && <PortfolioSummary key={selected?.id ?? "new"} name={name} json={json}
        disabled={busy || uncertain} models={models} onFundChange={updateFund} modelsError={modelsError} reloadModels={() => void loadModels()}
        openModels={() => { if (models === null && !modelsError) void loadModels(); }}
        changePayload={payload => setJson(JSON.stringify(payload, null, 2))} />}
    </section>
  </main>;
}
