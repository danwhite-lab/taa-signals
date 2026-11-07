import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, act, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/backtest.json";
import words from "../content/backtest-multi.json";
import usdWords from "../content/usd-equivalents.json";

const mock = vi.hoisted(() => ({ request: vi.fn(), download: vi.fn() }));
vi.mock("../lib/backtestApi", () => ({ backtestRequest: mock.request, backtestDownload: mock.download }));
vi.mock("next/navigation", () => ({ usePathname: () => "/backtest/" }));
vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: {
  getSession: async () => ({ data: { session: null }, error: null }),
  onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
} }) }));
import BacktestPage from "../app/backtest/page";
import AuthGate from "../components/AuthGate";

const table = { columns: ["mock"], rows: [{ mock: 100 }], total_rows: 1, shown_rows: 1 };
const chart = { series: [{ label: "Mock pre-tax", svg_points: "55,250 870,30" }], minimum: 100, maximum: 110, start: "2020-01-01", end: "2024-06-28", caption: "Mock unreduced curve" };
const options = { models: [{ label: "HAA-Simple", strategy: "HAA", variant: "Simple", implementation: "Original" }], label: "HAA-Simple", currency: "USD",
  bounds: { start_min: "2020-01-01", start_max: "2024-05-31", end_min: "2020-01-01", end_max: "2024-06-28" },
  captions: ["Mock source caption"], warnings: ["Minimum fee of 2 NIS is not modelled by this backtest"], data_validation: table,
  reference_replay_available: false, dca_caption: "Mock deposit caption", reference_caption: "Mock replay caption" };
const result = { label: "HAA-Simple", currency: "USD", settings: { tax_enabled: true, tax_rate: 25, fee_type: "percentage", fee_value: 0 }, engine_parameters: { tax_enabled: true, tax_rate: .25, transaction_cost: 0 },
  summary: table, periods: table, tax_events: table, annual: table, monthly: table, value_chart: chart, drawdown_chart: chart,
  cache: { key: "mock-key", hit: null }, calculated_at: "2026-01-01T00:00:00Z", captions: ["Mock result caption"], warnings: [],
  timing: { engine_seconds: .01 }, calculation_timing: { engine_seconds: .01 }, downloads: [{ kind: "tax_events", label: "Mock ledger download", filename: "mock.csv" }] };

afterEach(() => { cleanup(); mock.request.mockReset(); mock.download.mockReset(); });
function ready() {
  mock.download.mockResolvedValue(undefined);
  mock.request.mockImplementation(async (path: string) => path.startsWith("/api/backtest/options") ? options : result);
  render(<BacktestPage />);
  return screen.findByRole("button", { name: text.run });
}

it("is withheld by the existing login gate", async () => {
  render(<AuthGate><BacktestPage /></AuthGate>);
  await screen.findByText("Sign in with Google");
  expect(mock.request).not.toHaveBeenCalled();
  expect(screen.queryByText(text.run)).toBeNull();
});

it("defaults to tax ON at 25% and currency-specific broker fees, with the other modes enabled", async () => {
  await ready();
  expect(screen.getByLabelText(text.taxEnabled)).toHaveProperty("checked", true);
  expect(screen.getByLabelText(text.taxRate)).toHaveProperty("value", "25");
  expect(screen.getByLabelText("Trading fees")).toHaveProperty("checked", true);
  expect(screen.getByRole("heading", {name:"Amount and dates"})).toBeTruthy();
  expect(screen.getByRole("heading", {name:"Costs and tax"})).toBeTruthy();
  expect(screen.getByText("Start", {selector:"label"})).toBeTruthy();
  expect(screen.getByText("End", {selector:"label"})).toBeTruthy();
  expect(screen.getByText(text.start, {selector:".assumption-hint"})).toBeTruthy();
  expect(screen.getByLabelText(text.ilsFeePercent)).toHaveProperty("value", "0.05");
  expect(screen.getByLabelText(text.ilsMinimumFee)).toHaveProperty("value", "2");
  expect(screen.getByLabelText(text.usdFlatFee)).toHaveProperty("value", "5");
  expect(screen.getByRole("radio", { name: text.portfolio })).toHaveProperty("disabled", false);
  expect(screen.getByRole("radio", { name: text.deep })).toHaveProperty("disabled", false);
  expect(screen.queryByText(text.reference)).toBeNull();
});

