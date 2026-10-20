import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import words from "../content/backtest-multi.json";
import text from "../content/backtest.json";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../lib/backtestApi", () => ({ backtestRequest: mock.request, backtestDownload: vi.fn() }));
import MultiForm from "../app/backtest/multi-form";

const config = { models: [{ label: "HAA-Simple", strategy: "HAA", variant: "Simple", implementation: "Original" }],
  proxies: [{ key: "century_momentum", label: "Century proxy", caveat: "Mock caveat" }, { key: "haa_simple", label: "HAA proxy", caveat: "Mock caveat" }, { key: "gem", label: "GEM proxy", caveat: "Mock GEM caveat" }, { key: "rvol_daily", label: "Daily proxy", caveat: "Mock daily caveat" }],
  single_options: ["century_momentum", "haa_simple", "gem", "rvol_daily"], blend_options: ["century_momentum", "haa_simple", "gem"], benchmarks: [{ key: "sp500", label: "Mock benchmark", caveat: "Mock benchmark caveat" }] };
afterEach(() => { cleanup(); mock.request.mockReset(); });
function setup(mode: "portfolio" | "deep") {
  const run = vi.fn(async (_body: Record<string, unknown>) => {}); const changed = vi.fn();
  mock.request.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.startsWith("/api/backtest/config")) return config;
    if (path === "/api/portfolios") return [{ id: "fake-id", name: "Fake portfolio" }];
    if (path === "/api/backtest/load") return { sleeves: [{ id: 1, model: mode === "deep" ? "haa_simple" : "HAA-Simple", weight: 100 }], initial: 3000, warnings: [] };
    const body = JSON.parse(init?.body as string);
    if (body.sleeves.some((s: { weight: number }) => s.weight <= 0)) throw new Error(words.positivePortfolio);
    return { valid: true, message: words.weightSuccess };
  });
  render(<MultiForm mode={mode} running={false} onRun={run} onChange={changed} />);
  return { run, changed };
}

it("only validates on edits; runs solely on the explicit button, disabled for invalid weights", async () => {
  const {run} = setup("portfolio");
  await screen.findByText(words.weightSuccess);
  expect(run).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText(words.add));
  await screen.findByText(words.positivePortfolio);
  expect(screen.getByRole("button", { name: text.run })).toHaveProperty("disabled", true);
  fireEvent.click(screen.getAllByText(words.remove)[1]);
  await waitFor(() => expect(screen.getByRole("button", { name: text.run })).toHaveProperty("disabled", false));
  fireEvent.click(screen.getByRole("button", { name: text.run }));
  expect(run).toHaveBeenCalledTimes(1);
  expect(run.mock.calls[0][0]).toMatchObject({ mode: "portfolio", tax_enabled: true, tax_rate: 25, fee_value: 0 });
  expect(mock.request.mock.calls.every(([path]) => !["/api/workspace", "/api/backtest"].includes(path))).toBe(true);
});

it("retains daily single-proxy restrictions and benchmark caveats", async () => {
  setup("deep"); await screen.findByText(words.weightSuccess);
  fireEvent.change(screen.getByLabelText(words.proxyStrategy), {target: {value: "rvol_daily"}});
  await screen.findByLabelText(words.dailyTax);
  expect(screen.getByLabelText(words.dailyTax)).toHaveProperty("disabled", true);
  expect(screen.getByLabelText(words.dailyTax)).toHaveProperty("checked", false);
  expect(screen.getByLabelText(words.weight)).toHaveProperty("value", "100");
  expect(screen.getByLabelText(words.weight)).toHaveProperty("disabled", true);
  expect(screen.getByText(words.add)).toHaveProperty("disabled", true);
  expect(screen.getByText(words.benchmarkHelp)).toBeTruthy();
  expect(screen.getByText("Mock benchmark caveat")).toBeTruthy();
});

it("loads saved choices and Python-converted capital without running or saving", async () => {
  const {run} = setup("portfolio"); await screen.findByText(words.weightSuccess);
  const details = screen.getByText(words.load, {selector:"summary"}).closest("details")!;
  details.open = true; fireEvent(details, new Event("toggle"));
  await screen.findByText("Fake portfolio");
  fireEvent.click(screen.getByRole("button", {name: words.load}));
  await waitFor(() => expect(screen.getByLabelText(text.initial)).toHaveProperty("value", "3000"));
  expect(run).not.toHaveBeenCalled();
  expect(mock.request).toHaveBeenCalledWith("/api/backtest/load", expect.objectContaining({ method: "POST", body: JSON.stringify({mode:"portfolio", portfolio_id:"fake-id"}) }));
});

it("keeps all added component wording in data files and scopes Today wrapping", () => {
  const source = readFileSync("./app/backtest/multi-form.tsx", "utf8");
  expect(source).toContain('content/backtest-multi.json');
  expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);
  expect(source).not.toMatch(/reduce\(|toFixed|\/api\/workspace|localStorage|sessionStorage/);
  const css = readFileSync("./app/globals.css", "utf8");
  expect(css).toContain(".today-sleeve-table table { table-layout: auto; white-space: normal; min-width: 760px; }");
  expect(css).toContain(".signal-table-scroll table { width: 100%; border-collapse: collapse; font-size: .85rem; white-space: nowrap; }");
  expect(readFileSync("./app/today/page.tsx", "utf8")).toContain("signal-table-scroll today-sleeve-table");
});
