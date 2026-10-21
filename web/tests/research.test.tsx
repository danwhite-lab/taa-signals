import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { readFileSync } from "node:fs";
import text from "../content/research.json";

const mock = vi.hoisted(() => ({request: vi.fn(), download: vi.fn()}));
vi.mock("../lib/researchApi", () => ({researchRequest: mock.request, researchDownload: mock.download}));
vi.mock("next/navigation", () => ({usePathname: () => "/research/"}));
vi.mock("../lib/supabaseBrowser", () => ({supabaseBrowser: () => ({auth:{getSession:async()=>({data:{session:null},error:null}),onAuthStateChange:()=>({data:{subscription:{unsubscribe(){}}}})}})}));
import Page from "../app/research/page";
import AuthGate from "../components/AuthGate";

const table = {columns:["Mock column"],rows:[{"Mock column":"Mock evidence"}],total_rows:1,shown_rows:1};
const options = {models:[{label:"HAA-Simple",strategy:"HAA",variant:"Simple",implementation:"Original",gate:"available",reason:null},
  {label:"Fake unavailable",strategy:"Unavailable model",variant:null,implementation:"Original",gate:"no_profile",reason:"Mock original unavailability reason"}],
  gate:"available",reason:null,currency:"USD",profile:{caption:"Mock profile · Data confidence: Moderate",parameters:table,notes:"Mock notes"},
  history:{caption:"Mock full history caption"},data_validation:table,warnings:[]};
const report = {gate:"available",initial:10000,currency:"USD",profile:options.profile,history:options.history,
  cards:[{label:text.confidence,value:"Reasonably robust"},{label:text.cagr,value:"8.00%"},{label:text.drawdown,value:"-20.00%"}],
  grade:"B",verdict:"Reasonably robust",meaning:text.meanings["Reasonably robust"],checks:table,
  tables:Object.fromEntries(["scenarios","rolling","subperiods","data_quality","scorecard","monte_carlo","execution","proxies"].map(key=>[key,table])),
  charts:{scenarios:null,rolling:null,monte_carlo:null},has_bootstrap:true,warnings:[],cache:{key:"fake-key",hit:null},timing:{},calculation_timing:{},
  downloads:Object.entries(text.downloads).map(([kind,label])=>({kind,label,filename:`fake_${kind}.csv`}))};
afterEach(()=>{cleanup();mock.request.mockReset();mock.download.mockReset();});
async function ready() {
  mock.request.mockImplementation(async(path:string)=>path.startsWith("/api/research/options")?options:report);
  mock.download.mockResolvedValue(undefined);
  render(<Page/>); return screen.findByRole("button",{name:text.run});
}

it("is withheld by the existing login gate", async()=>{
  render(<AuthGate><Page/></AuthGate>); await screen.findByText("Sign in with Google"); expect(mock.request).not.toHaveBeenCalled();
});

it("does not auto-run, renders initial capital only and keeps explainers collapsed", async()=>{
  await ready();
  expect(mock.request.mock.calls.every(([path])=>path.startsWith("/api/research/options"))).toBe(true);
  expect(screen.getByLabelText(text.initial)).toHaveProperty("value","100000");
  expect(screen.getByText(text.readTitle).closest("details")).toHaveProperty("open",false);
  expect(screen.getByText(text.scope).closest("details")).toHaveProperty("open",false);
  expect(screen.queryByLabelText(/fee|tax|start|end/i)).toBeNull();
  expect(screen.getByText(text.before)).toBeTruthy();
});

it("renders only the gate reason instead of research controls/results", async()=>{
  mock.request.mockResolvedValue({...options,gate:"no_profile",reason:"Mock original unavailability reason",profile:null});
  render(<Page/>); await screen.findByText("Mock original unavailability reason");
  expect(screen.queryByText(text.caption)).toBeNull(); expect(screen.queryByText(text.scope)).toBeNull();
  expect(screen.queryByRole("button",{name:text.run})).toBeNull(); expect(screen.queryByLabelText(text.initial)).toBeNull();
});

it("renders Python verdict, evidence and six collapsed sections, and downloads Python CSVs", async()=>{
  fireEvent.click(await ready()); await screen.findByText(text.completed);
  expect(screen.getByText("Reasonably robust")).toBeTruthy(); expect(screen.getByText("8.00%")).toBeTruthy();
  expect(screen.getByText(text.checksTitle)).toBeTruthy();
  for(const section of text.sections) expect(screen.getByText(section,{selector:"summary"}).closest("details")).toHaveProperty("open",false);
  expect(screen.getByText(text.scoreTitle).closest("details")).toHaveProperty("open",false);
  fireEvent.click(screen.getByRole("button",{name:text.downloads.scenarios}));
  expect(mock.download).toHaveBeenCalledWith("fake-key","scenarios","fake_scenarios.csv");
  fireEvent.change(screen.getByLabelText(text.initial),{target:{value:"20000"}});
  expect(screen.queryByText(text.completed)).toBeNull(); expect(screen.getByText(text.changed)).toBeTruthy();
});

it("guards duplicate clicks and shows progress", async()=>{
  let resolve!: (value:unknown)=>void;
  mock.request.mockImplementation((path:string)=>path.startsWith("/api/research/options")?Promise.resolve(options):new Promise(done=>{resolve=done;}));
  render(<Page/>); const run=await screen.findByRole("button",{name:text.run});
  fireEvent.click(run); fireEvent.click(run);
  expect(mock.request.mock.calls.filter(([path])=>path==="/api/research")).toHaveLength(1);
  expect(run).toHaveProperty("disabled",true); expect(screen.getByText(text.longRun,{exact:false})).toBeTruthy();
  resolve(report); await screen.findByText(text.completed);
});

it("shows timeout without a partial result", async()=>{
  const run=await ready(); mock.request.mockRejectedValue(new Error(text.timeout)); fireEvent.click(run);
  await screen.findByText(text.timeout); expect(screen.queryByText(text.completed)).toBeNull();
});

it("clears results on model change and preserves declared gated models in selectors", async()=>{
  fireEvent.click(await ready()); await screen.findByText(text.completed);
  mock.request.mockResolvedValue({...options,gate:"no_profile",reason:"Mock original unavailability reason",profile:null});
  fireEvent.change(screen.getByLabelText(text.strategy),{target:{value:"Unavailable model"}});
  await screen.findByText("Mock original unavailability reason"); expect(screen.queryByText(text.completed)).toBeNull();
});

it("renders the no-bootstrap information and keeps all wording in data files", async()=>{
  const run=await ready(); mock.request.mockResolvedValue({...report,has_bootstrap:false}); fireEvent.click(run);
  await screen.findByText(text.noBootstrap);
  const source=readFileSync("./app/research/page.tsx","utf8");
  expect(source).toContain('content/research.json'); expect(source).not.toMatch(/>[A-Za-z][A-Za-z ]{4,}</);
  expect(source).not.toMatch(/\/api\/workspace|localStorage|sessionStorage|toFixed|parseFloat/);
  expect(source).not.toContain("Reasonably robust"); // Verdicts come from Python.
});
