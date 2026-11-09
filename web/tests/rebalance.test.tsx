import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/rebalance.json";
import holdings from "../content/holdings.json";
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
function chooseRole(id:string,name:string){fireEvent.change(screen.getByRole('combobox',{name:holdings.role+' '+id}),{target:{value:Object.entries(holdings.roles).find(([,label])=>label===name)![0]}});}
function priceDetails(id:string){return document.getElementById('holding-options-'+encodeURIComponent(id))!;}
function expandHolding(id:string){const fund=screen.getByLabelText(text.columns.Units+' '+id).closest('tr')!;fireEvent.click(within(fund).getByRole('button',{name:/Details for/}));}


const chartRows = [
  {...row, Units:"2"},
  {...row, Security:other.id, Fund:other.label, Units:"3"},
  {...row, Security:"TASE:OUTSIDE", Fund:"Outside holding", Currency:"ILS", Units:"10"},
  {...row, Security:"US:COMPANION", Fund:"Companion holding", Units:"1"},
];
const chartState = {
  ...state,
  account:{...state.account,cash_ils:"40"}, rows:chartRows,
  instruments:{...state.instruments,
    "TASE:OUTSIDE":{id:"TASE:OUTSIDE",identifier:"1234567",market:"TASE",currency:"ILS",label:"Outside holding"},
    "US:COMPANION":{id:"US:COMPANION",identifier:"COMP",market:"US",currency:"USD",label:"Companion holding"},
  },
  quotes:{[item.id]:{price:"10"},[other.id]:{price:"5"},"TASE:OUTSIDE":{price:"10"},"US:COMPANION":{price:"5"}}, fx:{price:"4",fresh:true},
  comparison:[
    {id:item.id,Fund:item.label,target_display:"",actual_display:"",Status:"On target"},
    {id:other.id,Fund:other.label,target_display:"",actual_display:"",Status:"On target"},
    {id:"TASE:OUTSIDE",Fund:"Outside holding",target_display:"",actual_display:"",Status:"Outside the rebalance"},
    {id:"US:COMPANION",Fund:"Companion holding",target_display:"",actual_display:"",Status:"Companion",companion_of:item.id},
  ],
};
const allocationButton = (label:string) => screen.getByRole("button", {name:text.allocationToggle.replace("{holding}",label)});
const extraChartRows = ["Extra one", "Extra two", "Extra three", "Extra four"].map((Fund, index) => ({...row, Security:`TASE:EXTRA-${index}`, Fund, Currency:"ILS", Units:String(index + 2)}));
const manyChartState = {
  ...chartState, rows:[...chartRows,...extraChartRows],
  instruments:{...chartState.instruments,...Object.fromEntries(extraChartRows.map((row, index) => [row.Security,{id:row.Security,identifier:String(1234500 + index),market:"TASE",currency:"ILS",label:row.Fund}]))},
  quotes:{...chartState.quotes,...Object.fromEntries(extraChartRows.map((row, index) => [row.Security,{price:String(7 + index)}]))},
  comparison:[...chartState.comparison,...extraChartRows.map(row => ({id:row.Security,Fund:row.Fund,target_display:"",actual_display:"",Status:"On target"}))],
};

