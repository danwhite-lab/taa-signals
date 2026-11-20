"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { authorizedResponse } from "../lib/api";
import text from "../content/strategy-health.json";
import * as fmt from "../lib/format";
import styles from "./strategy-health.module.css";

type Status = "normal" | "review" | "structural" | "insufficient";
type MetricKey = "drawdown" | "underwater" | "relative";
type Thresholds = typeof text.thresholdDefaults;
export type HealthInput = { sleeves?: { model: string; weight: number }[]; end?: string | null; checks_only?: boolean };
type Finding = { kind: string; status: Status; message: string; action?: string | null; rows?: Record<string, unknown>[] };
type Metric = { current: number | null; percentile: number | null; samples: number; status: Status; review_threshold: number; structural_threshold: number; review_value: number | null; structural_value: number | null; distribution: number[] };
type Report = { key: "cm" | "ic" | "combined"; status: Status; reason?: keyof typeof text | null; action: string; findings: Finding[]; as_of?: string; start?: string; peak?: string; models?: string[]; rolling?: { date: string; relative: number }[]; metrics: Partial<Record<MetricKey, Metric>> };
type Proxy = { model: string; underlying: string; holding: string; security: string | null; published_identifier: string | null; last_price_date: string | null; reason: string };
type Payload = { reports: Report[]; checks: { findings: Finding[]; proxies: Proxy[]; observations?: {model: string; asset: string; last_date: string | null; status: Status}[] }; reason?: keyof typeof text | null; weights?: { model: string; weight: number }[] };
const metricKeys: MetricKey[] = ["drawdown", "underwater", "relative"];
const thresholdKeys = ["review", "structural", "ic_review", "ic_structural"] as const;
const thresholdLabels = ["reviewPercentile", "structuralPercentile", "icReviewPercentile", "icStructuralPercentile"] as const;
const storageKey = "strategy-health-thresholds-v1";
const compactActions: Record<string, string> = { drawdown: text.shortDrawdown, underwater: text.shortUnderwater, relative: text.shortRelative, data: text.shortMissing };
const message = (key?: keyof typeof text | null) => key && typeof text[key] === "string" ? text[key] as string : text.insufficient;
const numeric = (value: number | null | undefined) => value !== null && value !== undefined && Number.isFinite(value);
function metricValue(key: MetricKey, value: number | null | undefined) {
  if (!numeric(value)) return text.insufficient;
  return key === "underwater" ? fmt.number(value!) : fmt.percent(-value!);
}
function validThresholds(value: Thresholds) {
  return thresholdKeys.every(key => Number.isFinite(value[key]) && value[key] > 0 && value[key] < 100)
    && value.review < value.structural && value.ic_review < value.ic_structural
    && value.ic_review <= value.review && value.ic_structural <= value.structural;
}

function Distribution({ metric, metricKey }: { metric: Metric; metricKey: MetricKey }) {
  if (!metric.distribution.length || !numeric(metric.current)) return null;
  const values = metric.distribution;
  const minimum = Math.min(values[0], metric.current!);
  const maximum = Math.max(values.at(-1)!, metric.current!);
  const position = (value: number) => 12 + (maximum === minimum ? .5 : (value - minimum) / (maximum - minimum)) * 376;
  return <figure className={styles.figure}>
    <figcaption>{text.distribution}</figcaption>
    <svg viewBox="0 0 400 65" role="img" aria-label={`${text[metricKey]} · ${text.current} ${metricValue(metricKey, metric.current)} · ${text.percentile} ${fmt.number(metric.percentile!)}`}>
      <line x1="12" x2="388" y1="28" y2="28" stroke="currentColor" opacity="0.2" />
      {values.map((value, index) => <line key={index} x1={position(value)} x2={position(value)} y1="20" y2="36" stroke="currentColor" opacity="0.18" />)}
      <line x1={position(metric.review_value!)} x2={position(metric.review_value!)} y1="12" y2="43" stroke="#a36a20"><title>{text.review}</title></line>
      <line x1={position(metric.structural_value!)} x2={position(metric.structural_value!)} y1="12" y2="43" stroke="#a33d37"><title>{text.structural}</title></line>
      <circle cx={position(metric.current!)} cy="28" r="5" fill="#17645f"><title>{text.current}</title></circle>
      <text x="12" y="60" fontSize="11" fill="currentColor">{metricValue(metricKey, minimum)}</text>
      <text x="388" y="60" textAnchor="end" fontSize="11" fill="currentColor">{metricValue(metricKey, maximum)}</text>
    </svg>
    <small>{text.current} ● · {text.review} {fmt.number(metric.review_threshold)} · {text.structural} {fmt.number(metric.structural_threshold)}</small>
  </figure>;
}

