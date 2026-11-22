import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/today.json";

const mock = vi.hoisted(() => ({ response: vi.fn(), portfolios: [{id:"fixture",is_default:true,updated_at:"revision-1",payload:{name:"Fake portfolio"}}] }));
vi.mock("../lib/api", () => ({ authorizedResponse: (path:string, init?:RequestInit) => path === "/api/portfolios" ? Promise.resolve(new Response(JSON.stringify(mock.portfolios))) : init === undefined ? mock.response(path) : mock.response(path,init), ApiError: class extends Error { constructor(public status: number, message: string) { super(message); } } }));
vi.mock("next/navigation", () => ({ usePathname: () => "/today/" }));
vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: {
  getSession: async () => ({ data: { session: null }, error: null }),
  onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
} }) }));
import Page from "../app/today/page";
import AuthGate, { SignedInUserContext } from "../components/AuthGate";
import { activateDeviceUser, syncPortfolio } from "../lib/device-results";
import { todayStorageKey, loadedTodayTime } from "../lib/today-local-result";
import { ApiError } from "../lib/api";
import { historyTable, historyCsv } from "../app/today/history-sources";

const payload = { has_default: true, has_holdings: false, actions: [], action_notice: null, comparison: null, pot_total: null,
  caption: "Fake portfolio · private synced portfolio", issues: [],
  signals: [{ label: "Fake sleeve", weight_text: "40.00%", holding: "Fake holding 100%", status: "Ready · fake", error_code: null,
    holding_display:[{name:"Fake holding",security_number:null,weight_text:null}],regime:"fake",status_code:"ok",
    amounts:[{holding:"Fake holding",amount:2500,currency:"USD"},{holding:"Fake local holding",amount:6000,currency:"ILS"}] }],
  holdings: [{ currency: "USD", rows: [{ holding: "Fake holding", weight_text: "40.00%", amount_text: "2,500.00" }] },
    { currency: "ILS", rows: [{ holding: "Fake local holding", weight_text: "60.00%", amount_text: "6,000.00" }] }],
  monthly_action: "unchanged", latest_caption: "Latest completed signal: 2026-09-30", stale: false,
  previews: [{ label: "Fake sleeve", allocation: "Fake holding 100%", allocation_display:[{name:"Fake holding",security_number:null,weight_text:null}], kind:null, change: "no", price_as_of: "2026-10-16", reason: null, error_code: null }],
  preview_caption: "Mock latest common eligible price caption", warnings: [], public_sleeves: [], timing: {} };
const json = (value: unknown, status=200) => new Response(JSON.stringify(value), { status });

it('renders the six clear signal columns, short names, separate security numbers, regime and statuses',async()=>{
  mock.response.mockResolvedValue(json({...payload,signals:[
    {...payload.signals[0],label:'A-RVol Shifter V3 Cash-Only',regime:'risk-on',holding_display:[{name:'Mock MTF fund',security_number:'5140850',weight_text:null}]},
    {...payload.signals[0],label:'Buy and Hold Gold GLD',status_code:'check_data'},
    {...payload.signals[0],label:'Inflation Compass Standard',status_code:'unavailable',status:'Mock missing prices',holding_display:[],regime:null,amounts:[]},
    {...payload.signals[0],label:'Unmapped full strategy name',holding_display:[{name:'SPMO',security_number:null,weight_text:'60%'},{name:'IEF',security_number:null,weight_text:'40%'}]},
  ]}));
  render(<Page/>);await screen.findByText(payload.caption);
  const table=within(screen.getByRole('table',{name:text.sleeveSignals}));
  expect(table.getAllByRole('columnheader').map(h=>h.textContent)).toEqual(['Sleeve','Weight','Holding','Security No.','Amount','Status']);
  for(const label of ['A-RVol V3','Gold GLD','Inflation Compass','Unmapped full strategy name','Mock MTF fund','5140850','risk-on','Check data','Unavailable','Mock missing prices','SPMO 60%','IEF 40%'])
    expect(table.getAllByText(label).length).toBeGreaterThan(0);
  expect(table.getByText('risk-on').tagName).toBe('SMALL');
  const cells=within(table.getAllByRole('row')[1]).getAllByRole('cell');
  expect(cells[2].textContent).toBe('Mock MTF fund');
  expect(cells[3].textContent).toBe('5140850');
  expect(cells[5].textContent).toBe('risk-on');
  expect(table.queryByText('OK')).toBeNull();
  expect(within(table.getAllByRole('row')[3]).getAllByRole('cell')[5].textContent).toBe('UnavailableMock missing prices');
  expect(table.queryByText(/100%/)).toBeNull();
  expect(table.queryByText(/Fake holding:/)).toBeNull();
  expect(table.getAllByText('-').length).toBeGreaterThan(0);
  expect(screen.queryByText(text.timing)).toBeNull();
});

