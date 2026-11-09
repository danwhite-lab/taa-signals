"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import words from "../content/pickers.json";
import { fundChoice, type FundIdentity, isKnownModel, loadPickerMetadata, matchingChoices, modelChoice, type Choice, type Metadata, type ModelOption } from "../lib/picker-display";
import styles from "./search-picker.module.css";

const pageSize = 10;
const implementationFilters = [{ key: "israel", label: words.israel }, { key: "originals", label: words.originals }];

export function usePickerMetadata(enabled: boolean) {
  const [value, setValue] = useState<Metadata>();
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!enabled) return;
    let live = true;
    void loadPickerMetadata().then(data => { if (live) setValue(data); })
      .catch(() => { if (live) setFailed(true); });
    return () => { live = false; };
  }, [enabled, attempt]);
  return { value, failed, retry: () => { setFailed(false); setAttempt(value => value + 1); } };
}

export function MetadataStatus({ state }: { state: ReturnType<typeof usePickerMetadata> }) {
  return state.failed ? <p role="alert">{words.metadataError} <button type="button" className="btn btn-secondary" onClick={state.retry}>{words.retry}</button></p>
    : state.value ? null : <p role="status">{words.loading}</p>;
}

export function ChoiceLabel({ choice }: { choice: Choice }) {
  return <span className={styles.name}>{choice.name}{choice.secondary && <>{" "}<small>{choice.secondary}</small></>}</span>;
}

export function ActualFundLabel({ fund }: { fund: FundIdentity }) {
  return <ChoiceLabel choice={fundChoice(fund)} />;
}

export function ChoiceDetails({ children }: { children: ReactNode }) {
  return <details className={styles.details}><summary>{words.details}</summary>
    <div className={styles.detailBody}>{children}</div>
  </details>;
}

type ResultsProps = {
  choices: Choice[]; selected: string[]; onSelect: (key: string) => void; searchLabel: string;
  multi?: boolean; browse?: boolean; modelFilters?: boolean; autoFocus?: boolean; busy?: boolean; filtersContent?: ReactNode; details?: (key: string) => ReactNode;
};

