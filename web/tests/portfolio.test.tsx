import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";

const calls = vi.hoisted(() => ({ api: vi.fn(), signOut: vi.fn() }));
vi.mock("../lib/api", () => ({ api: calls.api }));
vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: { signOut: calls.signOut } }) }));
import Portfolio from "../app/portfolio/page";

const payload = { version: 1, name: "Fake portfolio", sleeves: [{ model: "Buy and Hold SPY", weight: 100 }], total_ils: 100, ils_per_usd: 4 };
const saved = { id: "fake-id", name: "Fake portfolio", payload, updated_at: "mock-timestamp", is_default: true };
afterEach(() => { cleanup(); calls.api.mockReset(); vi.restoreAllMocks(); });

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
  vi.spyOn(window,"confirm").mockReturnValue(true);
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

it("loads the library automatically and marks the loaded selection",async()=>{
  mockLoad();render(<Portfolio/>);
  const button=await screen.findByRole("button",{name:"Fake portfolio · Default"});
  await waitFor(()=>expect(button).toHaveProperty("disabled",false));
  expect(calls.api.mock.calls.filter(([path])=>path==="/api/portfolios")).toHaveLength(1);
  expect(button.getAttribute("aria-pressed")).toBe("false");fireEvent.click(button);
  expect(button.getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
});

it.each(["Portfolio name","Portfolio JSON","Make this the default when saving"])("guards unsaved %s against replacing the form",async field=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  const second={...saved,id:"fake-second",name:"Fake second",payload:{...payload,name:"Fake second"}};
  calls.api.mockImplementation(async(path,init)=>path==="/api/portfolios"?[saved,second]:original(path,init));
  const confirm=vi.spyOn(window,"confirm").mockReturnValue(false);
  render(<Portfolio/>);fireEvent.click(await screen.findByText("Fake portfolio · Default"));
  const input=screen.getByLabelText(field);
  if(field==="Make this the default when saving")fireEvent.click(input);
  else fireEvent.change(input,{target:{value:"Unsaved fake draft"}});
  fireEvent.click(screen.getByText("Fake second · Default"));
  expect(confirm).toHaveBeenCalledOnce();expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
  expect(input).toHaveProperty(field==="Make this the default when saving"?"checked":"value",field==="Make this the default when saving"?false:"Unsaved fake draft");
  confirm.mockReturnValue(true);fireEvent.click(screen.getByText("Fake second · Default"));
  expect(screen.getByText("Loaded: Fake second")).toBeTruthy();
  expect(screen.getByLabelText("Portfolio name")).toHaveProperty("value","Fake second");
});

it("guards New portfolio and manual refresh, including workspace edits",async()=>{
  mockLoad();const confirm=vi.spyOn(window,"confirm").mockReturnValue(false);
  render(<Portfolio/>);fireEvent.click(await screen.findByText("Fake portfolio · Default"));
  fireEvent.change(screen.getByLabelText("Portfolio name"),{target:{value:"Unsaved fake draft"}});
  fireEvent.click(screen.getByText("New portfolio"));expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
  fireEvent.click(screen.getByText("Reload saved data"));expect(calls.api.mock.calls.filter(([path])=>path==="/api/portfolios")).toHaveLength(1);
  confirm.mockReturnValue(true);fireEvent.click(screen.getByText("New portfolio"));
  expect(screen.queryByText("Loaded: Fake portfolio")).toBeNull();
  fireEvent.change(screen.getByLabelText("Workspace portfolio name"),{target:{value:"Fake unsaved preference"}});
  confirm.mockReturnValue(false);fireEvent.click(screen.getByText("Reload saved data"));
  expect(screen.getByLabelText("Workspace portfolio name")).toHaveProperty("value","Fake unsaved preference");
});

it("still lists saved portfolios if another initial read fails",async()=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async(path,init)=>{if(path==="/api/workspace")throw new Error("Mock read failed");return original(path,init);});
  render(<Portfolio/>);await screen.findByRole("alert");expect(await screen.findByText("Fake portfolio · Default")).toBeTruthy();
});

it("workspace form saves one preference using its loaded revision, not fabricated holdings", async () => {
  mockLoad(); render(<Portfolio />);
  await screen.findByText("Fake portfolio · Default");
  fireEvent.click(screen.getByText("Save workspace preference"));
  await screen.findByText("Workspace saved.");
  const [, init] = calls.api.mock.calls.find(([, init]) => init?.method === "PUT")!;
  expect(JSON.parse(init.body)).toEqual({ revision: 7, payload: { portfolio_name: "Fake preference" } });
});
