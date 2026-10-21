import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/today.json";

const mock = vi.hoisted(() => ({ response: vi.fn() }));
vi.mock("../lib/api", () => ({ authorizedResponse: mock.response, ApiError: class extends Error { constructor(public status: number, message: string) { super(message); } } }));
vi.mock("next/navigation", () => ({ usePathname: () => "/today/" }));
vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: {
  getSession: async () => ({ data: { session: null }, error: null }),
  onAuthStateChange: () => ({ data: { subscription: { unsubscribe() {} } } }),
} }) }));
import Page from "../app/today/page";
import AuthGate from "../components/AuthGate";
import { ApiError } from "../lib/api";
import { historyTable, historyCsv } from "../app/today/history-sources";

const payload = { has_default: true, caption: "Fake portfolio · private synced portfolio", issues: [],
  signals: [{ label: "Fake sleeve", weight_text: "40.00%", holding: "Fake holding 100%", status: "Ready · fake", error_code: null,
    amounts:[{holding:"Fake holding",amount:2500,currency:"USD"},{holding:"Fake local holding",amount:6000,currency:"ILS"}] }],
  holdings: [{ currency: "USD", rows: [{ holding: "Fake holding", weight_text: "40.00%", amount_text: "2,500.00" }] },
    { currency: "ILS", rows: [{ holding: "Fake local holding", weight_text: "60.00%", amount_text: "6,000.00" }] }],
  monthly_action: "unchanged", latest_caption: "Latest completed signal: 2026-09-30", stale: false,
  previews: [{ label: "Fake sleeve", allocation: "Fake holding 100%", change: "no", price_as_of: "2026-10-16", reason: null, error_code: null }],
  preview_caption: "Mock latest common eligible price caption", warnings: [], public_sleeves: [], timing: {} };
const json = (value: unknown, status=200) => new Response(JSON.stringify(value), { status });
afterEach(() => { cleanup(); mock.response.mockReset(); vi.restoreAllMocks(); });

const plainSleeve = (asset: string, source: string, first: string, series: string) => ({
  model: `Fake plain ${asset}`,
  provenance: { columns: ['asset','source','identifier','price_field','history_kind','automatic_proxy_extension'], rows: [{asset,source,identifier:asset,price_field:series,history_kind:'Actual fund history',automatic_proxy_extension:false}] },
  data_ranges: { columns: ['asset','first_available','last_available','observations'], rows: [{asset,first_available:first,last_available:'2026-10-16',observations:123}] },
});