it("shows every physical holding and cash once, largest first, in the full-account chart", async () => {
  mock.request.mockResolvedValue(chartState); render(<Page />);
  await screen.findByText(text.holdings);
  fireEvent.click(screen.getByRole("button", { name: text.steps.action }));
  const chart = await screen.findByRole("img", { name: new RegExp(text.currentAllocation) });
  expect(screen.getAllByRole("button", {name:/Show or hide/}).map(button => button.getAttribute("aria-label"))).toEqual([
    text.allocationToggle.replace("{holding}","Outside holding"), text.allocationToggle.replace("{holding}",item.label),
    text.allocationToggle.replace("{holding}",other.label), text.allocationToggle.replace("{holding}",text.allocationCash),
    text.allocationToggle.replace("{holding}","Companion holding"),
  ]);
  expect(chart.getAttribute("aria-label")).toContain("Outside holding 33.3%");
  expect(chart.getAttribute("aria-label")).toContain("Companion holding 6.7%");
  expect(screen.getByText(text.allocationOutsidePlan)).toBeTruthy();
  expect(screen.getByText(text.currentAllocation).compareDocumentPosition(screen.getByText(text.rebalanceTotal)) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("recalculates visible allocation percentages and restores the full account", async () => {
  mock.request.mockResolvedValue(chartState); render(<Page />); await screen.findByText(text.holdings);
  fireEvent.click(screen.getByRole("button", {name:text.steps.action})); await screen.findByRole("img", {name:new RegExp(text.currentAllocation)});
  fireEvent.click(allocationButton("Outside holding"));
  expect(allocationButton("Outside holding").getAttribute("aria-pressed")).toBe("false");
  expect(allocationButton("Outside holding").textContent).toContain(text.allocationHidden);
  expect(allocationButton("Outside holding").textContent).not.toContain(text.unavailable);
  expect(screen.getByText(text.allocationVisibleOnly)).toBeTruthy();
  expect(allocationButton(item.label).textContent).toContain("40%");
  fireEvent.click(screen.getByRole("button", {name:text.allocationShowAll}));
  expect(screen.queryByText(text.allocationVisibleOnly)).toBeNull();
  expect(allocationButton(item.label).textContent).toContain("26.7%");
});

it("gives nine slices distinct stable colours", async () => {
  mock.request.mockResolvedValue(manyChartState); render(<Page />); await screen.findByText(text.holdings);
  fireEvent.click(screen.getByRole("button", {name:text.steps.action})); await screen.findByRole("img", {name:new RegExp(text.currentAllocation)});
  const swatch = (label:string) => allocationButton(label).querySelector(".holdings-allocation-swatch") as HTMLElement;
  const colours = [...document.querySelectorAll<HTMLElement>(".holdings-allocation-swatch")].map(node => node.style.backgroundColor);
  expect(colours).toHaveLength(9); expect(new Set(colours).size).toBe(9);
  const gold = swatch(item.label).style.backgroundColor;
  fireEvent.click(allocationButton("Extra one"));
  expect(swatch(item.label).style.backgroundColor).toBe(gold);
});

it("names an unpriceable held position instead of putting it in the chart", async () => {
  const unpriced = {...chartState, rows:[...chartRows,{...row,Security:"US:MISSING",Fund:"Missing price",Units:"2"}],instruments:{...chartState.instruments,"US:MISSING":{id:"US:MISSING",identifier:"MISS",market:"US",currency:"USD",label:"Missing price"}}};
  mock.request.mockResolvedValue(unpriced); render(<Page />); await screen.findByText(text.holdings);
  fireEvent.click(screen.getByRole("button", {name:text.steps.action}));
  await screen.findByRole("img", {name:new RegExp(text.currentAllocation)});
  expect(screen.getByText(text.allocationMissing.replace("{holdings}","Missing price"))).toBeTruthy();
  expect(screen.queryByRole("button", {name:text.allocationToggle.replace("{holding}","Missing price")})).toBeNull();
});

it('shows an unmatched companion as outside, with no target and the exclusion explanation',async()=>{
  const next={...state,targets:{[other.id]:1},comparison:[
    {id:item.id,Fund:item.label,target_display:'—',actual_display:'—',Status:'Outside the rebalance',companion_of:'US:OTHER'},
    {id:other.id,Fund:other.label,target_display:'100.00%',actual_display:'0.00%',Status:'Underweight'},
  ]};
  mock.request.mockResolvedValue(next);render(<Page/>);
  await screen.findByText(text.unmatchedCompanionNote);
  const table=screen.getByText(text.comparison).parentElement!.querySelector('table')!;
  const row=within(table).getByText(item.label).closest('tr')!;
  expect(within(row).getByText('Outside the rebalance')).toBeTruthy();
  expect(within(row).getAllByText('—')).toHaveLength(2);
  expect(within(row).queryByText(text.companionStatus)).toBeNull();
});

it('selects a companion generically, clears exclusion, and groups its comparison row once under its anchor',async()=>{
  const companion={...row,'Outside the rebalance':true};
  const next={...state,targets:{[other.id]:1},rows:[companion,{...row,Security:other.id,Fund:other.label}],comparison:[
    {id:item.id,Fund:item.label,target_display:'—',actual_display:'—',Status:'Companion',companion_of:other.id},
    {id:other.id,Fund:other.label,target_display:'100.00%',actual_display:'100.00%',Status:'On target'},
  ]};
  mock.request.mockImplementation(async(path:string)=>path==='/api/rebalance/editor'?preview:next);
  render(<Page/>);await screen.findByRole('combobox',{name:holdings.role+' '+item.id});
  chooseRole(item.id,holdings.roles.companion);
  const select=screen.getByRole('combobox',{name:holdings.companion+' '+item.id});
  expect(within(select).getByRole('option',{name:other.label})).toBeTruthy();
  expect(within(select).queryByRole('option',{name:item.label})).toBeNull();
  fireEvent.change(select,{target:{value:other.id}});
  expect(screen.getByRole('combobox',{name:holdings.role+' '+item.id})).toHaveProperty('value','companion');
  fireEvent.click(screen.getByText(text.advanced));fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(()=>expect(mock.request.mock.calls.some(([path])=>path==='/api/rebalance/editor')).toBe(true));
  const body=mock.request.mock.calls.find(([path])=>path==='/api/rebalance/editor')![1];
  expect(body.rows.find((r:Record<string,unknown>)=>r.Security===item.id)['Companion of']).toBe(other.id);
  const table=screen.getByText(text.comparison).parentElement!.querySelector('table')!;
  const rows=within(table).getAllByRole('row', {hidden:true});
  expect(rows[1].textContent).toContain(other.label);expect(rows[2].textContent).toContain(item.label);
  expect(within(table).getAllByText(item.label)).toHaveLength(1);
  expect(within(rows[2]).getByText(text.companionNote)).toBeTruthy();
  chooseRole(item.id,holdings.roles.outside);
  expect(screen.queryByRole('combobox',{name:holdings.companion+' '+item.id})).toBeNull();
});

afterEach(() => { cleanup(); mock.request.mockReset(); mock.save.mockReset(); mock.mode.mockReset(); vi.restoreAllMocks(); });
it("filters by fields, preserves a hidden selection and performs no requests while browsing", async () => {
  await ready(); const local = {id:"TASE:1234567",identifier:"1234567",market:"TASE",currency:"USD",label:"Example local dollar fund"};
  const localIls = {...local,id:"TASE:7654321",identifier:"7654321",currency:"ILS",label:"Example shekel fund"};
  const next={...state,instruments:{...state.instruments,[local.id]:local,[localIls.id]:localIls}};
  mock.request.mockResolvedValue(next);
  fireEvent.click(screen.getByText(text.advanced)); fireEvent.click(screen.getByText(text.reload));
  await waitFor(()=>expect(mock.request.mock.calls.length).toBe(2));
  fireEvent.click(screen.getByText(text.add)); await waitFor(() => expect(within(screen.getByRole("group",{name:text.search})).getAllByRole("button").length).toBeGreaterThan(0));
  const search=screen.getByRole("searchbox",{name:text.search});
  const list=screen.getByRole("group",{name:text.search});
  const market=screen.getByRole("group",{name:text.market}), currency=screen.getByRole("group",{name:text.currency});
  const before=mock.request.mock.calls.length;
  for(const [query,label] of [["gOlD",item.label],["ief",other.label],["1234567",local.label]]) {
    fireEvent.change(search,{target:{value:query}});
    expect(within(list).getAllByRole("button").map(n=>n.textContent)).toHaveLength(1);
    expect(within(list).getByText(label)).toBeTruthy();
  }
  fireEvent.keyDown(search,{key:"ArrowDown"}); fireEvent.keyDown(document.activeElement!,{key:"Enter"});
  expect(screen.getByText(text.selected,{selector:".chosen-fund"}).textContent).toContain(local.label);
  fireEvent.change(search,{target:{value:""}});
  fireEvent.click(within(market).getByRole("button",{name:"TASE"}));
  fireEvent.click(within(currency).getByRole("button",{name:"USD"}));
  expect(within(list).getAllByRole("button")).toHaveLength(1);
  expect(within(list).getByText(local.label)).toBeTruthy();
  fireEvent.click(within(market).getByRole("button",{name:"US"}));
  fireEvent.click(within(currency).getByRole("button",{name:"ILS"}));
  expect(screen.getByText("No matching choices.")).toBeTruthy();
  expect(within(market).getAllByRole("button").filter(b=>b.getAttribute("aria-pressed")==="true")).toHaveLength(1);
  expect(mock.request.mock.calls.length).toBe(before); expect(mock.save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText(text.addSelected));
  await screen.findByLabelText(text.columns.Units+" "+local.id);
  expect(screen.getByLabelText(text.columns.Units+" "+local.id).closest("tr")?.textContent).toContain("USD");
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
  fireEvent.click(screen.getByText(text.add)); await waitFor(() => expect(within(screen.getByRole("group",{name:text.search})).getAllByRole("button").length).toBeGreaterThan(0));
  fireEvent.change(screen.getByRole("searchbox",{name:text.search}),{target:{value:"gld"}});
  fireEvent.click(within(screen.getByRole("group",{name:text.search})).getByText(item.label));
  fireEvent.click(within(screen.getByRole("group",{name:text.market})).getByRole("button",{name:"US"}));
  fireEvent.change(screen.getByLabelText(text.columns.Units+" "+other.id),{target:{value:"9"}});
  fireEvent.change(screen.getByLabelText(text.cash),{target:{value:"13"}});
  chooseRole(other.id,holdings.roles.outside);
  fireEvent.click(screen.getByLabelText(holdings.actionsFund.replace("{fund}",item.label)));
  fireEvent.click(screen.getByRole("button",{name:"Remove "+item.label}));
  expect(screen.queryByRole("row",{name:item.label})).toBeNull();
  for(const key of ["Units","Manual price per unit","Price date"] as const) expect(screen.queryByLabelText(text.columns[key]+" "+item.id)).toBeNull();
  expect(screen.queryByText("Removed when you save")).toBeNull();expect(screen.queryByRole("button",{name:/Undo removal/})).toBeNull();
  expect(document.activeElement).toBe(screen.getByRole("heading",{name:text.holdings}));
  expect(screen.getByText(text.unsaved)).toBeTruthy(); expect(mock.save).not.toHaveBeenCalled();
  expect(screen.getByLabelText(text.columns.Units+" "+other.id)).toHaveProperty("value","9");
  expect(screen.getByLabelText(text.cash)).toHaveProperty("value","13");
  expect(screen.getByRole('combobox',{name:holdings.role+' '+other.id})).toHaveProperty('value','outside');
  expect(screen.getByRole("searchbox",{name:text.search})).toHaveProperty("value","gld");
  expect(screen.getByText(text.selected,{selector:".chosen-fund"})).toBeTruthy();
  fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(()=>expect(mock.request.mock.calls.some(([p,b])=>p==="/api/rebalance/editor"&&b.rows[0].Remove)).toBe(true));
  fireEvent.click(screen.getByText(text.save));await waitFor(()=>expect(mock.save).toHaveBeenCalled());
  const drafts=mock.request.mock.calls.filter(([p])=>p==="/api/rebalance/editor");
  expect(drafts.at(-1)![1]).toMatchObject({cash:"13",rows:[{...row,Remove:true},{...extra,Units:"9","Units edited":true,"Outside the rebalance":true}]});
  expect(mock.save).toHaveBeenCalledWith(state.workspace_revision,candidate);
  await waitFor(()=>expect(screen.getByText(text.save)).toHaveProperty("disabled",false));
  expect(screen.queryByRole("row",{name:item.label})).toBeNull();
  fireEvent.click(screen.getByText(text.reload));
  await waitFor(()=>expect(screen.getByText(text.save)).toHaveProperty("disabled",false));
  expect(screen.queryByRole("row",{name:item.label})).toBeNull();
});

it("re-adding a hidden holding restores its exact draft without appending a duplicate",async()=>{
  await ready();fireEvent.change(screen.getByLabelText(text.columns.Units+" "+item.id),{target:{value:"7"}});
  fireEvent.click(screen.getByLabelText(holdings.actionsFund.replace("{fund}",item.label)));
  fireEvent.click(screen.getByRole("button",{name:"Remove "+item.label}));
  expect(screen.getByRole("table",{name:text.holdings})).toBeTruthy();
  expect(within(screen.getByRole("table",{name:text.holdings})).queryAllByRole("row").filter(node=>node.hasAttribute("aria-label"))).toHaveLength(0);
  fireEvent.click(screen.getByText(text.add)); await waitFor(() => expect(within(screen.getByRole("group",{name:text.search})).getAllByRole("button").length).toBeGreaterThan(0));fireEvent.click(within(screen.getByRole("group",{name:text.search})).getByText(item.label));
  fireEvent.click(screen.getByText(text.addSelected));
  await screen.findByLabelText(text.columns.Units+" "+item.id);
  expect(within(screen.getByRole("table",{name:text.holdings})).getAllByRole("row").filter(node=>node.hasAttribute("aria-label"))).toHaveLength(1);
  expect(screen.getByLabelText(text.columns.Units+" "+item.id)).toHaveProperty("value","7");
  fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(()=>expect(mock.request.mock.calls.some(([p])=>p==="/api/rebalance/editor")).toBe(true));
  const body=mock.request.mock.calls.filter(([p])=>p==="/api/rebalance/editor").at(-1)![1];
  expect(body.rows).toHaveLength(1);expect(body.rows[0]).toMatchObject({Remove:false,Units:"7"});
  expect(mock.save).not.toHaveBeenCalled();
});

async function ready() {
  mock.request.mockImplementation(async (path: string) => path === "/api/rebalance/instruments" ? {instruments:state.instruments} : path === "/api/rebalance/editor" ? preview : path === "/api/rebalance/plan" ? { state, plan } : state);
  mock.save.mockResolvedValue({ saved: { revision: 2, payload: { holdings_account: candidate } }, uncertain: false });
  render(<Page />); await screen.findByText(text.holdings);
  await waitFor(() => expect(screen.getByText(text.save)).toHaveProperty("disabled", false));
}

it('sorts known securities by label and leaves the empty choice selected',async()=>{
  await ready(); fireEvent.click(screen.getByText(text.add)); await waitFor(() => expect(within(screen.getByRole("group",{name:text.search})).getAllByRole("button").length).toBeGreaterThan(0));
  expect(within(screen.getByRole("group",{name:text.search})).getAllByRole("button").map(node=>node.textContent)).toEqual([other.label+" IEF · US · USD",item.label+" GLD · US · USD"]);
  expect(screen.getByRole("button",{name:text.addSelected})).toHaveProperty("disabled",true);
});

it("requires the existing login gate before fetching holdings", async () => {
  render(<AuthGate><Page /></AuthGate>); await screen.findByText("Sign in with Google"); expect(mock.request).not.toHaveBeenCalled();
});

it("last edited value/units wins, outside edits invalidate the plan, and draft adds preserve inputs", async () => {
  await ready();
  fireEvent.click(screen.getByRole("button",{name:text.generate,hidden:true})); await screen.findByText(text.leftover+": 5.00");
  fireEvent.change(screen.getByLabelText(`${text.columns["Value (₪ / $)"]} US:GLD`), { target: { value: "125" } });
  expect(screen.getByRole("button",{name:text.generate,hidden:true})).toHaveProperty("disabled", true);
  expect(screen.queryByText(text.leftover+": 5.00")).toBeNull();
  fireEvent.click(screen.getByText(text.add)); await waitFor(() => expect(within(screen.getByRole("group",{name:text.search})).getAllByRole("button").length).toBeGreaterThan(0));
  fireEvent.click(within(screen.getByRole("group",{name:text.search})).getByText(other.label));
  fireEvent.click(screen.getByText(text.addSelected)); await screen.findByLabelText(`${text.columns.Units} US:IEF`);
  expect(screen.getByLabelText(`${text.columns["Value (₪ / $)"]} US:GLD`)).toHaveProperty("value", "125");
  chooseRole(item.id,holdings.roles.outside);
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

it("surfaces editor validation errors when Save holdings is rejected", async () => {
  await ready();
  const validation = "Russell 2000 Israel: enter the date of the price you are copying.";
  mock.request.mockImplementation(async (path: string) => path === "/api/rebalance/editor"
    ? { errors: [validation], preview: [{ Fund: "Russell 2000 Israel" }], account: null }
    : state);
  fireEvent.change(screen.getByLabelText(text.cash), { target: { value: "17" } });
  fireEvent.click(screen.getByRole("button", { name: text.save }));
  expect((await screen.findAllByRole("alert")).some(alert => alert.textContent?.includes(validation))).toBe(true);
  expect(mock.save).not.toHaveBeenCalled();
  expect(screen.getByText(text.unsaved)).toBeTruthy();
});

it("surfaces the validation fallback for an empty-error null-account save response", async () => {
  await ready();
  mock.request.mockImplementation(async (path: string) => path === "/api/rebalance/editor"
    ? { errors: [], preview: [], account: null }
    : state);
  fireEvent.change(screen.getByLabelText(text.cash), { target: { value: "17" } });
  fireEvent.click(screen.getByRole("button", { name: text.save }));
  expect((await screen.findAllByRole("alert")).some(alert => alert.textContent?.includes(text.validation))).toBe(true);
  expect(mock.save).not.toHaveBeenCalled();
});

it("keeps the successful Save holdings path unchanged", async () => {
  await ready();
  fireEvent.click(screen.getByRole("button", { name: text.save }));
  await waitFor(() => expect(mock.save).toHaveBeenCalledExactlyOnceWith(state.workspace_revision, candidate));
  await screen.findByText(text.saved);
  await waitFor(() => expect(screen.getByRole("button", { name: text.save })).toHaveProperty("disabled", false));
  expect(screen.queryByRole("alert")).toBeNull();
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
  fireEvent.click(screen.getByRole("button",{name:text.generate,hidden:true})); fireEvent.click(await screen.findByText(text.record));
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
  fireEvent.click(screen.getByRole("button",{name:text.generate,hidden:true})); fireEvent.click(await screen.findByText(text.record));
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
  fireEvent.click(screen.getByRole("button",{name:text.generate,hidden:true})); await screen.findByText(text.emptyPlan);
  expect(screen.queryByText(text.record)).toBeNull();
});

it("starts current rows collapsed, retains edits across price disclosure toggles, and sends the same fields", async () => {
  await ready();
  const toggle = screen.getByRole("button",{name:holdings.detailsFund.replace("{fund}",item.label)});
  expect(toggle.getAttribute("aria-expanded")).toBe("false");
  fireEvent.change(screen.getByLabelText(`${text.columns["Value (₪ / $)"]} ${item.id}`), {target:{value:"125"}});
  fireEvent.click(toggle);
  const edit=within(priceDetails(item.id)).getByRole("button",{name:holdings.editPrice});
  expect(edit.getAttribute("aria-expanded")).toBe("false");fireEvent.click(edit);
  fireEvent.change(screen.getByLabelText(`${text.columns["Manual price per unit"]} ${item.id}`), {target:{value:"11"}});
  fireEvent.click(edit); fireEvent.click(toggle); fireEvent.click(toggle); fireEvent.click(edit);
  expect(screen.getByLabelText(`${text.columns["Value (₪ / $)"]} ${item.id}`)).toHaveProperty("value","125");
  expect(screen.getByLabelText(`${text.columns["Manual price per unit"]} ${item.id}`)).toHaveProperty("value","11");
  fireEvent.click(screen.getByText(text.previewAction));
  await waitFor(()=>expect(mock.request.mock.calls.some(([p])=>p==="/api/rebalance/editor")).toBe(true));
  expect(mock.request.mock.calls.find(([p])=>p==="/api/rebalance/editor")![1].rows).toEqual([
    {...row,"Value (₪ / $)":"125","Enter as":"Value","Manual price per unit":"11"}
  ]);
  expect(screen.getByRole("button",{name:text.save}).classList.contains("btn-primary")).toBe(true);
});

it.each(["stale","missing","manual"])("keeps %s price controls compact until explicitly opened",async kind=>{
  const modified = {...state, rows:[{...row,"Manual price per unit":kind==="manual"?"11":null}],
    quotes:kind==="missing"?{}:{[item.id]:{...state.quotes[item.id],fresh:kind!=="stale"}}};
  mock.request.mockResolvedValue(modified);render(<Page/>);
  const toggle=await screen.findByRole("button",{name:holdings.detailsFund.replace("{fund}",item.label)});
  expect(toggle.getAttribute("aria-expanded")).toBe("false");fireEvent.click(toggle);
  expect(within(priceDetails(item.id)).getByRole("button",{name:holdings.editPrice}).getAttribute("aria-expanded")).toBe("false");
  if(kind!=="missing")expect(within(priceDetails(item.id)).getByTitle("Mock raw")).toBeTruthy();
});

it("shows the persisted proportional default and unspent pooled shares with server-priced unit costs",async()=>{
  await ready();
  expect(screen.getByRole("button",{name:text.allocationModes.proportional,hidden:true}).getAttribute("aria-pressed")).toBe("true");
  mock.request.mockResolvedValue({state,plan:{...plan,unspent_by_fund:{[item.id]:"12.50"},unit_costs_ils:{[item.id]:"35"}}});
  fireEvent.click(screen.getByRole("button",{name:text.generate,hidden:true}));
  await screen.findByText(text.unspentShare.replace("{fund}",item.label).replace("{unspent}","12.50").replace("{cost}","35.00"));
  expect(screen.getByText(text.pooledCash)).toBeTruthy();
  expect(screen.queryByText(text.singleOrder)).toBeNull();
});

it("saves a mode change through the workspace route and invalidates a pending list",async()=>{
  await ready();
  fireEvent.click(screen.getByRole("button",{name:text.generate,hidden:true})); await screen.findByText(text.leftover+": 5.00");
  mock.mode.mockResolvedValue({revision:2,payload:{rebalance_allocation_mode:"biggest_gap_first"}});
  mock.request.mockResolvedValue({...state,workspace_revision:2,allocation_mode:"biggest_gap_first"});
  fireEvent.click(screen.getByRole("button",{name:text.allocationModes.biggest_gap_first,hidden:true}));
  await waitFor(()=>expect(screen.getByRole("button",{name:text.allocationModes.biggest_gap_first,hidden:true})).toHaveProperty("disabled",false));
  expect(mock.mode).toHaveBeenCalledWith(1,"biggest_gap_first");
  expect(screen.getByRole("button",{name:text.allocationModes.biggest_gap_first,hidden:true}).getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByText(text.leftover+": 5.00")).toBeNull();
  expect(mock.save).not.toHaveBeenCalled();
});

it("mode changes preserve dirty holdings and failed preference writes pause safely",async()=>{
  await ready();
  const input=screen.getByLabelText(text.columns.Units+" "+item.id);
  fireEvent.change(input,{target:{value:"7"}});
  mock.mode.mockRejectedValue(new RebalanceError(409,text.uncertain));
  fireEvent.click(screen.getByRole("button",{name:text.allocationModes.biggest_gap_first,hidden:true}));
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
  fireEvent.click(screen.getByRole("button",{name:text.allocationModes.biggest_gap_first,hidden:true}));
  await waitFor(()=>expect(screen.getByRole("button",{name:text.allocationModes.biggest_gap_first,hidden:true})).toHaveProperty("disabled",false));
  expect(screen.getByLabelText(text.columns.Units+" "+item.id)).toHaveProperty("value","7");
  expect(screen.getByLabelText(text.cash)).toHaveProperty("value","17");
  expect(mock.save).not.toHaveBeenCalled();
});

it("groups holdings before buying and keeps Advanced closed initially",async()=>{
  await ready();
  const controls=screen.getByRole("group",{name:text.controls,hidden:true});
  const editor=screen.getByRole("table",{name:text.holdings});
  expect(editor.compareDocumentPosition(controls)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  for(const caption of [text.newMoney,text.allocationMode]){
    expect(screen.getAllByLabelText(caption)).toHaveLength(1);
    expect(within(controls).getByLabelText(caption)).toBeTruthy();
  }
  for(const caption of [text.save,text.generate]){
    expect(screen.getAllByRole("button",{name:caption,hidden:true})).toHaveLength(1);
    expect(screen.getByRole("button",{name:caption,hidden:true}).classList.contains("btn-primary")).toBe(true);
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
  expect(screen.queryByText(text.manualCaption)).toBeNull();
  expect(screen.getByRole("button",{name:holdings.detailsFund.replace("{fund}",item.label)}).getAttribute("aria-expanded")).toBe("false");
});

it("Advanced retains the existing unsaved reload confirmation and preview flow",async()=>{
  await ready(); fireEvent.click(screen.getByText(text.advanced));
  fireEvent.change(screen.getByLabelText(text.cash),{target:{value:"17"}});
  const confirm=vi.spyOn(window,"confirm").mockReturnValue(false);
  const before=mock.request.mock.calls.length;
  fireEvent.click(screen.getByText(text.reload));
  expect(confirm).toHaveBeenCalledWith(text.reloadConfirm);
  expect(mock.request.mock.calls).toHaveLength(before);
  expect(screen.getByRole("button",{name:text.generate,hidden:true})).toHaveProperty("disabled",true);
  fireEvent.click(screen.getByText(text.previewAction));
  await screen.findByText(text.preview);
  expect(screen.getByLabelText(text.cash)).toHaveProperty("value","17");
  expect(mock.save).not.toHaveBeenCalled();
});


it("shows one step at a time, preserves drafts, and keeps a stale plan chip after edits", async () => {
  await ready();
  expect(screen.getByRole("table", {name:text.holdings})).toBeTruthy();
  expect(screen.queryByRole("button", {name:text.generate})).toBeNull();
  fireEvent.click(screen.getByRole("button", {name:text.steps.action}));
  fireEvent.click(screen.getByRole("tab", {name:text.actionTabs.sell}));
  expect(screen.getByRole("heading", {name:text.sellTitle})).toBeTruthy();
  expect(screen.queryByRole("table", {name:text.holdings})).toBeNull();
  fireEvent.click(screen.getByRole("button", {name:text.nextBuy}));
  fireEvent.click(screen.getByRole("button", {name:text.generate}));
  await screen.findByText(text.planChip+" · "+text.currentChip);
  fireEvent.click(screen.getByRole("button", {name:text.steps.holdings}));
  fireEvent.change(screen.getByLabelText(text.cash), {target:{value:"17"}});
  expect(screen.getByText(text.planChip+" · "+text.staleChip)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name:text.steps.action}));
  expect(screen.getByRole("button", {name:text.generate})).toHaveProperty("disabled",true);
  expect(screen.queryByText(text.leftover+": 5.00")).toBeNull();
  fireEvent.click(screen.getByRole("button", {name:text.steps.holdings}));
  expect(screen.getByLabelText(text.cash)).toHaveProperty("value","17");
  expect(mock.save).not.toHaveBeenCalled();
});

it("reviews full exits without recording trades or funding buys from sales", async () => {
  mock.request.mockResolvedValue({...state, sell_review:[{id:item.id,action:"sell",before_units:"2",after_units:"0"}]});
  render(<Page/>); await screen.findByText(text.holdings);
  fireEvent.click(screen.getByRole("button", {name:text.steps.action}));
  fireEvent.click(screen.getByRole("tab", {name:text.actionTabs.sell}));
  expect(screen.getByRole("cell", {name:text.sellAction})).toBeTruthy();
  expect(screen.getByRole("cell", {name:"0"})).toBeTruthy();
  expect(mock.save).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name:text.nextBuy}));
  mock.request.mockResolvedValue({state,plan});
  fireEvent.click(screen.getByRole("button", {name:text.generate}));
  await screen.findByText(text.planChip+" · "+text.currentChip);
  expect(mock.request.mock.calls.find(([path])=>path==="/api/rebalance/plan")![1]).toEqual({portfolio_id:state.portfolio_id,account_hash:state.account_hash,new_money:"0"});
});

it('opens the compare-plan chip, shows the single-plan hint, and picks and collapses without changing holdings', async()=>{
  await ready();
  const caption=text.comparePlan.replace('{name}','Fake portfolio');
  const chip=screen.getByRole('button',{name:caption});
  expect(chip.getAttribute('aria-expanded')).toBe('false');
  fireEvent.click(chip);
  expect(chip.getAttribute('aria-expanded')).toBe('true');
  expect(screen.getByText(text.morePlans)).toBeTruthy();
  fireEvent.keyDown(screen.getByRole('group',{name:text.choosePlan}),{key:'Escape'});
  expect(chip.getAttribute('aria-expanded')).toBe('false');
  const next={...state,portfolios:[...state.portfolios,{id:'second',name:'Another plan'}],portfolio_id:'second'};
  mock.request.mockResolvedValue(next);
  // Refresh the saved portfolio list through the existing reload flow.
  fireEvent.click(screen.getByText(text.advanced));fireEvent.click(screen.getByText(text.reload));
  const updated=await screen.findByRole('button',{name:text.comparePlan.replace('{name}','Another plan')});
  fireEvent.change(screen.getByLabelText(text.cash),{target:{value:'17'}});
  fireEvent.click(updated);
  expect(screen.queryByText(text.morePlans)).toBeNull();
  mock.request.mockResolvedValue({...next,portfolio_id:'fake-portfolio'});
  fireEvent.click(screen.getByRole('button',{name:'Fake portfolio'}));
  await waitFor(()=>expect(mock.request).toHaveBeenCalledWith('/api/rebalance?portfolio_id=fake-portfolio'));
  expect((await screen.findByRole('button',{name:caption})).getAttribute('aria-expanded')).toBe('false');
  expect(screen.queryByRole('group',{name:text.choosePlan})).toBeNull();
  expect(screen.getByLabelText(text.cash)).toHaveProperty('value','17');
  expect(mock.save).not.toHaveBeenCalled();
});

it('defaults Action to balance, supports keyboard tabs, and switches without requests or losing inputs', async()=>{
  await ready();
  fireEvent.click(screen.getByRole('button',{name:text.steps.action}));
  const balance=screen.getByRole('tab',{name:text.actionTabs.balance});
  expect(balance.getAttribute('aria-selected')).toBe('true');
  expect(screen.getAllByRole('tabpanel')).toHaveLength(1);
  expect(screen.getByRole('tabpanel').getAttribute('aria-labelledby')).toBe(balance.id);
  fireEvent.change(screen.getByLabelText(text.newMoney),{target:{value:'123'}});
  const before=mock.request.mock.calls.length;
  fireEvent.keyDown(balance,{key:'ArrowRight'});
  const sell=screen.getByRole('tab',{name:text.actionTabs.sell});
  expect(sell.getAttribute('aria-selected')).toBe('true');expect(document.activeElement).toBe(sell);
  expect(screen.getByRole('heading',{name:text.sellTitle})).toBeTruthy();
  fireEvent.keyDown(sell,{key:'End'});
  const details=screen.getByRole('tab',{name:text.actionTabs.details});
  expect(details.getAttribute('aria-selected')).toBe('true');
  fireEvent.keyDown(details,{key:'Home'});
  expect(balance.getAttribute('aria-selected')).toBe('true');
  fireEvent.click(screen.getByRole('tab',{name:text.actionTabs.buy}));
  expect(screen.getByText(text.buyEmpty)).toBeTruthy();
  expect(screen.getByLabelText(text.newMoney)).toHaveProperty('value','123');
  expect(screen.getByRole('button',{name:text.generate})).toBeTruthy();
  expect(mock.request.mock.calls).toHaveLength(before);expect(mock.save).not.toHaveBeenCalled();
});

it('selects Buy list after generation, separates breakdowns, and preserves recording drafts across tabs',async()=>{
  await ready();fireEvent.click(screen.getByRole('button',{name:text.steps.action}));
  mock.request.mockResolvedValue({state,plan:{...plan,unspent_by_fund:{[item.id]:'12.50'},unit_costs_ils:{[item.id]:'35'}}});
  fireEvent.click(screen.getByRole('button',{name:text.generate}));
  await screen.findByText(text.planChip+' · '+text.currentChip);
  expect(screen.getByRole('tab',{name:text.actionTabs.buy}).getAttribute('aria-selected')).toBe('true');
  const buy=screen.getByRole('tabpanel');
  expect(within(buy).getByRole('heading',{name:text.buyList})).toBeTruthy();
  expect(within(buy).queryByText(text.pooledCash)).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:text.record}));
  fireEvent.change(screen.getByLabelText(text.bought),{target:{value:'1'}});
  fireEvent.change(screen.getByLabelText(text.paid),{target:{value:'36.25'}});
  const before=mock.request.mock.calls.length;
  fireEvent.click(screen.getByRole('tab',{name:text.actionTabs.details}));
  expect(within(screen.getByRole('tabpanel')).getByText(text.pooledCash)).toBeTruthy();
  fireEvent.click(screen.getByRole('tab',{name:text.actionTabs.balance}));
  expect(within(screen.getByRole('tabpanel')).getByText(text.comparison)).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:text.planChip+' · '+text.currentChip}));
  expect(screen.getByLabelText(text.bought)).toHaveProperty('value','1');
  expect(screen.getByLabelText(text.paid)).toHaveProperty('value','36.25');
  expect(mock.request.mock.calls).toHaveLength(before);expect(mock.save).not.toHaveBeenCalled();
});

