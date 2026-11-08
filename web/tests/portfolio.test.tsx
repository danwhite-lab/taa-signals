import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { readFileSync } from "node:fs";
import words from "../content/portfolio.json";

const calls = vi.hoisted(() => ({ api: vi.fn(), signOut: vi.fn() }));
vi.mock("../lib/api", () => ({ api: calls.api }));
vi.mock("../lib/supabaseBrowser", () => ({ supabaseBrowser: () => ({ auth: { signOut: calls.signOut } }) }));
import Portfolio from "../app/portfolio/page";

const payload = { version: 1, name: "Fake portfolio", sleeves: [{ model: "Buy and Hold SPY", weight: 100 }], total_ils: 100, ils_per_usd: 4 };
const saved = { id: "fake-id", name: "Fake portfolio", payload, updated_at: "mock-timestamp", is_default: true };
afterEach(() => { cleanup(); calls.api.mockReset(); vi.restoreAllMocks(); });
it("keeps one transfer button, hides helper lines, and opens invalid JSON rules without changing the draft",async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  const settings=screen.getByRole("group",{name:"Portfolio settings"});
  const table=screen.getByRole("table",{name:"Portfolio sleeves"});
  expect(settings.compareDocumentPosition(table)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  for(const label of ["Model to add","Total capital (ILS)","ILS per USD rate"]) expect(within(settings).getByLabelText(label)).toBeTruthy();
  const button=screen.getByRole("button",{name:"Transfer rule: None"});
  expect(button.getAttribute("aria-expanded")).toBe("false");
  expect(screen.queryByLabelText("Sleeve transfer rule")).toBeNull();
  const json=screen.getByLabelText("Portfolio JSON") as HTMLTextAreaElement;
  expect(JSON.parse(json.value)).toEqual(payload);
  fireEvent.click(button);expect(screen.getByLabelText("Sleeve transfer rule")).toHaveProperty("value","none");
  fireEvent.click(button);expect(screen.queryByLabelText("Sleeve transfer rule")).toBeNull();
  fireEvent.click(screen.getByText("Add a sleeve",{selector:"summary"}));
  fireEvent.change(screen.getByLabelText("Model to add"),{target:{value:"Buy and Hold IEF"}});
  expect(JSON.parse(json.value)).toEqual(payload);
  expect(within(settings).queryByText("Buy and Hold IEF",{selector:"p"})).toBeNull();
  expect(screen.queryByText(/New sleeves start at/)).toBeNull();
  for(const rule of [{mode:"unknown"},{mode:"rvol_cap",sleeve_model:"A-RVol missing",cap_percent:20,target_percent:10},null]){
    fireEvent.change(json,{target:{value:JSON.stringify({...payload,transfer_rule:rule})}});
    const invalid=screen.getByRole("button",{name:"Transfer rule: invalid"});
    expect(invalid.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByLabelText("Sleeve transfer rule")).toHaveProperty("value",rule?.mode??"");
    const alerts=screen.getAllByRole("alert").map(n=>n.textContent);
    fireEvent.click(invalid);
    expect(screen.getAllByRole("alert").map(n=>n.textContent)).toEqual(alerts);
    expect(JSON.parse(json.value).transfer_rule).toEqual(rule);
  }
  expect(calls.api.mock.calls.some(([,init])=>init?.method==="POST")).toBe(false);
});

it.each(["rvol_cap","annual_target"])("loads a valid active %s rule closed without rewriting it",async mode=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  const model="A-RVol Shifter V3 Cash-Only Israel";
  const rule={mode,sleeve_model:model,cap_percent:20.12345678,target_percent:10.12345678,extra:"kept"};
  const next={...payload,sleeves:[{model,weight:100}],transfer_rule:rule};
  calls.api.mockImplementation(async(path,init)=>path==="/api/portfolios"?[{...saved,payload:next}]:original(path,init));
  render(<Portfolio/>);await chooseSaved();
  const button=screen.getByRole("button",{name:mode==="rvol_cap"?"Transfer rule: Quarterly RVol cap":"Transfer rule: Annual reset"});
  expect(button.getAttribute("aria-expanded")).toBe("false");expect(screen.queryByLabelText("Sleeve transfer rule")).toBeNull();
  expect(JSON.parse((screen.getByLabelText("Portfolio JSON") as HTMLTextAreaElement).value)).toEqual(next);
  fireEvent.click(button);expect(screen.getByLabelText("Sleeve transfer rule")).toHaveProperty("value",mode);
  fireEvent.click(button);expect(screen.queryByLabelText("Sleeve transfer rule")).toBeNull();
});