it("uses the Parameters switch to load and reset each Backtest mode", async () => {
  mock.request.mockImplementation(async (path: string) => {
    if (path === "/api/backtest/config?mode=portfolio") return { models: options.models };
    if (path === "/api/backtest/config?mode=deep") return {
      models: [],
      proxies: [{ key: "century_momentum", label: "Century proxy", caveat: "Proxy caveat" }],
      single_options: ["century_momentum"], blend_options: ["century_momentum"],
      benchmarks: [{ key: "sp500", label: "S&P 500", caveat: "Benchmark caveat" }],
    };
    if (path.startsWith("/api/backtest/options")) return options;
    if (path === "/api/backtest/validate") return { valid: true, message: words.weightSuccess };
    return result;
  });
  render(<BacktestPage />);
  const history = () => screen.getByRole("switch", { name: text.extendedHistory });
  await screen.findByRole("option", { name: "HAA" });
  expect(history()).toHaveProperty("checked", false);
  expect(history().closest("section")?.getAttribute("aria-labelledby")).toBe("backtest-parameters-heading");
  expect(screen.queryByRole("radiogroup", { name: text.mode })).toBeNull();
  fireEvent.change(screen.getByLabelText(text.initial), { target: { value: "20000" } });

  fireEvent.click(history());
  await screen.findByRole("option", { name: "Century proxy" });
  expect(history()).toHaveProperty("checked", true);
  expect(screen.getByLabelText(text.initial)).toHaveProperty("value", "100000");
  expect(screen.queryByLabelText(text.strategy)).toBeNull();
  expect(screen.getByText("Proxy caveat")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: text.run }));
  await screen.findByRole("table", { name: text.summary });
  for (const path of ["/api/backtest/validate", "/api/backtest"]) {
    const request = mock.request.mock.calls.find(([url]) => url === path);
    expect(JSON.parse(request![1].body)).toMatchObject({ mode: "deep", sleeves: [{ model: "century_momentum", weight: 100 }] });
  }

  fireEvent.click(history());
  await screen.findByRole("option", { name: "HAA" });
  expect(history()).toHaveProperty("checked", false);
  expect(screen.queryByLabelText(words.proxyStrategy)).toBeNull();
  expect(screen.queryByRole("table", { name: text.summary })).toBeNull();
  expect(mock.request.mock.calls.filter(([path]) => path.startsWith("/api/backtest/config")).map(([path]) => path)).toEqual([
    "/api/backtest/config?mode=portfolio", "/api/backtest/config?mode=deep", "/api/backtest/config?mode=portfolio",
  ]);
});

it("validates controls before posting and clears stale results on edit", async () => {
  const run = await ready();
  fireEvent.change(screen.getByLabelText(text.initial), { target: { value: "-1" } });
  fireEvent.click(run); await screen.findByText(text.validationError);
  expect(mock.request.mock.calls.filter(([path]) => path === "/api/backtest")).toHaveLength(0);
  fireEvent.change(screen.getByLabelText(text.initial), { target: { value: "10000" } });
  fireEvent.click(run); await screen.findByText(text.calculatedNow, { exact: false });
  expect(screen.getByRole("table", { name: text.summary })).toBeTruthy();
  fireEvent.change(screen.getByLabelText(text.ilsFeePercent), { target: { value: ".1" } });
  expect(screen.queryByRole("table", { name: text.summary })).toBeNull();
  expect(screen.getByText(text.changed)).toBeTruthy();
});

it("sends editable currency fees, disables them explicitly and shows both fee totals", async () => {
  await ready();
  fireEvent.change(screen.getByLabelText(text.ilsFeePercent), {target:{value:'.1'}});
  fireEvent.change(screen.getByLabelText(text.ilsMinimumFee), {target:{value:'3'}});
  fireEvent.change(screen.getByLabelText(text.usdFlatFee), {target:{value:'6'}});
  mock.request.mockResolvedValue({...result, fees:{currency:'USD',enabled:true,pre_tax:24,after_tax:18}});
  fireEvent.click(screen.getByRole('button',{name:text.run}));
  await screen.findByText('Total fees paid (USD)');
  expect(screen.getByText('Pre-tax backtest: 24.00')).toBeTruthy();
  expect(screen.getByText('After-tax backtest: 18.00')).toBeTruthy();
  const call=mock.request.mock.calls.find(([path])=>path==='/api/backtest');
  expect(JSON.parse(call![1].body)).toMatchObject({fees_enabled:true,ils_fee_percent:.1,ils_minimum_fee:3,usd_flat_fee:6});
  fireEvent.click(screen.getByLabelText("Trading fees"));
  expect(screen.getByLabelText(text.ilsFeePercent)).toHaveProperty('disabled',true);
  expect(screen.queryByText('Total fees paid (USD)')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:text.run}));
  await waitFor(()=>expect(mock.request.mock.calls.filter(([path])=>path==='/api/backtest')).toHaveLength(2));
  const calls=mock.request.mock.calls.filter(([path])=>path==='/api/backtest');
  expect(JSON.parse(calls[1][1].body).fees_enabled).toBe(false);
});

