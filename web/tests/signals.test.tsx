import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const mocks = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("../lib/api", () => ({ api: mocks.api }));
import SignalsPage, { SignalsView, downloadHistory, type SignalsPayload } from "../app/signals/page";

const table = { columns: ["Mock asset", "Mock value"], rows: [{ "Mock asset": "SPY", "Mock value": 1 }], display_rows: [{ "Mock asset": "SPY", "Mock value": 1 }] };
function payload(mode: SignalsPayload["mode"]): SignalsPayload {
  return { mode, heading: mode === "daily" ? "Signal — 100% BIL · Hold" : "Signals", captions: ["Mock caption"],
    warnings: ["Mock risk warning"], current: { available: true, reason: null,
      allocation: "100% SPY", signal_date: "2024-05-31", regime: "Risk On", instruction: "Hold",
      ...(mode === "monthly" ? {} : { table }),
      ...(mode === "buy_and_hold" ? { information: "SPY is held continuously. There is no app-generated timing signal." } : {}) },
    preview: mode === "monthly" ? { heading: "Next month preview (provisional)", decision: { selected_asset: "SPY" },
      reason: null, price_as_of: "2024-06-14", allocation: "100% SPY", regime: "Risk On", changed: false,
      unavailable_text: "No preview", warning: "**Provisional only — not a trading instruction.** Mock preview." } : null,
    rationale: { heading: "Why this allocation", paragraphs: ["Mock explanation"], tables: [table], captions: ["Mock input caption"] },
    history: { table, count: 1, csv: "signal_date,asset\n2024-05-31,SPY\n", filename: "mock_signal_history.csv", download_label: "Download signal history CSV" },
    data: { sources: table, ranges: table, completed_through: "2024-05-31", captions: [], warnings: ["Mock provider warning"] },
    fallback_warnings: ["Mock live fallback warning"], cache: { hit: null, warnings: ["Mock cache warning"] },
    disclaimer: "Rules-based informational signal only; not investment advice. You are responsible for any trading decision and execution." };
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); mocks.api.mockReset(); });

it.each(["monthly", "daily", "buy_and_hold"] as const)("renders %s without calculating allocations in JS", mode => {
  render(<SignalsView value={payload(mode)} />);
  expect(screen.getByText("Mock risk warning")).toBeTruthy();
  expect(screen.getByText("Mock live fallback warning")).toBeTruthy();
  expect(screen.getByText("Mock provider warning")).toBeTruthy();
  expect(screen.getByText(/Rules-based informational signal only/)).toBeTruthy();
  if (mode === "monthly") {
    expect(screen.getByRole("region", { name: "Current allocation" })).toBeTruthy();
    expect(screen.getByText(/Provisional only/)).toBeTruthy();
    fireEvent.click(screen.getByRole("tab", { name: "Rationale" }));
    expect(screen.getByText("Mock explanation")).toBeTruthy();
  } else {
    expect(screen.getByRole("table", { name: "Current signal" })).toBeTruthy();
    expect(screen.queryByRole("tab", { name: "Overview" })).toBeNull();
    expect(screen.queryByText(/Provisional only/)).toBeNull();
  }
  fireEvent.click(screen.getByRole("tab", { name: "History" }));
  expect(screen.getByRole("table", { name: "Signal history" })).toBeTruthy();
  fireEvent.click(screen.getByRole("tab", { name: "Data" }));
  expect(screen.getByRole("table", { name: "Data sources" })).toBeTruthy();
});

it("surfaces the engine's unavailable reason verbatim, never an older current allocation", () => {
  const value = payload("monthly"); value.current = { available: false, reason: "No actionable signal: mock completed-month gap." };
  render(<SignalsView value={value} />);
  expect(screen.getByRole("alert").textContent).toBe("No actionable signal: mock completed-month gap.");
  expect(screen.queryByRole("region", { name: "Current allocation" })).toBeNull();
});

it("downloads exactly the Python-provided CSV and filename", () => {
  const create = vi.fn((_blob: Blob) => "blob:mock"); const revoke = vi.fn();
  Object.defineProperty(URL, "createObjectURL", { value: create, configurable: true });
  Object.defineProperty(URL, "revokeObjectURL", { value: revoke, configurable: true });
  const clicks: { filename: string; href: string }[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
    clicks.push({ filename: this.download, href: this.href });
  });
  const csv = "signal_date,asset\n2024-05-31,SPY\n";
  downloadHistory(csv, "engine.csv");
  expect(create.mock.calls[0][0]).toHaveProperty("size", new TextEncoder().encode(csv).length);
  expect(clicks).toEqual([{ filename: "engine.csv", href: "blob:mock" }]);
});

it("uses all three catalogue selectors, defaults to HAA-Simple and requests the exact implementation label", async () => {
  const rows = [
    { label: "HAA-Simple", strategy: "HAA", variant: "Simple", implementation: "Original" },
    { label: "HAA-Simple Israel", strategy: "HAA", variant: "Simple", implementation: "Israel" },
    { label: "Inflation Compass Standard", strategy: "Inflation Compass", variant: "Standard", implementation: "Original" },
    { label: "Inflation Compass Standard Israel", strategy: "Inflation Compass", variant: "Standard", implementation: "Israel" },
    { label: "Buy and Hold SPY", strategy: "Buy and Hold", variant: "S&P 500", implementation: "SPY" },
  ];
  mocks.api.mockImplementation(async (path: string) => path === "/api/strategies" ? rows : payload("monthly"));
  render(<SignalsPage />);
  await screen.findByLabelText("Strategy");
  expect(screen.getByLabelText("Variant")).toHaveProperty("value", "Simple");
  expect(screen.getByLabelText("Implementation")).toHaveProperty("value", "HAA-Simple");
  fireEvent.change(screen.getByLabelText("Implementation"), { target: { value: "HAA-Simple Israel" } });
  await waitFor(() => expect(mocks.api.mock.calls.some(([path]) => path === "/api/signals?label=HAA-Simple%20Israel")).toBe(true));
  fireEvent.change(screen.getByLabelText("Strategy"), { target: { value: "Inflation Compass" } });
  expect(screen.getByLabelText("Implementation")).toHaveProperty("value", "Inflation Compass Standard Israel");
});

it("offers retry when loading fails", async () => {
  mocks.api.mockRejectedValue(new Error("Mock API unavailable"));
  render(<SignalsPage />);
  await screen.findByText("Mock API unavailable");
  expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
});