it("pins an invalid stored rule open from initial load until explicitly repaired",async()=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  const rule={mode:"rvol_cap",sleeve_model:"A-RVol missing",cap_percent:20,target_percent:10};
  calls.api.mockImplementation(async(path,init)=>path==="/api/portfolios"?[{...saved,payload:{...payload,transfer_rule:rule}}]:original(path,init));
  render(<Portfolio/>);await chooseSaved();
  const button=screen.getByRole("button",{name:"Transfer rule: invalid"});
  expect(button.getAttribute("aria-expanded")).toBe("true");
  const warning=screen.getByText("Select an existing RVol sleeve to cap. The stored selection is not changed automatically.");
  fireEvent.click(button);expect(warning.isConnected).toBe(true);
  fireEvent.click(saveButton());
  expect(calls.api.mock.calls.some(([,init])=>init?.method==="POST")).toBe(false);
  fireEvent.change(screen.getByLabelText("Sleeve transfer rule"),{target:{value:"none"}});
  expect(JSON.parse((screen.getByLabelText("Portfolio JSON") as HTMLTextAreaElement).value).transfer_rule).toEqual({...rule,mode:"none"});
});

function mockLoad() {
  calls.api.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") return { ...saved, updated_at: "new-mock-timestamp" };
    if (path === "/api/workspace") return { revision: 7, payload: { portfolio_name: "Fake preference" } };
    if (path === "/api/portfolios") return [saved];
    if (path === "/api/me") return { email: "test@example.invalid" };
    if (path === "/api/backtest/config?mode=portfolio") return { models: [{label:'Buy and Hold SPY'},{label:'Buy and Hold IEF'},{label:'Century Momentum'},{label:'Buy and Hold IEF'}] };
    throw new Error("Unexpected mock request");
  });
}

async function chooseSaved(id = saved.id) {
  const picker = screen.getByRole("combobox", { name: words.savedPortfolios });
  await waitFor(() => {
    expect(picker).toHaveProperty("disabled", false);
    expect(Array.from((picker as HTMLSelectElement).options).some(option => option.value === id)).toBe(true);
  });
  fireEvent.change(picker, { target: { value: id } });
  return picker;
}

function openRename() {
  fireEvent.click(screen.getByRole("button", { name: words.renamePortfolio }));
}

function saveButton() {
  return screen.getByRole("button", { name: /^(Save changes|Save portfolio)$/ });
}

it("keeps saved portfolio choices ordered default first and then A–Z", async () => {
  mockLoad();
  const original = calls.api.getMockImplementation()!;
  const rows = [
    { ...saved, id: "b", name: "beta", is_default: false },
    { ...saved, id: "z", name: "Zulu", is_default: true },
    { ...saved, id: "a", name: "Alpha", is_default: false },
  ];
  calls.api.mockImplementation(async (path, init) => path === "/api/portfolios" ? rows : original(path, init));
  render(<Portfolio />);
  const picker = await chooseSaved("z");
  expect(within(picker).getAllByRole("option").map(option => option.textContent))
    .toEqual([words.choosePortfolio, "Zulu", "Alpha", "beta"]);
  expect(screen.getByText(words.defaultLabel, { selector: ".list-tag" })).toBeTruthy();
  expect(screen.getByRole("button", { name: words.newPortfolio }).classList.contains("btn-primary")).toBe(true);
});

it('sorts Model to add A-Z without choosing a model automatically',async()=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async(path,init)=>path==='/api/backtest/config?mode=portfolio'?{models:[{label:'Zulu'},{label:'beta'},{label:'Alpha'}]}:original(path,init));
  render(<Portfolio/>);await chooseSaved();
  fireEvent.click(screen.getByText('Add a sleeve',{selector:'summary'}));
  const select=screen.getByLabelText('Model to add');
  await waitFor(()=>expect(within(select).getAllByRole('option')).toHaveLength(4));
  expect(within(select).getAllByRole('option').map(o=>o.textContent)).toEqual(['Choose a model','Alpha','beta','Zulu']);
  expect(select).toHaveProperty('value','');
});