it('keeps blocking errors and data warnings visible across all Action tabs',async()=>{
  const warning='Mock target failure';
  mock.request.mockResolvedValue({...state,ready:false,errors:[warning],stale:[item.id]});
  render(<Page/>);await screen.findByText(text.holdings);
  fireEvent.click(screen.getByRole('button',{name:text.steps.action}));
  for(const name of Object.values(text.actionTabs)){
    fireEvent.click(screen.getByRole('tab',{name}));
    expect(screen.getByRole('alert').textContent).toContain(warning);
    expect(screen.getByRole('alert').closest('[role="tabpanel"]')).toBeNull();
    expect(screen.getByText(text.stalePricesOne.replace('{count}','1')).closest('[role="tabpanel"]')).toBeNull();
    expect(screen.getByRole('button',{name:text.generate})).toHaveProperty('disabled',true);
  }
});

it('saves compact row edits through the existing single global save', async()=>{
 await ready();
 fireEvent.change(screen.getByLabelText(text.columns['Value (₪ / $)']+' '+item.id),{target:{value:'125'}});
 fireEvent.change(screen.getByLabelText(text.columns.Units+' '+item.id),{target:{value:'7'}});
 expandHolding(item.id);
 fireEvent.click(within(priceDetails(item.id)).getByRole('button',{name:holdings.editPrice}));
 fireEvent.change(screen.getByLabelText(text.columns['Manual price per unit']+' '+item.id),{target:{value:'11.125'}});
 fireEvent.change(screen.getByLabelText(text.columns['Price date']+' '+item.id),{target:{value:'2026-11-03'}});
 fireEvent.change(screen.getByLabelText(text.columns['Minimum order (₪)']+' '+item.id),{target:{value:'50'}});
 chooseRole(item.id,holdings.roles.outside);
 expect(mock.save).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole('button',{name:text.save}));
 await waitFor(()=>expect(mock.save).toHaveBeenCalledExactlyOnceWith(1,candidate));
 const submitted=mock.request.mock.calls.filter(([path])=>path==='/api/rebalance/editor').at(-1)![1];
 expect(submitted.rows[0]).toMatchObject({Units:'7','Value (₪ / $)':'125','Enter as':'Units','Units edited':true,'Manual price per unit':'11.125','Price date':'2026-11-03','Minimum order (₪)':'50','Outside the rebalance':true});
});

