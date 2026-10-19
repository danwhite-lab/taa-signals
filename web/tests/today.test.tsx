import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/today.json";

const mock = vi.hoisted(() => ({ response: vi.fn() }));
vi.mock("../lib/api", () => ({ authorizedResponse: mock.response, ApiError: class extends Error { constructor(public status: number, message: string) { super(message); } } }));
vi.mock("next/navigation", () => ({ usePathname: () => "/today/" }));
vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: {
  getSession: async () => ({ data: { session: null }, error: null }),
  onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
} }) }));
import Page from "../app/today/page";
import AuthGate from "../components/AuthGate";
import { ApiError } from "../lib/api";

const payload = { has_default: true, caption: "Fake portfolio · private synced portfolio", issues: [],
  signals: [{ label: "Fake sleeve", weight_text: "40.00%", holding: "Fake holding 100%", status: "Ready · fake", error_code: null }],
  holdings: [{ currency: "USD", rows: [{ holding: "Fake holding", weight_text: "40.00%", amount_text: "2,500.00" }] },
    { currency: "ILS", rows: [{ holding: "Fake local holding", weight_text: "60.00%", amount_text: "6,000.00" }] }],
  monthly_action: "unchanged", latest_caption: "Latest completed signal: 2026-09-30", stale: false,
  previews: [{ label: "Fake sleeve", allocation: "Fake holding 100%", change: "no", price_as_of: "2026-10-16", reason: null, error_code: null }],
  preview_caption: "Mock latest common eligible price caption", warnings: [], public_sleeves: [], timing: {} };
const json = (value: unknown, status=200) => new Response(JSON.stringify(value), { status });
afterEach(() => { cleanup(); mock.response.mockReset(); });

it("does not mount or fetch Today before the existing login gate admits it", async () => {
  render(<AuthGate><Page /></AuthGate>); await screen.findByText("Sign in with Google"); expect(mock.response).not.toHaveBeenCalled();
});

it("renders only server-formatted currency amounts and starts with preview collapsed", async () => {
  mock.response.mockImplementation(async () => json(payload)); render(<Page />);
  await screen.findByText(payload.caption);
  expect(screen.getByText("2,500.00")).toBeTruthy(); expect(screen.getByText("6,000.00")).toBeTruthy();
  expect(screen.getByText(text.preview).closest("details")).toHaveProperty("open", false);
  expect(screen.getByText(text.actions.unchanged)).toBeTruthy();
  expect(screen.getAllByRole("button").map(button => button.textContent)).toEqual([text.refresh]);
  expect(mock.response).toHaveBeenCalledWith("/api/today");
});

it("fetches only on load and explicit Refresh and prevents concurrent refreshes", async () => {
  mock.response.mockImplementation(async () => json(payload)); render(<Page />); await screen.findByText(payload.caption);
  let resolve!: (value: Response) => void;
  mock.response.mockImplementation(() => new Promise(done => { resolve=done; }));
  fireEvent.click(screen.getByText(text.refresh)); fireEvent.click(screen.getByText(text.refresh));
  expect(mock.response).toHaveBeenCalledTimes(2); expect(screen.getByText(text.loading)).toBeTruthy();
  expect(screen.queryByText(payload.caption)).toBeNull();
  resolve(json(payload)); await screen.findByText(payload.caption);
  expect(mock.response.mock.calls.every(args => args.length === 1 && args[0] === "/api/today")).toBe(true);
});

it("shows the exact normal setup message when there is no default", async () => {
  mock.response.mockResolvedValue(json({ ...payload, has_default: false })); render(<Page />);
  await screen.findByText("Use as Today default");
  expect(screen.queryByText(text.holdNow)).toBeNull(); expect(screen.queryByText(text.monthlyAction)).toBeNull();
});

it("renders unavailable reasons, stale warning and provisional rows without guessing", async () => {
  mock.response.mockResolvedValue(json({ ...payload, holdings: null, stale: true, monthly_action: "unavailable",
    issues: ["invalid_capital_fx"], previews: [{ ...payload.previews[0], allocation: null, change: null, price_as_of: null, reason: "This sleeve is held continuously and has no next-month timing preview." }] }));
  render(<Page />); await screen.findByText(text.staleWarning);
  expect(screen.getByText(text.combinedWarning)).toBeTruthy(); expect(screen.getByText(text.errors.invalid_capital_fx)).toBeTruthy();
  expect(screen.getByText("This sleeve is held continuously and has no next-month timing preview.")).toBeTruthy();
});

it("does not expose raw request errors or keep an old report after failed refresh", async () => {
  mock.response.mockImplementation(async () => json(payload)); render(<Page />); await screen.findByText(payload.caption);
  mock.response.mockResolvedValue(new Response("fake private error body", { status: 502 }));
  fireEvent.click(screen.getByText(text.refresh)); await screen.findByText(text.requestErrors["502"]);
  expect(screen.queryByText(payload.caption)).toBeNull(); expect(screen.queryByText("fake private error body")).toBeNull();
});

it.each([400, 401, 403, 404, 429, 500, 502, 503, 504])("shows a safe specific reason for HTTP %s", async status => {
  mock.response.mockResolvedValue(new Response("fake private details", { status })); render(<Page />);
  await screen.findByText((text.requestErrors as Record<string, string>)[String(status)]);
  expect(screen.queryByText("fake private details")).toBeNull();
});

it("distinguishes connection failure from an unreadable successful response", async () => {
  mock.response.mockRejectedValue(new ApiError(0, "fake private details")); render(<Page />);
  await screen.findByText(text.requestErrors["0"]);
  mock.response.mockResolvedValue(new Response("not JSON", { status: 200 }));
  fireEvent.click(screen.getByText(text.refresh)); await screen.findByText(text.invalidResponse);
  expect(screen.queryByText("not JSON")).toBeNull();
});

it.each(Object.entries(text.requestDetails))("recognizes only the safe server reason %s", async (detail, message) => {
  mock.response.mockResolvedValue(json({ detail }, detail.startsWith("Sign-in") ? 503 : 502));
  render(<Page />); await screen.findByText(message);
});

it.each(["fake private details", "toString", { private: "fake" }])("does not echo unrecognized JSON error details", async detail => {
  mock.response.mockResolvedValue(json({ detail }, 502)); render(<Page />);
  await screen.findByText(text.requestErrors["502"]);
  expect(screen.queryByText("fake private details")).toBeNull();
});

it("uses content-file words with no browser financial/date math or user-data writes", () => {
  const source = readFileSync("./app/today/page.tsx", "utf8");
  expect(source).toContain('from "../../content/today.json"');
  expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);
  expect(source).not.toMatch(/parseFloat|toFixed|new Date|Math\.|localStorage|sessionStorage|setInterval|method:|\/api\/workspace/);
  const navigation = readFileSync("./components/top-navigation.tsx", "utf8");
  expect(navigation).toContain('const pages = ["Today",');
});