it("renames a saved portfolio in place only when Save changes is pressed", async () => {
  mockLoad();
  render(<Portfolio />);
  const picker = await chooseSaved();
  expect(picker).toHaveProperty("value", saved.id);
  expect(screen.queryByLabelText(words.portfolioName)).toBeNull();
  openRename();
  const name = screen.getByLabelText(words.portfolioName);
  expect(name).toHaveProperty("value", saved.name);
  fireEvent.change(name, { target: { value: "Renamed portfolio" } });
  expect(JSON.parse((screen.getByLabelText(words.portfolioJson) as HTMLTextAreaElement).value).name).toBe("Renamed portfolio");
  expect(calls.api.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  fireEvent.click(screen.getByRole("button", { name: words.saveChanges }));
  await screen.findByText("Portfolio saved.");
  const [, init] = calls.api.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(JSON.parse(init.body)).toEqual({
    id: saved.id, expected_updated_at: saved.updated_at, is_default: true,
    payload: { ...payload, name: "Renamed portfolio" },
  });
});

it("conflict preserves draft, blocks repeat mutations, and reload recovers", async () => {
  vi.spyOn(window,"confirm").mockReturnValue(true);
  mockLoad(); render(<Portfolio />);
  await chooseSaved();
  const before = calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async (path, init) => {
    if (init?.method === "POST") throw new Error("Mock conflict");
    return before(path, init);
  });
  openRename();
  fireEvent.change(screen.getByLabelText(words.portfolioName), { target: { value: "Unsaved fake draft" } });
  fireEvent.click(saveButton());
  await screen.findByRole("alert");
  expect(screen.getByLabelText("Portfolio name")).toHaveProperty("value", "Unsaved fake draft");
  expect(saveButton()).toHaveProperty("disabled", true);
  fireEvent.click(screen.getByText("Reload saved data"));
  await waitFor(() => expect(saveButton()).toHaveProperty("disabled", false));
});

it("loads saved choices automatically and selects by ID", async () => {
  mockLoad();
  render(<Portfolio />);
  const picker = screen.getByRole("combobox", { name: words.savedPortfolios });
  expect(picker).toHaveProperty("value", "");
  await chooseSaved();
  expect(calls.api.mock.calls.filter(([path]) => path === "/api/portfolios")).toHaveLength(1);
  expect(picker).toHaveProperty("value", saved.id);
  expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
});

it.each(["Portfolio name","Portfolio JSON",words.defaultLabel])("guards unsaved %s against replacing the form",async field=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  const second={...saved,id:"fake-second",name:"Fake second",payload:{...payload,name:"Fake second"}};
  calls.api.mockImplementation(async(path,init)=>path==="/api/portfolios"?[saved,second]:original(path,init));
  const confirm=vi.spyOn(window,"confirm").mockReturnValue(false);
  render(<Portfolio/>);await chooseSaved();
  if (field === words.portfolioName) openRename();
  const input=screen.getByLabelText(field);
  if(field===words.defaultLabel)fireEvent.click(input);
  else fireEvent.change(input,{target:{value:"Unsaved fake draft"}});
  await chooseSaved("fake-second");
  expect(confirm).toHaveBeenCalledOnce();expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
  expect(input).toHaveProperty(field===words.defaultLabel?"checked":"value",field===words.defaultLabel?false:"Unsaved fake draft");
  confirm.mockReturnValue(true);await chooseSaved("fake-second");
  expect(screen.getByText("Loaded: Fake second")).toBeTruthy();
  expect(screen.queryByLabelText(words.portfolioName)).toBeNull();
  openRename();
  expect(screen.getByLabelText(words.portfolioName)).toHaveProperty("value","Fake second");
});

it("guards New portfolio and manual refresh with an unsaved draft",async()=>{
  mockLoad();const confirm=vi.spyOn(window,"confirm").mockReturnValue(false);
  render(<Portfolio/>);await chooseSaved();
  openRename();
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:"Unsaved fake draft"}});
  fireEvent.click(screen.getByText("New portfolio"));expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
  fireEvent.click(screen.getByText("Reload saved data"));expect(calls.api.mock.calls.filter(([path])=>path==="/api/portfolios")).toHaveLength(1);
  confirm.mockReturnValue(true);fireEvent.click(screen.getByText("New portfolio"));
  expect(screen.queryByText("Loaded: Fake portfolio")).toBeNull();
  expect(screen.getByLabelText(words.portfolioName)).toHaveProperty("value", "");
  expect(screen.getByRole("button", { name: words.savePortfolio })).toBeTruthy();
  expect(screen.queryByRole("button", { name: words.deletePortfolio })).toBeNull();
});

it("still lists saved portfolios if another initial read fails",async()=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async(path,init)=>{if(path==="/api/workspace")throw new Error("Mock read failed");return original(path,init);});
  render(<Portfolio/>);await screen.findByRole("alert");expect(await screen.findByText("Fake portfolio")).toBeTruthy();
});