function Details({ report }: { report: Report }) {
  const rolling = report.rolling ?? [];
  const minimum = Math.min(0, ...rolling.map(row => row.relative));
  const maximum = Math.max(0, ...rolling.map(row => row.relative));
  const y = (value: number) => 15 + (maximum === minimum ? .5 : (maximum - value) / (maximum - minimum)) * 110;
  return <div>
    {report.start && <p>{text.window} {fmt.date(report.start)} – {fmt.date(report.as_of ?? "")}</p>}
    {report.models && <p>{report.models.join(" · ")}</p>}
    {report.peak && <p>{text.peak} {fmt.date(report.peak)}</p>}
    <div className={styles.metrics}>{metricKeys.map(key => {
      const metric = report.metrics[key];
      return <section key={key}><h4>{text[key]}</h4>
        <p>{metricValue(key, metric?.current)} · {text.percentile} {numeric(metric?.percentile) ? fmt.number(metric!.percentile!) : text.insufficient} · {text.observations} {metric?.samples ?? 0}</p>
        {metric && <Distribution metricKey={key} metric={metric} />}
      </section>;
    })}</div>
    {!!rolling.length && <figure className={styles.figure}><figcaption>{text.relative}</figcaption>
      <svg viewBox="0 0 400 155" role="img" aria-label={text.relative}>
        <line x1="12" x2="388" y1={y(0)} y2={y(0)} stroke="currentColor" opacity="0.3" />
        <polyline points={rolling.map((row, index) => `${12 + index / Math.max(1, rolling.length - 1) * 376},${y(row.relative)}`).join(" ")} stroke="#17645f" strokeWidth="2" fill="none" />
        <text x="12" y="13" fontSize="10" fill="currentColor">{fmt.percent(maximum)}</text>
        <text x="12" y="135" fontSize="10" fill="currentColor">{fmt.percent(minimum)}</text>
        <text x="12" y="152" fontSize="10" fill="currentColor">{fmt.date(rolling[0].date)}</text>
        <text x="388" y="152" textAnchor="end" fontSize="10" fill="currentColor">{fmt.date(rolling.at(-1)!.date)}</text>
      </svg>
    </figure>}
    {report.findings.length > 1 && <details><summary>{text.others}</summary>{report.findings.slice(1).map((finding, index) => <p key={index}>{finding.message} {finding.action}</p>)}</details>}
  </div>;
}

