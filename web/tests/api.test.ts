import { afterEach, expect, it, vi } from "vitest";

vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: {
  getSession: async () => ({ error: null, data: { session: { access_token: "fake-token" } } }),
} }) }));
import { api } from "../lib/api";
afterEach(() => vi.unstubAllGlobals());

it("sends only the access token as Bearer and prevents browser caching", async () => {
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ revision: 7 })));
  vi.stubGlobal("fetch", fetcher);
  expect(await api("/api/workspace")).toEqual({ revision: 7 });
  const [, init] = fetcher.mock.calls[0] as unknown as [string, RequestInit];
  expect(new Headers(init.headers).get("Authorization")).toBe("Bearer fake-token");
  expect(init.cache).toBe("no-store");
});

it("returns a conflict without echoing a private server response", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => new Response("mock-private-value", { status: 409 })));
  await expect(api("/api/workspace")).rejects.toMatchObject({ status: 409 });
  await expect(api("/api/workspace")).rejects.toThrow("Reload");
  try { await api("/api/workspace"); } catch (error) { expect(String(error)).not.toContain("mock-private-value"); }
});