it("loads the workspace guard without showing the workspace editor", async () => {
  mockLoad();
  render(<Portfolio />);
  await screen.findByRole("option", { name: saved.name });
  expect(calls.api).toHaveBeenCalledWith("/api/workspace");
  expect(screen.queryByText("Synced workspace")).toBeNull();
  expect(screen.queryByLabelText("Workspace portfolio name")).toBeNull();
  expect(screen.queryByRole("button", { name: "Save workspace preference" })).toBeNull();
});

it("confirms that deleting a portfolio leaves shared holdings intact", async () => {
  mockLoad();
  const original = calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async (path, init) => init?.method === "DELETE" ? undefined : original(path, init));
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<Portfolio />);
  await chooseSaved();
  const remove = screen.getByRole("button", { name: words.deletePortfolio });
  fireEvent.click(remove);
  expect(confirm).toHaveBeenCalledWith("Delete this saved portfolio? This does not delete your shared holdings.");
  expect(calls.api.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
  confirm.mockReturnValue(true);
  fireEvent.click(remove);
  await screen.findByText("Portfolio deleted.");
  expect(calls.api).toHaveBeenCalledWith(`/api/portfolios/${saved.id}?expected_updated_at=${saved.updated_at}`, { method: "DELETE" });
  expect(screen.queryByRole("button", { name: words.deletePortfolio })).toBeNull();
});

it("shows a readable loaded summary below the controls and keeps JSON collapsed",async()=>{
  mockLoad();render(<Portfolio/>);
  expect(screen.queryByRole("region",{name:"Portfolio summary"})).toBeNull();await chooseSaved();
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).getByRole("heading",{name:"Fake portfolio"})).toBeTruthy();
  expect(screen.getByText(words.defaultLabel, { selector: ".list-tag" })).toBeTruthy();
  expect(within(summary).getByLabelText("Total capital (ILS)")).toHaveProperty('value','100');
  expect(within(summary).getByLabelText("ILS per USD rate")).toHaveProperty('value','4');
  const table=within(summary).getByRole("table",{name:"Portfolio sleeves"});
  expect(within(table).getByRole("columnheader",{name:"Sleeve name"})).toBeTruthy();
  expect(within(table).getByRole("columnheader",{name:"Weight"})).toBeTruthy();
  expect(within(table).getByText("Buy and Hold SPY")).toBeTruthy();
  expect(within(table).getByLabelText('Weight for Buy and Hold SPY (row 1)')).toHaveProperty('value','100.00');
  expect(within(table).getByText("100.00%")).toBeTruthy();
  expect(saveButton().compareDocumentPosition(table) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  const advanced=screen.getByText("Advanced: edit JSON").closest("details")!;
  expect(advanced).toHaveProperty("open",false);expect(advanced.contains(screen.getByLabelText("Portfolio JSON"))).toBe(true);
  expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
});

it("updates the summary from edits and saves full precision without changing the request contract",async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  openRename();
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:"Fake edited name"}});
  screen.getByText("Advanced: edit JSON").closest("details")!.open=true;
  const edited={...payload,name:'Fake edited name',total_ils:12345.6789,ils_per_usd:3.14159,sleeves:[
    {model:"Fake long sleeve name with multiple whole words",weight:33.333333},
    {model:"Fake second sleeve",weight:66.666667}]};
  fireEvent.change(screen.getByLabelText("Portfolio JSON"),{target:{value:JSON.stringify(edited)}});
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).getByRole("heading",{name:"Fake edited name"})).toBeTruthy();
  for(const value of ["100.00%","Fake second sleeve"])
    expect(within(summary).getByText(value)).toBeTruthy();
  expect(within(summary).getByLabelText('Total capital (ILS)')).toHaveProperty('value','12345.6789');
  expect(within(summary).getByLabelText('ILS per USD rate')).toHaveProperty('value','3.14159');
  expect(within(summary).getByLabelText('Weight for Fake long sleeve name with multiple whole words (row 1)')).toHaveProperty('value','33.33');
  expect(within(summary).getByLabelText('Weight for Fake second sleeve (row 2)')).toHaveProperty('value','66.67');
  expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
  fireEvent.click(saveButton());await screen.findByText("Portfolio saved.");
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==="POST")!;
  expect(JSON.parse(init.body)).toEqual({id:saved.id,expected_updated_at:saved.updated_at,is_default:true,payload:{...edited,name:"Fake edited name",transfer_rule:{mode:'none'}}});
});