it('renders five preview columns, structured names and fixed labels while preserving other reasons and warnings',async()=>{
  mock.response.mockResolvedValue(json({...payload,previews:[
    {...payload.previews[0],label:'Buy and Hold Gold GLD',allocation_display:[{name:'Mock local gold',security_number:'1147875',weight_text:null}]},
    {...payload.previews[0],allocation_display:[],kind:'always_held'},
    {...payload.previews[0],allocation_display:[],kind:'daily_signals'},
    {...payload.previews[0],allocation_display:[],reason:'Mock data unavailable'},
  ]}));
  render(<Page/>);await screen.findByText(payload.caption);
  const details=screen.getByText(text.preview).closest('details')!;details.open=true;
  const table=within(screen.getByRole('table',{name:text.preview}));
  expect(table.getAllByRole('columnheader').map(h=>h.textContent)).toEqual(['Sleeve','Projected allocation','Security No.','Change vs current','Price data through']);
  for(const label of ['Gold · Buy and hold · GLD (USD)','Mock local gold','1147875',text.previewKinds.always_held,text.previewKinds.daily_signals,'Mock data unavailable']) expect(table.getByText(label)).toBeTruthy();
  expect(table.queryByText(/100%/)).toBeNull();
  expect(details.textContent).toContain('Provisional only');
  expect(details.textContent).toContain(payload.preview_caption);
});
afterEach(() => { cleanup(); window.localStorage.clear(); mock.portfolios=[{id:"fixture",is_default:true,updated_at:"revision-1",payload:{name:"Fake portfolio"}}]; mock.response.mockReset(); vi.restoreAllMocks(); vi.useRealTimers(); });

const plainSleeve = (asset: string, source: string, first: string, series: string) => ({
  model: `Fake plain ${asset}`,
  provenance: { columns: ['asset','source','identifier','price_field','history_kind','automatic_proxy_extension'], rows: [{asset,source,identifier:asset,price_field:series,history_kind:'Actual fund history',automatic_proxy_extension:false}] },
  data_ranges: { columns: ['asset','first_available','last_available','observations'], rows: [{asset,first_available:first,last_available:'2026-10-16',observations:123}] },
});