it('shows one grey note and one collapsed source table under the intro, only for default plain holdings',async()=>{
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
  expect(details.compareDocumentPosition(screen.getByText(text.monthlyAction))&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  details.open=true;fireEvent(details,new Event('toggle'));
  const table=screen.getByRole('table',{name:text.historySources});
  expect(table.querySelectorAll('tbody tr')).toHaveLength(2);
  for(const value of ['FAKE_GOLD','FAKE_BONDS','Mock gold source','Mock bond source','18 Nov 2004','26 Jul 2002','Adjusted mock close','Mock total-return NAV'])
    expect(table.textContent).toContain(value);
  expect(mock.response).toHaveBeenCalledTimes(1); // Opening history never requests a preview or changes signals.
  expect(screen.getByText(text.actions.unchanged)).toBeTruthy();
  expect(screen.getByText('Fake holding: 2,500.00 USD')).toBeTruthy();
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

it('scopes grey caption and whole-word phone layout to Today history only',()=>{
  const css=readFileSync('./app/today/history-sources.module.css','utf8');
  expect(css).toContain('font-size: .85rem');expect(css).toContain('color: #626b7a');
  expect(css).toContain('white-space: normal');expect(css).toContain('overflow-wrap: normal');
  expect(css).toContain('word-break: normal');expect(css).toContain('hyphens: none');
  expect(css).not.toMatch(/break-all|anywhere|overflow:\s*hidden/);
  expect(css).toContain('min-width: 52rem'); // Existing scroll wrapper, not clipped cells or broken words.
});

it("does not mount or fetch Today before the existing login gate admits it", async () => {
  render(<AuthGate><Page /></AuthGate>); await screen.findByText("Sign in with Google"); expect(mock.response).not.toHaveBeenCalled();
});

it("renders only server-formatted currency amounts and starts with preview collapsed", async () => {
  mock.response.mockImplementation(async () => json(payload)); render(<Page />);
  await screen.findByText(payload.caption);
  expect(screen.getByText("Fake holding: 2,500.00 USD")).toBeTruthy(); expect(screen.getByText("Fake local holding: 6,000.00 ILS")).toBeTruthy();
  expect(screen.getByText(text.preview).closest("details")).toHaveProperty("open", false);
  expect(screen.getByText(text.actions.unchanged)).toBeTruthy();
  expect(screen.getAllByRole("button").map(button => button.textContent)).toEqual([text.refresh]);
  expect(mock.response).toHaveBeenCalledWith("/api/today?preview=false");
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
  let resolve!: (value: Response) => void;
  mock.response.mockImplementation(() => new Promise(done => { resolve=done; }));
  fireEvent.click(screen.getByText(text.refresh)); fireEvent.click(screen.getByText(text.refresh));
  expect(mock.response).toHaveBeenCalledTimes(2); expect(screen.getByText(text.loading)).toBeTruthy();
  expect(screen.queryByText(payload.caption)).toBeNull();
  resolve(json(payload)); await screen.findByText(payload.caption);
  expect(mock.response.mock.calls.every(args => args.length === 1 && args[0] === "/api/today?preview=false")).toBe(true);
});

it("shows the exact normal setup message when there is no default", async () => {
  mock.response.mockResolvedValue(json({ ...payload, has_default: false })); render(<Page />);
  await screen.findByText("Use as Today default");
  expect(screen.queryByText(text.holdNow)).toBeNull(); expect(screen.queryByText(text.monthlyAction)).toBeNull();
});

it("renders unavailable reasons, stale warning and provisional rows without guessing", async () => {
  mock.response.mockResolvedValue(json({ ...payload, holdings: null, stale: true, monthly_action: "unavailable",
    issues: ["invalid_capital_fx"], previews: [{ ...payload.previews[0], allocation: null, change: null, price_as_of: null, reason: "This sleeve is held continuously and has no next-month timing preview." }] }));
  render(<Page />); await screen.findByText(text.staleWarning);
  expect(screen.getByText(text.combinedWarning)).toBeTruthy(); expect(screen.getByText(text.errors.invalid_capital_fx)).toBeTruthy();
  expect(screen.getByText("This sleeve is held continuously and has no next-month timing preview.")).toBeTruthy();
});

it("does not expose raw request errors or keep an old report after failed refresh", async () => {
  mock.response.mockImplementation(async () => json(payload)); render(<Page />); await screen.findByText(payload.caption);
  mock.response.mockResolvedValue(new Response("fake private error body", { status: 502 }));
  fireEvent.click(screen.getByText(text.refresh)); await screen.findByText(text.requestErrors["502"]);
  expect(screen.queryByText(payload.caption)).toBeNull(); expect(screen.queryByText("fake private error body")).toBeNull();
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
  fireEvent.click(screen.getByText(text.refresh)); await screen.findByText(text.invalidResponse);
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

it("uses content-file words with no browser financial/date math or user-data writes", () => {
  const source = readFileSync("./app/today/page.tsx", "utf8");
  expect(source).toContain('from "../../content/today.json"');
  expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);
  expect(source).not.toMatch(/parseFloat|toFixed|new Date|Math\.|localStorage|sessionStorage|setInterval|method:|\/api\/workspace/);
  const navigation = readFileSync("./components/top-navigation.tsx", "utf8");
  expect(navigation).toContain('const pages = ["Today",');
});
