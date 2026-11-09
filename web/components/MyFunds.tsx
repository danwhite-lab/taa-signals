"use client";

import { useEffect, useId, useState } from "react";
import { registryResponseMessage } from "../lib/my-funds-errors";
import { authorizedResponse } from "../lib/api";
import { type ModelOption, type RegisteredFund } from "../lib/picker-display";
import words from "../content/my-funds.json";
import styles from "./search-picker.module.css";

type Quote = { price: string; as_of: string; source: string };
type Preview = { fund: RegisteredFund; quote: Quote };
const paths = { list: "/api/my-funds", check: "/api/my-funds/check" };

async function request<T>(path: string, input?: object): Promise<T> {
  const response = await authorizedResponse(path, input ? { method: "POST", body: JSON.stringify(input) } : {});
  if (!response.ok) {
    const registryError = await registryResponseMessage(response);
    if (registryError) throw new Error(registryError);
    // Registry validation messages are fixed provider-safe text.
    const value = response.status === 422 || response.status === 409
      ? await response.json().catch(() => null) : null;
    throw new Error(typeof value?.detail === "string" ? value.detail : words.failed);
  }
  return response.json() as Promise<T>;
}

export function asModel(fund: RegisteredFund): ModelOption & { execution_currency: string } {
  return { label: fund.model, strategy: "Buy and Hold", variant: fund.name,
    implementation: fund.market === "TASE" ? "Israel" : fund.exchange,
    execution_currency: fund.currency, fund };
}

export function useMyFunds(enabled: boolean) {
  const [funds, setFunds] = useState<RegisteredFund[]>();
  const [configured, setConfigured] = useState(false);
  const [error, setError] = useState("");
  const [rejected, setRejected] = useState(0);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled || funds !== undefined) return;
    let live = true;
    void request<{ funds: RegisteredFund[]; configured: boolean; rejected: number }>(paths.list)
      .then(data => { if (live) { setConfigured(data.configured); setFunds(data.funds); setRejected(data.rejected); } })
      .catch(problem => { if (live) setError(problem instanceof Error ? problem.message : words.failed); });
    return () => { live = false; };
  }, [enabled, funds, attempt]);
  return { funds, configured, error, rejected, retry: () => { setError(""); setAttempt(n => n + 1); },
    update: (fund: RegisteredFund) => setFunds(previous => [...(previous ?? []).filter(row => row.model !== fund.model), fund]) };
}

export function FundRegistration({ market, state, onChange }: {
  market: "TASE" | "Global"; state: ReturnType<typeof useMyFunds>; onChange: (fund: RegisteredFund) => void;
}) {
  const id = useId();
  const [identifier, setIdentifier] = useState("");
  const [preview, setPreview] = useState<Preview>();
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function run(work: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try { await work(); } catch (problem) { setError(problem instanceof Error ? problem.message : words.failed); }
    finally { setBusy(false); }
  }
  if (state.error) return <p role="alert">{state.error} <button type="button" className="btn btn-secondary" onClick={state.retry}>{words.retry}</button></p>;
  if (!state.funds) return <p role="status">{words.loading}</p>;
  if (!state.configured) return <p>{words.unconfigured}</p>;
  return <div className={styles.detailBody}>
    {state.rejected > 0 && <p className="signal-warning" role="alert">{words.rejectedRows}</p>}
    <label htmlFor={id}>{market === "TASE" ? words.securityNumber : words.yahooTicker}</label>
    <div className={`${styles.filters} ${styles.fundEntry}`}>
      <input id={id} value={identifier} inputMode={market === "TASE" ? "numeric" : "text"} maxLength={market === "TASE" ? 7 : 24}
        disabled={busy} onChange={event => { setIdentifier(event.target.value); setPreview(undefined); setError(""); setMessage(""); }} />
      <button className="btn btn-secondary" type="button" disabled={busy || !identifier.trim()} onClick={() => void run(async () => {
        setPreview(undefined);
        setPreview(await request<Preview>(paths.check, { market, identifier }));
      })}>{words.check}</button>
    </div>
    {busy && <p role="status">{words.checking}</p>}
    {error && <p role="alert">{error}</p>}
    {message && <p role="status">{message}</p>}
    {preview && <div>
      <p><strong>{preview.fund.name}</strong> · {preview.fund.identifier}{preview.fund.isin && ` · ${preview.fund.isin}`}</p>
      <p>{preview.fund.kind === "mutual" ? words.mutual : words.etf} · {preview.quote.price} {preview.fund.currency} · {preview.quote.as_of}</p>
      <p>{preview.quote.source}</p>
      {preview.fund.fx && <p>{preview.fund.fx.source} · {preview.fund.fx.price} · {preview.fund.fx.as_of}</p>}
      <button className="btn btn-primary" type="button" disabled={busy} onClick={() => void run(async () => {
        onChange(await request<RegisteredFund>(paths.list, { market, identifier: preview.fund.identifier, name: preview.fund.name }));
        setPreview(undefined); setIdentifier(""); setMessage(words.added);
      })}>{words.confirm}</button>
    </div>}
  </div>;
}

export function ArchiveFund({ fund, onChange }: { fund: RegisteredFund; onChange: (fund: RegisteredFund) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(false);
  return <>
    <p>{words.archiveCaption}</p>
    <button className="btn btn-secondary" type="button" disabled={busy} onClick={async () => {
      setBusy(true); setError(false);
      try {
        await request(`${paths.list}/${encodeURIComponent(fund.model.slice("MY-FUND-".length))}/archive`, {});
        onChange({ ...fund, archived: true });
      } catch { setError(true); } finally { setBusy(false); }
    }}>{busy ? words.archiving : words.archive}</button>
    {error && <p role="alert">{words.failed}</p>}
  </>;
}