it("shows compact data and signals with correct percentage-point sleeve weights and hidden technical data",async()=>{
  mock.request.mockResolvedValue({...state,
    signals:[{name:"Century Momentum",weight:45,target_weights:{SPMO:1},signal_date:"2026-10-15"},
      {name:"Inflation Compass",weight:20,target_weights:{GLD:.25,IEF:.75},signal_date:"2026-10-14"}],
    target_diagnostics:[{stage:"ticker",code:"ticker_defaulted",message:"Used built-in default tickers for missing roles: SOXX. Saved settings were not changed."}]
  });
  await ready();
  fireEvent.click(screen.getByRole("button",{name:text.steps.action}));
  fireEvent.click(screen.getByRole("tab",{name:"Data & Signals"}));
  const panel=screen.getByRole("tabpanel");
  expect(within(panel).getByText("45.00% sleeve",{exact:false})).toBeTruthy();
  expect(within(panel).getByText("20.00% sleeve",{exact:false})).toBeTruthy();
  expect(within(panel).getByText("SPMO 100.00%")).toBeTruthy();
  expect(within(panel).getByText(/Built-in ticker used for missing saved setting: SOXX/)).toBeTruthy();
  const technical=within(panel).getByText("Technical details").closest("details")!;
  expect(technical.open).toBe(false);
  expect(within(technical).getByText(/"workspace_revision"/)).toBeTruthy();
  expect(within(panel).getByText("Price sources (1)").closest("details")!.open).toBe(false);
});

