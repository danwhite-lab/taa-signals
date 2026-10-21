"use client";
import { useEffect, useRef, useState } from "react";
import text from "../../content/backtest.json";
import words from "../../content/backtest-multi.json";
import { backtestRequest } from "../../lib/backtestApi";
import Fees, { defaultFees, type FeeAssumptions } from "./fee-assumptions";

type Model = { label: string; strategy: string; variant: string | null; implementation: string };
type Sleeve = { id: number; model: string; weight: number };
type Config = { dca_caption: string; models: Model[]; proxies: { key: string; label: string; caveat: string }[]; single_options: string[]; blend_options: string[];
  benchmarks: { key: string; label: string; caveat: string }[] };
type Form = { initial: number; start: string; end: string; fee_type: "percentage" | "fixed"; fee_value: number; tax_enabled: boolean; tax_rate: number;
  monthly_contribution: number; benchmark: string; sleeve_rebalance_mode: string; rebalance_sleeve: number | null; rebalance_cap: number; rebalance_target: number } & FeeAssumptions;
const defaults: Form = { ...defaultFees, initial: 100000, start: "", end: "", fee_type: "percentage", fee_value: 0, tax_enabled: true, tax_rate: 25,
  monthly_contribution: 1000, benchmark: "sp500", sleeve_rebalance_mode: "none", rebalance_sleeve: null, rebalance_cap: 15, rebalance_target: 10 };

