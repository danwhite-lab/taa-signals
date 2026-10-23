"use client";

import { useEffect, useRef, useState } from "react";
import text from "../../content/rebalance.json";
import holdings from "../../content/holdings.json";
import HoldingEditorRow from "../../components/HoldingEditorRow";
import { rebalanceRequest as request, saveHoldings, saveAllocationMode, type AllocationMode, RebalanceError } from "../../lib/rebalanceApi";
import * as fmt from "../../lib/format";

type Row = Record<string, string | boolean | null>;
type Instrument = { id: string; identifier: string; market: string; currency: string; label: string };
type Account = { revision: number; cash_ils: string; manual_fx?: string | null; manual_fx_date?: string | null; [key: string]: unknown };
type Quote = Record<string, unknown>;
type State = { workspace_revision: number; account: Account; account_hash: string; portfolio_id: string | null; allocation_mode: AllocationMode;
  portfolios: { id: string; name: string }[]; rows: Row[]; instruments: Record<string, Instrument>; quotes: Record<string, Quote>;
  comparison: { id: string; Fund: string; target_display: string; actual_display: string; Status: string }[];
  total_display: string; full_total_display: string; full_total_ils: string | null; ready: boolean; blocked: string[];
  held_blocked: string[]; fx: Quote; partial: boolean; overweight: boolean; signals: unknown[]; errors: string[]; source_settings: string; seconds: number };
type Plan = { id: string; orders: { id: string; units: number; estimated_ils: string }[]; leftover_ils: string; unspent_by_fund?: Record<string, string>; unit_costs_ils?: Record<string, string> };
type Preview = { account: Account | null; preview: Record<string, unknown>[]; errors: string[]; quotes?: Record<string, Quote> };
const show = (value: unknown, context="") => fmt.cell(value, context);

