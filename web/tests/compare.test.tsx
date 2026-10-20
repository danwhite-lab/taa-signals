import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/compare.json";
const mock=vi.hoisted(()=>({request:vi.fn(),download:vi.fn()}));
vi.mock("../lib/compareApi",()=>({compareRequest:mock.request,compareDownload:mock.download}));
vi.mock("next/navigation",()=>({usePathname:()=>"/compare/"}));
vi.mock("../lib/supabaseBrowser",()=>({supabaseBrowser:()=>({auth:{getSession:async()=>({data:{session:null},error:null}),onAuthStateChange:()=>({data:{subscription:{unsubscribe(){}}}})}})}));
import Page from "../app/compare/page";
import AuthGate from "../components/AuthGate";
const table={columns:["metric","SPY buy-and-hold"],rows:[{metric:"Mock metric","SPY buy-and-hold":.1}],total_rows:1,shown_rows:1};
const options={models:[{label:"HAA-Simple",benchmark:"SPY",execution_currency:"USD"},{label:"Inflation Compass Standard",benchmark:"SPY",execution_currency:"USD"},{label:"Mock ILS model",benchmark:"Local SPY",execution_currency:"ILS"}],
  portfolios:[{id:"fake-a",name:"Fake portfolio A"},{id:"fake-b",name:"Fake portfolio B"}],defaults:{mode:"models",models:["HAA-Simple","Inflation Compass Standard"],portfolio_ids:[],method:"monthly",initial:100000,fee_pct:0,tax_enabled:false,tax_rate:25,start:null,end:null}};
const report={gate:"available",mode:"models",tax_enabled:true,success:"All results below use **2020-01-01 through 2024-01-01** (48 complete monthly holding periods).",source_caption:"Mock shared data window",window:{start:"2020-01-01",end:"2024-01-01",periods:48},coverage:table,
  tables:Object.fromEntries(["summary_pre","summary_after","annual_pre","annual_after","monthly_pre","monthly_after","allocation"].map(key=>[key,table])),charts:{},warnings:[],cache:{key:"fake-key",hit:null},timing:{},data_validation:table,
  downloads:[{kind:"monthly-returns",label:text.downloads["monthly-returns"],filename:"haa_model_comparison_monthly_returns.csv"},{kind:"audit:HAA-Simple",label:"Download HAA-Simple common-period audit CSV",filename:"haa-simple_comparison_audit.csv"}]};
afterEach(()=>{cleanup();mock.request.mockReset();mock.download.mockReset();});
async function ready(){
  mock.request.mockImplementation(async(path:string)=>path==="/api/compare/options"?options:report);
  mock.download.mockResolvedValue(undefined);render(<Page/>);return screen.findByRole("button",{name:text.run});
}
function select(label:string,values:string[]){
  const select=screen.getByLabelText(label) as HTMLSelectElement;
  for(const option of Array.from(select.options)) option.selected=values.includes(option.value);
  fireEvent.change(select);
}

