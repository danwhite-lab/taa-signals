import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";

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

it("shows a readable loaded summary above the form and keeps JSON collapsed",async()=>{
  mockLoad();render(<Portfolio/>);const button=await screen.findByText("Fake portfolio · Default");
  expect(screen.queryByRole("region",{name:"Portfolio summary"})).toBeNull();fireEvent.click(button);
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).getByRole("heading",{name:"Fake portfolio"})).toBeTruthy();
  expect(within(summary).getByText("Default")).toBeTruthy();
  expect(within(summary).getByText("₪100.00")).toBeTruthy();expect(within(summary).getByText("4")).toBeTruthy();
  const table=within(summary).getByRole("table",{name:"Portfolio sleeves"});
  expect(within(table).getByRole("columnheader",{name:"Sleeve name"})).toBeTruthy();
  expect(within(table).getByRole("columnheader",{name:"Weight"})).toBeTruthy();
  expect(within(table).getByText("Buy and Hold SPY")).toBeTruthy();
  expect(within(table).getAllByText("100.00%")).toHaveLength(2);
  expect(summary.compareDocumentPosition(screen.getByRole("heading",{name:"Edit saved portfolio"}))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const advanced=screen.getByText("Advanced: edit JSON").closest("details")!;
  expect(advanced).toHaveProperty("open",false);expect(advanced.contains(screen.getByLabelText("Portfolio JSON"))).toBe(true);
  expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
});

it("updates the summary from edits and saves full precision without changing the request contract",async()=>{
  mockLoad();render(<Portfolio/>);fireEvent.click(await screen.findByText("Fake portfolio · Default"));
  fireEvent.change(screen.getByLabelText("Portfolio name"),{target:{value:"Fake edited name"}});
  screen.getByText("Advanced: edit JSON").closest("details")!.open=true;
  const edited={...payload,total_ils:12345.6789,ils_per_usd:3.14159,sleeves:[
    {model:"Fake long sleeve name with multiple whole words",weight:33.333333},
    {model:"Fake second sleeve",weight:66.666667}]};
  fireEvent.change(screen.getByLabelText("Portfolio JSON"),{target:{value:JSON.stringify(edited)}});
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).getByRole("heading",{name:"Fake edited name"})).toBeTruthy();
  for(const value of ["₪12,345.68","3.14","33.33%","66.67%","100.00%","Fake second sleeve"])
    expect(within(summary).getByText(value)).toBeTruthy();
  expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
  fireEvent.click(screen.getByText("Save portfolio"));await screen.findByText("Portfolio saved.");
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==="POST")!;
  expect(JSON.parse(init.body)).toEqual({id:saved.id,expected_updated_at:saved.updated_at,is_default:true,payload:{...edited,name:"Fake edited name"}});
});

it("updates a pending default badge but does not pretend unchecking clears a saved default",async()=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async(path,init)=>path==="/api/portfolios"?[{...saved,is_default:false}]:original(path,init));
  render(<Portfolio/>);fireEvent.click(await screen.findByRole("button",{name:"Fake portfolio"}));
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).queryByText("Default")).toBeNull();
  fireEvent.click(screen.getByLabelText("Make this the default when saving"));
  expect(within(summary).getByText("Default on save")).toBeTruthy();
  fireEvent.click(screen.getByLabelText("Make this the default when saving"));
  expect(within(summary).queryByText("Default on save")).toBeNull();
  cleanup();mockLoad();render(<Portfolio/>);fireEvent.click(await screen.findByText("Fake portfolio · Default"));
  fireEvent.click(screen.getByLabelText("Make this the default when saving"));
  expect(within(screen.getByRole("region",{name:"Portfolio summary"})).getByText("Default")).toBeTruthy();
});

it("does not show stale saved numbers or invented totals for invalid or incomplete draft JSON",async()=>{
  mockLoad();render(<Portfolio/>);fireEvent.click(await screen.findByText("Fake portfolio · Default"));
  fireEvent.change(screen.getByLabelText("Portfolio JSON"),{target:{value:"{"}});
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).getByRole("alert").textContent).toContain("Summary unavailable");
  expect(within(summary).queryByText("₪100.00")).toBeNull();expect(within(summary).queryByRole("table")).toBeNull();
  fireEvent.change(screen.getByLabelText("Portfolio JSON"),{target:{value:JSON.stringify({sleeves:[{model:"Fake missing weight"}]})}});
  const table=within(summary).getByRole("table");
  expect(within(table).getAllByText("Unavailable")).toHaveLength(2);
  expect(within(table).queryByText("100.00%")).toBeNull();
  expect(calls.api.mock.calls.some(([,init])=>init?.method==="POST")).toBe(false);
});

it("shows the actual draft total rather than normalizing weights to 100",async()=>{
  mockLoad();render(<Portfolio/>);fireEvent.click(await screen.findByText("Fake portfolio · Default"));
  fireEvent.change(screen.getByLabelText("Portfolio JSON"),{target:{value:JSON.stringify({...payload,sleeves:[
    {model:"Fake first",weight:50},{model:"Fake second",weight:40}]})}});
  const table=screen.getByRole("table",{name:"Portfolio sleeves"});
  expect(within(table).getByRole("row",{name:/Total/}).textContent).toBe("Total90.00%");
});

it("keeps phone wrapping and overflow rules local to Portfolio without mid-word breaks",()=>{
  const css=readFileSync("./app/portfolio/portfolio.module.css","utf8");
  expect(css).toContain("word-break: normal");expect(css).toContain("overflow-wrap: normal");
  expect(css).toContain("overflow-x: auto");expect(css).toContain("flex-wrap: wrap");
  expect(css).not.toMatch(/break-all|break-word|anywhere|overflow:\s*hidden/);
});
