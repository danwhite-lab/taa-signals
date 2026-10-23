import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/rebalance.json";
const mock = vi.hoisted(() => ({ request: vi.fn(), save: vi.fn(), mode: vi.fn() }));
vi.mock("../lib/rebalanceApi", () => ({ rebalanceRequest: mock.request, saveHoldings: mock.save, saveAllocationMode: mock.mode,
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
const state = { workspace_revision: 1, allocation_mode: "proportional", account_hash: "fake-hash", account: { revision: 0, cash_ils: "5" }, portfolio_id: "fake-portfolio",
  portfolios: [{ id: "fake-portfolio", name: "Fake portfolio" }], rows: [row], instruments: { [item.id]: item, [other.id]: other },
  quotes: { [item.id]: { price: "10", as_of: "2026-10-15", source: "Mock raw", fresh: true } }, fx: { fresh: true },
  comparison: [{ id: item.id, Fund: item.label, target_display: "100.00%", actual_display: "100.00%", Status: "On target" }],
  total_display: "₪75.00", full_total_display: "₪75.00", full_total_ils: "75", ready: true, blocked: [], held_blocked: [], partial: false,
  overweight: false, signals: [], errors: [], source_settings: "Mock sources", seconds: .01 };
const candidate = { ...state.account, last_operation_id: "fake-operation", revision: 1 };
const preview = { account: candidate, preview: [{ Fund: item.label, "Units to save": "2.00" }], errors: [] };
const plan = { id: "fake-plan", orders: [{ id: item.id, units: 2, estimated_ils: "70" }], leftover_ils: "5" };

afterEach(() => { cleanup(); mock.request.mockReset(); mock.save.mockReset(); mock.mode.mockReset(); vi.restoreAllMocks(); });
it("filters by fields, preserves a hidden selection and performs no requests while browsing", async () => {
  await ready(); const local = {id:"TASE:1234567",identifier:"1234567",market:"TASE",currency:"USD",label:"Example local dollar fund"};
  const localIls = {...local,id:"TASE:7654321",identifier:"7654321",currency:"ILS",label:"Example shekel fund"};
  const next={...state,instruments:{...state.instruments,[local.id]:local,[localIls.id]:localIls}};
  mock.request.mockResolvedValue(next);
  fireEvent.click(screen.getByText(text.advanced)); fireEvent.click(screen.getByText(text.reload));
  await waitFor(()=>expect(mock.request.mock.calls.length).toBe(2));
  fireEvent.click(screen.getByText(text.add));
  const search=screen.getByRole("combobox",{name:text.search});
  const list=screen.getByRole("listbox");
  const market=screen.getByRole("group",{name:text.market}), currency=screen.getByRole("group",{name:text.currency});
  const before=mock.request.mock.calls.length;
  for(const [query,label] of [["gOlD",item.label],["ief",other.label],["1234567",local.label]]) {
    fireEvent.change(search,{target:{value:query}});
    expect(within(list).getAllByRole("option").map(n=>n.textContent)).toHaveLength(1);
    expect(within(list).getByText(label)).toBeTruthy();
  }
  fireEvent.keyDown(search,{key:"ArrowDown"}); fireEvent.keyDown(search,{key:"Enter"});
  expect(screen.getByText(text.selected+": "+local.label)).toBeTruthy();
  fireEvent.change(search,{target:{value:""}});
  fireEvent.click(within(market).getByRole("button",{name:"TASE"}));
  fireEvent.click(within(currency).getByRole("button",{name:"USD"}));
  expect(within(list).getAllByRole("option")).toHaveLength(1);
  expect(within(list).getByText(local.label)).toBeTruthy();
  fireEvent.click(within(market).getByRole("button",{name:"US"}));
  fireEvent.click(within(currency).getByRole("button",{name:"ILS"}));
  expect(screen.getByText(text.noResults)).toBeTruthy();
  expect(within(market).getAllByRole("button").filter(b=>b.getAttribute("aria-pressed")==="true")).toHaveLength(1);
  expect(mock.request.mock.calls.length).toBe(before); expect(mock.save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText(text.addSelected));
  await screen.findByLabelText(text.columns.Units+" "+local.id);
  expect(screen.getByLabelText(text.columns.Units+" "+local.id).closest("article")?.textContent).toContain("USD");
  fireEvent.click(screen.getByText(text.notFound));
  expect(screen.getByRole("combobox",{name:text.market})).toHaveProperty("value","US");
  expect(screen.getByRole("combobox",{name:text.currency})).toHaveProperty("value","");
});

it("minus hides the whole row but preserves removal in requests and every other draft field", async () => {
  await ready();const extra={...row,Security:other.id,Fund:other.label,Units:"8"};
  const next={...state,rows:[row,extra]};
  let savedRemoval=false;
  mock.request.mockImplementation(async(path:string)=>path==="/api/rebalance/editor"?preview:savedRemoval
    ?{...next,rows:[{...extra,Units:"9","Outside the rebalance":true}],account:{...state.account,cash_ils:"13"}}:next);
  mock.save.mockImplementation(async()=>{savedRemoval=true;return {saved:{revision:2,payload:{holdings_account:candidate}},uncertain:false};});
  fireEvent.click(screen.getByText(text.advanced));fireEvent.click(screen.getByText(text.reload));
  await screen.findByLabelText(text.columns.Units+" "+other.id);
  fireEvent.click(screen.getByText(text.add));
  fireEvent.change(screen.getByRole("combobox",{name:text.search}),{target:{value:"gld"}});
  fireEvent.click(within(screen.getByRole("listbox")).getByText(item.label));
  fireEvent.click(within(screen.getByRole("group",{name:text.market})).getByRole("button",{name:"US"}));
  fireEvent.change(screen.getByLabelText(text.columns.Units+" "+other.id),{target:{value:"9"}});
  fireEvent.change(screen.getByLabelText(text.cash),{target:{value:"13"}});
  fireEvent.click(screen.getByLabelText(text.columns["Outside the rebalance"]+" "+other.id));
  fireEvent.click(screen.getByRole("button",{name:"Remove "+item.label}));
  expect(screen.queryByRole("listitem",{name:item.label})).toBeNull();
  for(const key of ["Units","Manual price per unit","Price date"] as const) expect(screen.queryByLabelText(text.columns[key]+" "+item.id)).toBeNull();
  expect(screen.queryByText("Removed when you save")).toBeNull();expect(screen.queryByRole("button",{name:/Undo removal/})).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("heading",{name:text.holdings}));
  expect(screen.getByText(text.unsaved)).toBeTruthy(); expect(mock.save).not.toHaveBeenCalled();
  expect(screen.getByLabelText(text.columns.Units+" "+other.id)).toHaveProperty("value","9");
  expect(screen.getByLabelText(text.cash)).toHaveProperty("value","13");
  expect(screen.getByLabelText(text.columns["Outside the rebalance"]+" "+other.id)).toHaveProperty("checked",true);
  expect(screen.getByRole("combobox",{name:text.search})).toHaveProperty("value","gld");
  expect(screen.getByText(text.selected+": "+item.label)).toBeTruthy();
  fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(()=>expect(mock.request.mock.calls.some(([p,b])=>p==="/api/rebalance/editor"&&b.rows[0].Remove)).toBe(true));
  fireEvent.click(screen.getByText(text.save));await waitFor(()=>expect(mock.save).toHaveBeenCalled());
  const drafts=mock.request.mock.calls.filter(([p])=>p==="/api/rebalance/editor");
  expect(drafts.at(-1)![1]).toMatchObject({cash:"13",rows:[{...row,Remove:true},{...extra,Units:"9","Units edited":true,"Outside the rebalance":true}]});
  expect(mock.save).toHaveBeenCalledWith(state.workspace_revision,candidate);
  await waitFor(()=>expect(screen.getByText(text.save)).toHaveProperty("disabled",false));
  expect(screen.queryByRole("listitem",{name:item.label})).toBeNull();
  fireEvent.click(screen.getByText(text.reload));
  await waitFor(()=>expect(screen.getByText(text.save)).toHaveProperty("disabled",false));
  expect(screen.queryByRole("listitem",{name:item.label})).toBeNull();
});

it("re-adding a hidden holding restores its exact draft without appending a duplicate",async()=>{
  await ready();fireEvent.change(screen.getByLabelText(text.columns.Units+" "+item.id),{target:{value:"7"}});
  fireEvent.click(screen.getByRole("button",{name:"Remove "+item.label}));
  expect(screen.getAllByRole("list")).toHaveLength(1);
  expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  fireEvent.click(screen.getByText(text.add));fireEvent.click(within(screen.getByRole("listbox")).getByText(item.label));
  fireEvent.click(screen.getByText(text.addSelected));
  await screen.findByLabelText(text.columns.Units+" "+item.id);
  expect(screen.getAllByRole("listitem")).toHaveLength(1);
  expect(screen.getByLabelText(text.columns.Units+" "+item.id)).toHaveProperty("value","7");
  fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(()=>expect(mock.request.mock.calls.some(([p])=>p==="/api/rebalance/editor")).toBe(true));
  const body=mock.request.mock.calls.filter(([p])=>p==="/api/rebalance/editor").at(-1)![1];
  expect(body.rows).toHaveLength(1);expect(body.rows[0]).toMatchObject({Remove:false,Units:"7"});
  expect(mock.save).not.toHaveBeenCalled();
});

async function ready() {
  mock.request.mockImplementation(async (path: string) => path === "/api/rebalance/editor" ? preview : path === "/api/rebalance/plan" ? { state, plan } : state);
  mock.save.mockResolvedValue({ saved: { revision: 2, payload: { holdings_account: candidate } }, uncertain: false });
  render(<Page />); await screen.findByText(text.holdings);
  await waitFor(() => expect(screen.getByText(text.save)).toHaveProperty("disabled", false));
}

it('sorts known securities by label and leaves the empty choice selected',async()=>{
  await ready(); fireEvent.click(screen.getByText(text.add));
  expect(screen.getAllByRole("option").filter(node=>node.parentElement?.getAttribute("role")==="listbox").map(node=>node.textContent)).toEqual([other.label+"US · IEF · USD",item.label+"US · GLD · USD"]);
  expect(screen.getByRole("button",{name:text.addSelected})).toHaveProperty("disabled",true);
});

it("requires the existing login gate before fetching holdings", async () => {
  render(<AuthGate><Page /></AuthGate>); await screen.findByText("Sign in with Google"); expect(mock.request).not.toHaveBeenCalled();
});

it("last edited value/units wins, outside edits invalidate the plan, and draft adds preserve inputs", async () => {
  await ready();
  fireEvent.click(screen.getByRole("button",{name:text.generate})); await screen.findByText(text.leftover+": 5.00");
  fireEvent.change(screen.getByLabelText(`${text.columns["Value (₪ / $)"]} US:GLD`), { target: { value: "125" } });
  expect(screen.getByRole("button",{name:text.generate})).toHaveProperty("disabled", true);
  expect(screen.queryByText(text.leftover+": 5.00")).toBeNull();
  fireEvent.click(screen.getByText(text.add));
  fireEvent.click(within(screen.getByRole("listbox")).getByText(other.label));
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
  fireEvent.click(screen.getByRole("button",{name:text.generate})); fireEvent.click(await screen.findByText(text.record));
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
  fireEvent.click(screen.getByRole("button",{name:text.generate})); fireEvent.click(await screen.findByText(text.record));
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
  fireEvent.click(screen.getByRole("button",{name:text.generate})); await screen.findByText(text.emptyPlan);
  expect(screen.queryByText(text.record)).toBeNull();
});

it("starts current rows collapsed, retains edits across price disclosure toggles, and sends the same fields", async () => {
  await ready();
  const holding = screen.getByRole("listitem", {name:item.label});
  const details = within(holding).getByText("Edit price").closest("details")!;
  expect(details.open).toBe(false);
  fireEvent.change(screen.getByLabelText(`${text.columns["Value (₪ / $)"]} ${item.id}`), {target:{value:"125"}});
  fireEvent.click(within(holding).getByText("Edit price"));
  fireEvent.change(screen.getByLabelText(`${text.columns["Manual price per unit"]} ${item.id}`), {target:{value:"11"}});
  fireEvent.click(within(holding).getByText("Edit price"));
  expect(screen.getByLabelText(`${text.columns["Value (₪ / $)"]} ${item.id}`)).toHaveProperty("value","125");
  expect(screen.getByLabelText(`${text.columns["Manual price per unit"]} ${item.id}`)).toHaveProperty("value","11");
  fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(()=>expect(mock.request.mock.calls.some(([p])=>p==="/api/rebalance/editor")).toBe(true));
  expect(mock.request.mock.calls.find(([p])=>p==="/api/rebalance/editor")![1].rows).toEqual([
    {...row,"Value (₪ / $)":"125","Enter as":"Value","Manual price per unit":"11"}
  ]);
  expect(screen.getByRole("button",{name:text.save}).classList.contains("btn-primary")).toBe(true);
});

it.each(["stale","missing","manual"])("starts %s holding price controls expanded",async kind=>{
  const modified = {...state, rows:[{...row,"Manual price per unit":kind==="manual"?"11":null}],
    quotes:kind==="missing"?{}:{[item.id]:{...state.quotes[item.id],fresh:kind!=="stale"}}};
  mock.request.mockResolvedValue(modified);
  render(<Page/>);
  const holding=await screen.findByRole("listitem",{name:item.label});
  expect(within(holding).getByText("Edit price").closest("details")).toHaveProperty("open",true);
  if(kind!=="missing")expect(within(holding).getByText("Mock raw")).toBeTruthy();
});

it("shows the persisted proportional default and unspent pooled shares with server-priced unit costs",async()=>{
  await ready();
  expect(screen.getByLabelText(text.allocationMode)).toHaveProperty("value","proportional");
  mock.request.mockResolvedValue({state,plan:{...plan,unspent_by_fund:{[item.id]:"12.50"},unit_costs_ils:{[item.id]:"35"}}});
  fireEvent.click(screen.getByRole("button",{name:text.generate}));
  await screen.findByText(text.unspentShare.replace("{fund}",item.label).replace("{unspent}","12.50").replace("{cost}","35.00"));
  expect(screen.getByText(text.pooledCash)).toBeTruthy();
  expect(screen.queryByText(text.singleOrder)).toBeNull();
});

it("saves a mode change through the workspace route and invalidates a pending list",async()=>{
  await ready();
  fireEvent.click(screen.getByRole("button",{name:text.generate})); await screen.findByText(text.leftover+": 5.00");
  mock.mode.mockResolvedValue({revision:2,payload:{rebalance_allocation_mode:"biggest_gap_first"}});
  mock.request.mockResolvedValue({...state,workspace_revision:2,allocation_mode:"biggest_gap_first"});
  fireEvent.change(screen.getByLabelText(text.allocationMode),{target:{value:"biggest_gap_first"}});
  await waitFor(()=>expect(screen.getByLabelText(text.allocationMode)).toHaveProperty("disabled",false));
  expect(mock.mode).toHaveBeenCalledWith(1,"biggest_gap_first");
  expect(screen.getByLabelText(text.allocationMode)).toHaveProperty("value","biggest_gap_first");
  expect(screen.queryByText(text.leftover+": 5.00")).toBeNull();
  expect(mock.save).not.toHaveBeenCalled();
});

it("mode changes preserve dirty holdings and failed preference writes pause safely",async()=>{
  await ready();
  const input=screen.getByLabelText(text.columns.Units+" "+item.id);
  fireEvent.change(input,{target:{value:"7"}});
  mock.mode.mockRejectedValue(new RebalanceError(409,text.uncertain));
  fireEvent.change(screen.getByLabelText(text.allocationMode),{target:{value:"biggest_gap_first"}});
  await screen.findByText(text.uncertain);
  expect(input).toHaveProperty("value","7");
  expect(screen.getByText(text.save)).toHaveProperty("disabled",true);
  expect(mock.save).not.toHaveBeenCalled();
});

it("a successful mode save and display refresh preserve unsaved units and cash",async()=>{
  await ready();
  fireEvent.change(screen.getByLabelText(text.columns.Units+" "+item.id),{target:{value:"7"}});
  fireEvent.change(screen.getByLabelText(text.cash),{target:{value:"17"}});
  mock.mode.mockResolvedValue({revision:2,payload:{rebalance_allocation_mode:"biggest_gap_first"}});
  mock.request.mockResolvedValue({...state,workspace_revision:2,allocation_mode:"biggest_gap_first"});
  fireEvent.change(screen.getByLabelText(text.allocationMode),{target:{value:"biggest_gap_first"}});
  await waitFor(()=>expect(screen.getByLabelText(text.allocationMode)).toHaveProperty("disabled",false));
  expect(screen.getByLabelText(text.columns.Units+" "+item.id)).toHaveProperty("value","7");
  expect(screen.getByLabelText(text.cash)).toHaveProperty("value","17");
  expect(mock.save).not.toHaveBeenCalled();
});

it("groups holdings before buying and keeps Advanced closed initially",async()=>{
  await ready();
  const controls=screen.getByRole("group",{name:text.controls});
  const editor=screen.getByRole("list",{name:text.holdings});
  expect(editor.compareDocumentPosition(controls)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  for(const caption of [text.newMoney,text.allocationMode]){
    expect(screen.getAllByLabelText(caption)).toHaveLength(1);
    expect(within(controls).getByLabelText(caption)).toBeTruthy();
  }
  for(const caption of [text.save,text.generate]){
    expect(screen.getAllByRole("button",{name:caption})).toHaveLength(1);
    expect(screen.getByRole("button",{name:caption}).classList.contains("btn-primary")).toBe(true);
  }
  const advanced=screen.getByText(text.advanced).closest("details")!;
  expect(advanced.open).toBe(false);
  for(const caption of [text.reload,text.previewAction]){
    expect(screen.getAllByRole("button",{name:caption,hidden:true})).toHaveLength(1);
    expect(within(advanced).getByText(caption)).toBeTruthy();
  }
  expect(within(advanced).getByText(text.fx)).toBeTruthy();
  expect(within(advanced).getByText(text.automaticCaption)).toBeTruthy();
  fireEvent.click(screen.getByText(text.advanced));
  expect(advanced.open).toBe(true);
  const holding=screen.getByRole("listitem",{name:item.label});
  expect(within(holding).getByText(text.manualCaption).closest(".holding-price-editor")).toBeTruthy();
  expect(screen.getAllByText(text.manualCaption)).toHaveLength(1);
});

it("Advanced retains the existing unsaved reload confirmation and preview flow",async()=>{
  await ready(); fireEvent.click(screen.getByText(text.advanced));
  fireEvent.change(screen.getByLabelText(text.cash),{target:{value:"17"}});
  const confirm=vi.spyOn(window,"confirm").mockReturnValue(false);
  const before=mock.request.mock.calls.length;
  fireEvent.click(screen.getByText(text.reload));
  expect(confirm).toHaveBeenCalledWith(text.reloadConfirm);
  expect(mock.request.mock.calls).toHaveLength(before);
  expect(screen.getByRole("button",{name:text.generate})).toHaveProperty("disabled",true);
  fireEvent.click(screen.getByText(text.previewAction));
  await screen.findByText(text.preview);
  expect(screen.getByLabelText(text.cash)).toHaveProperty("value","17");
  expect(mock.save).not.toHaveBeenCalled();
});
