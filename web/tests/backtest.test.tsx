import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/backtest.json";

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
  expect(screen.getByLabelText(text.feesEnabled)).toHaveProperty("checked", true);
  expect(screen.getByLabelText(text.ilsFeePercent)).toHaveProperty("value", "0.05");
  expect(screen.getByLabelText(text.ilsMinimumFee)).toHaveProperty("value", "2");
  expect(screen.getByLabelText(text.usdFlatFee)).toHaveProperty("value", "5");
  expect(screen.getByRole("radio", { name: text.portfolio })).toHaveProperty("disabled", false);
  expect(screen.getByRole("radio", { name: text.deep })).toHaveProperty("disabled", false);
  expect(screen.queryByText(text.reference)).toBeNull();
});

it('switches all three modes with the same default using native grouped radios',async()=>{
  await ready();const original=mock.request.getMockImplementation()!;
  mock.request.mockImplementation(async(path,init)=>path.startsWith('/api/backtest/config')?{models:[],proxies:[],single_options:[],blend_options:[],benchmarks:[]}:
    path==='/api/backtest/validate'?{valid:true,message:'Example validated'}:path==='/api/compare/options'?{portfolios:[]}:path==='/api/portfolios'?[]:original(path,init));
  expect(screen.getByRole('radiogroup',{name:text.mode})).toBeTruthy();
  expect(screen.getByRole('radio',{name:text.single})).toHaveProperty('checked',true);
  for(const label of [text.portfolio,text.deep,text.single]){
    fireEvent.click(screen.getByRole('radio',{name:label}));
    expect(screen.getByRole('radio',{name:label})).toHaveProperty('checked',true);
  }
  expect(mock.request.mock.calls.some(([path])=>path==='/api/backtest')).toBe(false);
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
  fireEvent.click(screen.getByLabelText(text.feesEnabled));
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

it("uses authenticated full CSV downloads and content-file labels", async () => {
  const run = await ready(); fireEvent.click(run);
  fireEvent.click(await screen.findByText("Mock ledger download"));
  expect(mock.download).toHaveBeenCalledWith("mock-key", "tax_events", "mock.csv");
  const source = readFileSync("./app/backtest/page.tsx", "utf8");
  expect(source).toContain('from "../../content/backtest.json"');
  expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);
});