it("prevents a second run and shows progress while waiting", async () => {
  let resolve!: (result: unknown) => void;
  mock.request.mockImplementation((path: string) => path.startsWith("/api/backtest/options") ? Promise.resolve(options) : new Promise(done => { resolve = done; }));
  render(<BacktestPage />);
  const run = await screen.findByRole("button", { name: text.run });
  fireEvent.click(run); fireEvent.click(run);
  expect(screen.getByText(text.longRun)).toBeTruthy();
  expect(mock.request.mock.calls.filter(([path]) => path === "/api/backtest")).toHaveLength(1);
  await act(async () => resolve(result));
  await screen.findByRole("table", { name: text.summary });
});

it("shows timeout without partial results", async () => {
  await ready();
  mock.request.mockImplementation(async (path: string) => { if (path === "/api/backtest") throw new Error(text.timeout); return options; });
  fireEvent.click(screen.getByText(text.run));
  await screen.findByText(text.timeout);
  expect(screen.queryByRole("table", { name: text.summary })).toBeNull();
});

it.each([false, true])("organizes results and keeps requests unchanged with Extended History set to %s", async (deep) => {
  const periods = deep
    ? { columns: ["Strategy", "Benchmark", "Delta"], rows: [{ Strategy: 2, Benchmark: 1, Delta: 1 }] }
    : { columns: ["Strategy"], rows: [{ Strategy: 2 }] };
  mock.download.mockResolvedValue(undefined);
  mock.request.mockImplementation(async (path: string) => {
    if (path === "/api/backtest/config?mode=portfolio") return { models: options.models };
    if (path === "/api/backtest/config?mode=deep") return {
      models: [], proxies: [{ key: "century_momentum", label: "Century proxy", caveat: "Proxy caveat" }],
      single_options: ["century_momentum"], blend_options: ["century_momentum"],
      benchmarks: [{ key: "sp500", label: "S&P 500", caveat: "Benchmark caveat" }],
    };
    if (path.startsWith("/api/backtest/options")) return options;
    if (path === "/api/backtest/validate") return { valid: true, message: words.weightSuccess };
    if (path === "/api/backtest/models") return { models: options.models };
    return {
      ...result, periods, warnings: ["Result warning"], data_validation: table, data_origin: "Source metadata",
      usd_equivalents: { enabled: !deep, currency: "USD", mapping_version: "test", mappings: [] },
      extra_tables: [{ label: words.selected, value: table }, { label: words.dailySignals, value: table }],
      extra_charts: [{ label: words.syntheticCurve, value: chart }],
      rolling: deep ? [{ years: 5, label: "Five-year returns", table, chart }] : [],
      downloads: [...result.downloads, { kind: "audit", label: "Mock audit download", filename: "audit.csv", bytes: 512 }],
    };
  });
  render(<BacktestPage />);
  if (deep) fireEvent.click(screen.getByRole("switch", { name: text.extendedHistory }));
  const run = screen.getByRole("button", { name: text.run });
  await waitFor(() => expect(run).toHaveProperty("disabled", false));
  fireEvent.click(run);
  await screen.findByRole("heading", { name: words.resultsComplete });
  const callsAfterRun = mock.request.mock.calls.length;
  const tab = (name: string) => screen.getByRole("tab", { name });
  const panel = (name: string) => within(screen.getByRole("tabpanel", { name }));
  const overview = tab(words.resultTabs.overview);
  expect(overview.getAttribute("aria-selected")).toBe("true");
  expect(panel(words.resultTabs.overview).getByRole("table", { name: text.summary })).toBeTruthy();
  const tablist = screen.getByRole("tablist", { name: text.results });
  expect(screen.getByText("Result warning").compareDocumentPosition(tablist) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  fireEvent.keyDown(overview, { key: "ArrowRight" });
  const charts = panel(words.resultTabs.charts);
  expect(document.activeElement).toBe(tab(words.resultTabs.charts));
  expect(charts.getByRole("img", { name: text.performance })).toBeTruthy();
  expect(charts.getByRole("img", { name: words.syntheticCurve })).toBeTruthy();
  expect(charts.queryByRole("table")).toBeNull();

  fireEvent.click(tab(words.resultTabs.statistics));
  const stats = panel(words.resultTabs.statistics);
  expect(within(stats.getByRole("table", { name: text.periods })).getAllByRole("columnheader")
    .map(node => node.textContent)).toEqual(periods.columns);
  expect(stats.getByText(words.selected)).toBeTruthy();
  expect(stats.queryByText(words.dailySignals)).toBeNull();

  fireEvent.keyDown(tab(words.resultTabs.statistics), { key: "End" });
  const history = panel(words.resultTabs.history);
  expect(history.getByText(text.ledger)).toBeTruthy();
  expect(history.getByText(words.dailySignals)).toBeTruthy();
  expect(history.getByText("mock.csv")).toBeTruthy();
  expect(history.getAllByText(/bytes$/).map(node => node.textContent)).toEqual(["512 bytes"]);
  expect(screen.getByText("Result warning")).toBeTruthy();
  expect(screen.getByText("Mock result caption")).toBeTruthy();
  if (!deep) expect(screen.getByText(usdWords.banner)).toBeTruthy();
  expect(mock.request.mock.calls).toHaveLength(callsAfterRun);
  fireEvent.click(history.getByRole("button", { name: "Mock ledger download" }));
  expect(mock.download).toHaveBeenCalledWith("mock-key", "tax_events", "mock.csv");
  const source = readFileSync("./app/backtest/page.tsx", "utf8");
  expect(source).toContain('from "../../content/backtest.json"');
  expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);
});