export function SearchResults({ choices, selected, onSelect, searchLabel, multi, browse, modelFilters, autoFocus, busy, filtersContent, details }: ResultsProps) {
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("");
  const [page, setPage] = useState(0);
  const field = useRef<HTMLInputElement>(null);
  const results = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => { if (autoFocus) field.current?.focus(); }, [autoFocus]);

  const matched = matchingChoices(choices, query, filter);
  const pages = Math.max(1, Math.ceil(matched.length / pageSize));
  const activePage = Math.min(page, pages - 1);
  const visible = matched.slice(activePage * pageSize, (activePage + 1) * pageSize);
  const filters = modelFilters ? implementationFilters.filter(option => choices.some(choice => choice.filter === option.key)) : [];
  function move(event: KeyboardEvent, current: number) {
    if (!["ArrowDown", "ArrowUp", "Enter"].includes(event.key)) return;
    if (event.key === "Enter" && current < 0) { event.preventDefault(); return; }
    const buttons = results.current?.querySelectorAll<HTMLElement>("[data-picker-option]");
    if (!buttons?.length) return;
    event.preventDefault();
    if (event.key === "Enter") { buttons[current]?.click(); return; }
    const next = event.key === "ArrowDown" ? current + 1 : current < 0 ? buttons.length - 1 : current - 1;
    if (next < 0) field.current?.focus();
    else buttons[next % buttons.length]?.focus();
  }
  return <div className={styles.results}>
    <label className={styles.search} htmlFor={id}>{searchLabel}
      <input ref={field} id={id} type="search" value={query}
        onChange={event => { setQuery(event.target.value); setPage(0); }}
        onKeyDown={event => move(event, -1)} />
    </label>
    {filters.length > 1 && <div role="group" aria-label={words.implementation} className={styles.filters}>
      {[{ key: "", label: words.all }, ...filters].map(option => <button type="button" key={option.key}
        className="btn btn-secondary" aria-pressed={filter === option.key}
        onClick={() => { setFilter(option.key); setPage(0); }}>{option.label}</button>)}
    </div>}
    {filtersContent}
    <p className={styles.count} role="status">{matched.length === 1 ? words.oneMatch : words.count.replace("{count}", String(matched.length))}</p>
    {!busy && matched.length === 0 && <p>{words.noMatches}</p>}
    <div ref={results} role="group" aria-label={searchLabel}>
      {visible.map((choice, index) => {
        const checked = selected.includes(choice.key);
        const usesFamilyHeading = choice.family === choice.name && !!choice.secondary;
        const rowChoice = usesFamilyHeading ? { ...choice, name: choice.secondary!, secondary: undefined } : choice;
        const accessibleName = usesFamilyHeading ? `${choice.name} ${choice.secondary}` : undefined;
        return <div key={choice.key}>
          {choice.family && choice.family !== visible[index - 1]?.family && <h3 className={styles.family}>{choice.family}</h3>}
          <div className={styles.result}>
            {multi ? <label className={styles.check}>
              <input aria-label={accessibleName} data-picker-option type="checkbox" value={choice.key} checked={checked} onChange={() => onSelect(choice.key)}
                onKeyDown={event => move(event, index)} />
              <ChoiceLabel choice={rowChoice} />
            </label> : <button type="button" data-picker-option className={styles.option} aria-label={accessibleName} aria-pressed={browse ? checked : undefined}
              onClick={() => onSelect(choice.key)} onKeyDown={event => move(event, index)}><ChoiceLabel choice={rowChoice} /></button>}
            {details?.(choice.key)}
          </div>
        </div>;
      })}
    </div>
    {pages > 1 && <div className={styles.filters}>
      <button type="button" className="btn btn-secondary" disabled={activePage === 0} onClick={() => setPage(activePage - 1)}>{words.previous}</button>
      <span>{words.page.replace("{page}", String(activePage + 1)).replace("{pages}", String(pages))}</span>
      <button type="button" className="btn btn-secondary" disabled={activePage + 1 === pages} onClick={() => setPage(activePage + 1)}>{words.next}</button>
    </div>}
  </div>;
}

const seriesText = (series: NonNullable<Metadata["models"][string]["signal"]>[number]) =>
  [...new Set([series.name, series.identifier, series.type, series.source, series.currency ?? `${words.seriesCurrency}: ${words.notSpecified}`].filter(Boolean))].join(" · ");

export function FundFacts({ fund, quoteCurrency }: { fund?: Metadata["funds"][string]; quoteCurrency?: string }) {
  return <dl className={styles.facts}>
    <dt>{words.fullName}</dt><dd>{fund?.full_name ?? words.notVerified}</dd>
    <dt>{words.tracks}</dt><dd>{fund?.tracks ?? words.notSpecified}</dd>
    <dt>{words.quoteCurrency}</dt><dd>{fund?.currency ?? quoteCurrency ?? words.notVerified}</dd>
    <dt>{words.seriesCurrency}</dt><dd>{fund?.underlying_currency ?? words.notSpecified}</dd>
    <dt>{words.domicile}</dt><dd>{fund?.domicile ?? words.notVerified}</dd>
    <dt>{words.ucits}</dt><dd>{fund?.ucits === true ? words.yes : words.notVerified}</dd>
    {fund?.source && <><dt>{words.source}</dt><dd>{fund.source}</dd></>}
  </dl>;
}