export default function RebalanceHoldings() {
  const [state, setState] = useState<State | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [cash, setCash] = useState(""); const [fx, setFx] = useState(""); const [fxDate, setFxDate] = useState("");
  const [money, setMoney] = useState("0"); const [portfolio, setPortfolio] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false); const [paused, setPaused] = useState(false); const [busy, setBusy] = useState(false);
  const [error, setError] = useState(""); const [message, setMessage] = useState(""); const [changed, setChanged] = useState(false);
  const [preview, setPreview] = useState<Preview | null>(null); const [plan, setPlan] = useState<Plan | null>(null);
  const [recording, setRecording] = useState(false); const [ack, setAck] = useState(false);
  const [confirmed, setConfirmed] = useState<Record<string, { units: string; paid_ils: string }>>({});
  const [known, setKnown] = useState(""); const [market, setMarket] = useState("US"); const [identifier, setIdentifier] = useState(""); const [currency, setCurrency] = useState("");
  const [query, setQuery] = useState(""); const [marketFilter, setMarketFilter] = useState(""); const [currencyFilter, setCurrencyFilter] = useState("");
  const [active, setActive] = useState(-1);
  const results = Object.values(state?.instruments ?? {}).filter(item => (!marketFilter || item.market === marketFilter)
    && (!currencyFilter || item.currency === currencyFilter)
    && [item.label, item.identifier, item.market].some(value => value.toLowerCase().includes(query.toLowerCase())))
    .sort((a, b) => a.label.localeCompare(b.label, "en", { sensitivity: "base" }));
  const identity = (item: Instrument) => [item.market, item.identifier, item.currency].join(" · ");
  const inFlight = useRef(false); const generation = useRef(0);

  function invalidate(edit = false) {
    generation.current++; if (plan) setChanged(true); setPlan(null); setRecording(false); setAck(false); setPreview(null); setError(""); setMessage("");
    if (edit) setDirty(true);
  }
  function seed(value: State) {
    setState(value); setRows(value.rows); setCash(value.account.cash_ils); setFx(value.account.manual_fx ?? ""); setFxDate(value.account.manual_fx_date ?? "");
    setPortfolio(value.portfolio_id); setDirty(false); setPlan(null); setRecording(false); setPreview(null); setChanged(false); setConfirmed({});
  }
  async function action(operation: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try { await operation(); }
    catch (failure) { setError(failure instanceof Error ? failure.message : text.error); if (failure instanceof RebalanceError && failure.status === 409) setPaused(true); }
    finally { inFlight.current = false; setBusy(false); }
  }
  async function load() {
    const value = await request<State>("/api/rebalance"); seed(value); setPaused(false); setError(""); setMessage("");
  }
  useEffect(() => { void action(load); }, []);
  function edit(key: string, field: string, value: string | boolean) {
    invalidate(true); setRows(previous => previous.map(row => row.Security === key ? { ...row, [field]: value,
      ...(field === "Units" ? { "Enter as": "Units", "Units edited": true } : field === "Value (₪ / $)" ? { "Enter as": "Value" } : {}) } : row));
  }
  function args() { return { portfolio_id: portfolio, account_hash: state?.account_hash, new_money: money }; }
  async function editor() {
    return request<Preview>("/api/rebalance/editor", { ...args(), rows: rows.map(row => ({ ...row,
      "Manual price per unit": row["Manual price per unit"] === "" ? null : row["Manual price per unit"], "Price date": row["Price date"] || null })),
      cash, manual_fx: fx, manual_fx_date: fxDate || null });
  }
  async function convert() {
    const at = generation.current; const value = await editor(); if (at === generation.current) {
      setPreview(value); if (value.quotes) setState(previous => previous && ({ ...previous, quotes: { ...previous.quotes, ...value.quotes } }));
    }
  }
  async function persist(account: Account, recorded: boolean) {
    if (!state || paused) return;
    const result = await saveHoldings(state.workspace_revision, account);
    if (result.uncertain) { setPaused(true); setError(text.uncertain); }
    if (!result.saved) return;
    setMessage(recorded ? text.recorded : text.saved);
    setPlan(null); setRecording(false);
    if (recorded) setMoney("0");
    if (!result.uncertain) {
      // Save is already confirmed. A failed display reload must not retry it.
      try { seed(await request<State>(`/api/rebalance${portfolio ? `?portfolio_id=${encodeURIComponent(portfolio)}` : ""}`)); }
      catch { setPaused(true); setError(text.uncertain); }
    }
  }
  async function add(item: Instrument) {
    if (rows.some(row => row.Security === item.id) || rows.length >= 200) throw new Error(text.validation);
    invalidate(true); setRows(previous => [...previous, { Security: item.id, Fund: item.label, Currency: item.currency, Units: "0", "Value (₪ / $)": "",
      "Outside the rebalance": false, "Enter as": "Units", "Manual price per unit": null, "Price date": null, "Minimum order (₪)": "0", Remove: false }]);
    setState(previous => previous && ({ ...previous, instruments: { ...previous.instruments, [item.id]: item } }));
  }
  async function refresh(nextPortfolio = portfolio, clear = true) {
    invalidate();
    const value = clear ? await request<State>("/api/rebalance/refresh", { ...args(), portfolio_id: nextPortfolio }) :
      await request<State>(`/api/rebalance${nextPortfolio ? `?portfolio_id=${encodeURIComponent(nextPortfolio)}` : ""}`);
    if (state && value.account_hash !== state.account_hash) throw new RebalanceError(409, text.paused);
    setState(value); setPortfolio(value.portfolio_id);
    if (!dirty) setRows(value.rows);
    else setRows(previous => [...previous, ...value.rows.filter(row => !previous.some(old => old.Security === row.Security))]);
  }
  return <main className="rebalance-page"><h1>{text.title}</h1>
    {busy && <p role="status">{state ? text.working : text.loading}</p>}
    {!state && <>{message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}</>}
    {paused && <p role="alert">{text.paused}</p>}

    {!state && <details><summary>{text.advanced}</summary>
      <button className="btn btn-secondary" disabled={busy} onClick={() => { if (!dirty || window.confirm(text.reloadConfirm)) void action(load); }}>{text.reload}</button>
    </details>}
    {state && <>

      {!!state.blocked.length && <p className="signal-warning">{text.missing} {state.blocked.map(key => state.instruments[key].label).join(", ")}</p>}
      {!!state.held_blocked.length && <p>{text.heldBlocked}</p>}
      {!state.fx.fresh && <p>{text.fxMissing}</p>}
      <section aria-label={text.holdings}><h2>{text.holdings}</h2><p className="holding-hint">{text.editorCaption}</p>
        <div className="holdings-editor" role="list" aria-label={text.holdings}>
          <div className="holding-column-headings" aria-hidden="true">{[holdings.fund, holdings.value, holdings.units, holdings.price, holdings.outside, holdings.remove].map(value => <span key={value}>{value}</span>)}</div>
          {rows.map(row => <HoldingEditorRow key={String(row.Security)} row={row} quote={state.quotes[String(row.Security)]} busy={busy} onEdit={edit}
            onBlur={() => { const at = generation.current; void convert().catch(() => { if (at === generation.current) setError(text.validation); }); }} />)}
        </div>
        <details><summary>{text.add}</summary>
          <label>{text.search}<input role="combobox" aria-expanded={true} aria-controls="fund-results"
            aria-activedescendant={active >= 0 && active < results.length ? `fund-option-${active}` : undefined}
            value={query} disabled={busy} onChange={event => { setQuery(event.target.value); setActive(-1); }}
            onKeyDown={event => {
              if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                event.preventDefault(); setActive(index => results.length ? (index + (event.key === "ArrowDown" ? 1 : -1) + results.length) % results.length : -1);
              } else if (event.key === "Enter" && results[active]) { event.preventDefault(); setKnown(results[active].id); }
              else if (event.key === "Escape") { setQuery(""); setActive(-1); }
            }} /></label>
          <p className="holding-hint">{text.searchCaption}</p>
          {[[text.market, marketFilter, setMarketFilter, text.markets], [text.currency, currencyFilter, setCurrencyFilter, text.currencies]].map(([caption, value, change, choices]) =>
            <div className="fund-filters" role="group" aria-label={caption as string} key={caption as string}>
              <span>{caption as string}</span>{["", ...(choices as string[])].map(option =>
                <button type="button" className="btn btn-secondary" aria-pressed={value === option} key={option}
                  onClick={() => { (change as (value: string) => void)(option); setActive(-1); }}>{option || text.all}</button>)}
            </div>)}
          <div id="fund-results" role="listbox" aria-label={text.search} className="fund-results">
            {results.map((item, index) => <div role="option" id={`fund-option-${index}`} key={item.id} aria-selected={known === item.id}
              className={active === index ? "fund-option active" : "fund-option"} onClick={() => { setKnown(item.id); setActive(index); }}>
              <span>{item.label}</span><small>{identity(item)}</small>
            </div>)}
          </div>
          {!results.length && <p>{text.noResults}</p>}
          {known && state.instruments[known] && <p className="chosen-fund">{text.selected}: {state.instruments[known].label}<small>{identity(state.instruments[known])}</small></p>}
          <button className="btn btn-secondary" disabled={busy || !known} onClick={() => void action(() => add(state.instruments[known]))}>{text.addSelected}</button>
          <details><summary>{text.notFound}</summary>
          <p>{text.customCaption}</p><label>{text.market}<select value={market} onChange={event => setMarket(event.target.value)}>{text.markets.map(value => <option key={value}>{value}</option>)}</select></label>
          <label>{text.identifier}<input value={identifier} onChange={event => setIdentifier(event.target.value)} /></label>
          <label>{text.currency}<select value={currency} onChange={event => setCurrency(event.target.value)}><option value="">{text.marketDefault}</option>{text.currencies.map(value => <option key={value}>{value}</option>)}</select></label>
          <button className="btn btn-secondary" disabled={busy} onClick={() => void action(async () => add(await request<Instrument>("/api/rebalance/security", { identifier, market, currency: currency || null })))}>{text.custom}</button>
          </details>
        </details>
            <label>{text.cash}<input value={cash} inputMode="decimal" disabled={busy} onChange={event => { invalidate(true); setCash(event.target.value); }} /></label>
        {dirty && <p>{text.unsaved}</p>}
        {message && <p role="status">{message}</p>}{error && <p role="alert">{error}</p>}
            <button className="btn btn-primary" disabled={busy || paused} onClick={() => void action(async () => { const value = await editor(); setPreview(value); if (value.account && !value.errors.length) await persist(value.account, false); })}>{text.save}</button>
      </section>
      <section aria-label={text.generate}><h2>{text.generate}</h2>
        <div className="rebalance-controls" role="group" aria-label={text.controls}>
          <div className="rebalance-control-fields">
            <label>{text.portfolio}<select value={portfolio ?? ""} disabled={busy || paused} onChange={event => void action(() => refresh(event.target.value, false))}>
        {!state.portfolios.length && <option value="">—</option>}{state.portfolios.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
                        <label>{text.newMoney}<input value={money} inputMode="decimal" disabled={busy} onChange={event => { invalidate(); setMoney(event.target.value); }} /></label>
                        <label>{text.allocationMode}<select value={state.allocation_mode} disabled={busy || paused} onChange={event => {
              const mode = event.target.value as AllocationMode;
              invalidate();
              void action(async () => {
                const saved = await saveAllocationMode(state.workspace_revision, mode);
                setState(previous => previous && ({ ...previous, workspace_revision: saved.revision, allocation_mode: mode }));
                await refresh(portfolio, false);
              });
            }}>{Object.entries(text.allocationModes).map(([key, caption]) => <option key={key} value={key}>{caption}</option>)}</select></label>
          </div>
          {!state.portfolios.length && <p>{text.noPortfolio}</p>}
          {changed && <p>{text.changed}</p>}
                      <button className="btn btn-primary" disabled={busy || paused || dirty || !state.ready} onClick={() => void action(async () => {
              const value = await request<{ plan: Plan; state: State }>("/api/rebalance/plan", args()); setState(value.state); setPlan(value.plan); setChanged(false);
            })}>{text.generate}</button>
        </div>
      <section><h2>{text.rebalanceTotal}</h2><p>{fmt.cell(state.total_display,"value")}</p><h2>{text.fullTotal}</h2><p>{fmt.cell(state.full_total_display,"value")}</p>{state.full_total_ils === null && <p>{text.fullMissing}</p>}</section>
      <section><h2>{text.comparison}</h2><table><thead><tr><th>{text.fund}</th><th>{text.target}</th><th>{text.actual}</th><th>{text.status}</th></tr></thead><tbody>
        {state.comparison.map(row => <tr key={row.id}><td>{row.Fund}</td><td>{row.target_display}</td><td>{row.actual_display}</td><td>{row.Status}</td></tr>)}</tbody></table>{state.overweight && <p>{text.overweight}</p>}</section>
      {plan && <section><h2>{text.buyList}</h2><table><thead><tr><th>{text.fund}</th><th>{text.wholeUnits}</th><th>{text.estimated}</th></tr></thead><tbody>
        {plan.orders.map(order => <tr key={order.id}><td>{state.instruments[order.id].label}</td><td>{fmt.number(order.units)}</td><td>{fmt.cell(order.estimated_ils,"cost")}</td></tr>)}</tbody></table>
        {state.allocation_mode === "biggest_gap_first" && plan.orders.length === 1 && <p>{text.singleOrder}</p>}{!plan.orders.length && <p>{text.emptyPlan}</p>}<p>{text.leftover}: {fmt.cell(plan.leftover_ils,"cash")}</p>{state.partial && <p>{text.partial}</p>}
        {state.allocation_mode === "proportional" && <>
          {Object.entries(plan.unspent_by_fund ?? {}).filter(([, value]) => Number(value) > 0).map(([key, value]) =>
            <p key={key}>{text.unspentShare.replace("{fund}", state.instruments[key].label).replace("{unspent}", fmt.cell(value, "cash"))
              .replace("{cost}", fmt.cell(plan.unit_costs_ils?.[key], "price"))}</p>)}
          <p>{text.pooledCash}</p>
        </>}
        {!!plan.orders.length && <button className="btn btn-secondary" disabled={busy || paused} onClick={() => { setRecording(true); setAck(false); setConfirmed(Object.fromEntries(plan.orders.map(order => [order.id, { units: "0", paid_ils: "0" }]))); }}>{text.record}</button>}
        {recording && <section><h3>{text.record}</h3><p>{text.recordCaption}</p>{plan.orders.map(order => <div key={order.id}><p>{state.instruments[order.id].label}</p>
          <label>{text.bought}<input inputMode="numeric" value={confirmed[order.id]?.units ?? "0"} disabled={busy} onChange={event => setConfirmed(previous => ({ ...previous, [order.id]: { ...previous[order.id], units: event.target.value } }))} /></label>
          <label>{text.paid}<input inputMode="decimal" value={confirmed[order.id]?.paid_ils ?? "0"} disabled={busy} onChange={event => setConfirmed(previous => ({ ...previous, [order.id]: { ...previous[order.id], paid_ils: event.target.value } }))} /></label></div>)}
          <label><input type="checkbox" checked={ack} disabled={busy} onChange={event => setAck(event.target.checked)} />{text.acknowledge}</label>
          <button className="btn btn-secondary" disabled={busy || paused || !ack} onClick={() => void action(async () => { const value = await request<{ account: Account }>("/api/rebalance/record", {
            ...args(), plan, acknowledge: ack, confirmations: plan.orders.map(order => ({ id: order.id, ...confirmed[order.id] })) }); await persist(value.account, true); })}>{text.done}</button>
          <button className="btn btn-secondary" disabled={busy} onClick={() => setRecording(false)}>{text.cancel}</button></section>}
      </section>}
      </section>
          <details><summary>{text.advanced}</summary>
            <button className="btn btn-secondary" disabled={busy} onClick={() => { if (!dirty || window.confirm(text.reloadConfirm)) void action(load); }}>{text.reload}</button>
            <p>{text.automaticCaption}</p>
            <button className="btn btn-secondary" disabled={busy || paused} onClick={() => void action(convert)}>{text.previewAction}</button>
            {preview && <section><h3>{text.preview}</h3>{preview.errors.map((value, index) => <p role="alert" key={index}>{value}</p>)}
              <div className="signal-table-scroll"><table><thead><tr>{Object.keys(preview.preview[0] ?? {}).map(key => <th key={key}>{key}</th>)}</tr></thead>
                <tbody>{preview.preview.map((row, index) => <tr key={index}>{Object.entries(row).map(([key,value]) => <td key={key}>{show(value,key)}</td>)}</tr>)}</tbody></table></div></section>}

            <details><summary>{text.fx}</summary><p>{text.fxCaption}</p><label>{text.fxRate}<input value={fx} inputMode="decimal" disabled={busy} onChange={event => { invalidate(true); setFx(event.target.value); }} /></label>
              <label>{text.fxDate}<input type="date" value={fxDate} disabled={busy} onChange={event => { invalidate(true); setFxDate(event.target.value); }} /></label></details>


        <button className="btn btn-secondary" disabled={busy || paused} onClick={() => void action(() => refresh())}>{text.refresh}</button>
        <p>{text.pricesCaption}</p><p>{text.fundCaption}</p><p>{text.costCaption}</p><p>{text.conflictDetails}</p>
        <pre>{fmt.json({ quotes: state.quotes, fx: state.fx, seconds: state.seconds, revision: state.workspace_revision })}</pre>
        <p>{text.signalCaption}</p><p>{state.source_settings}</p>{state.errors.map((value, i) => <p key={i}>{value}</p>)}<pre>{fmt.json(state.signals)}</pre>
      </details>
    </>}
    <footer>{text.neverOrders}</footer>
  </main>;
}
