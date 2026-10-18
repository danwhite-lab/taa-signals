"use client";

import { useEffect, useState } from "react";

type Strategy = {
  label: string;
  strategy: string;
  variant: string | null;
  implementation: string;
  execution_currency: string;
};

export default function Home() {
  const [strategies, setStrategies] = useState<Strategy[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setFailed(false);
    setStrategies(null);

    async function load() {
      try {
        const response = await fetch("/api/strategies", {
          signal: controller.signal,
          cache: "no-store",
        });
        if (!response.ok) throw new Error("Catalogue request failed");
        const data: unknown = await response.json();
        if (
          !Array.isArray(data) ||
          !data.every(
            (item) =>
              item &&
              typeof item.label === "string" &&
              typeof item.strategy === "string" &&
              typeof item.implementation === "string" &&
              typeof item.execution_currency === "string",
          )
        ) {
          throw new Error("Invalid catalogue response");
        }
        setStrategies(data as Strategy[]);
      } catch {
        if (!controller.signal.aborted) setFailed(true);
      }
    }

    void load();
    return () => controller.abort();
  }, [attempt]);

  return (
    <main>
      <header>
        <p className="eyebrow">TAA Signals · Migration preview</p>
        <h1>Strategy catalogue</h1>
        <p>The existing Python engine, connected to a new front end.</p>
      </header>

      <section aria-labelledby="catalogue-heading" aria-busy={!strategies && !failed}>
        <h2 id="catalogue-heading">Available strategies</h2>
        {!strategies && !failed && <p role="status">Loading strategies…</p>}
        {failed && (
          <div role="alert">
            <p>Could not load strategies. Check that the API is running.</p>
            <button type="button" onClick={() => setAttempt((value) => value + 1)}>
              Try again
            </button>
          </div>
        )}
        {strategies && (
          <>
            <p className="count" role="status">{strategies.length} implementations from the Python catalogue</p>
            <ul>
              {strategies.map((item) => (
                <li key={item.label}>
                  <span>{item.label}</span>
                  <span className="currency">{item.execution_currency}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </section>
      <footer>Read-only skeleton. No login, holdings or backtests on this page yet.</footer>
    </main>
  );
}