export function ModelFacts({ label, metadata }: { label: string; metadata?: Metadata }) {
  const entry = metadata?.models[label];
  return <ChoiceDetails>
    <dl className={styles.facts}>
      <dt>{words.held}</dt><dd>{entry?.held?.length ? <ul>{entry.held.map(id => {
        const fund = metadata?.funds[id];
        return <li key={id}>{fund ? <ActualFundLabel fund={{ ...fund, label: fund.name }} /> : id}</li>;
      })}</ul> : entry?.held ? words.notApplicable : words.notSpecified}</dd>
      <dt>{words.signal}</dt><dd>{entry?.signal?.length ? <ul>{entry.signal.map(series => <li key={series.identifier}>{seriesText(series)}</li>)}</ul>
        : entry?.signal ? words.notApplicable : words.notSpecified}</dd>
      {entry?.proxies.length ? <><dt>{words.proxy}</dt><dd><ul>{entry.proxies.map((proxy, index) => <li key={index}>{seriesText(proxy.series)}. {proxy.note}</li>)}</ul></dd></> : null}
      {entry?.benchmark && <><dt>{words.benchmark}</dt><dd>{seriesText(entry.benchmark)}</dd></>}
      {entry?.source && <><dt>{words.source}</dt><dd>{entry.source}</dd></>}
    </dl>
    {entry?.notes && <p>{entry.notes}</p>}
  </ChoiceDetails>;
}

export function ModelResults({ models, selected, onSelect, multi, browse, autoFocus }: {
  models: ModelOption[]; selected: string[]; onSelect: (key: string) => void; multi?: boolean; browse?: boolean; autoFocus?: boolean;
}) {
  const metadata = usePickerMetadata(true);
  return <>
    <MetadataStatus state={metadata} />
    <SearchResults choices={models.map(model => modelChoice(model, metadata.value))} selected={selected} onSelect={onSelect}
      searchLabel={words.searchModels} multi={multi} browse={browse} autoFocus={autoFocus} modelFilters busy={!metadata.value && !metadata.failed}
      details={key => <ModelFacts label={key} metadata={metadata.value} />} />
  </>;
}

type PickerProps = {
  value: string; onSelect: (key: string) => void; disabled?: boolean; onOpen?: () => void;
  loading?: boolean; error?: string; retry?: () => void; retryLabel?: string; caption?: string;
} & ({ models: ModelOption[]; choices?: never } | { choices: Choice[]; models?: never });

export default function SearchPicker({ value, onSelect, disabled, onOpen, loading, error, retry, retryLabel, caption, models, choices }: PickerProps) {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement>(null);
  const selected = models ? models.find(option => option.label === value) : choices?.find(option => option.key === value);
  const choice = selected ? "label" in selected ? modelChoice(selected) : selected
    : models && loading && isKnownModel(value) ? modelChoice({ label: value }) : null;
  function close() { setOpen(false); opener.current?.focus(); }
  function choose(key: string) { if (key !== value) onSelect(key); close(); }
  return <div className={styles.picker} onKeyDown={event => {
    if (open && event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
  }}>
    <div className={styles.selected}>
      {choice ? <ChoiceLabel choice={choice} /> : value ? <ChoiceLabel choice={{ key: value, name: value, secondary: loading ? undefined : words.unavailable }} /> : null}
      <button className="btn btn-secondary" ref={opener} type="button" disabled={disabled} aria-expanded={open}
        onClick={() => { if (open) close(); else { setOpen(true); onOpen?.(); } }}>
        {value ? words.change : caption ?? words.chooseModel}
      </button>
    </div>
    {open && <div className={styles.panel}>
      {error ? <p role="alert">{error} {retry && <button type="button" className="btn btn-secondary" onClick={retry}>{retryLabel ?? words.retry}</button>}</p>
        : loading ? <p role="status">{words.loading}</p>
        : models ? <ModelResults models={models} selected={[value]} onSelect={choose} autoFocus />
        : <SearchResults choices={choices ?? []} selected={[value]} onSelect={choose} autoFocus searchLabel={words.searchProxies}
          details={key => <ChoiceDetails><p>{choices?.find(choice => choice.key === key)?.aliases?.[0]}</p></ChoiceDetails>} />}
      <button className="btn btn-secondary" type="button" onClick={close}>{words.cancel}</button>
    </div>}
  </div>;
}
