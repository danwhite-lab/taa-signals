import { afterEach, expect, it, vi } from "vitest";
import text from "../content/backtest.json";

const mocks = vi.hoisted(() => ({ response: vi.fn() }));
vi.mock("../lib/api", () => ({ authorizedResponse: mocks.response, ApiError: class extends Error { status = 0; } }));
import { backtestRequest, backtestDownload } from "../lib/backtestApi";

afterEach(() => { mocks.response.mockReset(); vi.restoreAllMocks(); });

it("maps platform 504 to the exact timeout text in content", async () => {
  mocks.response.mockResolvedValue(new Response("Gateway timeout", { status: 504 }));
  await expect(backtestRequest("/api/backtest")).rejects.toThrow(text.timeout);
});

it("surfaces a plain validated engine 400 and never a raw gateway body", async () => {
  mocks.response.mockResolvedValue(new Response(JSON.stringify({ detail: "Mock missing adjusted opens" }), { status: 400 }));
  await expect(backtestRequest("/api/backtest")).rejects.toThrow("Mock missing adjusted opens");
  mocks.response.mockResolvedValue(new Response("Mock gateway private debug data", { status: 502 }));
  await expect(backtestRequest("/api/backtest")).rejects.toThrow(text.requestError);
});

it("downloads the exact server CSV bytes through authorization", async () => {
  const csv = "date,tax_paid\n2024-01-01,1.25\n";
  const raw = new Blob([csv]);
  mocks.response.mockResolvedValue({ ok: true, blob: async () => raw });
  const create = vi.fn((_blob: Blob) => "blob:mock");
  Object.defineProperty(URL, "createObjectURL", { configurable: true, value: create });
  Object.defineProperty(URL, "revokeObjectURL", { configurable: true, value: vi.fn() });
  const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  await backtestDownload("mock-key", "tax_events", "ledger.csv");
  expect(mocks.response).toHaveBeenCalledWith("/api/backtest/download?key=mock-key&kind=tax_events");
  expect(create).toHaveBeenCalledWith(raw);
  expect(click).toHaveBeenCalledOnce();
});