it("summarizes manual, stale and unavailable prices without exposing raw JSON by default",async()=>{
  mock.request.mockResolvedValue({...state,
    quotes:{[item.id]:{price:"10",as_of:"2026-10-15",source:"Manual dated per-unit override",field:"Manual per-unit price",fresh:false},
      [other.id]:{error:"unavailable",fresh:false}},
    stale:[item.id],blocked:[other.id]
  });
  await ready();
  fireEvent.click(screen.getByRole("button",{name:text.steps.action}));
  fireEvent.click(screen.getByRole("tab",{name:"Data & Signals"}));
  const panel=screen.getByRole("tabpanel");
  expect(within(panel).getByText("0 automatic · 1 manual")).toBeTruthy();
  expect(within(panel).getByText(/Older price: Fake gold/)).toBeTruthy();
  expect(within(panel).getByText(/Unavailable price: Fake bonds/)).toBeTruthy();
  fireEvent.click(within(panel).getByText("Price sources (2)"));
  expect(within(panel).getByText("Manual")).toBeTruthy();
  expect(within(panel).getByText("Unavailable",{selector:"td"})).toBeTruthy();
});

it("shows automatic dated published valuations for the ex-US and Russell funds", async () => {
  const funds = {
    "TASE:5139837": {id:"TASE:5139837",identifier:"5139837",market:"TASE",currency:"ILS",label:"Russell 2000 Israel"},
    "TASE:5142476": {id:"TASE:5142476",identifier:"5142476",market:"TASE",currency:"ILS",label:"Ex-US Israel"},
  };
  const fundRows = Object.values(funds).map(fund => ({...row,Security:fund.id,Fund:fund.label,Currency:"ILS",Units:"1000","Manual price per unit":null,"Price date":null}));
  const fundQuotes = {
    "TASE:5139837": {price:"1.0885",as_of:"2026-11-04",expected_through:"2026-11-05",fresh:false,valuation_kind:"fund_nav",field:"Published fund redemption valuation"},
    "TASE:5142476": {price:"0.9776",as_of:"2026-11-03",expected_through:"2026-11-05",fresh:false,valuation_kind:"fund_nav",field:"Published fund redemption valuation"},
  };
  const next = {...state,rows:fundRows,instruments:{...state.instruments,...funds},quotes:fundQuotes,stale:Object.keys(funds),
    comparison:Object.values(funds).map(fund=>({id:fund.id,Fund:fund.label,target_display:"50.00%",actual_display:"50.00%",Status:"On target"}))};
  mock.request.mockResolvedValue(next); render(<Page/>); await screen.findByText(text.holdings);
  fireEvent.click(screen.getByRole("button",{name:text.steps.action}));
  expect(screen.getByText(text.staleFundNav.replace("{date}","2026-11-04").replace("{session}","2026-11-05"))).toBeTruthy();
  expect(screen.getByText(text.staleFundNav.replace("{date}","2026-11-03").replace("{session}","2026-11-05"))).toBeTruthy();
  fireEvent.click(screen.getByRole("tab",{name:text.actionTabs.details}));
  const panel=screen.getByRole("tabpanel");
  expect(within(panel).getAllByText("Automatic")).toHaveLength(2);
  expect(within(panel).getAllByText("Published fund valuation")).toHaveLength(2);
  expect(within(panel).getAllByText("4 Nov 2026")).toHaveLength(2);
  expect(within(panel).getByText("3 Nov 2026")).toBeTruthy();
});


