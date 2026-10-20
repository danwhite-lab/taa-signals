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

it("defaults to tax ON at 25%, zero percentage fee, with the other modes enabled", async () => {
  await ready();
  expect(screen.getByLabelText(text.taxEnabled)).toHaveProperty("checked", true);
  expect(screen.getByLabelText(text.taxRate)).toHaveProperty("value", "25");
  expect(screen.getByLabelText(text.feePercent)).toHaveProperty("value", "0");
  expect(screen.getByRole("option", { name: text.portfolio })).toHaveProperty("disabled", false);
  expect(screen.getByRole("option", { name: text.deep })).toHaveProperty("disabled", false);
  expect(screen.queryByText(text.reference)).toBeNull();
});

it("validates controls before posting and clears stale results on edit", async () => {
  const run = await ready();
  fireEvent.change(screen.getByLabelText(text.initial), { target: { value: "-1" } });
  fireEvent.click(run); await screen.findByText(text.validationError);
  expect(mock.request.mock.calls.filter(([path]) => path === "/api/backtest")).toHaveLength(0);
  fireEvent.change(screen.getByLabelText(text.initial), { target: { value: "10000" } });
  fireEvent.click(run); await screen.findByText(text.calculatedNow, { exact: false });
  expect(screen.getByRole("table", { name: text.summary })).toBeTruthy();
  fireEvent.change(screen.getByLabelText(text.feePercent), { target: { value: ".05" } });
  expect(screen.queryByRole("table", { name: text.summary })).toBeNull();
  expect(screen.getByText(text.changed)).toBeTruthy();
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
