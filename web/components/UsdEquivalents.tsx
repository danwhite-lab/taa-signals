"use client";
import {useEffect,useRef,useState} from "react";
import words from "../content/usd-equivalents.json";
import {Toggle} from "./BacktestAssumptions";
import {compareRequest} from "../lib/compareApi";
export type Mapping = {original:string;resolved:string;funds:string;assets:string;caveat:string;warning?:string};
export type UsdInfo = {enabled:boolean;currency:string;mapping_version:string;mappings:Mapping[];tested?:{start:string;end:string};bounds?:Bounds;fees?:string;benchmark?:string};
export type Bounds = {start_min:string;start_max:string;end_min:string;end_max:string};
export function UsdToggle({checked,onChange,disabled=false}:{checked:boolean;onChange:(value:boolean)=>void;disabled?:boolean}){
 return <div className="usd-equivalent-control"><Toggle checked={checked} onChange={onChange} disabled={disabled}>{words.toggle}</Toggle>{checked && <p>{words.amounts}</p>}</div>;
}
export function UsdBanner({value}:{value?:UsdInfo}){
 if(!value?.enabled)return null;
 return <aside className="usd-equivalent-banner" aria-label={words.banner}><strong>{words.banner}</strong><p>{words.currency}{value.tested && <> · {words.tested}: {value.tested.start} – {value.tested.end}</>}{!value.tested && value.bounds && <> · {words.available}: {value.bounds.start_min} – {value.bounds.end_max}</>}</p><p>{words.notice}</p>{value.mappings.filter(row=>row.warning).map((row,i)=><p className="signal-warning" key={i}>{row.original}: {row.warning}</p>)}
 <details><summary>{words.sources}</summary><p>{words.no_reconstruction}</p><p>{value.benchmark ?? words.benchmark}</p><p>{value.fees ?? words.backtest_fees}</p>
 <div className="usd-mapping-scroll"><table><thead><tr>{[words.original,words.resolved,words.funds,words.assets,words.caveat].map(word=><th key={word}>{word}</th>)}</tr></thead><tbody>{value.mappings.map((row,i)=><tr key={i}><td>{row.original}</td><td>{row.resolved}</td><td>{row.funds}</td><td>{row.assets}</td><td>{row.caveat}</td></tr>)}</tbody></table></div></details></aside>;
}
export type Selection={mode:"portfolio"|"models"|"portfolios";models?:string[];portfolio_ids?:string[];method?:"monthly"|"daily"};
export function useUsdAvailability(usd:boolean,selection:Selection,onBounds:(bounds:Bounds)=>void,paused=false){
 const [value,setValue]=useState<(UsdInfo&{bounds:Bounds})|null>(null),[error,setError]=useState(""),[loading,setLoading]=useState(false);
 const callback=useRef(onBounds);callback.current=onBounds;
 const ever=useRef(false);const lastChecked=useRef("");const key=JSON.stringify(selection);
 useEffect(()=>{
  if (paused) return;
  if(usd)ever.current=true;
  const picked=selection.mode==="portfolios"?selection.portfolio_ids:selection.models;
  if(!ever.current || !picked?.length){lastChecked.current="";setValue(null);setError("");setLoading(false);return;}
  const requestKey=`${usd}:${key}`;
  if (lastChecked.current === requestKey) return;
  lastChecked.current="";
  const controller=new AbortController();setValue(null);setError("");setLoading(true);
  void compareRequest<UsdInfo&{bounds:Bounds}>("/api/usd-equivalents/options",{method:"POST",signal:controller.signal,body:JSON.stringify({...JSON.parse(key),usd_equivalents:usd})})
   .then(result=>{if(!controller.signal.aborted){lastChecked.current=requestKey;setValue({...result,enabled:usd});callback.current(result.bounds);}})
   .catch(failure=>{if(!controller.signal.aborted)setError((failure as Error).message);})
   .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
  return()=>controller.abort();
 },[usd,key,paused]);
 return {value,error,loading};
}
export function fitDates<T extends {start:string;end:string}>(form:T,bounds:Bounds):T{
 return {...form,start:form.start && form.start>=bounds.start_min && form.start<=bounds.start_max?form.start:bounds.start_min,
  end:form.end && form.end>=bounds.end_min && form.end<=bounds.end_max?form.end:bounds.end_max};
}
