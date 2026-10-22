import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import words from "../content/backtest-multi.json";
import text from "../content/backtest.json";

const mock = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../lib/backtestApi", () => ({ backtestRequest: mock.request, backtestDownload: vi.fn() }));
import MultiForm from "../app/backtest/multi-form";

const config = { models: [{ label: "HAA-Simple", strategy: "HAA", variant: "Simple", implementation: "Original" }],
  proxies: [{ key: "century_momentum", label: "Century proxy", caveat: "Mock caveat" }, { key: "haa_simple", label: "HAA proxy", caveat: "Mock caveat" }, { key: "gem", label: "GEM proxy", caveat: "Mock GEM caveat" }, { key: "rvol_daily", label: "Daily proxy", caveat: "Mock daily caveat" }],
  single_options: ["century_momentum", "haa_simple", "gem", "rvol_daily"], blend_options: ["century_momentum", "haa_simple", "gem"], benchmarks: [{ key: "sp500", label: "Mock benchmark", caveat: "Mock benchmark caveat" }] };
afterEach(() => { cleanup(); mock.request.mockReset(); });
function setup(mode: "portfolio" | "deep", defaultId?: string) {
  const run = vi.fn(async (_body: Record<string, unknown>) => {}); const changed = vi.fn();
  mock.request.mockImplementation(async (path: string, init?: RequestInit) => {
    if (path.startsWith("/api/backtest/config")) return config;
    if (path === "/api/portfolios") return defaultId ? [{id:'fake-id',is_default:defaultId==='fake-id'},{id:'fake-second',is_default:defaultId==='fake-second'}] : [{ id: "fake-id", name: "Fake portfolio" }];
    if (path === "/api/compare/options") return {portfolios:[{ id: "fake-id", name: "Fake portfolio" },{id:"fake-second",name:"Fake second"}]};
    if (path === "/api/backtest/load") return { sleeves: [{ id: 1, model: mode === "deep" ? "haa_simple" : "HAA-Simple", weight: 100 }], initial: 3000, warnings: [] };
    const body = JSON.parse(init?.body as string);
    if (body.sleeves.some((s: { weight: number }) => s.weight <= 0)) throw new Error(words.positivePortfolio);
    return { valid: true, message: words.weightSuccess };
  });
  render(<MultiForm mode={mode} running={false} onRun={run} onChange={changed} />);
  return { run, changed };
}

it('puts the default saved portfolio first and selects it when the old default was first item',async()=>{
  setup('portfolio','fake-second');await screen.findByText('Fake second');
  const select=screen.getByLabelText(words.saved) as HTMLSelectElement;
  expect(Array.from(select.options).map(o=>o.value)).toEqual(['fake-second','fake-id']);
  expect(select.value).toBe('fake-second');
  fireEvent.change(select,{target:{value:'fake-id'}});expect(select.value).toBe('fake-id');
});

it("only validates on edits; runs solely on the explicit button, disabled for invalid weights", async () => {
  const {run} = setup("portfolio");
  await screen.findByText(words.weightSuccess);
  expect(run).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText(words.add));
  await screen.findByText(words.positivePortfolio);
  expect(screen.getByRole("button", { name: text.run })).toHaveProperty("disabled", true);
  fireEvent.click(screen.getAllByText(words.remove)[1]);
  await waitFor(() => expect(screen.getByRole("button", { name: text.run })).toHaveProperty("disabled", false));
  fireEvent.click(screen.getByRole("button", { name: text.run }));
  expect(run).toHaveBeenCalledTimes(1);
  expect(run.mock.calls[0][0]).toMatchObject({ mode: "portfolio", tax_enabled: true, tax_rate: 25, fee_value: 0 });
  expect(run.mock.calls[0][0]).toMatchObject({fees_enabled:true,ils_fee_percent:.05,ils_minimum_fee:2,usd_flat_fee:5});
  expect(mock.request.mock.calls.every(([path]) => !["/api/workspace", "/api/backtest"].includes(path))).toBe(true);
});

it('passes editable fee assumptions and an explicit off switch in portfolio mode', async()=>{
  const {run}=setup('portfolio');await screen.findByText(words.weightSuccess);
  fireEvent.change(screen.getByLabelText(text.usdFlatFee),{target:{value:'7'}});
  fireEvent.change(screen.getByLabelText(text.ilsMinimumFee),{target:{value:'4'}});
  fireEvent.change(screen.getByLabelText(text.ilsFeePercent),{target:{value:'.1'}});
  fireEvent.click(screen.getByLabelText(text.feesEnabled));
  await waitFor(()=>expect(screen.getByRole('button',{name:text.run})).toHaveProperty('disabled',false));
  fireEvent.click(screen.getByRole('button',{name:text.run}));
  expect(run.mock.calls[0][0]).toMatchObject({fees_enabled:false,usd_flat_fee:7,ils_minimum_fee:4,ils_fee_percent:.1});
});

