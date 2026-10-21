import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const mock = vi.hoisted(() => ({ pathname: "/portfolio/", session: null as null | { user: { id: string } },
  callback: null as null | ((event: string, session: unknown) => void),
  oauth: vi.fn(async () => ({ error: null })), signout: vi.fn(), unsubscribe: vi.fn() }));
vi.mock("next/navigation", () => ({ usePathname: () => mock.pathname }));
vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: {
  getSession: async () => ({ data: { session: mock.session }, error: null }),
  onAuthStateChange: (callback: (event: string, session: unknown) => void) => {
    mock.callback = callback; return { data: { subscription: { unsubscribe: mock.unsubscribe } } };
  }, signInWithOAuth: mock.oauth, signOut: mock.signout,
} }) }));
import AuthGate from "../components/AuthGate";
import Login from "../app/login/page";
import { api } from "../lib/api";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); mock.session = null; mock.pathname = "/portfolio/"; });

describe("browser authentication", () => {
  it("never mounts private data until a session exists", async () => {
    render(<AuthGate><p>Private mock data</p></AuthGate>);
    await screen.findByText("Sign in with Google");
    expect(screen.queryByText("Private mock data")).toBeNull();
  });
  it("mounts a signed-in user and unsubscribes on unmount", async () => {
    mock.session = { user: { id: "fake-user" } };
    const mounted = render(<AuthGate><p>Private mock data</p></AuthGate>);
    await screen.findByText("Private mock data"); mounted.unmount();
    expect(mock.unsubscribe).toHaveBeenCalled();
  });
  it("removes private content as soon as the browser signs out", async () => {
    mock.session = { user: { id: "fake-user" } };
    render(<AuthGate><p>Private mock data</p></AuthGate>);
    await screen.findByText("Private mock data");
    await act(async () => mock.callback?.("SIGNED_OUT", null));
    expect(screen.queryByText("Private mock data")).toBeNull();
  });
  it("login uses Google and the fixed callback at this origin", async () => {
    render(<Login />); fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(mock.oauth).toHaveBeenCalledWith({ provider: "google",
      options: { redirectTo: `${window.location.origin}/auth/callback/` } }));
  });
  it("API rejects absent sessions before fetching", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    await expect(api("/api/workspace")).rejects.toThrow("Sign in");
    expect(fetcher).not.toHaveBeenCalled();
  });
});
