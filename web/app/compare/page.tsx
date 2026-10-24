"use client";
import { useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";
import DisplayTable from "../../components/DisplayTable";
import * as fmt from "../../lib/format";
import text from "../../content/compare.json";
import { compareRequest, compareDownload } from "../../lib/compareApi";
import { AmountAndDates, DateField, CostsAndTax, TaxControls } from "../../components/BacktestAssumptions";
import { savedChoices } from "../../lib/ui-order";

type Mode = "models" | "portfolios";
type Settings = {mode: Mode; models: string[]; portfolio_ids: string[]; method: "monthly" | "daily"; initial: number; monthly_contribution: number; fee_pct: number; tax_enabled: boolean; tax_rate: number; start: string; end: string};
type Table = {columns: string[]; rows: Record<string, unknown>[]; display_rows?: Record<string, unknown>[]; total_rows?: number; shown_rows?: number};
type Chart = {series: {label: string; svg_points: string}[]; start: string; end: string; minimum: number; maximum: number; caption: string};
type Options = {models: {label: string; strategy?: string; benchmark: string; execution_currency: string}[]; portfolios: {id: string; name: string}[]; defaults: Settings};
type Result = {gate: string; reason?: string; mode: Mode; tax_enabled: boolean; window: {start: string; end: string; periods: number};
  success: string | null; source_caption: string | null; coverage: Table; tables: Record<string, Table>; charts: Record<string, Chart>;
  downloads: {kind: string; label: string; filename: string}[]; cache: {key: string; hit: string | null}; warnings: string[]; timing: unknown; data_validation: Table};

function DataTable({value,label}:{value:Table;label?:string}) { return <DisplayTable value={value} label={label}/>; }

function Plot({value, title}: {value?: Chart; title: string}) {
  if (!value) return null;
  const colors = ["#17645f", "#6488a3", "#b58a52", "#7b799c", "#ad6971"];
  return <section><h3>{title}</h3><svg viewBox="0 0 930 300" role="img" aria-label={title}>
    <text x="0" y="20" fontSize="11">{fmt.axis(value.maximum,title)}</text><text x="0" y="250" fontSize="11">{fmt.axis(value.minimum,title)}</text>
    {value.series.map((series,i) => <polyline key={series.label} points={series.svg_points} fill="none" stroke={colors[i%colors.length]} strokeWidth="1.5"><title>{series.label}</title></polyline>)}
    <text x="55" y="285" fontSize="11">{fmt.date(value.start)}</text><text x="870" y="285" fontSize="11" textAnchor="end">{fmt.date(value.end)}</text>
    </svg><ul>{value.series.map((series,i)=><li style={{color:colors[i%colors.length]}} key={series.label}>{series.label}</li>)}</ul><p>{value.caption}</p></section>;
}

export default function ComparePage() {
  const [options,setOptions] = useState<Options | null>(null), [settings,setSettings] = useState<Settings | null>(null);
  const [result,setResult] = useState<Result | null>(null), [error,setError] = useState(""), [running,setRunning] = useState(false), [changed,setChanged] = useState(false), [retry,setRetry] = useState(0);
  const inFlight = useRef(false);
  const [search,setSearch] = useState("");
  useEffect(()=>{
    const controller = new AbortController(); setError("");
    void compareRequest<Options>("/api/compare/options",{signal:controller.signal}).then(async value=>{
      const portfolios = await savedChoices(value.portfolios, () => compareRequest<{id:string;is_default?:boolean}[]>("/api/portfolios", {signal:controller.signal}));
      if(!controller.signal.aborted) {setOptions({...value,portfolios});setSettings(previous=>previous ?? {...value.defaults,start:"",end:""});}
    }).catch((failure:Error)=>{if(!controller.signal.aborted) setError(failure.message);});
    return ()=>controller.abort();
  },[retry]);
  function change(patch: Partial<Settings>) {setSettings(value=>value && {...value,...patch}); if(result) setChanged(true); setResult(null); setError("");}
  async function run() {
    if(inFlight.current || !settings) return;
    inFlight.current=true; setRunning(true);setResult(null);setError("");setChanged(false);
    const controller=new AbortController();let timedOut=false;
    const timer=setTimeout(()=>{timedOut=true;controller.abort();},305000);
    try {setResult(await compareRequest<Result>("/api/compare",{method:"POST",signal:controller.signal,body:JSON.stringify({...settings,monthly_contribution:settings.mode==="models"?settings.monthly_contribution:0,start:settings.start || null,end:settings.end || null})}));}
    catch(failure) {setError(timedOut ? text.timeout : (failure as Error).message);}
    finally {clearTimeout(timer);inFlight.current=false;setRunning(false);}
  }
  function download(kind: string) {
    const item=result?.downloads.find(d=>d.kind===kind);
    return item && <button className="btn btn-secondary" key={kind} onClick={()=>void compareDownload(result!.cache.key,kind,item.filename).catch(()=>setError(text.downloadError))}>{item.label}</button>;
  }
  const models=settings?.mode!=="portfolios";
  const selected=options?.models.filter(m=>settings?.models.includes(m.label)) ?? [];
  const mismatch=new Set(selected.map(m=>m.execution_currency)).size>1;
  const enough=(models ? settings?.models.length ?? 0 : settings?.portfolio_ids.length ?? 0)>=2;
  const suffix=result?.tax_enabled ? "after" : "pre";
  const groups = new Map<string, Options["models"]>();
  for(const model of options?.models ?? []) {
    if(!model.label.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase())) continue;
    const family=model.strategy?.trim() || text.otherGroup;
    groups.set(family,[...(groups.get(family) ?? []),model]);
  }
  const alphabetical=(a:string,b:string)=>a.localeCompare(b,undefined,{sensitivity:"base"});
  return <main className="backtest-page compare-page"><h1>{models ? text.title : text.portfolioTitle}</h1>
    {error && <p role="alert">{error}</p>}
    {error && options && <button className="btn btn-secondary" disabled={running} onClick={()=>void run()}>{text.retry}</button>}
    {!options && !error && <p role="status">{text.loading}</p>}
    {!options && error && <button className="btn btn-secondary" onClick={()=>setRetry(n=>n+1)}>{text.retry}</button>}
    {options && settings && <>
      <fieldset disabled={running}>
      <div className="segmented" role="radiogroup" aria-label={text.mode}>{Object.entries(text.modes).map(([key,label])=><label className="segment" key={key}><input type="radio" name="compare-mode" checked={settings.mode===key} value={key} onChange={()=>change({mode:key as Mode})}/>{label}</label>)}</div>
      {models ? <fieldset aria-label={text.models}><legend>{text.models}</legend>
        <label>{text.search}<input type="search" placeholder={text.searchPlaceholder} value={search} onChange={e=>setSearch(e.target.value)}/></label>
        <p className="compare-selection-count">{text.selectedCount.replace("{count}",String(settings.models.length))}</p>
        {[...groups].sort(([a],[b])=>alphabetical(a,b)).map(([family,entries])=><section className="compare-model-group" key={family} aria-label={family}><h3>{family}</h3><div>{entries.sort((a,b)=>alphabetical(a.label,b.label)).map(m=><label key={m.label}><input type="checkbox" checked={settings.models.includes(m.label)} onChange={e=>change({models:e.target.checked?[...settings.models,m.label]:settings.models.filter(label=>label!==m.label)})}/>{m.label}</label>)}</div></section>)}
        </fieldset> :
        <fieldset aria-label={text.saved}><legend>{text.saved}</legend>{options.portfolios.map(p=><label key={p.id}><input type="checkbox" value={p.id} checked={settings.portfolio_ids.includes(p.id)} onChange={e=>change({portfolio_ids:e.target.checked?[...settings.portfolio_ids,p.id]:settings.portfolio_ids.filter(id=>id!==p.id)})}/>{p.name}</label>)}</fieldset>}
      </fieldset>
      {!enough ? <p className="signal-info">{models ? text.modelsGate : text.portfoliosGate}</p> : <>
      <p>{models ? text.modelsCaption : text.savedCaption}</p>
      {!models && <p>{text.neutral}</p>}
      <fieldset className={`compare-settings${models ? " compare-model-settings" : ""}`} disabled={running}>
        {!models && <><label>{text.method}<select value={settings.method} onChange={e=>change({method:e.target.value as Settings["method"]})}>{Object.entries(text.methods).map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><p>{text.methodCaption}</p></>}
        <AmountAndDates initial={<label>{models ? text.initial : text.portfolioInitial}<input type="number" min="1" step={models ? 1000 : 1} value={settings.initial} onChange={e=>change({initial:e.target.valueAsNumber})}/></label>}
          contribution={models && <label>{text.contribution}<input type="number" min="0" step="100" value={settings.monthly_contribution} onChange={e=>change({monthly_contribution:e.target.valueAsNumber})}/></label>}
          start={<DateField label={text.startLabel} hint={models ? text.start : text.portfolioStart}><input aria-label={models ? text.start : text.portfolioStart} type="date" value={settings.start} onChange={e=>change({start:e.target.value})}/></DateField>} end={<DateField label={text.endLabel} hint={models ? text.end : text.portfolioEnd}><input aria-label={models ? text.end : text.portfolioEnd} type="date" value={settings.end} onChange={e=>change({end:e.target.value})}/></DateField>} />
        {models && <p className="assumption-hint">{text.contributionCaption}</p>}
        <CostsAndTax><TaxControls leading={<label>{models ? text.fee : text.portfolioFee}<input type="number" min="0" max="10" step="0.01" value={settings.fee_pct} onChange={e=>change({fee_pct:e.target.valueAsNumber})}/></label>}
          enabled={settings.tax_enabled} rate={settings.tax_rate} step={.1} label={text.tax} rateLabel={text.rate} onEnabled={tax_enabled=>change({tax_enabled})} onRate={tax_rate=>change({tax_rate})}/></CostsAndTax>
        <p>{text.dateHelp}</p>{models && mismatch && <p className="signal-warning">{text.hint}</p>}
      </fieldset><button className="btn btn-primary" disabled={running} onClick={()=>void run()}>{running ? text.running : text.run}</button>
      {running && <p role="status">{text.progress}</p>}{!running && !result && <p>{text.before}</p>}{changed && <p>{text.changed}</p>}
      </>}
    </>}
    {result?.gate === "selection" && <p className="signal-info">{result.reason}</p>}
    {result?.gate === "available" && <section aria-label={text.completed}>
      <p>{text.completed}</p>{result.success && <Markdown>{fmt.text(result.success ?? "")}</Markdown>}{result.source_caption && <p>{fmt.text(result.source_caption)}</p>}
      <p>{result.cache.hit ? text.cached : text.calculated}</p>{result.warnings.map((w,i)=><p className="signal-warning" key={i}>{w}</p>)}
      <details><summary>{text.coverage}</summary><DataTable value={result.coverage}/></details>
      <details><summary>{text.sections[0]}</summary>
        {models ? <><Plot value={result.charts.value_pre} title={text.preChart}/>{result.tax_enabled && <Plot value={result.charts.value_after} title={text.afterChart}/>}</> : <Plot value={result.charts[`value_${suffix}`]} title={text.portfolioChart}/>}
      </details>
      <details><summary>{text.sections[1]}</summary><Plot value={result.charts.drawdown} title={models ? text.drawdown : text.portfolioDrawdown}/></details>
      <details><summary>{text.sections[2]}</summary>
        {models ? <><h2>{text.pre}</h2><DataTable value={result.tables.summary_pre}/>{result.tax_enabled && <><h2>{text.after}</h2><DataTable value={result.tables.summary_after}/></>}
          <h2>{text.latest}</h2><DataTable value={result.tables.allocation}/><h2>{text.audits}</h2>{result.downloads.filter(d=>d.kind.startsWith("audit:")).map(d=>download(d.kind))}</> :
          <><h2>{result.tax_enabled ? text.portfolioAfter : text.portfolioPre}</h2><DataTable value={result.tables[`summary_${suffix}`]}/></>}
      </details>
      <details><summary>{text.sections[3]}</summary>
        {models ? <><h2>{text.annual}</h2><DataTable value={result.tables.annual_pre}/><h2>{text.monthly}</h2><DataTable value={result.tables.monthly_pre}/>{download("monthly-returns")}
          {result.tax_enabled && <><h2>{text.afterAnnual}</h2><DataTable value={result.tables.annual_after}/><h2>{text.afterMonthly}</h2><DataTable value={result.tables.monthly_after}/>{download("after-tax-monthly-returns")}</>}</> :
          <><h2>{text.monthly}</h2><DataTable value={result.tables[`monthly_${suffix}`]}/>{download("portfolio-returns")}</>}
      </details>
      {!models && <p>{text.closing}</p>}
      <details><summary>{text.sources}</summary><DataTable value={result.data_validation}/></details>
      <details><summary>{text.timing}</summary><pre>{fmt.json(result.timing)}</pre></details>
    </section>}
  </main>;
}
