import words from "../content/formatting.json";

export function number(value: number, money=false): string {
  if(!Number.isFinite(value))return words.empty;
  return new Intl.NumberFormat(words.locale,{maximumFractionDigits:2,minimumFractionDigits:money?2:0}).format(Object.is(value,-0)?0:value);
}
export function percent(value: number): string {
  if(!Number.isFinite(value))return words.empty;
  return new Intl.NumberFormat(words.locale,{style:"percent",maximumFractionDigits:2,minimumFractionDigits:2}).format(Object.is(value,-0)?0:value);
}
export function date(value: string): string {
  const match=/^(\d{4})-(\d{2})-(\d{2})(?:T.*)?$/.exec(value);
  if(!match)return value;
  const day=new Date(Date.UTC(Number(match[1]),Number(match[2])-1,Number(match[3])));
  if(day.getUTCFullYear()!==Number(match[1]) || day.getUTCMonth()!==Number(match[2])-1 || day.getUTCDate()!==Number(match[3]))return value;
  return new Intl.DateTimeFormat(words.locale,{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"}).format(day);
}
const rates=/cagr|return|drawdown|volatility|turnover|probability|prob\b|p\(|fraction|\brate\b|weight|proportion|percent|transaction[_ ]cost|rebalance[_ ](?:cap|target)|%/i;
const isRate=(context:string)=>!/(?:\bfx\b|exchange|price)/i.test(context) && rates.test(context.replaceAll("_"," "));
const amounts=/amount|value|capital|contribut|investment|gain|cost|cash|notional|price|commission|balance|ils|usd|allocation\s*\(/i;
const identifiers=/^(id|identifier|security|ticker|sleeve|symbol)$/i;
const isIdentifier=(context:string)=>identifiers.test(context.split(".").at(-1) ?? "");
export function axis(value:number|string,title:string):string {
  return typeof value==="string"?text(value):isRate(title)?percent(value):number(value,true);
}
export function text(value: string | null | undefined): string {
  if(value===null || value===undefined)return words.empty;
  return value.replace(/\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?)?/g,match=>date(match))
    .replace(/(?<![\w.])([-+]?\d[\d,]*(?:\.\d+)?)%/g,(_all,n:string)=>percent(Number(n.replaceAll(",",""))/100))
    .replace(/(?<![\w.])[-+]?\d[\d,]*\.\d{3,}(?![\w.%])/g,match=>number(Number(match.replaceAll(",",""))));
}
export function cell(value: unknown, context=""): string {
  if(value===null || value===undefined || value==="")return words.empty;
  if(typeof value==="boolean")return String(value);
  if(typeof value==="object")return json(value,context);
  if(typeof value==="number"){
    if(isIdentifier(context) || (context==="index" && Number.isInteger(value) && value>=1900 && value<=2200))return String(value);
    return isRate(context)?percent(value):number(value,amounts.test(context));
  }
  const raw=String(value);
  if(/^[-+]?\d[\d,]*(?:\.\d+)?%$/.test(raw))return percent(Number(raw.slice(0,-1).replaceAll(",",""))/100);
  if(!isIdentifier(context) && /^[-+]?\d[\d,]*(?:\.\d+)?$/.test(raw)){
    const numeric=Number(raw.replaceAll(",",""));return isRate(context)?percent(numeric):number(numeric,amounts.test(context));
  }
  return text(raw);
}
export function json(value: unknown, context=""): string {
  function walk(item: unknown,key:string): unknown {
    if(Array.isArray(item))return item.map(v=>walk(v,key));
    if(item && typeof item==="object")return Object.fromEntries(Object.entries(item).map(([k,v])=>[k,walk(v,key?`${key}.${k}`:k)]));
    return item===null?null:cell(item,key);
  }
  return JSON.stringify(walk(value,context),null,2);
}

// Form settings use percentage points; engine outputs use fractions. Display
// conversions must never be written back to either source object.
export function configuration(value: unknown, key:string, percentageFee=false):string {
  function walk(item:unknown,name:string):unknown {
    if(Array.isArray(item))return item.map(v=>walk(v,name));
    if(item && typeof item==="object")return Object.fromEntries(Object.entries(item).map(([k,v])=>[k,walk(v,k)]));
    if(typeof item==="number" && (/^(weight|tax_rate|fee_pct|rebalance_cap|rebalance_target)$/.test(name) || (name==="fee_value" && percentageFee)))return percent(item/100);
    return cell(item,name);
  }
  const result=walk(value,key);
  return typeof result==="object"?JSON.stringify(result,null,2):String(result);
}