it("uses the existing sign-in gate",async()=>{
  render(<AuthGate><Page/></AuthGate>);await screen.findByText("Sign in with Google");expect(mock.request).not.toHaveBeenCalled();
});
it("loads options only and preserves independent tax-off defaults",async()=>{
  await ready();expect(mock.request).toHaveBeenCalledTimes(1);expect(mock.request.mock.calls[0][0]).toBe("/api/compare/options");
  expect(screen.getByLabelText(text.tax)).toHaveProperty("checked",false);expect(screen.getByLabelText(text.rate)).toHaveProperty("disabled",true);
  expect(screen.getByLabelText(text.initial)).toHaveProperty("value","100000");expect(screen.getByLabelText(text.start)).toHaveProperty("value","");
  expect(screen.getByText(text.modelsCaption)).toBeTruthy();expect(screen.getByText(text.dateHelp)).toBeTruthy();
});
it("shows both exact insufficient-selection gates without controls",async()=>{
  await ready();select(text.models,["HAA-Simple"]);expect(screen.getByText(text.modelsGate)).toBeTruthy();expect(screen.queryByText(text.run)).toBeNull();
  fireEvent.change(screen.getByLabelText(text.mode),{target:{value:"portfolios"}});expect(screen.getByText(text.portfoliosGate)).toBeTruthy();
  expect(screen.queryByLabelText(text.portfolioInitial)).toBeNull();
});
it("shows the engine refusal without pre-blocking mixed benchmarks",async()=>{
  await ready();select(text.models,["HAA-Simple","Mock ILS model"]);expect(screen.getByText(text.hint)).toBeTruthy();
  mock.request.mockRejectedValue(new Error(text.mismatch));fireEvent.click(screen.getByRole("button",{name:text.run}));
  await screen.findByText(text.mismatch);expect(screen.queryByText(text.completed)).toBeNull();
});
it("renders collapsed results, benchmark labels and Python CSV manifest",async()=>{
  fireEvent.click(await ready());await screen.findByText(text.completed);
  for(const section of text.sections)expect(screen.getByText(section,{selector:"summary"}).closest("details")).toHaveProperty("open",false);
  expect(screen.getAllByText("SPY buy-and-hold").length).toBeGreaterThan(0);expect(screen.getByText(text.latest)).toBeTruthy();
  expect(screen.getByText(text.pre)).toBeTruthy();expect(screen.getByText(text.after)).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:text.downloads["monthly-returns"]}));
  expect(mock.download).toHaveBeenCalledWith("fake-key","monthly-returns","haa_model_comparison_monthly_returns.csv");
});
it.each([text.initial,text.fee,text.start,text.end,text.rate])("clears results when %s changes",async(label)=>{
  fireEvent.click(await ready());await screen.findByText(text.completed);
  fireEvent.change(screen.getByLabelText(label),{target:{value:label===text.start||label===text.end?"2021-01-01":"1"}});
  expect(screen.queryByText(text.completed)).toBeNull();expect(screen.getByText(text.changed)).toBeTruthy();
});
it("clears on tax, model, mode, method and saved selections",async()=>{
  fireEvent.click(await ready());await screen.findByText(text.completed);fireEvent.click(screen.getByLabelText(text.tax));expect(screen.queryByText(text.completed)).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:text.run}));await screen.findByText(text.completed);select(text.models,["Inflation Compass Standard","Mock ILS model"]);expect(screen.queryByText(text.completed)).toBeNull();
  fireEvent.change(screen.getByLabelText(text.mode),{target:{value:"portfolios"}});select(text.saved,["fake-a","fake-b"]);
  mock.request.mockResolvedValue({...report,mode:"portfolios",success:null,downloads:[{kind:"portfolio-returns",label:text.downloads["portfolio-returns"],filename:"portfolio_comparison.csv"}]});
  fireEvent.click(screen.getByRole("button",{name:text.run}));await screen.findByText(text.completed);
  expect(screen.getByText(text.closing)).toBeTruthy();expect(screen.getByText(text.savedCaption)).toBeTruthy();expect(screen.getByText(text.methodCaption)).toBeTruthy();
  expect(screen.getByText(text.portfolioAfter)).toBeTruthy();
  fireEvent.change(screen.getByLabelText(text.method),{target:{value:"daily"}});expect(screen.queryByText(text.completed)).toBeNull();
  fireEvent.click(screen.getByRole("button",{name:text.run}));await screen.findByText(text.completed);select(text.saved,["fake-a"]);expect(screen.queryByText(text.completed)).toBeNull();
});
it("guards duplicate requests and disables controls in flight",async()=>{
  let resolve!:(value:unknown)=>void;
  mock.request.mockImplementation((path:string)=>path==="/api/compare/options"?Promise.resolve(options):new Promise(done=>{resolve=done;}));
  render(<Page/>);const run=await screen.findByRole("button",{name:text.run});fireEvent.click(run);fireEvent.click(run);
  expect(mock.request.mock.calls.filter(([path])=>path==="/api/compare")).toHaveLength(1);expect(run).toHaveProperty("disabled",true);
  expect((screen.getByLabelText(text.mode) as HTMLSelectElement).closest("fieldset")).toHaveProperty("disabled",true);
  expect(screen.getByText(text.progress)).toBeTruthy();resolve(report);await screen.findByText(text.completed);
});
it("shows timeout without partial results",async()=>{
  const run=await ready();mock.request.mockRejectedValue(new Error(text.timeout));fireEvent.click(run);await screen.findByText(text.timeout);expect(screen.queryByText(text.completed)).toBeNull();
});
it("keeps words in data and contains no financial calculations, local storage or record writes",()=>{
  const source=readFileSync("./app/compare/page.tsx","utf8");expect(source).toContain('content/compare.json');
  expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);expect(source).not.toMatch(/\/api\/workspace|\/api\/portfolios|localStorage|sessionStorage|toFixed|parseFloat|cumprod|cummax/);
});