it("selects an available rolling period after rerunning Extended History", async () => {
  const oneYear = { years: 1, label: "One-year returns", table, chart };
  const threeYears = { years: 3, label: "Three-year returns", table, chart };
  const fiveYears = { years: 5, label: "Five-year returns", table, chart };
  const responses = [
    { ...result, rolling: [oneYear, fiveYears] },
    { ...result, rolling: [oneYear, threeYears] },
    { ...result, rolling: [] },
    result,
  ];
  mock.request.mockImplementation(async (path: string) => {
    if (path === "/api/backtest/config?mode=deep") return {
      models: [],
      proxies: [{ key: "century_momentum", label: "Century proxy", caveat: "Proxy caveat" }],
      single_options: ["century_momentum"], blend_options: ["century_momentum"],
      benchmarks: [{ key: "sp500", label: "S&P 500", caveat: "Benchmark caveat" }],
    };
    if (path === "/api/backtest/validate") return { valid: true, message: words.weightSuccess };
    if (path === "/api/backtest") return responses.shift();
    return options;
  });
  render(<BacktestPage />);
  fireEvent.click(screen.getByRole("switch", { name: text.extendedHistory }));

  async function runAndOpenCharts() {
    const run = screen.getByRole("button", { name: text.run });
    await waitFor(() => expect(run).toHaveProperty("disabled", false));
    fireEvent.click(run);
    await waitFor(() => expect(run).toHaveProperty("disabled", false));
    fireEvent.click(await screen.findByRole("tab", { name: words.resultTabs.charts }));
    const charts = within(screen.getByRole("tabpanel", { name: words.resultTabs.charts }));
    const rolling = charts.queryByText(words.rolling, { selector: "summary" });
    if (rolling) fireEvent.click(rolling);
    return charts;
  }

  let charts = await runAndOpenCharts();
  let period = charts.getByLabelText(words.rollingPeriod);
  expect(period).toHaveProperty("value", "5");
  fireEvent.change(period, { target: { value: "1" } });
  expect(charts.getByRole("img", { name: oneYear.label })).toBeTruthy();
  fireEvent.change(period, { target: { value: "5" } });
  expect(charts.getByRole("img", { name: fiveYears.label })).toBeTruthy();

  charts = await runAndOpenCharts();
  period = charts.getByLabelText(words.rollingPeriod);
  expect(period).toHaveProperty("value", "3");
  expect(charts.getByRole("img", { name: threeYears.label })).toBeTruthy();
  expect(charts.queryByRole("img", { name: fiveYears.label })).toBeNull();

  for (const caseLabel of ["empty", "missing"]) {
    charts = await runAndOpenCharts();
    expect(charts.queryByText(words.rolling), caseLabel).toBeNull();
    expect(charts.queryByLabelText(words.rollingPeriod)).toBeNull();
  }
});
