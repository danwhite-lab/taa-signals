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

export default function RulesPage() {
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
          setContent(data);
          setSelected((previous) => data.models.some((model) => model.label === previous) ? previous : data.models[0].label);
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
        <p className="eyebrow">Strategy methodology</p>
        <h1>Rules</h1>
        <p className="lede">The same strategy descriptions as the Streamlit app, read from one shared source.</p>
      </div>
      {error && <section role="alert" className="rules-error">
        <h2>Rules could not be loaded</h2>
        <pre>{error}</pre>
        <button onClick={() => setAttempt((value) => value + 1)}>Try again</button>
      </section>}
      {!content && !error && <p role="status">Loading methodology…</p>}
      {content && model && <>
        <div className="rule-picker">
          <label htmlFor="rule-model">Strategy implementation</label>
          <select id="rule-model" value={selected} onChange={(event) => setSelected(event.target.value)}>
            {content.models.map((item) => <option key={item.label} value={item.label}>{item.label}</option>)}
          </select>
        </div>
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
      <footer>Migration preview · Only Rules is available in the navigation. Other pages have not been migrated.</footer>
    </main>
  );
}
