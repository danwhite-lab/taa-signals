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
  risk_warning: string | null;
  description_missing: boolean;
};

type RulesResponse = { models: ModelRules[]; implementation_notes: string; source: string };

export default function StrategyCataloguePage() {
  const [content, setContent] = useState<RulesResponse | null>(null);
  const [selected, setSelected] = useState("");
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);

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

  const model = content?.models.find((item) => item.label === selected);

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
      {content && model && <>
        <ul className="rule-list" aria-label="Strategies">
          {content.models.map((item) => <li key={item.label}>
            <button className={`btn list-row${selected === item.label ? " is-selected" : ""}`} type="button" aria-pressed={selected === item.label} onClick={() => setSelected(item.label)}>
              {item.label} <span className="currency">{item.execution_currency}</span>
            </button>
          </li>)}
        </ul>
        <section className="rule-card" aria-labelledby="model-heading">
          <div className="rule-meta"><span>{model.execution_currency}</span><span>{model.implementation}</span></div>
          <h2 id="model-heading">{model.label}</h2>
          {model.description_missing || model.markdown === null
            ? <p className="missing-rule" role="status">This implementation has no rule description in the existing Streamlit source. No substitute text has been added.</p>
            : <div className="rule-copy"><Markdown>{model.markdown}</Markdown></div>}
        </section>
        {model.risk_warning && <aside className="rule-warning" aria-label="Risk and implementation warning">
          <div className="rule-copy"><Markdown>{model.risk_warning}</Markdown></div>
        </aside>}
        {content.implementation_notes && <details className="rule-notes">
          <summary>Implementation and data notes</summary>
          <div className="rule-copy"><Markdown>{content.implementation_notes}</Markdown></div>
        </details>}
      </>}
    </main>
  );
}