it("shows the draft Default choice and preserves the current default when unchecked", async () => {
  mockLoad();
  const original = calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async (path, init) => path === "/api/portfolios" && !init?.method
    ? [{ ...saved, is_default: false }] : original(path, init));
  render(<Portfolio />);
  await chooseSaved();
  const draftDefault = screen.getByRole("checkbox", { name: words.defaultLabel });
  expect(draftDefault).toHaveProperty("checked", false);
  fireEvent.click(draftDefault);
  expect(screen.getByText(words.defaultOnSave)).toBeTruthy();
  expect(calls.api.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  fireEvent.click(draftDefault);
  expect(screen.queryByText(words.defaultOnSave)).toBeNull();

  cleanup();
  mockLoad();
  render(<Portfolio />);
  await chooseSaved();
  const currentDefault = screen.getByRole("checkbox", { name: words.defaultLabel });
  expect(currentDefault).toHaveProperty("checked", true);
  fireEvent.click(currentDefault);
  expect(screen.getByText(words.defaultLabel, { selector: ".list-tag" })).toBeTruthy();
  fireEvent.click(saveButton());
  await screen.findByText("Portfolio saved.");
  const [, init] = calls.api.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(JSON.parse(init.body)).toMatchObject({ id: saved.id, is_default: false });
  expect(screen.getByText(words.defaultLabel, { selector: ".list-tag" })).toBeTruthy();
});

it("does not show stale saved numbers or invented totals for invalid or incomplete draft JSON",async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  fireEvent.change(screen.getByLabelText("Portfolio JSON"),{target:{value:"{"}});
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).getByRole("alert").textContent).toContain("Summary unavailable");
  expect(within(summary).queryByText("₪100.00")).toBeNull();expect(within(summary).queryByRole("table")).toBeNull();
  fireEvent.change(screen.getByLabelText("Portfolio JSON"),{target:{value:JSON.stringify({sleeves:[{model:"Fake missing weight"}]})}});
  const table=within(summary).getByRole("table");
  expect(within(table).getByText("Unavailable")).toBeTruthy();
  expect(within(table).getByLabelText('Weight for Fake missing weight (row 1)')).toHaveProperty('value','');
  expect(within(table).queryByText("100.00%")).toBeNull();
  expect(calls.api.mock.calls.some(([,init])=>init?.method==="POST")).toBe(false);
});

it("shows the actual draft total rather than normalizing weights to 100",async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
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

it('edits name, capital, FX and weights into JSON without losing unrelated fields or changing untouched precision',async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  fireEvent.change(screen.getByLabelText('Portfolio JSON'),{target:{value:JSON.stringify({...payload,custom_note:'Fake retained field',sleeves:[{id:17,model:'Buy and Hold SPY',weight:100}]})}});
  openRename();
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:'Fake builder name'}});
  fireEvent.change(screen.getByLabelText('Total capital (ILS)'),{target:{value:'5432.1234'}});
  fireEvent.change(screen.getByLabelText('ILS per USD rate'),{target:{value:'3.612345'}});
  const input=screen.getByLabelText('Weight for Buy and Hold SPY (row 1)');
  fireEvent.focus(input);fireEvent.change(input,{target:{value:'95.126'}});fireEvent.blur(input);
  expect(input).toHaveProperty('value','95.13');
  const draft=JSON.parse((screen.getByLabelText('Portfolio JSON') as HTMLTextAreaElement).value);
  expect(draft).toEqual({...payload,name:'Fake builder name',total_ils:5432.1234,ils_per_usd:3.612345,custom_note:'Fake retained field',sleeves:[{id:17,model:'Buy and Hold SPY',weight:95.13}]});
  expect(screen.getByRole('row',{name:/Total/}).textContent).toBe('Total95.13%');
  expect(screen.getByRole('alert').textContent).toContain('not 100%');
  expect(screen.getByText('Loaded: Fake portfolio')).toBeTruthy();
});