it.each([1,2,3])('collapses %i older quotes into a counted notice with unchanged labels and dates',async count=>{
  const ids=Array.from({length:count},(_,index)=>'TASE:STALE-'+index);
  const staleInstruments=Object.fromEntries(ids.map((id,index)=>[id,{...item,id,label:'Older fund '+index}]));
  const staleQuotes=Object.fromEntries(ids.map((id,index)=>[id,{price:'10',as_of:'2026-11-0'+(index+1),fresh:false}]));
  mock.request.mockResolvedValue({...state,stale:ids,blocked:[other.id],instruments:{...state.instruments,...staleInstruments},quotes:{...state.quotes,...staleQuotes}});
  render(<Page/>);await screen.findByText(text.holdings);
  const summary=screen.getByText((count===1?text.stalePricesOne:text.stalePricesMany).replace('{count}',String(count)),{selector:'summary'});
  const notice=summary.closest('details')!;
  expect(notice.open).toBe(false);expect(notice.classList.contains('signal-warning')).toBe(true);
  expect(notice.closest('.rebalance-step-content')).toBeNull();
  fireEvent.click(summary);expect(notice.open).toBe(true);
  expect(within(notice).getAllByRole('listitem').map(node=>node.textContent)).toEqual(ids.map((id,index)=>
    text.stalePricesItem.replace('{fund}',staleInstruments[id].label).replace('{date}','2026-11-0'+(index+1))));
  expect(notice.textContent).not.toContain(other.label);
  expect(screen.getByText(text.missing+' '+other.label)).toBeTruthy();
  fireEvent.click(summary);expect(notice.open).toBe(false);
});

