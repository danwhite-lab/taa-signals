import { afterEach, beforeEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ create: vi.fn(), exchange: vi.fn() }));
vi.mock("@supabase/supabase-js", () => ({ createClient: mocks.create }));

beforeEach(() => {
  vi.resetModules(); mocks.create.mockReset(); mocks.exchange.mockReset();
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_URL", "https://mock.invalid");
  vi.stubEnv("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY", "mock-public");
  mocks.create.mockReturnValue({ auth: { exchangeCodeForSession: mocks.exchange } });
});
afterEach(() => { vi.unstubAllEnvs(); window.history.replaceState({}, "", "/"); });

it("initializes exactly one browser client with PKCE and browser-owned refresh", async () => {
  const { supabaseBrowser } = await import("../lib/supabaseBrowser");
  expect(supabaseBrowser()).toBe(supabaseBrowser());
  expect(mocks.create).toHaveBeenCalledTimes(1);
  expect(mocks.create).toHaveBeenCalledWith("https://mock.invalid", "mock-public", {
    auth: { flowType: "pkce", persistSession: true, autoRefreshToken: true, detectSessionInUrl: false },
  });
});

it("exchanges a PKCE code once and removes it from the URL", async () => {
  window.history.replaceState({}, "", "/auth/callback/?code=mock-code");
  mocks.exchange.mockResolvedValue({ error: null });
  const { completeLogin } = await import("../lib/supabaseBrowser");
  await Promise.all([completeLogin(), completeLogin()]);
  expect(mocks.exchange).toHaveBeenCalledExactlyOnceWith("mock-code");
  expect(window.location.search).toBe("");
});

it("does not echo a provider error or PKCE code on failure", async () => {
  window.history.replaceState({}, "", "/auth/callback/?code=mock-code");
  mocks.exchange.mockResolvedValue({ error: new Error("mock-private-token") });
  const { completeLogin } = await import("../lib/supabaseBrowser");
  await expect(completeLogin()).rejects.toThrow("same browser");
  expect(window.location.search).toBe("");
});