it('uses the Backtest model list without duplicates and removes the requested row, not the last',async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  fireEvent.click(screen.getByText('Add a sleeve',{selector:'summary'}));
  const dropdown=screen.getByLabelText('Model to add');
  await waitFor(()=>expect(dropdown).toHaveProperty('disabled',false));
  expect(calls.api).toHaveBeenCalledWith('/api/backtest/config?mode=portfolio');
  expect(within(dropdown).queryByRole('option',{name:'Buy and Hold SPY'})).toBeNull();
  expect(within(dropdown).getAllByRole('option',{name:'Buy and Hold IEF'})).toHaveLength(1);
  fireEvent.change(dropdown,{target:{value:'Buy and Hold IEF'}});fireEvent.click(screen.getByRole('button',{name:'Add sleeve'}));
  let draft=JSON.parse((screen.getByLabelText('Portfolio JSON') as HTMLTextAreaElement).value);
  expect(draft.sleeves).toEqual([{model:'Buy and Hold SPY',weight:100},{model:'Buy and Hold IEF',weight:0}]);
  expect(within(dropdown).queryByRole('option',{name:'Buy and Hold IEF'})).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:'Remove Buy and Hold SPY (row 1)'}));
  draft=JSON.parse((screen.getByLabelText('Portfolio JSON') as HTMLTextAreaElement).value);
  expect(draft.sleeves).toEqual([{model:'Buy and Hold IEF',weight:0}]);
  expect(within(dropdown).getByRole('option',{name:'Buy and Hold SPY'})).toBeTruthy();
});

it('warns live and requires confirmation to save a non-100 draft without normalization',async()=>{
  mockLoad();const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  render(<Portfolio/>);await chooseSaved();
  fireEvent.change(screen.getByLabelText('Weight for Buy and Hold SPY (row 1)'),{target:{value:'90'}});
  expect(screen.getByRole('row',{name:/Total/}).textContent).toBe('Total90.00%');
  fireEvent.click(saveButton());
  expect(confirm).toHaveBeenCalledWith(expect.stringContaining('do not total 100%'));
  expect(calls.api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
  expect(screen.getByLabelText('Weight for Buy and Hold SPY (row 1)')).toHaveProperty('value','90.00');
  confirm.mockReturnValue(true);fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body)).toMatchObject({allow_non_100_weights:true,id:saved.id,expected_updated_at:saved.updated_at,is_default:true,payload:{sleeves:[{model:'Buy and Hold SPY',weight:90}]}});
});

it('updates every editable field and available models from Advanced JSON',async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  screen.getByText('Advanced: edit JSON').closest('details')!.open=true;
  const next={...payload,name:'Fake from JSON',total_ils:500,ils_per_usd:3.5,sleeves:[{model:'Buy and Hold IEF',weight:100}]};
  fireEvent.change(screen.getByLabelText('Portfolio JSON'),{target:{value:JSON.stringify(next)}});
  openRename();
  expect(screen.getByLabelText(words.portfolioName)).toHaveProperty('value','Fake from JSON');
  expect(screen.getByLabelText('Total capital (ILS)')).toHaveProperty('value','500');
  expect(screen.getByLabelText('ILS per USD rate')).toHaveProperty('value','3.5');
  expect(screen.getByLabelText('Weight for Buy and Hold IEF (row 1)')).toHaveProperty('value','100.00');
  expect(screen.queryByLabelText('Weight for Buy and Hold SPY (row 1)')).toBeNull();
  fireEvent.click(screen.getByText('Add a sleeve',{selector:'summary'}));
  const dropdown=screen.getByLabelText('Model to add');
  await waitFor(()=>expect(within(dropdown).getByRole('option',{name:'Buy and Hold SPY'})).toBeTruthy());
  expect(within(dropdown).queryByRole('option',{name:'Buy and Hold IEF'})).toBeNull();
});

it.each(['Total capital (ILS)','ILS per USD rate','Weight for Buy and Hold SPY (row 1)'])('guards unsaved table edit %s before another portfolio is loaded',async label=>{
  mockLoad();const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  render(<Portfolio/>);await chooseSaved();
  fireEvent.change(screen.getByLabelText(label),{target:{value:'50'}});
  fireEvent.click(screen.getByText('New portfolio'));
  expect(confirm).toHaveBeenCalledWith('Discard unsaved portfolio edits?');
  expect(screen.getByText('Loaded: Fake portfolio')).toBeTruthy();
});

it('can build a new portfolio without inventing capital or FX',async()=>{
  mockLoad();render(<Portfolio/>);await screen.findByText('Fake portfolio');
  fireEvent.click(screen.getByText('New portfolio'));
  expect(screen.getByLabelText('Total capital (ILS)')).toHaveProperty('value','');
  expect(screen.getByLabelText('ILS per USD rate')).toHaveProperty('value','');
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:'Fake new'}});
  fireEvent.change(screen.getByLabelText('Total capital (ILS)'),{target:{value:'200'}});
  fireEvent.change(screen.getByLabelText('ILS per USD rate'),{target:{value:'4'}});
  fireEvent.click(screen.getByText('Add a sleeve',{selector:'summary'}));
  const dropdown=screen.getByLabelText('Model to add');await waitFor(()=>expect(dropdown).toHaveProperty('disabled',false));
  fireEvent.change(dropdown,{target:{value:'Buy and Hold SPY'}});fireEvent.click(screen.getByRole('button',{name:'Add sleeve'}));
  fireEvent.change(screen.getByLabelText('Weight for Buy and Hold SPY (row 1)'),{target:{value:'100'}});
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body)).toMatchObject({id:null,expected_updated_at:null,is_default:false,payload:{version:1,name:'Fake new',total_ils:200,ils_per_usd:4,sleeves:[{model:'Buy and Hold SPY',weight:100}]}});
});