export default function MultiForm({ mode, running, onRun, onChange }: { mode: "portfolio" | "deep"; running: boolean;
  onRun: (body: Record<string, unknown>) => Promise<void>; onChange: () => void }) {
  const [config, setConfig] = useState<Config | null>(null);
  const [form, setForm] = useState(defaults);
  const [sleeves, setSleeves] = useState<Sleeve[]>([{ id: 1, model: mode === "deep" ? "century_momentum" : "HAA-Simple", weight: 100 }]);
  const [dca, setDca] = useState(false);
  const [valid, setValid] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<{ id: string; name: string }[]>([]);
  const [selected, setSelected] = useState("");
  const [warnings, setWarnings] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [loadingSaved, setLoadingSaved] = useState(false);
  const [savedError, setSavedError] = useState("");
  const [loadingPortfolio, setLoadingPortfolio] = useState(false);
  const loadController = useRef<AbortController | null>(null);
  const loadInFlight = useRef(false);
  const nextId = useRef(2);
  const daily = mode === "deep" && sleeves.some(s => s.model === "rvol_daily");
  const body = { ...form, mode, sleeves, start: form.start || null, end: form.end || null, tax_enabled: daily ? false : form.tax_enabled,
    monthly_contribution: dca ? form.monthly_contribution : 0 };
  const serialized = JSON.stringify(body);
  useEffect(() => {
    const controller = new AbortController();
    void backtestRequest<Config>(`/api/backtest/config?mode=${mode}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setConfig(value); })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => { controller.abort(); loadController.current?.abort(); };
  }, [mode]);
  useEffect(() => {
    if (mode !== "portfolio") return;
    const controller = new AbortController();
    void listSaved(controller.signal);
    return () => controller.abort();
  }, [mode]);
  useEffect(() => {
    const controller = new AbortController(); setValid(false); setMessage("");
    void backtestRequest<{ valid: boolean; message: string }>("/api/backtest/validate", { method: "POST", body: serialized, signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) { setValid(value.valid); setMessage(value.message); } })
      .catch((failure: Error) => { if (!controller.signal.aborted) setMessage(failure.message); });
    return () => controller.abort();
  }, [serialized]);
  function change(patch: Partial<Form>) { setValid(false); setForm(previous => ({ ...previous, ...patch })); setError(""); onChange(); }
  function edit(id: number, patch: Partial<Sleeve>) {
    setValid(false); setSleeves(previous => previous.map(s => s.id === id ? { ...s, ...patch } : s)); setWarnings([]); onChange();
  }
  function choose(s: Sleeve, strategy: string, requestedVariant?: string) {
    const current = config?.models.find(m => m.label === s.model);
    const candidates = config?.models.filter(m => m.strategy === strategy) ?? [];
    const preferred = requestedVariant ?? current?.variant;
    const variant = candidates.some(m => m.variant === preferred) ? preferred : candidates[0]?.variant;
    const group = candidates.filter(m => m.variant === variant);
    const model = group.find(m => m.implementation === current?.implementation) ?? group[0];
    if (model) edit(s.id, { model: model.label });
  }
  async function listSaved(signal?: AbortSignal) {
    setLoadingSaved(true); setSavedError("");
    try {
      const rows = mode === "portfolio"
        ? (await backtestRequest<{portfolios: {id: string; name: string}[]}>("/api/compare/options", {signal})).portfolios
        : await backtestRequest<{id: string; name: string}[]>("/api/portfolios", {signal});
      if (signal?.aborted) return;
      setSaved(rows); setSelected(previous => rows.some(row => row.id === previous) ? previous : rows[0]?.id ?? "");
    } catch (failure) { if (!signal?.aborted) setSavedError((failure as Error).message); }
    finally { if (!signal?.aborted) setLoadingSaved(false); }
  }
  async function load(payload?: unknown) {
    if (loadInFlight.current || running) return;
    const controller = new AbortController(); loadController.current = controller;
    loadInFlight.current = true; setLoadingPortfolio(true); setError("");
    try {
      const loaded = await backtestRequest<{ sleeves: Sleeve[]; initial: number; warnings: string[] }>("/api/backtest/load", {
        method: "POST", signal: controller.signal, body: JSON.stringify(payload === undefined ? { mode, portfolio_id: selected } : { mode, payload }) });
      if (controller.signal.aborted) return;
      setValid(false); setSleeves(loaded.sleeves); nextId.current = Math.max(...loaded.sleeves.map(s => s.id))+1;
      setForm(previous => ({ ...previous, initial: loaded.initial, rebalance_sleeve: null, start: "", end: "" }));
      setWarnings(loaded.warnings); onChange();
    } catch (failure) { if (!controller.signal.aborted) setError((failure as Error).message); }
    finally { loadInFlight.current = false; if (!controller.signal.aborted) setLoadingPortfolio(false); }
  }
  async function loadFile() {
    if (!file) return;
    if (file.size > 100000) { setError(words.fileSize); return; }
    try { await load(JSON.parse(await file.text())); }
    catch { setError(mode === "deep" ? words.invalidSavedDeep : words.invalidSaved); }
  }
  const options = config ? (sleeves.length === 1 ? config.single_options : config.blend_options) : [];
  return <section><p>{words.choose}</p>
    {!config && !error && <p role="status">{text.loading}</p>}
    {error && <p role="alert">{error}</p>}
    {savedError && <p role="alert">{words.savedListError} {savedError}</p>}
    {loadingPortfolio && <p role="status">{words.loadingPortfolio}</p>}
    <fieldset disabled={running || loadingPortfolio || !config}>
      <details onToggle={event => { if (mode === "deep" && event.currentTarget.open && !saved.length && !loadingSaved) void listSaved(); }}>
        <summary>{words.load}</summary>
        {loadingSaved && <p role="status">{words.loadingSaved}</p>}
        <label>{words.saved}<select value={selected} disabled={loadingSaved} onChange={event => setSelected(event.target.value)}>{saved.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        {!saved.length && !loadingSaved && !savedError && <p>{words.emptySaved}</p>}
        {savedError && <button type="button" onClick={() => void listSaved()}>{words.retrySaved}</button>}
        <button type="button" disabled={!selected || loadingSaved} onClick={() => void load()}>{words.load}</button>
        <label>{words.file}<input type="file" accept=".json,application/json" onChange={event => setFile(event.target.files?.[0] ?? null)} /></label>
        <button type="button" disabled={!file} onClick={() => void loadFile()}>{words.loadFile}</button>
        <p>{mode === "deep" ? words.deepLoadCaption : words.loadCaption}</p>
      </details>
      {warnings.map((warning, i) => <p role="alert" key={i}>{warning}</p>)}
      <h2>{mode === "deep" ? words.proxySleeves : words.sleeves}</h2><p>{mode === "deep" ? words.proxyCaption : words.sleeveCaption}</p>
      <button type="button" title={mode === "deep" ? words.addProxyHelp : words.addHelp}
        disabled={daily || (mode === "deep" ? sleeves.length >= (config?.blend_options.length ?? 0) : sleeves.length >= 100)} onClick={() => {
          const model = mode === "deep" ? config?.blend_options.find(key => !sleeves.some(s => s.model === key)) : "HAA-Simple";
          if (!model) return; setValid(false); setSleeves(previous => [...previous, { id: nextId.current++, model, weight: 0 }]); onChange();
        }}>{words.add}</button>
      {sleeves.map(s => {
        const current = config?.models.find(m => m.label === s.model);
        const variants = [...new Set(config?.models.filter(m => m.strategy === current?.strategy).map(m => m.variant) ?? [])];
        return <div className="backtest-sleeve" key={s.id}>
          <button type="button" disabled={sleeves.length === 1} onClick={() => { setValid(false); setSleeves(previous => previous.filter(row => row.id !== s.id)); onChange(); }}>{words.remove}</button>
          {mode === "deep" ? <label>{words.proxyStrategy}<select value={s.model} onChange={event => edit(s.id, { model: event.target.value, ...(event.target.value === "rvol_daily" ? { weight: 100 } : {}) })}>
            {options.map(key => <option key={key} value={key}>{config?.proxies.find(p => p.key === key)?.label}</option>)}</select></label> : <div className="signal-selector">
            {!current && <p role="alert">{words.unavailable.replace("{model}", s.model)}</p>}
            <label>{text.strategy}<select value={current?.strategy ?? ""} onChange={event => choose(s, event.target.value)}>
              {[...new Set(config?.models.map(m => m.strategy) ?? [])].sort().map(name => <option key={name}>{name}</option>)}</select></label>
            <label>{text.variant}<select value={current?.variant ?? ""} disabled={variants.length === 1 && variants[0] === null} onChange={event => choose(s, current?.strategy ?? "", event.target.value)}>
              {variants.map(v => <option key={v ?? "none"} value={v ?? ""}>{v ?? text.noVariants}</option>)}</select></label>
            <label>{text.implementation}<select value={s.model} onChange={event => edit(s.id, { model: event.target.value })}>
              {config?.models.filter(m => m.strategy === current?.strategy && m.variant === current?.variant).map(m => <option key={m.label} value={m.label}>{m.implementation}</option>)}</select></label>
          </div>}
          <label>{words.weight}<input type="number" min="0" max="100" value={s.weight} disabled={s.model === "rvol_daily"}
            onChange={event => edit(s.id, { weight: event.target.valueAsNumber })} /></label>
          {mode === "deep" && <p className="signal-warning">{config?.proxies.find(p => p.key === s.model)?.caveat}</p>}
        </div>;
      })}
      {message && <p role="status">{message}</p>}
      {mode === "portfolio" ? <><h2>{words.mixed}</h2><p>{words.mixedCaption}</p>
        <label>{words.rule}<select value={form.sleeve_rebalance_mode} onChange={event => change({ sleeve_rebalance_mode: event.target.value,
          ...(event.target.value === "rvol_cap" ? { rebalance_sleeve: sleeves.find(s => s.id === form.rebalance_sleeve && s.model.includes("RVol"))?.id ?? sleeves.find(s => s.model.includes("RVol"))?.id ?? null } : {}) })}>
          {Object.entries(words.rules).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        {form.sleeve_rebalance_mode === "rvol_cap" && <><label>{words.capSleeve}<select value={form.rebalance_sleeve ?? ""} onChange={event => change({ rebalance_sleeve: Number(event.target.value) })}>
          <option value="" />{sleeves.filter(s => s.model.includes("RVol")).map(s => <option key={s.id} value={s.id}>{s.model} ({s.id})</option>)}</select></label>
          <label>{words.cap}<input type="number" min="1" max="99" value={form.rebalance_cap} onChange={event => change({ rebalance_cap: event.target.valueAsNumber })} /></label>
          <label>{words.target}<input type="number" min="1" max="98" value={form.rebalance_target} onChange={event => change({ rebalance_target: event.target.valueAsNumber })} /></label></>}
        <p>{words.taxCaption}</p></> : <><label title={words.benchmarkHelp}>{words.benchmark}<select value={form.benchmark} onChange={event => change({ benchmark: event.target.value })}>
          {config?.benchmarks.map(b => <option key={b.key} value={b.key}>{b.label}</option>)}</select></label><p>{words.benchmarkHelp}</p>
          <p>{config?.benchmarks.find(b => b.key === form.benchmark)?.caveat}</p><p>{daily ? words.dailyCaption : words.proxyTax.replace("{benchmark}", config?.benchmarks.find(b => b.key === form.benchmark)?.label ?? "")}</p>
          {sleeves.some(s => s.model === "rvol_synthetic") && <p className="signal-warning">{words.syntheticTax}</p>}</>}
      <div className="backtest-grid">
        <label>{text.initial}<input type="number" min="1" value={form.initial} onChange={event => change({ initial: event.target.valueAsNumber })} /></label>
        <Fees value={form} onChange={change} />
        <label>{daily ? words.dailyTax : text.taxEnabled}<input type="checkbox" disabled={daily} checked={!daily && form.tax_enabled} onChange={event => change({ tax_enabled: event.target.checked })} /></label>
        {!daily && <label>{text.taxRate}<input type="number" min="0" max="100" disabled={!form.tax_enabled} value={form.tax_rate} onChange={event => change({ tax_rate: event.target.valueAsNumber })} /></label>}
        <label>{text.dcaEnabled}<input type="checkbox" checked={dca} onChange={event => { setDca(event.target.checked); change({}); }} /></label>
        {dca && <label>{text.dcaAmount}<input type="number" min="0" value={form.monthly_contribution} onChange={event => change({ monthly_contribution: event.target.valueAsNumber })} /></label>}
        <label>{mode === "portfolio" ? words.portfolioStart : sleeves.length > 1 ? words.blendStart : words.proxyStart}<input type="date" value={form.start} onChange={event => change({ start: event.target.value })} /></label>
        <label>{mode === "portfolio" ? words.portfolioEnd : sleeves.length > 1 ? words.blendEnd : words.proxyEnd}<input type="date" value={form.end} onChange={event => change({ end: event.target.value })} /></label>
      </div>{dca && <p>{config?.dca_caption}</p>}<p>{words.dateHelp}</p>
      <button type="button" disabled={!valid || running || !config} onClick={() => void onRun(body)}>{running ? text.running : text.run}</button>
    </fieldset>
  </section>;
}