it('keeps step navigation horizontal and content full-width without changing the phone button rules',()=>{
  const css=readFileSync('./app/globals.css','utf8');
  const workflow=css.match(/\.rebalance-workflow \{[^}]+\}/)![0];
  const steps=css.match(/\.rebalance-steps \{[^}]+\}/)![0];
  expect(workflow).toContain('grid-template-columns: minmax(0, 1fr)');
  expect(steps).toContain('flex-direction: row');expect(steps).toContain('gap: .5rem');
  expect(steps).not.toMatch(/sticky|top:/);
  expect(css).toContain('.rebalance-steps button { flex: 1; text-align: center; padding: .65rem .3rem; }');
});

it("shows the actual TASE identifier and currency through comparison, sale, buy and record", async () => {
  const fund = { id: "TASE:1189596", identifier: "1189596", market: "TASE", currency: "ILS", label: "World Value Israel — 1189596" };
  const localState = {...state, instruments: {...state.instruments,[fund.id]:fund},
    comparison: [{...state.comparison[0], id:fund.id, Fund:fund.label}],
    sell_review: [{id:fund.id,action:"sell",before_units:"2",after_units:"0"}]};
  const localPlan = {...plan, orders:[{...plan.orders[0],id:fund.id}]};
  mock.request.mockImplementation(async (path:string) => path === "/api/rebalance/plan" ? {state:localState,plan:localPlan}
    : path === "/api/rebalance/record" ? {account:candidate} : localState);
  mock.save.mockResolvedValue({saved:{revision:2,payload:{holdings_account:candidate}},uncertain:false});
  render(<Page/>); await screen.findByText(text.holdings);
  fireEvent.click(screen.getByRole("button",{name:text.steps.action}));
  for (const tab of [text.actionTabs.balance,text.actionTabs.sell]) {
    fireEvent.click(screen.getByRole("tab",{name:tab}));
    expect(within(screen.getByRole("tabpanel")).getByText("1189596 · TASE · ILS")).toBeTruthy();
  }
  fireEvent.click(screen.getByRole("button",{name:text.generate}));
  const record = await screen.findByText(text.record);
  expect(within(screen.getByRole("tabpanel")).getByText("1189596 · TASE · ILS")).toBeTruthy();
  fireEvent.click(record);
  expect(screen.getAllByText("1189596 · TASE · ILS", {selector:".record-order small"})).toHaveLength(1);
  fireEvent.change(screen.getByLabelText(text.bought),{target:{value:"1"}});
  fireEvent.change(screen.getByLabelText(text.paid),{target:{value:"40"}});
  fireEvent.click(screen.getByLabelText(text.acknowledge)); fireEvent.click(screen.getByText(text.done));
  await screen.findByText(text.recorded);
  expect(mock.request.mock.calls.find(([path])=>path==="/api/rebalance/record")![1].confirmations).toEqual([{id:fund.id,units:"1",paid_ils:"40"}]);
});