it('does not overwrite malformed JSON through the builder or save empty/invalid fields',async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  fireEvent.change(screen.getByLabelText('Portfolio JSON'),{target:{value:'{'}});
  expect(screen.getByLabelText('Total capital (ILS)')).toHaveProperty('disabled',true);
  expect(screen.getByLabelText('Model to add')).toHaveProperty('disabled',true);
  expect(screen.getByLabelText('Portfolio JSON')).toHaveProperty('value','{');
  fireEvent.change(screen.getByLabelText('Portfolio JSON'),{target:{value:JSON.stringify({...payload,sleeves:[{model:'Buy and Hold SPY',weight:0}]})}});
  fireEvent.click(saveButton());
  expect(screen.getByText(words.invalidWeights)).toBeTruthy();
  expect(calls.api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
});

it('retries a failed model list without losing the editable draft',async()=>{
  mockLoad();const original=calls.api.getMockImplementation()!;let fail=true;
  calls.api.mockImplementation(async(path,init)=>{if(path==='/api/backtest/config?mode=portfolio'&&fail)throw Error('Mock failure');return original(path,init);});
  render(<Portfolio/>);await chooseSaved();fireEvent.click(screen.getByText('Add a sleeve',{selector:'summary'}));
  await screen.findByText('Available models could not be loaded. Existing drafts are unchanged.');
  openRename();
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:'Fake draft preserved'}});
  fail=false;fireEvent.click(screen.getByText('Retry model list'));
  await waitFor(()=>expect(screen.getByLabelText('Model to add')).toHaveProperty('disabled',false));
  expect(screen.getByLabelText('Portfolio name')).toHaveProperty('value','Fake draft preserved');
});

it('defaults legacy portfolios to no transfers and stores that rule on save',async()=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async(path,init)=>path==="/api/backtest/config?mode=portfolio"
    ?{models:[{label:"Buy and Hold SPY",signal_mode:"internal"}]}:original(path,init));
  render(<Portfolio/>);await chooseSaved();
  expect(screen.queryByLabelText('Sleeve transfer rule')).toBeNull();
  expect(JSON.parse((screen.getByLabelText('Portfolio JSON') as HTMLTextAreaElement).value).transfer_rule).toBeUndefined();
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body).payload).toEqual({...payload,transfer_rule:{mode:'none'}});
});

it('edits and saves the quarterly cap with its model identity and precise parameters',async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  const base={...payload,sleeves:[{id:991,model:'A-RVol Shifter V3 Cash-Only',weight:20},{model:'Buy and Hold SPY',weight:80}]};
  fireEvent.change(screen.getByLabelText('Portfolio JSON'),{target:{value:JSON.stringify(base)}});
  fireEvent.click(screen.getByRole('button',{name:'Transfer rule: None'}));
  fireEvent.change(screen.getByLabelText('Sleeve transfer rule'),{target:{value:'rvol_cap'}});
  fireEvent.change(screen.getByLabelText('RVol sleeve to cap'),{target:{value:'A-RVol Shifter V3 Cash-Only'}});
  fireEvent.change(screen.getByLabelText('RVol cap (%)'),{target:{value:'17.5'}});
  fireEvent.change(screen.getByLabelText('RVol reset target (%)'),{target:{value:'9.25'}});
  const rule={mode:'rvol_cap',sleeve_model:'A-RVol Shifter V3 Cash-Only',cap_percent:17.5,target_percent:9.25};
  expect(JSON.parse((screen.getByLabelText('Portfolio JSON') as HTMLTextAreaElement).value)).toEqual({...base,transfer_rule:rule});
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body)).toMatchObject({expected_updated_at:saved.updated_at,is_default:true,payload:{...base,transfer_rule:rule}});
});

