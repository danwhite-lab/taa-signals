"use client";

import { useEffect, useState } from "react";
import Markdown from "react-markdown";

type ModelRules = {
  label: string;
  strategy: string;
  variant: string | null;
  implementation: string;
  execution_currency: string;
  markdown: string | null;
  plain_text?: string | null;
  plain_flags?: string[];
  risk_warning: string | null;
  description_missing: boolean;
};

type RulesResponse = { models: ModelRules[]; implementation_notes: string; source: string };

export default function StrategyCataloguePage() {
  const [content, setContent] = useState<RulesResponse | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [view, setView] = useState<"plain" | "technical">("plain");
  const [filter, setFilter] = useState("All");

  useEffect(() => {
    try {
      if (localStorage.getItem("catalogue-view") === "technical") setView("technical");
    } catch { /* Storage can be unavailable; Plain remains the default. */ }
  }, []);

  function chooseView(value: "plain" | "technical") {
    setView(value);
    try { localStorage.setItem("catalogue-view", value); } catch { /* The toggle still works without storage. */ }
  }

  useEffect(() => {
    const controller = new AbortController();
    setError("");
    async function load() {
      try {
        const response = await fetch("/api/rules", { signal: controller.signal, cache: "no-store" });
        const text = await response.text();
        if (!response.ok) throw new Error(`HTTP ${response.status}: ${text}`);
        const data = JSON.parse(text) as RulesResponse;
        if (!Array.isArray(data.models) || !data.models.length || typeof data.implementation_notes !== "string"
          || !data.models.every((model) => typeof model.label === "string"
            && (model.markdown === null || typeof model.markdown === "string"))) {
          throw new Error("The rules API returned an invalid response.");
        }
        if (!controller.signal.aborted) {
          const models = [...data.models].sort((a, b) => a.label.localeCompare(b.label, "en", { sensitivity: "base" }));
          setContent({ ...data, models });
          setSelected((previous) => models.some((model) => model.label === previous) ? previous : models[0].label);
        }
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : String(failure));
      }
    }
    void load();
    return () => controller.abort();
  }, [attempt]);

  const visible = content?.models.filter(item => filter === "All" || item.execution_currency === (filter === "Israel" ? "ILS" : "USD")) ?? [];
  const model = visible.find(item => item.label === selected) ?? visible[0];
  const plain = view === "plain" && Boolean(model?.plain_text);
  const copy = plain ? model?.plain_text : model?.markdown;

  return (
    <main className="rules-page" id="main-content">
      <div className="rules-heading">
        <p className="eyebrow">Strategy Catalogue</p>
        <h1>Strategy Catalogue</h1>
        <p className="lede">Browse strategy rules and implementation details.</p>
      </div>
      {error && <section role="alert" className="rules-error">
        <h2>Strategy Catalogue could not be loaded</h2>
        <pre>{error}</pre>
        <button className="btn btn-secondary" onClick={() => setAttempt((value) => value + 1)}>Try again</button>
      </section>}
      {!content && !error && <p role="status">Loading methodology…</p>}
      {content && <div className="catalogue-layout">
        <div className="catalogue-sidebar">
        <fieldset className="segmented" aria-label="Execution market"><legend>Execution market</legend>
          {["All", "Israel", "US"].map(value => <label className="segment" key={value}><input type="radio" name="catalogue-filter" checked={filter === value} onChange={() => {
            setFilter(value);
            const first = content.models.filter(item => value === "All" || item.execution_currency === (value === "Israel" ? "ILS" : "USD"));
            if (!first.some(item => item.label === selected)) setSelected(first[0]?.label ?? "");
          }} />{value}</label>)}
        </fieldset>
        <p className="assumption-hint" role="status">{visible.length} strategies</p>
        <ul className="rule-list" aria-label="Strategies">
          {visible.map((item) => <li key={item.label}>
            <button className={`btn list-row${model?.label === item.label ? " is-selected" : ""}`} type="button" aria-pressed={model?.label === item.label} onClick={() => setSelected(item.label)}>
              {item.label} <span className="currency">{item.execution_currency}</span>
            </button>
          </li>)}
        </ul>
        </div>
        <div className="catalogue-detail">
        <fieldset className="segmented" aria-label="Rule view"><legend>Rule view</legend>
          {(["plain", "technical"] as const).map(value => <label className="segment" key={value}><input type="radio" name="catalogue-view" checked={view === value} onChange={() => chooseView(value)} />{value === "plain" ? "Plain" : "Technical"}</label>)}
        </fieldset>
        {!model && <p>No strategies in this filter.</p>}
        {model && <>
        <section className="rule-card" aria-labelledby="model-heading">
          <div className="rule-meta"><span>{model.execution_currency}</span><span>{model.implementation}</span></div>
          <h2 id="model-heading">{model.label}</h2>
          {!copy
            ? <p className="missing-rule" role="status">This implementation has no rule description in the existing Streamlit source. No substitute text has been added.</p>
            : <div className="rule-copy"><Markdown>{copy}</Markdown></div>}
          {view === "plain" && <>
            {!plain && <p className="assumption-hint">No plain version yet</p>}
            <p className="assumption-hint">Simplified. The Technical view has the exact numbers.</p>
            {plain && Boolean(model.plain_flags?.length) && <ul className="plain-flags" aria-label="Plain-language notes">
              {model.plain_flags?.map(flag => <li key={flag}>{flag}</li>)}
            </ul>}
          </>}
        </section>
        {model.risk_warning && <aside className="rule-warning" aria-label="Risk and implementation warning">
          <div className="rule-copy"><Markdown>{model.risk_warning}</Markdown></div>
        </aside>}
        {content.implementation_notes && <details className="rule-notes">
          <summary>Implementation and data notes</summary>
          <div className="rule-copy"><Markdown>{content.implementation_notes}</Markdown></div>
        </details>}
        </>}
        </div>
      </div>}
    </main>
  );
}