it("retains daily single-proxy restrictions and benchmark caveats", async () => {
  setup("deep"); await screen.findByText(words.weightSuccess);
  fireEvent.change(screen.getByLabelText(words.proxyStrategy), {target: {value: "rvol_daily"}});
  await screen.findByLabelText(words.dailyTax);
  expect(screen.getByLabelText(words.dailyTax)).toHaveProperty("disabled", true);
  expect(screen.getByLabelText(words.dailyTax)).toHaveProperty("checked", false);
  expect(screen.getByLabelText(words.weight)).toHaveProperty("value", "100");
  expect(screen.getByLabelText(words.weight)).toHaveProperty("disabled", true);
  expect(screen.getByText(words.add)).toHaveProperty("disabled", true);
  expect(screen.getByText(words.benchmarkHelp)).toBeTruthy();
  expect(screen.getByText("Mock benchmark caveat")).toBeTruthy();
});

it("loads saved choices and Python-converted capital without running or saving", async () => {
  const {run} = setup("portfolio"); await screen.findByText(words.weightSuccess);
  expect(mock.request).toHaveBeenCalledWith("/api/compare/options",expect.objectContaining({signal:expect.any(AbortSignal)}));
  const details = screen.getByText(words.load, {selector:"summary"}).closest("details")!;
  details.open = true; fireEvent(details, new Event("toggle"));
  await screen.findByText("Fake portfolio");
  fireEvent.click(screen.getByRole("button", {name: words.load}));
  await waitFor(() => expect(screen.getByLabelText(text.initial)).toHaveProperty("value", "3000"));
  expect(run).not.toHaveBeenCalled();
  expect(mock.request).toHaveBeenCalledWith("/api/backtest/load", expect.objectContaining({ method: "POST", body: JSON.stringify({mode:"portfolio", portfolio_id:"fake-id"}) }));
});

it("loads the chosen saved portfolio, replaces sleeves and preserves server-converted capital",async()=>{
  const {run}=setup("portfolio");await screen.findByText(words.weightSuccess);await screen.findByText("Fake second");
  const original=mock.request.getMockImplementation()!;
  mock.request.mockImplementation(async(path,init)=>path==="/api/backtest/load"?
    {sleeves:[{id:3,model:"HAA-Simple",weight:60},{id:9,model:"HAA-Simple",weight:40}],initial:7654,warnings:[]} : original(path,init));
  fireEvent.change(screen.getByLabelText(words.saved),{target:{value:"fake-second"}});
  fireEvent.click(screen.getByRole("button",{name:words.load}));
  await waitFor(()=>expect(screen.getByLabelText(text.initial)).toHaveProperty("value","7654"));
  expect(screen.getAllByLabelText(words.weight).map(input=>(input as HTMLInputElement).value)).toEqual(["60","40"]);
  expect(mock.request).toHaveBeenCalledWith("/api/backtest/load",expect.objectContaining({body:JSON.stringify({mode:"portfolio",portfolio_id:"fake-second"})}));
  expect(run).not.toHaveBeenCalled();
});

it('restores the saved transfer rule and parameters into the run request, then resets them for a legacy portfolio',async()=>{
  const {run}=setup('portfolio');await screen.findByText(words.weightSuccess);await screen.findByText('Fake portfolio');
  const original=mock.request.getMockImplementation()!;let legacy=false;
  mock.request.mockImplementation(async(path,init)=>path==='/api/backtest/load' ?
    legacy ? {sleeves:[{id:1,model:'HAA-Simple',weight:100}],initial:3000,warnings:[]} :
    {sleeves:[{id:1,model:'HAA-Simple',weight:80},{id:2,model:'A-RVol Shifter V3 Cash-Only',weight:20}],initial:3000,warnings:[],sleeve_rebalance_mode:'rvol_cap',rebalance_sleeve:2,rebalance_cap:17.5,rebalance_target:9.25} : original(path,init));
  fireEvent.click(screen.getByRole('button',{name:words.load}));
  await waitFor(()=>expect(screen.getByLabelText(words.rule)).toHaveProperty('value','rvol_cap'));
  expect(screen.getByLabelText(words.capSleeve)).toHaveProperty('value','2');
  expect(screen.getByLabelText(words.cap)).toHaveProperty('value','17.5');
  expect(screen.getByLabelText(words.target)).toHaveProperty('value','9.25');
  await waitFor(()=>expect(screen.getByRole('button',{name:text.run})).toHaveProperty('disabled',false));
  fireEvent.click(screen.getByRole('button',{name:text.run}));
  expect(run.mock.calls[0][0]).toMatchObject({sleeve_rebalance_mode:'rvol_cap',rebalance_sleeve:2,rebalance_cap:17.5,rebalance_target:9.25});
  legacy=true;fireEvent.click(screen.getByRole('button',{name:words.load}));
  await waitFor(()=>expect(screen.getByLabelText(words.rule)).toHaveProperty('value','none'));
  await waitFor(()=>expect(screen.getByRole('button',{name:text.run})).toHaveProperty('disabled',false));
  fireEvent.click(screen.getByRole('button',{name:text.run}));
  expect(run.mock.calls[1][0]).toMatchObject({sleeve_rebalance_mode:'none',rebalance_sleeve:null,rebalance_cap:15,rebalance_target:10});
});

