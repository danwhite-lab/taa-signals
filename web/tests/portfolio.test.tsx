import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const calls = vi.hoisted(() => ({ api: vi.fn(), signOut: vi.fn() }));
vi.mock("../lib/api", () => ({ api: calls.api }));
vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: { signOut: calls.signOut } }) }));
import Portfolio from "../app/portfolio/page";

const payload = { version: 1, name: "Fake portfolio", sleeves: [{ model: "Buy and Hold SPY", weight: 100 }], total_ils: 100, ils_per_usd: 4 };
const saved = { id: "fake-id", name: "Fake portfolio", payload, updated_at: "mock-timestamp", is_default: true };
afterEach(() => { cleanup(); calls.api.mockReset(); });

function mockLoad() {
  calls.api.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") return { ...saved, updated_at: "new-mock-timestamp" };
    if (init?.method === "PUT") return { revision: 8, payload: { portfolio_name: "Fake preference" } };
    if (path === "/api/workspace") return { revision: 7, payload: { portfolio_name: "Fake preference" } };
    if (path === "/api/portfolios") return [saved];
    if (path === "/api/me") return { email: "test@example.invalid" };
    throw new Error("Unexpected mock request");
  });
}

it("lists saved data, revision, default and sends loaded timestamp on edit", async () => {
  mockLoad(); render(<Portfolio />);
  fireEvent.click(await screen.findByText("Fake portfolio · Default"));
  expect(screen.getByLabelText("Portfolio name")).toHaveProperty("value", "Fake portfolio");
  fireEvent.click(screen.getByText("Save portfolio"));
  await screen.findByText("Portfolio saved.");
  const [, init] = calls.api.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(JSON.parse(init.body)).toMatchObject({ id: "fake-id", expected_updated_at: "mock-timestamp", is_default: true, payload });
});

it("conflict preserves draft, blocks repeat mutations, and reload recovers", async () => {
  mockLoad(); render(<Portfolio />);
  fireEvent.click(await screen.findByText("Fake portfolio · Default"));
  const before = calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async (path, init) => {
    if (init?.method === "POST") throw new Error("Mock conflict");
    return before(path, init);
  });
  fireEvent.change(screen.getByLabelText("Portfolio name"), { target: { value: "Unsaved fake draft" } });
  fireEvent.click(screen.getByText("Save portfolio"));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Portfolio name")).toHaveProperty("value", "Unsaved fake draft");
  expect(screen.getByText("Save portfolio")).toHaveProperty("disabled", true);
  fireEvent.click(screen.getByText("Reload saved data"));
  await waitFor(() => expect(screen.getByText("Save portfolio")).toHaveProperty("disabled", false));
});

it("workspace form saves one preference using its loaded revision, not fabricated holdings", async () => {
  mockLoad(); render(<Portfolio />);
  await screen.findByText("Fake portfolio · Default");
  fireEvent.click(screen.getByText("Save workspace preference"));
  await screen.findByText("Workspace saved.");
  const [, init] = calls.api.mock.calls.find(([, init]) => init?.method === "PUT")!;
  expect(JSON.parse(init.body)).toEqual({ revision: 7, payload: { portfolio_name: "Fake preference" } });
});