it('keeps transfer controls in sync with JSON and warns instead of retargeting a removed cap sleeve',async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  const rule={mode:'rvol_cap',sleeve_model:'A-RVol Shifter V3 Cash-Only',cap_percent:22,target_percent:11};
  const next={...payload,sleeves:[{model:rule.sleeve_model,weight:10},{model:'Buy and Hold SPY',weight:90}],transfer_rule:rule};
  fireEvent.change(screen.getByLabelText('Portfolio JSON'),{target:{value:JSON.stringify(next)}});
  fireEvent.click(screen.getByRole('button',{name:'Transfer rule: Quarterly RVol cap'}));
  expect(screen.getByLabelText('Sleeve transfer rule')).toHaveProperty('value','rvol_cap');
  expect(screen.getByLabelText('RVol cap (%)')).toHaveProperty('value','22');
  expect(screen.getByLabelText('RVol reset target (%)')).toHaveProperty('value','11');
  fireEvent.click(screen.getByRole('button',{name:`Remove ${rule.sleeve_model} (row 1)`}));
  expect(screen.getByText('Select an existing RVol sleeve to cap. The stored selection is not changed automatically.')).toBeTruthy();
  expect(JSON.parse((screen.getByLabelText('Portfolio JSON') as HTMLTextAreaElement).value).transfer_rule).toEqual(rule);
  fireEvent.click(saveButton());
  expect(calls.api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
  fireEvent.change(screen.getByLabelText('Sleeve transfer rule'),{target:{value:'annual_target'}});
  expect(JSON.parse((screen.getByLabelText('Portfolio JSON') as HTMLTextAreaElement).value).transfer_rule.mode).toBe('annual_target');
  expect(screen.queryByLabelText('RVol cap (%)')).toBeNull();
});

it('treats transfer edits as unsaved and refuses invalid cap parameters',async()=>{
  mockLoad();const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  render(<Portfolio/>);await chooseSaved();
  fireEvent.click(screen.getByRole('button',{name:'Transfer rule: None'}));
  fireEvent.change(screen.getByLabelText('Sleeve transfer rule'),{target:{value:'annual_target'}});
  fireEvent.click(screen.getByText('New portfolio'));expect(confirm).toHaveBeenCalledWith('Discard unsaved portfolio edits?');
  const next={...payload,sleeves:[{model:'A-RVol Shifter V3 Cash-Only',weight:100}],transfer_rule:{mode:'rvol_cap',sleeve_model:'A-RVol Shifter V3 Cash-Only',cap_percent:10,target_percent:20}};
  fireEvent.change(screen.getByLabelText('Portfolio JSON'),{target:{value:JSON.stringify(next)}});
  fireEvent.click(saveButton());
  expect(screen.getByText('Enter an RVol cap from 1–99% and a reset target from 1–98%, below the cap. No save was attempted.')).toBeTruthy();
  expect(calls.api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
});

it.each([false,true])('saves weights without capital/FX for a new or selected portfolio (selected=%s)',async selected=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async(path,init)=>init?.method==='POST'
    ?{...saved,payload:JSON.parse(init.body).payload}:original(path,init));
  render(<Portfolio/>);await screen.findByRole("option", { name: saved.name });
  if (selected) await chooseSaved();
  else fireEvent.click(screen.getByRole("button", { name: words.newPortfolio }));
  const draft={...payload,total_ils:null,ils_per_usd:null};
  fireEvent.change(screen.getByLabelText('Portfolio JSON'),{target:{value:JSON.stringify(draft)}});
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body)).toEqual({payload:{...draft,transfer_rule:{mode:'none'}},
    id:selected?saved.id:null,expected_updated_at:selected?saved.updated_at:null,is_default:selected});
  expect(screen.getByLabelText('Total capital (ILS)')).toHaveProperty('value','');
  expect(screen.getByLabelText('ILS per USD rate')).toHaveProperty('value','');
});

it('saves omitted capital/FX without auto-filling or adding fields',async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  const {total_ils:capital,ils_per_usd:fx,...draft}=payload;
  fireEvent.change(screen.getByLabelText('Portfolio JSON'),{target:{value:JSON.stringify(draft)}});
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body).payload).toEqual({...draft,transfer_rule:{mode:'none'}});
});

it.each(['total_ils','ils_per_usd'])('keeps legacy optional %s untouched in Advanced JSON',async field=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  const label=field==='total_ils'?'Total capital (ILS)':'ILS per USD rate';
  expect(screen.queryByLabelText(label)).toBeNull();
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  expect(JSON.parse(calls.api.mock.calls.find(([,init])=>init?.method==='POST')![1].body).payload[field]).toEqual(payload[field as "total_ils" | "ils_per_usd"]);
});
