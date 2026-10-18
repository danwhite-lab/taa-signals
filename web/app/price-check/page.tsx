"use client";

import { useState } from "react";

function readable(value: unknown): string {
  if (value === null) return "Not available";
  if (Array.isArray(value)) return value.map(readable).join("\n\n");
  if (typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${key.replaceAll("_", " ")}: ${readable(item)}`)
      .join("\n");
  }
  return String(value);
}

export default function PriceCheck() {
  const [output, setOutput] = useState("");
  const [running, setRunning] = useState(false);

  async function runChecks() {
    setRunning(true);
    setOutput("");
    try {
      const response = await fetch("/api/price-check", { cache: "no-store" });
      const body = await response.text();
      if (!response.ok) {
        setOutput(`HTTP ${response.status} ${response.statusText}\n${body}`);
        return;
      }
      try {
        setOutput(readable(JSON.parse(body)));
      } catch (error) {
        setOutput(`Response parsing failed: ${String(error)}\nRaw response:\n${body}`);
      }
    } catch (error) {
      setOutput(error instanceof Error ? `${error.name}: ${error.message}\n${error.stack ?? ""}` : String(error));
    } finally {
      setRunning(false);
    }
  }

  return (
    <main>
      <a href="/">Strategy catalogue</a>
      <h1>Price check</h1>
      <p>Live checks for SPY, QQQ, VXUS, TASE 1159250 (CSPX), 1187079 and 5134713.</p>
      <p>Also calculates or retrieves a data-versioned cached result for the original USD A-RVol V3 daily backtest.
        This is a diagnostic, not a trading quote. It may take several minutes.</p>
      <p>Press once to run. Prices are checked live. Backtest cache status, data source and original calculation timings are shown below. No automatic polling, retries or proxy history.</p>
      <button type="button" disabled={running} onClick={() => void runChecks()}>
        {running ? "Running live checks…" : "Run live checks"}
      </button>
      {running && <p role="status">Waiting for providers and the backtest. Any returned errors will appear below.</p>}
      <pre role="log" aria-live="polite" style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", lineHeight: 1.6 }}>
        {output || (!running ? "No checks run yet." : "")}
      </pre>
    </main>
  );
}
