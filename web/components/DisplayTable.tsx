import words from "../content/formatting.json";
import { cell, percent } from "../lib/format";
export type DisplayTableValue={columns:string[];rows:Record<string,unknown>[];display_rows?:Record<string,unknown>[];total_rows?:number;shown_rows?:number};
export default function DisplayTable({value,label}:{value:DisplayTableValue;label?:string}) {
  return <div className="signal-table-scroll">{value.total_rows!==undefined && <p>{words.preview}: {value.shown_rows} / {value.total_rows}</p>}
    <table aria-label={label}><thead><tr>{value.columns.map(column=><th key={column}>{column}</th>)}</tr></thead>
    <tbody>{value.rows.map((row,i)=><tr key={i}>{value.columns.map(column=>{
      const hint=value.display_rows?.[i]?.[column];const raw=row[column];
      return <td key={column}>{column!=="index" && typeof raw==="number" && typeof hint==="string" && hint.endsWith("%") ? percent(raw) : cell(raw,String(row.metric ?? column))}</td>;
    })}</tr>)}</tbody></table>
    {!value.rows.length && <p>{words.emptyTable}</p>}</div>;
}
