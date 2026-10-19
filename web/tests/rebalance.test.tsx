import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/rebalance.json";
const mock = vi.hoisted(() => ({ request: vi.fn(), save: vi.fn() }));
vi.mock("../lib/rebalanceApi", () => ({ rebalanceRequest: mock.request, saveHoldings: mock.save,
  RebalanceError: class extends Error { constructor(public status: number, message: string) { super(message); } } }));
vi.mock("next/navigation", () => ({ usePathname: () => "/rebalance-holdings/" }));
vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: {
  getSession: async () => ({ data: { session: null }, error: null }),
  onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
} }) }));
import Page from "../app/rebalance-holdings/page";
import AuthGate from "../components/AuthGate";
import { RebalanceError } from "../lib/rebalanceApi";

const item = { id: "US:GLD", identifier: "GLD", market: "US", currency: "USD", label: "Fake gold" };
const other = { id: "US:IEF", identifier: "IEF", market: "US", currency: "USD", label: "Fake bonds" };
const row = { Security: item.id, Fund: item.label, Currency: "USD", Units: "2", "Value (₪ / $)": "20", "Enter as": "Units",
  "Outside the rebalance": false, "Manual price per unit": null, "Price date": null, "Minimum order (₪)": "0", Remove: false };
const state = { workspace_revision: 1, account_hash: "fake-hash", account: { revision: 0, cash_ils: "5" }, portfolio_id: "fake-portfolio",
  portfolios: [{ id: "fake-portfolio", name: "Fake portfolio" }], rows: [row], instruments: { [item.id]: item, [other.id]: other },
  quotes: { [item.id]: { price: "10", as_of: "2026-10-15", source: "Mock raw", fresh: true } }, fx: { fresh: true },
  comparison: [{ id: item.id, Fund: item.label, target_display: "100.00%", actual_display: "100.00%", Status: "On target" }],
  total_display: "₪75.00", full_total_display: "₪75.00", full_total_ils: "75", ready: true, blocked: [], held_blocked: [], partial: false,
  overweight: false, signals: [], errors: [], source_settings: "Mock sources", seconds: .01 };
const candidate = { ...state.account, last_operation_id: "fake-operation", revision: 1 };
const preview = { account: candidate, preview: [{ Fund: item.label, "Units to save": "2.00" }], errors: [] };
const plan = { id: "fake-plan", orders: [{ id: item.id, units: 2, estimated_ils: "70" }], leftover_ils: "5" };

afterEach(() => { cleanup(); mock.request.mockReset(); mock.save.mockReset(); vi.restoreAllMocks(); });
async function ready() {
  mock.request.mockImplementation(async (path: string) => path === "/api/rebalance/editor" ? preview : path === "/api/rebalance/plan" ? { state, plan } : state);
  mock.save.mockResolvedValue({ saved: { revision: 2, payload: { holdings_account: candidate } }, uncertain: false });
  render(<Page />); await screen.findByText(text.holdings);
  await waitFor(() => expect(screen.getByText(text.save)).toHaveProperty("disabled", false));
}

it("requires the existing login gate before fetching holdings", async () => {
  render(<AuthGate><Page /></AuthGate>); await screen.findByText("Sign in with Google"); expect(mock.request).not.toHaveBeenCalled();
});

it("last edited value/units wins, outside edits invalidate the plan, and draft adds preserve inputs", async () => {
  await ready();
  fireEvent.click(screen.getByText(text.generate)); await screen.findByText(text.leftover+": 5");
  fireEvent.change(screen.getByLabelText(`${text.columns["Value (₪ / $)"]} US:GLD`), { target: { value: "125" } });
  expect(screen.getByText(text.generate)).toHaveProperty("disabled", true);
  expect(screen.queryByText(text.leftover+": 5")).toBeNull();
  fireEvent.change(screen.getByLabelText(text.known), { target: { value: other.id } });
  fireEvent.click(screen.getByText(text.addSelected)); await screen.findByLabelText(`${text.columns.Units} US:IEF`);
  expect(screen.getByLabelText(`${text.columns["Value (₪ / $)"]} US:GLD`)).toHaveProperty("value", "125");
  fireEvent.click(screen.getByLabelText(`${text.columns["Outside the rebalance"]} US:GLD`));
  fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(() => expect(mock.request.mock.calls.some(([p]) => p === "/api/rebalance/editor")).toBe(true));
  const body = mock.request.mock.calls.find(([p]) => p === "/api/rebalance/editor")![1];
  expect(body.rows[0]["Enter as"]).toBe("Value"); expect(body.rows[0]["Outside the rebalance"]).toBe(true);
  fireEvent.change(screen.getByLabelText(`${text.columns.Units} US:GLD`), { target: { value: "3" } });
  fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(() => expect(mock.request.mock.calls.filter(([p]) => p === "/api/rebalance/editor")).toHaveLength(2));
  expect(mock.request.mock.calls.filter(([p]) => p === "/api/rebalance/editor")[1][1].rows[0]["Enter as"]).toBe("Units");
});

