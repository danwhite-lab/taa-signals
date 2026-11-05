"use client";
import { useEffect, useRef, useState } from "react";
import text from "../../content/backtest.json";
import words from "../../content/backtest-multi.json";
import { backtestRequest } from "../../lib/backtestApi";
import Fees, { defaultFees, type FeeAssumptions } from "./fee-assumptions";
import { AmountAndDates, DateField, Toggle, TaxControls } from "../../components/BacktestAssumptions";
import { savedChoices } from "../../lib/ui-order";

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
  useEffect(() => {
    const controller = new AbortController();
    void backtestRequest<Config>(`/api/backtest/config?mode=${mode}`, { signal: controller.signal })
      .then(value => { if (!controller.signal.aborted) setConfig(value); })
      .catch((failure: Error) => { if (!controller.signal.aborted) setError(failure.message); });
    return () => { controller.abort(); loadController.current?.abort(); };
  }, [mode]);
  function change(patch: Partial<Form>) { setValid(false); setMessage(""); setForm(previous => ({ ...previous, ...patch })); setError(""); onChange(); }
  function edit(id: number, patch: Partial<Sleeve>) {
    setValid(false); setMessage(""); setSleeves(previous => previous.map(s => s.id === id ? { ...s, ...patch } : s)); setWarnings([]); onChange();
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
        ? (await backtestRequest<{portfolios: {id: string; name: string}[]}>("/api/compare/options?kind=portfolios", {signal})).portfolios
        : await backtestRequest<{id: string; name: string}[]>("/api/portfolios", {signal});
      if (signal?.aborted) return;
      const ordered = await savedChoices(rows, () => backtestRequest<{id:string;is_default?:boolean}[]>("/api/portfolios", {signal}));
      if (signal?.aborted) return;
      setSaved(ordered); setSelected(previous => ordered.some(row => row.id === previous) ? previous : ordered[0]?.id ?? "");
    } catch (failure) { if (!signal?.aborted) setSavedError((failure as Error).message); }
    finally { if (!signal?.aborted) setLoadingSaved(false); }
  }
  async function load(payload?: unknown) {
    if (loadInFlight.current || running) return;
    const controller = new AbortController(); loadController.current = controller;
    loadInFlight.current = true; setLoadingPortfolio(true); setMessage(""); setError("");
    try {
      const loaded = await backtestRequest<{ sleeves: Sleeve[]; initial: number | null; warnings: string[] } & Partial<Pick<Form,
        "sleeve_rebalance_mode" | "rebalance_sleeve" | "rebalance_cap" | "rebalance_target">>>("/api/backtest/load", {
        method: "POST", signal: controller.signal, body: JSON.stringify(payload === undefined ? { mode, portfolio_id: selected } : { mode, payload }) });
      if (controller.signal.aborted) return;
      setValid(false); setMessage(""); setSleeves(loaded.sleeves); nextId.current = Math.max(...loaded.sleeves.map(s => s.id))+1;
      setForm(previous => ({ ...previous, ...(loaded.initial === null ? {} : { initial: loaded.initial }), start: "", end: "",
        ...(mode === "portfolio" ? { sleeve_rebalance_mode: loaded.sleeve_rebalance_mode ?? "none",
          rebalance_sleeve: loaded.rebalance_sleeve ?? null, rebalance_cap: loaded.rebalance_cap ?? 15,
          rebalance_target: loaded.rebalance_target ?? 10 } : { rebalance_sleeve: null }) }));
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
  async function validateAndRun() {
    if (running || !config) return;
    setValid(false); setMessage(""); setError("");
    try {
      const value = await backtestRequest<{valid:boolean;message:string}>("/api/backtest/validate", {method:"POST", body:JSON.stringify(body)});
      setValid(value.valid); setMessage(value.message);
      if (value.valid) await onRun(body);
    } catch (failure) { setMessage((failure as Error).message); }
  }
  const options = config ? (sleeves.length === 1 ? config.single_options : config.blend_options) : [];
  const transferControls = <>
        <label>{words.rule}<select value={form.sleeve_rebalance_mode} onChange={event => change({ sleeve_rebalance_mode: event.target.value,
          ...(event.target.value === "rvol_cap" ? { rebalance_sleeve: sleeves.find(s => s.id === form.rebalance_sleeve && s.model.includes("RVol"))?.id ?? sleeves.find(s => s.model.includes("RVol"))?.id ?? null } : {}) })}>
          {Object.entries(words.rules).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        {form.sleeve_rebalance_mode === "rvol_cap" && <><label>{words.capSleeve}<select value={form.rebalance_sleeve ?? ""} onChange={event => change({ rebalance_sleeve: Number(event.target.value) })}>
          <option value="" />{sleeves.filter(s => s.model.includes("RVol")).map(s => <option key={s.id} value={s.id}>{s.model} ({s.id})</option>)}</select></label>
          <label>{words.cap}<input type="number" min="1" max="99" value={form.rebalance_cap} onChange={event => change({ rebalance_cap: event.target.valueAsNumber })} /></label>
          <label>{words.target}<input type="number" min="1" max="98" value={form.rebalance_target} onChange={event => change({ rebalance_target: event.target.valueAsNumber })} /></label></>}
        <details><summary>{words.settingsHelp}</summary><p>{words.mixedCaption}</p><p>{words.taxCaption}</p></details></>;
  const compact = mode === "portfolio";
  let total = 0;
  for (const sleeve of sleeves) total += sleeve.weight;
  const totalLabel = Number.isFinite(total) ? new Intl.NumberFormat("en", {maximumFractionDigits:2}).format(total) : "—";
  const allocationValid = Number.isFinite(total) && Math.abs(total - 100) < 1e-8 && sleeves.every(s => Number.isFinite(s.weight) && s.weight > 0);
  const footerSummary = words.footerSummary.replace("{count}", String(sleeves.length)).replace("{total}", totalLabel)
    .replace("{initial}", new Intl.NumberFormat("en", {style:"currency",currency:"USD",maximumFractionDigits:0}).format(Number.isFinite(form.initial) ? form.initial : 0));
  return <section className={compact ? "portfolio-compact" : undefined}>{!compact && <p>{words.choose}</p>}
    {!config && !error && <p role="status">{text.loading}</p>}

    {savedError && <p role="alert">{words.savedListError} {savedError}</p>}
    {loadingPortfolio && <p role="status">{words.loadingPortfolio}</p>}
    <fieldset disabled={running || loadingPortfolio || !config}>
      <section className={compact ? "portfolio-allocation" : undefined}>
      <header className={compact ? "portfolio-allocation-header" : undefined}>{compact && <h2>{words.allocationTitle}</h2>}
      <details className="portfolio-saved-loader" onToggle={event => { if (event.currentTarget.open && !saved.length && !loadingSaved) void listSaved(); }}>
        <summary>{words.load}</summary>
        {loadingSaved && <p role="status">{words.loadingSaved}</p>}
        <label>{words.saved}<select value={selected} disabled={loadingSaved} onChange={event => setSelected(event.target.value)}>{saved.map(row => <option key={row.id} value={row.id}>{row.name}</option>)}</select></label>
        {!saved.length && !loadingSaved && !savedError && <p>{words.emptySaved}</p>}
        {savedError && <button className="btn btn-secondary" type="button" onClick={() => void listSaved()}>{words.retrySaved}</button>}
        <button className="btn btn-secondary" type="button" disabled={!selected || loadingSaved} onClick={() => void load()}>{words.load}</button>
        <label>{words.file}<input type="file" accept=".json,application/json" onChange={event => setFile(event.target.files?.[0] ?? null)} /></label>
        <button className="btn btn-secondary" type="button" disabled={!file} onClick={() => void loadFile()}>{words.loadFile}</button>
        <details><summary>{words.loadingHelp}</summary><p>{mode === "deep" ? words.deepLoadCaption : words.loadCaption}</p></details>
      </details>
      </header>
      {warnings.map((warning, i) => <p role="alert" key={i}>{warning}</p>)}
      {compact ? <details className="portfolio-help"><summary>{words.allocationHelp}</summary><p>{words.sleeveCaption}</p></details> : <><h2>{words.proxySleeves}</h2><p>{words.proxyCaption}</p></>}
      {compact ? <div className="portfolio-sleeves-scroll"><table className="portfolio-sleeves-table" aria-label={words.allocationTitle}><thead><tr>
        <th scope="col">{text.strategy}</th><th scope="col">{text.variant}</th><th scope="col">{text.implementation}</th><th scope="col" className="numeric">{words.weight}</th><th scope="col"><span className="visually-hidden">{words.actions}</span></th>
      </tr></thead><tbody>{sleeves.map((s, index) => {
        const current = config?.models.find(m => m.label === s.model);
        const variants = [...new Set(config?.models.filter(m => m.strategy === current?.strategy).map(m => m.variant) ?? [])];
        return <tr key={s.id}><td>{!current && <p role="alert">{words.unavailable.replace("{model}", s.model)}</p>}
            <label>{text.strategy}<select value={current?.strategy ?? ""} onChange={event => choose(s, event.target.value)}>
              {[...new Set(config?.models.map(m => m.strategy) ?? [])].sort().map(name => <option key={name}>{name}</option>)}</select></label></td><td><label>{text.variant}<select value={current?.variant ?? ""} disabled={variants.length === 1 && variants[0] === null} onChange={event => choose(s, current?.strategy ?? "", event.target.value)}>
              {variants.map(v => <option key={v ?? "none"} value={v ?? ""}>{v ?? text.noVariants}</option>)}</select></label></td><td><label>{text.implementation}<select value={s.model} onChange={event => edit(s.id, { model: event.target.value })}>
              {config?.models.filter(m => m.strategy === current?.strategy && m.variant === current?.variant).map(m => <option key={m.label} value={m.label}>{m.implementation}</option>)}</select></label>
          </td><td className="numeric">          <label>{words.weight}<input type="number" min="0" max="100" value={s.weight} disabled={s.model === "rvol_daily"}
            onChange={event => edit(s.id, { weight: event.target.valueAsNumber })} /></label>
</td><td><button className="portfolio-remove" type="button" aria-label={words.removeSleeve.replace("{number}",String(index+1))} title={words.remove}
          disabled={sleeves.length === 1} onClick={() => {setValid(false); setMessage(""); setSleeves(previous => previous.filter(row => row.id !== s.id)); onChange();}}>×</button></td></tr>;
      })}</tbody></table></div> : <>      {sleeves.map(s => {
        const current = config?.models.find(m => m.label === s.model);
        const variants = [...new Set(config?.models.filter(m => m.strategy === current?.strategy).map(m => m.variant) ?? [])];
        return <div className="backtest-sleeve" key={s.id}>
          <button className="btn btn-destructive" type="button" disabled={sleeves.length === 1} onClick={() => { setValid(false); setMessage(""); setSleeves(previous => previous.filter(row => row.id !== s.id)); onChange(); }}>{words.remove}</button>
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
</>}
      <div className="portfolio-allocation-bottom">      <button className="btn btn-secondary" type="button" title={mode === "deep" ? words.addProxyHelp : words.addHelp}
        disabled={daily || (mode === "deep" ? sleeves.length >= (config?.blend_options.length ?? 0) : sleeves.length >= 100)} onClick={() => {
          const model = mode === "deep" ? config?.blend_options.find(key => !sleeves.some(s => s.model === key)) : "HAA-Simple";
          if (!model) return; setValid(false); setMessage(""); setSleeves(previous => [...previous, { id: nextId.current++, model, weight: 0 }]); onChange();
        }}>{compact ? words.addSleeve : words.add}</button>
{compact && <span className={allocationValid ? "allocation-total" : "allocation-total invalid"} role="status">{words.total.replace("{total}",totalLabel)}</span>}</div>
      </section>
      <AmountAndDates title={compact ? words.investmentTitle : undefined} initial={<label>{text.initial}<input type="number" min="1" value={form.initial} onChange={event => change({ initial: event.target.valueAsNumber })} /></label>} start={<DateField label="Start" hint={mode === "portfolio" ? words.portfolioStart : sleeves.length > 1 ? words.blendStart : words.proxyStart}><input aria-label={mode === "portfolio" ? words.portfolioStart : sleeves.length > 1 ? words.blendStart : words.proxyStart} type="date" value={form.start} onChange={event => change({ start: event.target.value })} /></DateField>} end={<DateField label="End" hint={mode === "portfolio" ? words.portfolioEnd : sleeves.length > 1 ? words.blendEnd : words.proxyEnd}><input aria-label={mode === "portfolio" ? words.portfolioEnd : sleeves.length > 1 ? words.blendEnd : words.proxyEnd} type="date" value={form.end} onChange={event => change({ end: event.target.value })} /></DateField>}
        dca={<><Toggle checked={dca} onChange={value => { setDca(value); change({}); }}>{text.dcaEnabled}</Toggle>{dca && <label>{text.dcaAmount}<input type="number" min="0" value={form.monthly_contribution} onChange={event => change({ monthly_contribution: event.target.valueAsNumber })} /></label>}</>} />
      {dca && <p className="portfolio-dca-caption">{config?.dca_caption}</p>}
      {compact ? <details className="portfolio-advanced"><summary><strong>{words.advancedTitle}</strong><span>{words.rebalancingTitle}: {words.rules[form.sleeve_rebalance_mode as keyof typeof words.rules]} · {words.feesTitle}: {form.fees_enabled ? words.on : words.off} · {words.taxTitle}: {form.tax_enabled ? `${form.tax_rate}%` : words.off}</span></summary>
        <div className="portfolio-advanced-grid"><section><h3>{words.rebalancingTitle}</h3>      {transferControls}
</section>
        <section><h3>{words.feesTitle}</h3><Fees compact value={form} onChange={change} /></section><section><h3>{words.taxTitle}</h3>        <TaxControls enabled={!daily && form.tax_enabled} rate={form.tax_rate} disabled={daily} hideRate={daily} label={daily ? words.dailyTax : text.taxEnabled}
          onEnabled={tax_enabled => change({tax_enabled})} onRate={tax_rate => change({tax_rate})} /></section></div>
        <details><summary>{words.settingsHelp}</summary><p>{words.dateHelp}</p></details>
      </details> : <>      <label title={words.benchmarkHelp}>{words.benchmark}<select value={form.benchmark} onChange={event => change({ benchmark: event.target.value })}>
          {config?.benchmarks.map(b => <option key={b.key} value={b.key}>{b.label}</option>)}</select></label><p>{words.benchmarkHelp}</p>
          <p>{config?.benchmarks.find(b => b.key === form.benchmark)?.caveat}</p><p>{daily ? words.dailyCaption : words.proxyTax.replace("{benchmark}", config?.benchmarks.find(b => b.key === form.benchmark)?.label ?? "")}</p>
          {sleeves.some(s => s.model === "rvol_synthetic") && <p className="signal-warning">{words.syntheticTax}</p>}
      <Fees value={form} onChange={change}>
        <TaxControls enabled={!daily && form.tax_enabled} rate={form.tax_rate} disabled={daily} hideRate={daily} label={daily ? words.dailyTax : text.taxEnabled}
          onEnabled={tax_enabled => change({tax_enabled})} onRate={tax_rate => change({tax_rate})} />
      </Fees>
<p>{words.dateHelp}</p></>}
      <footer className="portfolio-run-footer"><div>{compact && <p>{footerSummary}</p>}
      {compact && !allocationValid && <p role="alert">{(sleeves.some(s => !Number.isFinite(s.weight) || s.weight <= 0) ? words.positivePortfolio : words.weightWarning.replace("{total:.2f}",totalLabel))}</p>}
      {error && <p role="alert">{error}</p>}
      {message && <p role={valid ? "status" : "alert"}>{message}</p>}</div>
      <button className="btn btn-primary" type="button" disabled={running || !config || (compact && !allocationValid)} onClick={() => void validateAndRun()}>{running ? text.running : text.run}</button>
      </footer>
    </fieldset>
  </section>;
}
