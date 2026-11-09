import labels from "../content/picker-labels.json";
import words from "../content/pickers.json";
import { byLabel } from "./ui-order";

export type RegisteredFund = {
  model: string; name: string; market: "TASE" | "Global"; identifier: string; currency: string;
  kind: "etf" | "mutual"; exchange?: string; isin?: string; archived: boolean;
  fx?: { price: string; as_of: string; source: string };
};

export type ModelOption = {
  label: string;
  fund?: RegisteredFund;
  strategy?: string;
  variant?: string | null;
  implementation?: string;
  execution_currency?: string;
};
type ModelLabel = { name: string; family: string; version: string[]; filter: string };
type FundLabel = { name: string; labels: string[] };
const models: Record<string, ModelLabel> = labels.models;
const funds: Record<string, FundLabel> = labels.funds;

export type FundIdentity = { id: string; label: string; market: string; identifier: string; currency: string };
export type FundDetails = FundIdentity & {
  name: string; full_name: string | null; ticker: string | null; security_number: string | null;
  aliases: string[]; provider_identifiers: string[]; tracks: string | null; underlying_currency: string | null;
  domicile: string | null; ucits: boolean | null; source: string;
};
type Series = { identifier: string; name: string | null; type: string; source: string; currency: string | null; aliases: string[] };
type Proxy = { series: Series; note: string };
type ModelDetails = {
  held: string[] | null; signal: Series[] | null; benchmark: Series | null;
  proxies: Proxy[]; notes: string | null; source: string;
};
export type Metadata = { models: Record<string, ModelDetails>; funds: Record<string, FundDetails> };

let metadata: Promise<Metadata> | undefined;
export function loadPickerMetadata() {
  metadata ??= import("../content/picker-metadata.json")
    .then(module => module.default as Metadata)
    .catch(error => { metadata = undefined; throw error; });
  return metadata;
}

export const isKnownModel = (key: string) => Object.hasOwn(models, key);

export function modelDisplay(value: ModelOption) {
  if (value.fund) return { name: value.fund.name, family: words.buyAndHold,
    version: [value.fund.identifier, value.fund.currency], filter: value.fund.market === "TASE" ? "israel" : "originals" };
  return isKnownModel(value.label) ? models[value.label] : {
    name: value.strategy || value.label, family: value.strategy || words.other,
    version: [...new Set([value.variant, value.implementation].filter((part): part is string => !!part))],
    filter: value.implementation === "Israel" ? "israel" : value.implementation ? "originals" : undefined,
  };
}

export function modelCaption(label: string) {
  if (!isKnownModel(label)) return label;
  const {name, version} = models[label];
  return [name, ...version].join(" · ");
}

export function fundName(id: string, savedLabel: string) {
  const entry = Object.hasOwn(funds, id) ? funds[id] : undefined;
  return entry?.labels.includes(savedLabel) ? entry.name : savedLabel;
}

export function fundIdentity(value: FundIdentity, details?: FundDetails) {
  return [...new Set([value.identifier, details?.ticker, value.market, value.currency].filter(Boolean))].join(" · ");
}

export type Choice = {
  key: string; name: string; family?: string; secondary?: string;
  filter?: string; tabs?: string[]; aliases?: (string | null | undefined)[];
};

const seriesAliases = (series: Series) => [series.identifier, series.name, ...series.aliases];

export function modelChoice(value: ModelOption, metadata?: Metadata): Choice {
  const label = modelDisplay(value);
  const individual = label.family.toLowerCase() === "buy and hold" || value.strategy === "Buy and Hold";
  const tabs = individual ? [label.filter === "israel" ? "tase" : "global"]
    : ["strategies", ...(label.filter === "israel" ? ["israel"] : [])];
  const details = metadata?.models[value.label];
  const held = details?.held?.map(id => metadata?.funds[id]).filter((fund): fund is FundDetails => !!fund) ?? [];
  return {
    key: value.label, name: label.name, family: label.family, secondary: label.version.join(" · "), filter: label.filter, tabs,
    aliases: [
      value.strategy, value.variant, value.implementation,
      ...held.flatMap(fund => [fund.name, fund.full_name, fund.identifier, fund.ticker, fund.tracks, ...fund.aliases, ...fund.provider_identifiers]),
      ...(details?.signal?.flatMap(seriesAliases) ?? []),
      ...(details?.proxies.flatMap(proxy => seriesAliases(proxy.series)) ?? []),
      ...(details?.benchmark?.type === "Price index" ? seriesAliases(details.benchmark) : []),
    ],
  };
}

export function fundChoice(value: FundIdentity, metadata?: Metadata): Choice {
  const details = metadata?.funds[value.id];
  return {
    key: value.id, name: fundName(value.id, value.label), secondary: fundIdentity(value, details),
    aliases: [value.label, details?.full_name, details?.tracks, ...(details?.aliases ?? []), ...(details?.provider_identifiers ?? [])],
  };
}

export function matchingChoices(choices: Choice[], query: string, filter: string) {
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const matched = choices.filter(choice => {
    if (filter && !(choice.tabs?.includes(filter) ?? choice.filter === filter)) return false;
    const searchable = [choice.key, choice.name, choice.family, choice.secondary, ...(choice.aliases ?? [])].join(" ").toLowerCase();
    return terms.every(term => searchable.includes(term));
  });
  return matched.sort((a, b) => byLabel(a.family ?? "", b.family ?? "") || byLabel(a.name, b.name)
    || byLabel(a.secondary ?? "", b.secondary ?? "") || byLabel(a.key, b.key));
}