it("manual price dates start empty and explicit dates are sent unchanged", async () => {
  await ready();
  const date = screen.getByLabelText(`${text.columns["Price date"]} US:GLD`);
  expect(date).toHaveProperty("value", "");
  fireEvent.change(screen.getByLabelText(`${text.columns["Manual price per unit"]} US:GLD`), { target: { value: "9.123456" } });
  fireEvent.change(date, { target: { value: "2026-10-12" } });
  fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(() => expect(mock.request.mock.calls.some(([p]) => p === "/api/rebalance/editor")).toBe(true));
  const body = mock.request.mock.calls.find(([p]) => p === "/api/rebalance/editor")![1];
  expect(body.rows[0]["Price date"]).toBe("2026-10-12"); expect(body.rows[0]["Manual price per unit"]).toBe("9.123456");
});

it("save conflict preserves draft, pauses writes and shows no saved confirmation", async () => {
  await ready(); mock.save.mockRejectedValue(new RebalanceError(409, text.paused));
  fireEvent.change(screen.getByLabelText(text.cash), { target: { value: "17" } });
  fireEvent.click(screen.getByText(text.save));
  await waitFor(() => expect(screen.getByText(text.save)).toHaveProperty("disabled", true));
  expect(screen.getByLabelText(text.cash)).toHaveProperty("value", "17"); expect(screen.getAllByText(text.paused).length).toBeGreaterThan(0);
  expect(screen.queryByText(text.saved)).toBeNull();
});

it("uncertain response keeps draft paused even when readback confirmed", async () => {
  await ready(); mock.save.mockResolvedValue({ saved: { revision: 2 }, uncertain: true });
  fireEvent.change(screen.getByLabelText(text.cash), { target: { value: "17" } }); fireEvent.click(screen.getByText(text.save));
  await screen.findByText(text.uncertain);
  expect(screen.getByLabelText(text.cash)).toHaveProperty("value", "17");
  expect(screen.getByText(text.save)).toHaveProperty("disabled", true); expect(screen.getByText(text.saved)).toBeTruthy();
});

it("record appears only for orders, needs acknowledgement, and cancel does not write", async () => {
  await ready(); expect(screen.queryByText(text.record)).toBeNull();
  fireEvent.click(screen.getByText(text.generate)); fireEvent.click(await screen.findByText(text.record));
  expect(screen.getByText(text.done)).toHaveProperty("disabled", true);
  fireEvent.click(screen.getByLabelText(text.acknowledge)); expect(screen.getByText(text.done)).toHaveProperty("disabled", false);
  fireEvent.click(screen.getByText(text.cancel)); expect(mock.save).not.toHaveBeenCalled();
});

it("all page-owned words come from content; no browser money math or order routing", () => {
  const source = readFileSync("./app/rebalance-holdings/page.tsx", "utf8");
  expect(source).toContain('from "../../content/rebalance.json"'); expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);
  expect(source).not.toMatch(/parseFloat|toFixed|Math\.floor|localStorage|sessionStorage/);
});

it("records actual confirmations through preparation then the single workspace save", async () => {
  await ready();
  const original = mock.request.getMockImplementation()!;
  mock.request.mockImplementation(async (path: string, body: unknown) => path === "/api/rebalance/record" ? { account: candidate } : original(path, body));
  fireEvent.click(screen.getByText(text.generate)); fireEvent.click(await screen.findByText(text.record));
  fireEvent.change(screen.getByLabelText(text.bought), { target: { value: "1" } });
  fireEvent.change(screen.getByLabelText(text.paid), { target: { value: "36.25" } });
  fireEvent.click(screen.getByLabelText(text.acknowledge)); fireEvent.click(screen.getByText(text.done));
  await screen.findByText(text.recorded);
  expect(mock.request.mock.calls.find(([p]) => p === "/api/rebalance/record")![1].confirmations).toEqual([{ id: item.id, units: "1", paid_ils: "36.25" }]);
  expect(mock.save).toHaveBeenCalledWith(1, candidate);
});

it("empty order list does not expose the recording step", async () => {
  await ready();
  mock.request.mockResolvedValue({ state, plan: { ...plan, orders: [] } });
  fireEvent.click(screen.getByText(text.generate)); await screen.findByText(text.emptyPlan);
  expect(screen.queryByText(text.record)).toBeNull();
});