it('shows the unchanged history component below Sleeve signals, only for default plain holdings',async()=>{
  const gold=plainSleeve('FAKE_GOLD','Mock gold source','2004-11-18','Adjusted mock close');
  const bonds=plainSleeve('FAKE_BONDS','Mock bond source','2002-07-26','Mock total-return NAV');
  mock.response.mockResolvedValue(json({...payload,public_sleeves:[gold,bonds,gold,{model:'Fake timing strategy'}]}));
  render(<Page/>);await screen.findByText(text.buyHoldNote);
  expect(screen.getAllByText(text.buyHoldNote)).toHaveLength(1);
  const note=screen.getByText(text.buyHoldNote), intro=screen.getByText(payload.caption);
  const details=screen.getByText(text.historySources).closest('details')!;
  expect(details.open).toBe(false);
  expect(intro.compareDocumentPosition(note)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(note.compareDocumentPosition(details)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByRole('table',{name:text.sleeveSignals}).compareDocumentPosition(note)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.getByText(text.preview).compareDocumentPosition(details)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  details.open=true;fireEvent(details,new Event('toggle'));
  const table=screen.getByRole('table',{name:text.historySources});
  expect(table.querySelectorAll('tbody tr')).toHaveLength(2);
  for(const value of ['FAKE_GOLD','FAKE_BONDS','Mock gold source','Mock bond source','18 Nov 2004','26 Jul 2002','Adjusted mock close','Mock total-return NAV'])
    expect(table.textContent).toContain(value);
  expect(mock.response).toHaveBeenCalledTimes(1); // Opening history never requests a preview or changes signals.
  expect(screen.getByText(text.actions.unchanged)).toBeTruthy();
  expect(screen.getByText('2,500.00 USD')).toBeTruthy();
});

it('hides history without plain holdings or without a default',async()=>{
  mock.response.mockResolvedValue(json(payload));render(<Page/>);await screen.findByText(payload.caption);
  expect(screen.queryByText(text.buyHoldNote)).toBeNull();expect(screen.queryByText(text.historySources)).toBeNull();
  cleanup();
  mock.response.mockResolvedValue(json({...payload,has_default:false,public_sleeves:[plainSleeve('FAKE','Mock','2000-01-01','Mock NAV')]}));
  render(<Page/>);await screen.findByText('Use as Today default');
  expect(screen.queryByText(text.buyHoldNote)).toBeNull();expect(screen.queryByText(text.historySources)).toBeNull();
});

it('uses the server provenance and per-asset first observations without guessing or mutating them',()=>{
  const sleeve=plainSleeve('FAKE','Mock "quoted", source','2004-11-18T00:00:00','Unadjusted mock close');
  const missing={...sleeve,provenance:{...sleeve.provenance,rows:[{...sleeve.provenance.rows[0],asset:'MISSING',history_kind:'Selected source / stand-in'}]}};
  const original=JSON.stringify([sleeve,missing]);
  const table=historyTable([sleeve,missing]);
  expect(table.rows[0]).toMatchObject({Source:'Mock "quoted", source','First available date':'2004-11-18T00:00:00','Price series used':'Unadjusted mock close'});
  expect(table.rows[1]).toMatchObject({'First available date':text.unavailable,'History kind':'Selected source / stand-in'});
  expect(JSON.stringify([sleeve,missing])).toBe(original);
  const csv=historyCsv(table);
  expect(csv).toContain('"Mock ""quoted"", source"');
  expect(csv).toContain('"2004-11-18T00:00:00"');
  expect(csv).toContain('"Unadjusted mock close"');
  expect(csv).toContain('"Selected source / stand-in"');
});

it('downloads the displayed combined table as CSV',async()=>{
  const sleeves=[plainSleeve('FAKE','Mock source','2004-11-18','Mock NAV')];
  mock.response.mockResolvedValue(json({...payload,public_sleeves:sleeves}));
  const create=vi.fn((_blob:Blob)=>'blob:mock'),revoke=vi.fn();
  Object.defineProperty(URL,'createObjectURL',{value:create,configurable:true});
  Object.defineProperty(URL,'revokeObjectURL',{value:revoke,configurable:true});
  const clicks:{filename:string;href:string}[]=[];
  vi.spyOn(HTMLAnchorElement.prototype,'click').mockImplementation(function(this:HTMLAnchorElement){clicks.push({filename:this.download,href:this.href});});
  render(<Page/>);await screen.findByText(text.buyHoldNote);
  screen.getByText(text.historySources).closest('details')!.open=true;
  fireEvent.click(screen.getByRole('button',{name:text.historyCsv}));
  expect(create.mock.calls[0][0].size).toBe(new TextEncoder().encode(historyCsv(historyTable(sleeves))).length);
  expect(create.mock.calls[0][0].type).toBe('text/csv;charset=utf-8');
  expect(clicks).toEqual([{filename:'plain_holdings_history_sources.csv',href:'blob:mock'}]);
  expect(revoke).toHaveBeenCalledWith('blob:mock');
});

it('scopes muted caption and whole-word phone layout to Today history only',()=>{
  const css=readFileSync('./app/today/history-sources.module.css','utf8');
  expect(css).toContain('font-size: .85rem');expect(css).toContain('color: var(--muted)');
  expect(css).toContain('white-space: normal');expect(css).toContain('overflow-wrap: normal');
  expect(css).toContain('word-break: normal');expect(css).toContain('hyphens: none');
  expect(css).not.toMatch(/break-all|anywhere|overflow:\s*hidden/);
  expect(css).toContain('min-width: 52rem'); // Existing scroll wrapper, not clipped cells or broken words.
  const secondary=readFileSync('./app/today/today.module.css','utf8');
  expect(secondary).toContain('display: block');
  expect(secondary).toContain('word-break: normal');
  expect(secondary).toContain('overflow-wrap: normal');
  expect(secondary).not.toMatch(/break-all|anywhere/);
});

it("does not mount or fetch Today before the existing login gate admits it", async () => {
  render(<AuthGate><Page /></AuthGate>); await screen.findByText("Sign in with Google"); expect(mock.response).not.toHaveBeenCalled();
});

it("renders server-formatted actions and keeps the complete comparison and preview closed", async () => {
  const comparison = [
    { id: "TASE:5140850", Fund: "Mock MTF fund", "Target %": 0.5, "Actual %": 0.38, "Gap (₪)": 12444.6 },
    { id: "US:IEF", Fund: "Mock bonds", "Target %": 0.25, "Actual %": 0.38, "Gap (₪)": -13000 },
    { id: "US:BIL", Fund: "Below threshold", "Target %": 0.25, "Actual %": 0.24, "Gap (₪)": 1000 },
  ];
  mock.response.mockImplementation(async () => json({ ...payload, has_holdings: true, pot_total: 100000, comparison, actions: [
    { id: "US:IEF", fund: "Mock bonds", direction: "over", amount_text: "about ₪13,000", moved_here: [] },
    { id: "TASE:5140850", fund: "Mock MTF fund", direction: "buy", amount_text: "about ₪12,445", moved_here: ["Fake sleeve"] },
  ] })); render(<Page />);
  await screen.findByText(payload.caption);
  const table = within(screen.getByRole("table", { name: text.whatToDo }));
  expect(table.getAllByRole("columnheader").map(cell => cell.textContent)).toEqual(["Fund", "Security No.", "Buy", "Above target"]);
  const [, over, buy] = table.getAllByRole("row");
  const cells = (row: HTMLElement) => within(row).getAllByRole("cell").map(cell => cell.textContent);
  expect(cells(over)).toEqual(["Mock bonds", "IEF", text.dash, "about ₪13,000"]);
  expect(cells(buy).slice(1)).toEqual(["5140850", "about ₪12,445", text.dash]);
  const note = within(buy).getByText("This month, Fake sleeve now points here.");
  expect(note.tagName).toBe("SMALL");
  expect(table.getAllByText(/now points here/)).toEqual([note]);
  expect(table.queryByText("Below threshold")).toBeNull();
  expect(screen.getAllByText(/Your rebalancing pot/)).toHaveLength(1);
  const details = screen.getByText(text.fullComparison).closest("details")!;
  expect(details.open).toBe(false);
  details.open = true;
  const fullTable = within(details).getByRole("table", { name: text.fullComparison });
  expect(within(fullTable).getAllByRole("columnheader").map(cell => cell.textContent))
    .toEqual(["Fund", "Security No.", "Target %", "Now %", "Gap (ILS)", "Price date"]);
  expect(within(fullTable).getAllByRole("row")).toHaveLength(4);
  expect(within(fullTable).getByText("Below threshold")).toBeTruthy();
  expect(screen.getByText(text.preview).closest("details")).toHaveProperty("open", false);
  expect(screen.getByText(text.actions.unchanged)).toBeTruthy();
  expect(screen.getAllByRole("button").map(button => button.textContent)).toEqual([text.refresh,text.refresh]);
  expect(mock.response).toHaveBeenCalledWith("/api/today?preview=false");
});

it.each(["nothing_to_do", "cannot_price", "valuation_failed"] as const)("keeps the %s notice outside the collapsed comparison", async action_notice => {
  mock.response.mockResolvedValue(json({ ...payload, has_holdings: true, action_notice,
    comparison: action_notice === "valuation_failed" ? null : [] }));
  render(<Page />);
  expect((await screen.findByText(text.actionNotices[action_notice])).closest("details")).toBeNull();
  expect(screen.queryByRole("table", { name: text.whatToDo })).toBeNull();
});

it("links to Rebalance Holdings when the account has no holdings", async () => {
  mock.response.mockResolvedValue(json(payload));
  render(<Page />);
  const link = await screen.findByRole("link", { name: text.noHoldings });
  expect(link.getAttribute("href")).toBe("/rebalance-holdings");
  expect(screen.queryByRole("table", { name: text.whatToDo })).toBeNull();
});

it("loads provisional preview only on opening and keeps action before the merged sleeve table",async()=>{
  mock.response.mockImplementation(async()=>json(payload));render(<Page/>);await screen.findByText(payload.caption);
  const action=screen.getByText(text.monthlyAction), table=screen.getByRole("table",{name:text.sleeveSignals});
  expect(action.compareDocumentPosition(table)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(mock.response).toHaveBeenCalledTimes(1);
  const details=screen.getByText(text.preview).closest("details")!;details.open=true;fireEvent(details,new Event("toggle"));
  await waitFor(()=>expect(mock.response).toHaveBeenCalledWith("/api/today?preview=true"));
  await screen.findByText("16 Oct 2026");
});

it("fetches only on load and explicit Refresh and prevents concurrent refreshes", async () => {
  mock.response.mockImplementation(async () => json(payload)); render(<Page />); await screen.findByText(payload.caption);
  const resolves:((value:Response)=>void)[]=[];
  mock.response.mockImplementation(() => new Promise<Response>(done => { resolves.push(done); }));
  fireEvent.click(screen.getByRole("button",{name:text.refresh,exact:true})); fireEvent.click(screen.getByRole("button",{name:text.refresh,exact:true}));
  await waitFor(()=>expect(mock.response).toHaveBeenCalledTimes(3));
  expect(screen.getByText(payload.caption)).toBeTruthy();
  for(const resolve of resolves)resolve(json(payload));
  await waitFor(()=>expect(screen.getByRole("button",{name:text.refresh,exact:true})).toHaveProperty("disabled",false));
  expect(mock.response.mock.calls.map(args=>args[0])).toEqual(["/api/today?preview=false","/api/today?preview=false&live=true","/api/today?preview=true&live=true"]);
});

it('keeps a live Refresh live when its preview is subsequently opened',async()=>{
  mock.response.mockImplementation(async()=>json(payload));render(<Page/>);await screen.findByText(payload.caption);
  fireEvent.click(screen.getByRole("button",{name:text.refresh,exact:true}));await screen.findByText(payload.caption);
  const details=screen.getByText(text.preview).closest('details')!;details.open=true;fireEvent(details,new Event('toggle'));
  await waitFor(()=>expect(mock.response).toHaveBeenCalledWith('/api/today?preview=true&live=true'));
});

it('gives table-heavy pages room without changing default or Rules widths',()=>{
  const css=readFileSync('./app/globals.css','utf8');
  expect(css).toContain('.today-page, .compare-page, .research-page, .rebalance-page, .portfolio-page { max-width: 1160px; }');
  expect(css).toContain('main { max-width: 860px;');
  expect(css).toContain('.rules-page { max-width: 1160px;');
});

it("shows the exact normal setup message when there is no default", async () => {
  mock.response.mockResolvedValue(json({ ...payload, has_default: false })); render(<Page />);
  await screen.findByText("Use as Today default");
  expect(screen.queryByText(text.holdNow)).toBeNull(); expect(screen.queryByText(text.monthlyAction)).toBeNull();
});

it("renders unavailable reasons, stale warning and provisional rows without guessing", async () => {
  mock.response.mockResolvedValue(json({ ...payload, has_holdings: false, stale: true, monthly_action: "unavailable",
    previews: [{ ...payload.previews[0], allocation: null, allocation_display:[], kind:"always_held", change: null, price_as_of: null, reason: "This sleeve is held continuously and has no next-month timing preview." }] }));
  render(<Page />); await screen.findByText(text.staleWarning);
  expect(screen.getByText(text.noHoldings)).toBeTruthy();
  expect(screen.getByText(text.previewKinds.always_held)).toBeTruthy();
});

it("keeps an old report after failed refresh without exposing raw request errors", async () => {
  mock.response.mockImplementation(async () => json(payload)); render(<Page />); await screen.findByText(payload.caption);
  mock.response.mockResolvedValue(new Response("fake private error body", { status: 502 }));
  fireEvent.click(screen.getByRole("button",{name:text.refresh,exact:true})); await screen.findAllByText(text.refreshFailed);
  expect(screen.getByText(payload.caption)).toBeTruthy(); expect(screen.queryByText("fake private error body")).toBeNull();
});

it.each([400, 401, 403, 404, 429, 500, 502, 503, 504])("shows a safe specific reason for HTTP %s", async status => {
  mock.response.mockResolvedValue(new Response("fake private details", { status })); render(<Page />);
  await screen.findByText((text.requestErrors as Record<string, string>)[String(status)]);
  expect(screen.queryByText("fake private details")).toBeNull();
});

it("distinguishes connection failure from an unreadable successful response", async () => {
  mock.response.mockRejectedValue(new ApiError(0, "fake private details")); render(<Page />);
  await screen.findByText(text.requestErrors["0"]);
  mock.response.mockResolvedValue(new Response("not JSON", { status: 200 }));
  fireEvent.click(screen.getByRole("button",{name:text.refresh,exact:true})); await screen.findByText(text.invalidResponse);
  expect(screen.queryByText("not JSON")).toBeNull();
});

it.each(Object.entries(text.requestDetails))("recognizes only the safe server reason %s", async (detail, message) => {
  mock.response.mockResolvedValue(json({ detail }, detail.startsWith("Sign-in") ? 503 : 502));
  render(<Page />); await screen.findByText(message);
});

it.each(["fake private details", "toString", { private: "fake" }])("does not echo unrecognized JSON error details", async detail => {
  mock.response.mockResolvedValue(json({ detail }, 502)); render(<Page />);
  await screen.findByText(text.requestErrors["502"]);
  expect(screen.queryByText("fake private details")).toBeNull();
});

it("uses content-file words with no financial math or server data writes", () => {
  const source = readFileSync("./app/today/page.tsx", "utf8");
  expect(source).toContain('from "../../content/today.json"');
  expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);
  expect(source).not.toMatch(/parseFloat|toFixed|new Date|Math\.|localStorage|sessionStorage|setInterval|method:|\/api\/workspace/);
  const navigation = JSON.parse(readFileSync("./content/navigation.json", "utf8"));
  expect(navigation.pages).toEqual([
    { label: "Today", href: "/today/" },
    { label: "Signals", href: "/signals/" },
    { label: "Portfolio", href: "/portfolio/" },
    { label: "Rebalance Holdings", href: "/rebalance-holdings/" },
    { label: "Backtest", href: "/backtest/" },
    { label: "Research", href: "/research/" },
    { label: "Compare", href: "/compare/" },
    { label: "Strategy Catalogue", href: "/strategy-catalogue/" },
  ]);
});

it("shows the Gold Cross-Asset signal inputs beside its local holding", async () => {
  const details = { "Signal month-end": "2026-10-31", "US close date": "2026-10-30",
    "GLD 12-month return": "12.00%", "IEF 12-month return": "2.00%",
    "Rule result": "Both positive", "Target holding": "Tachlit Gold 5141627", "Execution currency": "ILS" };
  mock.response.mockResolvedValue(json({ ...payload, signals: [{ ...payload.signals[0],
    label: "Gold Cross-Asset Israel", signal_details: details }] }));
  render(<Page />);
  fireEvent.click(await screen.findByText(text.signalInputs));
  const panel = within(screen.getByText(text.signalInputs).closest("details")!);
  for (const value of Object.values(details)) expect(panel.getByText(value)).toBeTruthy();
});

const signedPage = (id = "user-a") => <SignedInUserContext.Provider value={id}><Page/></SignedInUserContext.Provider>;
const stored = (result: unknown = payload, loadedAt = new Date().toISOString(), id = "user-a") => {
  activateDeviceUser(id);syncPortfolio(id,mock.portfolios);
  const snapshot = {version:1,loadedAt,result};
  window.localStorage.setItem(todayStorageKey(id),JSON.stringify(snapshot));
  return snapshot;
};

it("opens the full saved Today immediately without a Today request and shows the saved 24-hour load time", () => {
  const time = new Date(2026,10,22,11,40);
  vi.spyOn(Date,"now").mockReturnValue(time.getTime());
  const snapshot=stored(payload,time.toISOString());
  render(signedPage());
  expect(screen.getByText(payload.caption)).toBeTruthy();
  const line=screen.getByText(text.loaded.replace("{time}",loadedTodayTime(snapshot.loadedAt)),{exact:false});
  expect(line.textContent).toContain("22 Nov 2026, 11:40");
  expect(screen.getByText(/Latest completed signal:/).closest("p")?.nextElementSibling).toBe(line);
  expect(mock.response).not.toHaveBeenCalled();
  expect(screen.queryByText(text.loading)).toBeNull();
});

it("labels a saved result from the previous local day and does not refresh automatically", () => {
  const yesterday=new Date();yesterday.setDate(yesterday.getDate()-1);
  stored(payload,yesterday.toISOString());
  render(signedPage());
  expect(screen.getByText(text.refreshSaved,{exact:false})).toBeTruthy();
  expect(mock.response).not.toHaveBeenCalled();
});

it("retains the normal cold load, saves its full response, then reopens it without a request", async () => {
  mock.response.mockImplementation(async()=>json(payload));
  const mounted=render(signedPage());
  await screen.findByText(payload.caption);
  expect(mock.response).toHaveBeenCalledWith("/api/today?preview=false");
  const snapshot=JSON.parse(window.localStorage.getItem(todayStorageKey("user-a"))!);
  expect(snapshot.result).toEqual(payload);
  expect(Number.isFinite(new Date(snapshot.loadedAt).getTime())).toBe(true);
  mounted.unmount();mock.response.mockClear();
  render(signedPage());
  expect(screen.getByText(payload.caption)).toBeTruthy();
  expect(mock.response).not.toHaveBeenCalled();
});

it("Refresh fetches live and replaces the saved result and original load time", async () => {
  stored(payload,"2020-01-01T11:40:00.000Z");
  const next={...payload,caption:"Refreshed complete portfolio"};
  mock.response.mockImplementation(async()=>json(next));
  render(signedPage());
  await waitFor(()=>expect(screen.getByRole("button",{name:text.refresh})).toHaveProperty("disabled",false));
  fireEvent.click(screen.getByRole("button",{name:text.refresh}));
  await screen.findByText(next.caption);
  expect(mock.response.mock.calls.map(args=>args[0])).toEqual(["/api/today?preview=false&live=true","/api/today?preview=true&live=true"]);
  const snapshot=JSON.parse(window.localStorage.getItem(todayStorageKey("user-a"))!);
  expect(snapshot.result).toEqual(next);
  expect(snapshot.loadedAt).not.toBe("2020-01-01T11:40:00.000Z");
  expect(screen.queryByText(text.refreshSaved,{exact:false})).toBeNull();
  expect(within(screen.getByText(text.monthlyAction).closest("section")!).getByText(text.loaded.replace("{time}",loadedTodayTime(snapshot.loadedAt)))).toBeTruthy();
});

it.each([
  {monthly_action:"unavailable"},
  {issues:["missing_name"]},
  {signals:[{...payload.signals[0],status_code:"unavailable",error_code:"unknown_model"}]},
  {signals:[{...payload.signals[0],status_code:"check_data"}]},
  {has_holdings:true,action_notice:"cannot_price",comparison:[]},
  {has_holdings:true,action_notice:"valuation_failed",comparison:null},
])("never replaces the saved full result with a partial response: %j", async patch => {
  const previous=stored();
  mock.response.mockImplementation(async()=>json({...payload,...patch}));
  render(signedPage());
  await waitFor(()=>expect(screen.getByRole("button",{name:text.refresh})).toHaveProperty("disabled",false));
  fireEvent.click(screen.getByRole("button",{name:text.refresh}));
  await waitFor(()=>expect(screen.getByRole("button",{name:text.refresh})).toHaveProperty("disabled",false));
  expect(JSON.parse(window.localStorage.getItem(todayStorageKey("user-a"))!)).toEqual(previous);
});

it("a failed Refresh never overwrites the last complete saved result", async () => {
  const previous=stored();mock.response.mockResolvedValue(json({},502));
  render(signedPage());await waitFor(()=>expect(screen.getByRole("button",{name:text.refresh})).toHaveProperty("disabled",false));fireEvent.click(screen.getByRole("button",{name:text.refresh}));
  await screen.findAllByText(text.refreshFailed);
  expect(JSON.parse(window.localStorage.getItem(todayStorageKey("user-a"))!)).toEqual(previous);
});

it("does not show another signed-in account's saved Today", async () => {
  stored();
  mock.response.mockResolvedValue(json({...payload,caption:"User B portfolio"}));
  const mounted=render(signedPage());
  expect(screen.getByText(payload.caption)).toBeTruthy();
  mounted.rerender(signedPage("user-b"));
  expect(screen.queryByText(payload.caption)).toBeNull();
  await screen.findByText("User B portfolio");
  expect(window.localStorage.getItem(todayStorageKey("user-a"))).toBeNull();
});

it("corrupt storage and unavailable storage do not prevent the normal load", async () => {
  window.localStorage.setItem(todayStorageKey("user-a"),"not JSON");
  mock.response.mockImplementation(async()=>json(payload));
  const mounted=render(signedPage());await screen.findByText(payload.caption);
  mounted.unmount();
  vi.spyOn(Storage.prototype,"getItem").mockImplementation(()=>{throw Error("Storage blocked");});
  vi.spyOn(Storage.prototype,"setItem").mockImplementation(()=>{throw Error("Quota exceeded");});
  render(signedPage());await screen.findByText(payload.caption);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("loads Strategy Health after displaying the saved result without reloading Today", async () => {
  stored({...payload,signals:[{...payload.signals[0],label:"Century Momentum Move to Cash"}]});
  mock.response.mockImplementation(async(path:string)=>{
    expect(screen.getByText(payload.caption)).toBeTruthy();
    expect(path).toBe("/api/strategy-health");
    return json({reports:[],checks:{findings:[],proxies:[]}});
  });
  render(signedPage());
  await waitFor(()=>expect(mock.response).toHaveBeenCalledTimes(1));
  expect(mock.response.mock.calls[0][0]).toBe("/api/strategy-health");
});

const healthResult = (summary="Complete saved health") => {
  const metric={current:.1,percentile:50,samples:10,status:"green",review_value:.2,structural_value:.3,distribution:[.1,.2]};
  return {reports:[{key:"combined",status:"green",summary,models:["Century Momentum Move to Cash"],findings:[],metrics:{drawdown:metric,underwater:metric,relative:metric}}],checks:{findings:[],proxies:[]}};
};
const completePortfolio = {...payload,signals:[{...payload.signals[0],label:"Century Momentum Move to Cash"}],
  previews:[{...payload.previews[0],label:"Century Momentum Move to Cash"}]};
const resultRecords = () => Object.keys(localStorage).filter(k=>k.endsWith(":today") || k.endsWith(":preview") || k.includes(":health:"));
async function seedAllResults() {
  mock.response.mockImplementation(async(path:string)=>json(path==="/api/strategy-health" ? healthResult() : completePortfolio));
  const mounted=render(signedPage());await screen.findByText(completePortfolio.caption);
  const details=screen.getByText(text.preview).closest('details')!;details.open=true;fireEvent(details,new Event('toggle'));
  await waitFor(()=>expect(resultRecords()).toHaveLength(3));
  mounted.unmount();mock.response.mockClear();
  for(const key of resultRecords()) {
    const value=JSON.parse(localStorage.getItem(key)!);value.loadedAt="2020-01-01T11:40:00.000Z";localStorage.setItem(key,JSON.stringify(value));
  }
}

it("reopens all three complete results with their own times and no calculation request", async()=>{
  await seedAllResults();
  render(signedPage());
  expect(screen.getByText(completePortfolio.caption)).toBeTruthy();
  expect(screen.getByText('Complete saved health')).toBeTruthy();
  const details=screen.getByText(text.preview).closest('details')!;details.open=true;fireEvent(details,new Event('toggle'));
  await waitFor(()=>expect(screen.getByRole('button',{name:text.refresh,exact:true})).toHaveProperty('disabled',false));
  expect(screen.getAllByText(/Loaded 01 Jan 2020, 11:40/)).toHaveLength(3);
  expect(mock.response).not.toHaveBeenCalled();
});

it("refreshes Health and preview separately, then the main Refresh replaces all three",async()=>{
  await seedAllResults();render(signedPage());
  await waitFor(()=>expect(screen.getByRole('button',{name:text.refresh,exact:true})).toHaveProperty('disabled',false));
  const original=new Map(resultRecords().map(k=>[k,localStorage.getItem(k)]));
  mock.response.mockImplementation(async(path:string)=>json(path==='/api/strategy-health' ? healthResult('Health refreshed alone') : {...completePortfolio,preview_caption:'Preview refreshed alone'}));
  fireEvent.click(screen.getByRole('button',{name:'Refresh Strategy Health'}));
  await screen.findByText('Health refreshed alone');
  expect(mock.response.mock.calls.map(args=>args[0])).toEqual(['/api/strategy-health']);
  for(const [key,value] of original)if(!key.includes(':health:'))expect(localStorage.getItem(key)).toBe(value);
  const details=screen.getByText(text.preview).closest('details')!;details.open=true;fireEvent(details,new Event('toggle'));
  fireEvent.click(screen.getByRole('button',{name:text.refreshPreview}));
  await screen.findByText('Preview refreshed alone');
  expect(screen.getByText(completePortfolio.caption)).toBeTruthy();
  expect(mock.response.mock.calls[1][0]).toBe('/api/today?preview=true&live=true');
  mock.response.mockClear();
  mock.response.mockImplementation(async(path:string)=>json(path==='/api/strategy-health' ? healthResult('Main refreshed health') : {...completePortfolio,caption:'Main refreshed Today',preview_caption:'Main refreshed preview'}));
  fireEvent.click(screen.getByRole('button',{name:text.refresh,exact:true}));
  await screen.findByText('Main refreshed Today');await screen.findByText('Main refreshed health');await screen.findByText('Main refreshed preview');
  expect(mock.response.mock.calls.map(args=>args[0]).sort()).toEqual(['/api/strategy-health','/api/today?preview=false&live=true','/api/today?preview=true&live=true'].sort());
  expect(screen.queryAllByText(/Loaded 01 Jan 2020/)).toHaveLength(0);
});

it.each(['http','partial'])('failed %s refreshes keep all three saved results and original times',async kind=>{
  await seedAllResults();const original=new Map(resultRecords().map(k=>[k,localStorage.getItem(k)]));
  render(signedPage());await waitFor(()=>expect(screen.getByRole('button',{name:text.refresh,exact:true})).toHaveProperty('disabled',false));
  mock.response.mockImplementation(async(path:string)=>kind==='http' ? json({},502) : json(path==='/api/strategy-health' ? {reports:[],checks:{findings:[],proxies:[]}} : {...completePortfolio,monthly_action:'unavailable',previews:[]}));
  fireEvent.click(screen.getByRole('button',{name:text.refresh,exact:true}));
  const details=screen.getByText(text.preview).closest('details')!;details.open=true;fireEvent(details,new Event('toggle'));
  await waitFor(()=>expect(screen.getAllByText(text.refreshFailed)).toHaveLength(3));
  for(const [key,value] of original)expect(localStorage.getItem(key)).toBe(value);
  expect(screen.getByText(completePortfolio.caption)).toBeTruthy();expect(screen.getByText('Complete saved health')).toBeTruthy();
  expect(screen.getAllByText(/Loaded 01 Jan 2020, 11:40/)).toHaveLength(3);
});

it('clears all old sections when the saved default portfolio changes elsewhere',async()=>{
  await seedAllResults();const oldKeys=resultRecords();
  mock.portfolios=[{id:'new-default',is_default:true,updated_at:'revision-2',payload:{name:'New default'}}];
  mock.response.mockImplementation(async(path:string)=>json(path==='/api/strategy-health' ? healthResult('New health') : {...completePortfolio,caption:'New portfolio Today',preview_caption:'New portfolio preview'}));
  render(signedPage());await screen.findByText('New portfolio Today');
  for(const key of oldKeys)expect(localStorage.getItem(key)).toBeNull();
  expect(screen.queryByText('Complete saved health')).toBeNull();
});

it.each(['health','preview'])('main Refresh queues an update when the %s section is already refreshing',async section=>{
  await seedAllResults();render(signedPage());
  await waitFor(()=>expect(screen.getByRole('button',{name:text.refresh,exact:true})).toHaveProperty('disabled',false));
  const details=screen.getByText(text.preview).closest('details')!;details.open=true;fireEvent(details,new Event('toggle'));
  let finish!:(value:Response)=>void;let focusedCalls=0;
  mock.response.mockImplementation(async(path:string)=>{
    const focused=section==='health' ? path==='/api/strategy-health' : path.includes('preview=true');
    if(focused && ++focusedCalls===1)return new Promise<Response>(resolve=>{finish=resolve;});
    return json(path==='/api/strategy-health' ? healthResult('Final queued health') : {...completePortfolio,preview_caption:'Final queued preview'});
  });
  fireEvent.click(screen.getByRole('button',{name:section==='health'?'Refresh Strategy Health':text.refreshPreview}));
  await waitFor(()=>expect(focusedCalls).toBe(1));
  fireEvent.click(screen.getByRole('button',{name:text.refresh,exact:true}));
  await waitFor(()=>expect(mock.response.mock.calls.some(([path])=>path==='/api/today?preview=false&live=true')).toBe(true));
  finish(json(section==='health' ? healthResult('Interim health') : {...completePortfolio,preview_caption:'Interim preview'}));
  await screen.findByText(section==='health'?'Final queued health':'Final queued preview');
  expect(focusedCalls).toBe(2);
});