export default function StrategyHealth({ input = {}, automatic = false, compact = false }: { input?: HealthInput; automatic?: boolean; compact?: boolean }) {
  const [payload, setPayload] = useState<Payload | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [thresholds, setThresholds] = useState<Thresholds>(text.thresholdDefaults);
  const [draft, setDraft] = useState<Thresholds>(text.thresholdDefaults);
  const inFlight = useRef(false);
  async function run(policy = thresholds) {
    if (inFlight.current) return;
    inFlight.current = true; setBusy(true); setError("");
    try {
      const response = await authorizedResponse("/api/strategy-health", { method: "POST", body: JSON.stringify({ ...input, thresholds: policy }) });
      if (!response.ok) throw new Error(text.error);
      const next = await response.json() as Payload;
      if (!Array.isArray(next.reports) || !next.checks || !Array.isArray(next.checks.findings)) throw new Error(text.error);
      setPayload(next);
    } catch { setError(text.error); }
    finally { inFlight.current = false; setBusy(false); }
  }
  useEffect(() => {
    let stored = text.thresholdDefaults;
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey) ?? "null") as Thresholds | null;
      if (parsed && validThresholds(parsed)) stored = parsed;
    } catch { /* Browser storage is optional. */ }
    setThresholds(stored); setDraft(stored);
    if (automatic) void run(stored);
    // The parent keys this component by portfolio revision or backtest inputs.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const technical = payload?.checks.findings.find(finding => finding.status === "review");
  return <section className={`${styles.health} ${compact ? styles.compact : styles.expanded}`} id="strategy-health" aria-label={input.checks_only ? text.checks : text.title}>
    <h2>{input.checks_only ? text.checks : text.title}</h2>
    {!input.sleeves && <p>{text.defaultContext}</p>}
    {!input.checks_only && <p className={styles.note}>{compact ? text.compactNote : text.simulation}</p>}
    <button className="btn btn-secondary" disabled={busy} onClick={() => void run()}>{error ? text.retry : text.run}</button>
    {busy && <p role="status">{text.loading}</p>}
    {error && <p role="alert">{error}</p>}
    {payload?.reason && <p>{message(payload.reason)}</p>}
    {payload && <>
      {technical && <div className="signal-warning"><strong>{text.checks}</strong><p>{technical.message}</p><p>{text.suggested} · {technical.action ?? text.technicalAction}</p></div>}
      {!input.checks_only && <div className={styles.cards}>{payload.reports.map(report => <article key={report.key}>
        <header><h3>{text[report.key]}</h3><strong className={styles[report.status]}>{text[report.status]}</strong></header>
        {report.as_of && <small>{text.asOf} {fmt.date(report.as_of ?? "")}</small>}
        <dl>{metricKeys.map(key => <div key={key}><dt title={text[key]}>{compact ? text.metricShorts[key] : text[key]}</dt><dd>{metricValue(key, report.metrics[key]?.current)}</dd></div>)}</dl>
        {report.reason && <p>{message(report.reason)}</p>}
        {!compact && report.findings[0] && <p>{report.findings[0].message}</p>}
        <p><strong>{text.suggested}</strong> {compact
          ? compactActions[report.findings[0]?.kind ?? ""] ?? (report.status === "normal" ? text.shortMonitor : text.shortMissing)
          : report.action}</p>
        <details><summary>{text.details}</summary><Details report={report} /></details>
      </article>)}</div>}
      <details open={input.checks_only}><summary>{text.checks}</summary><p>{text.checksNote}</p><p>{text.historicalCheck}</p>
        {payload.checks.findings.map((finding, index) => <div key={index}><p><strong>{text[finding.status]}</strong> · {finding.message}</p>{finding.action && <p>{text.suggested} · {finding.action}</p>}
          {finding.rows && <div className="signal-table-scroll"><table aria-label={text.holdings}><thead><tr><th>{text.mapping}</th><th>{text.reference}</th><th>{text.current}</th></tr></thead><tbody>{finding.rows.map((row, i) => <tr key={i}><td>{String(row.Fund ?? row.id)}</td><td>{numeric(row["Target %"] as number) ? fmt.percent(row["Target %"] as number) : text.insufficient}</td><td>{numeric(row["Actual %"] as number) ? fmt.percent(row["Actual %"] as number) : text.insufficient}</td></tr>)}</tbody></table></div>}
        </div>)}
        {!!payload.checks.observations?.length && <><h3>{text.inputDates}</h3><p>{text.inputDateNote}</p><div className="signal-table-scroll"><table aria-label={text.inputDates}><thead><tr><th>{text.asset}</th><th>{text.date}</th><th>{text.title}</th></tr></thead><tbody>{payload.checks.observations.map((row, index) => <tr key={index}><td>{row.model} · {row.asset}</td><td>{row.last_date ? fmt.date(row.last_date) : text.insufficient}</td><td>{text[row.status]}</td></tr>)}</tbody></table></div></>}
        <h3>{text.tracking}</h3>
        {!payload.checks.proxies.length && <p>{text.noLocal}</p>}
        {payload.checks.proxies.map((proxy, index) => <p key={index}>{proxy.model} · {proxy.underlying} → {proxy.holding} ({proxy.security}) · {proxy.last_price_date ? fmt.date(proxy.last_price_date) : text.insufficient}. {proxy.reason}</p>)}
      </details>
    </>}
    {!input.checks_only && <details><summary>{text.configure}</summary><p>{text.limits}</p><p>{text.thresholdStored}</p>
      <form onSubmit={event => {
        event.preventDefault();
        if (!validThresholds(draft)) { setError(text.invalidThresholds); return; }
        setThresholds(draft);
        try { localStorage.setItem(storageKey, JSON.stringify(draft)); } catch { /* This visit still uses the chosen thresholds. */ }
        void run(draft);
      }}><div className={styles.thresholds}>{thresholdKeys.map((key, index) => <label key={key}>{text[thresholdLabels[index]]}<input type="number" step="0.1" min="0.1" max="99.9" required value={draft[key]} disabled={busy} onChange={event => setDraft(previous => ({ ...previous, [key]: event.target.valueAsNumber }))} /></label>)}</div>
      <button className="btn btn-secondary" disabled={busy} type="submit">{text.apply}</button></form>
      <p>{text.method}</p><p>{text.sample}</p><p>{text.weights}</p>
      {payload?.weights && <ul>{payload.weights.map((sleeve, index) => <li key={index}>{sleeve.model} · {fmt.percent(sleeve.weight / 100)}</li>)}</ul>}
    </details>}
    {compact && <Link href="/backtest/?health=default#strategy-health">{text.open}</Link>}
  </section>;
}