it('restores an annual rule without changing unrelated assumptions',async()=>{
  const {run}=setup('portfolio');await screen.findByText(words.weightSuccess);await screen.findByText('Fake portfolio');
  fireEvent.change(screen.getByLabelText(text.usdFlatFee),{target:{value:'7'}});
  const original=mock.request.getMockImplementation()!;
  mock.request.mockImplementation(async(path,init)=>path==='/api/backtest/load' ?
    {sleeves:[{id:1,model:'HAA-Simple',weight:100}],initial:4321,warnings:[],sleeve_rebalance_mode:'annual_target',rebalance_sleeve:null,rebalance_cap:15,rebalance_target:10}:original(path,init));
  fireEvent.click(screen.getByRole('button',{name:words.load}));
  await waitFor(()=>expect(screen.getByLabelText(words.rule)).toHaveProperty('value','annual_target'));
  await waitFor(()=>expect(screen.getByRole('button',{name:text.run})).toHaveProperty('disabled',false));
  fireEvent.click(screen.getByRole('button',{name:text.run}));
  expect(run.mock.calls[0][0]).toMatchObject({sleeve_rebalance_mode:'annual_target',initial:4321,usd_flat_fee:7,tax_rate:25});
});

it("shows saved-list failures and retries without calling a backtest",async()=>{
  const {run}=setup("portfolio");await screen.findByText(words.weightSuccess);
  // Remount to exercise the automatic read failing, not only a disclosure.
  cleanup();const original=mock.request.getMockImplementation()!;
  mock.request.mockImplementation(async(path,init)=>{if(path==="/api/compare/options")throw new Error("Mock library unavailable");return original(path,init);});
  render(<MultiForm mode="portfolio" running={false} onRun={run} onChange={vi.fn()}/>);
  await screen.findByText(`${words.savedListError} Mock library unavailable`);
  expect(screen.queryByText(words.emptySaved)).toBeNull();
  mock.request.mockImplementation(original);
  fireEvent.click(screen.getByRole("button",{name:words.retrySaved}));await screen.findByText("Fake second");
  expect(screen.queryByText(`${words.savedListError} Mock library unavailable`)).toBeNull();
  expect(run).not.toHaveBeenCalled();
});

it("keeps the current form and shows a visible error when loading fails",async()=>{
  setup("portfolio");await screen.findByText(words.weightSuccess);await screen.findByText("Fake portfolio");
  const original=mock.request.getMockImplementation()!;
  mock.request.mockImplementation(async(path,init)=>{if(path==="/api/backtest/load")throw new Error("Mock portfolio unavailable");return original(path,init);});
  fireEvent.click(screen.getByRole("button",{name:words.load}));
  expect(await screen.findByRole("alert")).toHaveProperty("textContent","Mock portfolio unavailable");
  expect(screen.getByLabelText(text.initial)).toHaveProperty("value","100000");
  expect(screen.getByLabelText(words.weight)).toHaveProperty("value","100");
});

it("prevents duplicate loads and form edits while a saved portfolio is loading",async()=>{
  setup("portfolio");await screen.findByText(words.weightSuccess);await screen.findByText("Fake portfolio");
  const original=mock.request.getMockImplementation()!;let resolve!:(value:unknown)=>void;
  mock.request.mockImplementation((path,init)=>path==="/api/backtest/load"?new Promise(done=>{resolve=done;}):original(path,init));
  const button=screen.getByRole("button",{name:words.load});fireEvent.click(button);fireEvent.click(button);
  expect(mock.request.mock.calls.filter(([path])=>path==="/api/backtest/load")).toHaveLength(1);
  expect(screen.getByText(words.loadingPortfolio)).toBeTruthy();
  expect(screen.getByLabelText(text.initial).closest("fieldset")).toHaveProperty("disabled",true);
  resolve({sleeves:[{id:1,model:"HAA-Simple",weight:100}],initial:3000,warnings:[]});
  await waitFor(()=>expect(screen.getByLabelText(text.initial)).toHaveProperty("value","3000"));
});

it("keeps all added component wording in data files and scopes Today wrapping", () => {
  const source = readFileSync("./app/backtest/multi-form.tsx", "utf8");
  expect(source).toContain('content/backtest-multi.json');
  expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);
  expect(source).not.toMatch(/reduce\(|toFixed|\/api\/workspace|localStorage|sessionStorage/);
  const css = readFileSync("./app/globals.css", "utf8");
  expect(css).toContain(".today-sleeve-table table { table-layout: auto; white-space: normal; min-width: 760px; }");
  expect(css).toContain(".signal-table-scroll table { width: 100%; border-collapse: collapse; font-size: .85rem; white-space: nowrap; }");
  expect(readFileSync("./app/today/page.tsx", "utf8")).toContain("signal-table-scroll today-sleeve-table");
});
