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
import AuthGate, { SignedInUserContext } from "../components/AuthGate";
import {activateDeviceUser,syncPortfolio,saveDeviceResult,resultKey} from "../lib/device-results";
import { useContext } from "react";
import Login from "../app/login/page";
import { api } from "../lib/api";

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); mock.session = null; mock.pathname = "/portfolio/"; });

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

it("provides the signed-in account scope and changes it when the account changes", async () => {
  function AccountScope() { return <p>{useContext(SignedInUserContext)}</p>; }
  mock.session = {user:{id:"user-a"}};
  render(<AuthGate><AccountScope/></AuthGate>);
  await screen.findByText("user-a");
  await act(async()=>mock.callback?.("SIGNED_IN",{user:{id:"user-b"}}));
  expect(screen.queryByText("user-a")).toBeNull();
  expect(screen.getByText("user-b")).toBeTruthy();
});

it("clears all saved result sections on the auth sign-out event", async()=>{
  mock.session={user:{id:"a"}};activateDeviceUser("a");
  const scope={userId:"a",portfolio:syncPortfolio("a",[{id:"p",is_default:true,updated_at:"one",payload:{}}])!};
  for(const key of ["today","health","preview"])saveDeviceResult(scope,key,{},()=>true);
  render(<AuthGate><p>Signed in</p></AuthGate>);await screen.findByText("Signed in");
  await act(async()=>mock.callback?.("SIGNED_OUT",null));
  for(const key of ["today","health","preview"])expect(localStorage.getItem(resultKey(scope,key))).toBeNull();
});
it("invalidates saved results only after a successful portfolio mutation",async()=>{
  mock.session={user:{id:"a"}};activateDeviceUser("a");
  const scope={userId:"a",portfolio:syncPortfolio("a",[{id:"p",is_default:true,updated_at:"one",payload:{}}])!};
  saveDeviceResult(scope,"health",{},()=>true);
  vi.stubGlobal("fetch",vi.fn(async()=>new Response(JSON.stringify({id:"p"}))));
  await api("/api/portfolios",{method:"POST",body:"{}"});
  expect(localStorage.getItem(resultKey(scope,"health"))).toBeNull();
});
