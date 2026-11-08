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
it("keeps the moved Add a sleeve control lazy and leaves choosing a model non-mutating",async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  const add=screen.getByRole("button",{name:words.addSleeve});
  const actions=add.closest<HTMLDivElement>(".actions")!;
  expect(within(actions).getByRole("button",{name:words.saveChanges})).toBeTruthy();
  expect(actions.lastElementChild?.contains(add)).toBe(true);
  expect(screen.getByRole("region",{name:"Portfolio summary"}).contains(add)).toBe(false);
  expect(calls.api.mock.calls.some(([path])=>path.includes("/api/backtest/config"))).toBe(false);
  fireEvent.click(add);
  fireEvent.click(await screen.findByRole("button",{name:/Buy and Hold · US Treasury Bonds IEF/}));
  expect(screen.queryByLabelText("Weight for Buy and Hold IEF (row 2)")).toBeNull();
  expect(screen.queryByText(/New sleeves start at/)).toBeNull();
  fireEvent.click(saveButton());await screen.findByText("Portfolio saved.");
  expect(savedPayload()).toEqual(payload);
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
  expect(screen.getByLabelText(`Weight for ${model} (row 1)`)).toHaveProperty("value","100.00");
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
  fireEvent.click(saveButton());await screen.findByText("Portfolio saved.");
  expect(savedPayload().transfer_rule).toEqual({...rule,mode:"none"});
});

function mockLoad(initialPayload: unknown = payload) {
  calls.api.mockImplementation(async (path: string, init?: RequestInit) => {
    if (init?.method === "POST") return { ...saved, payload: JSON.parse(String(init.body)).payload, updated_at: "new-mock-timestamp" };
    if (path === "/api/workspace") return { revision: 7, payload: { portfolio_name: "Fake preference" } };
    if (path === "/api/portfolios") return [{...saved,payload:initialPayload}];
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

function savedPayload() {
  return JSON.parse(calls.api.mock.calls.find(([,init])=>init?.method==="POST")![1].body).payload;
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
  fireEvent.click(screen.getByRole('button',{name:words.addSleeve}));
  const results = await screen.findByRole("group", { name: "Search models" });
  expect(within(results).getAllByRole("button").map(button => button.textContent)).toEqual(["Alpha","beta","Zulu"]);
  expect(screen.getByRole("button", { name: words.addSleeveButton })).toHaveProperty("disabled",true);
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
  expect(screen.getByRole("heading",{name:"Renamed portfolio"})).toBeTruthy();
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

it.each(["Portfolio name","Weight for Buy and Hold SPY (row 1)",words.defaultLabel])("guards unsaved %s against replacing the form",async field=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  const second={...saved,id:"fake-second",name:"Fake second",payload:{...payload,name:"Fake second"}};
  calls.api.mockImplementation(async(path,init)=>path==="/api/portfolios"?[saved,second]:original(path,init));
  const confirm=vi.spyOn(window,"confirm").mockReturnValue(false);
  render(<Portfolio/>);await chooseSaved();
  if (field === words.portfolioName) openRename();
  const input=screen.getByLabelText(field);
  if(field===words.defaultLabel)fireEvent.click(input);
  else fireEvent.change(input,{target:{value:field.startsWith("Weight")?"90":"Unsaved fake draft"}});
  await chooseSaved("fake-second");
  expect(confirm).toHaveBeenCalledOnce();expect(screen.getByText("Loaded: Fake portfolio")).toBeTruthy();
  expect(input).toHaveProperty(field===words.defaultLabel?"checked":"value",field===words.defaultLabel?false:field.startsWith("Weight")?"90.00":"Unsaved fake draft");
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

it("shows a readable loaded summary below the controls with no JSON editor or default helper",async()=>{
  mockLoad();render(<Portfolio/>);
  expect(screen.queryByRole("region",{name:"Portfolio summary"})).toBeNull();
  expect(screen.queryByRole("button",{name:words.addSleeve})).toBeNull();
  await chooseSaved();
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).getByRole("heading",{name:"Fake portfolio"})).toBeTruthy();
  const table=within(summary).getByRole("table",{name:"Portfolio sleeves"});
  expect(within(table).getByRole("columnheader",{name:"Sleeve name"})).toBeTruthy();
  expect(within(table).getByRole("columnheader",{name:"Weight"})).toBeTruthy();
  expect(within(table).getByLabelText("Weight for Buy and Hold SPY (row 1)")).toHaveProperty("value","100.00");
  expect(within(table).getByText("100.00%")).toBeTruthy();
  expect(saveButton().compareDocumentPosition(table)&Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByText("Advanced: edit JSON")).toBeNull();
  expect(screen.queryByLabelText("Portfolio JSON")).toBeNull();
  expect(screen.queryByRole("textbox",{name:"Portfolio JSON"})).toBeNull();
  expect(document.querySelector("#portfolio-default-note")).toBeNull();
  expect(screen.getByRole("checkbox",{name:words.defaultLabel}).hasAttribute("aria-describedby")).toBe(false);
  expect(screen.queryByText(/Leaving this unchecked preserves existing defaults/)).toBeNull();
});

it("updates the summary from visible edits and saves untouched precision with the existing request contract",async()=>{
  const initial={...payload,total_ils:12345.6789,ils_per_usd:3.14159,sleeves:[
    {model:"Fake long sleeve name with multiple whole words",weight:33.333333},
    {model:"Fake second sleeve",weight:66.666667}]};
  mockLoad(initial);render(<Portfolio/>);await chooseSaved();openRename();
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:"Fake edited name"}});
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).getByRole("heading",{name:"Fake edited name"})).toBeTruthy();
  expect(within(summary).getByLabelText("Weight for Fake long sleeve name with multiple whole words (row 1)")).toHaveProperty("value","33.33");
  expect(within(summary).getByLabelText("Weight for Fake second sleeve (row 2)")).toHaveProperty("value","66.67");
  expect(within(summary).getByText("100.00%")).toBeTruthy();
  fireEvent.click(saveButton());await screen.findByText("Portfolio saved.");
  expect(JSON.parse(calls.api.mock.calls.find(([,init])=>init?.method==="POST")![1].body)).toEqual({
    id:saved.id,expected_updated_at:saved.updated_at,is_default:true,payload:{...initial,name:"Fake edited name"}});
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

it.each(["{",{version:1,name:"Missing sleeves"}])("does not invent a summary for malformed or missing saved data %j",async initial=>{
  mockLoad(initial);render(<Portfolio/>);await chooseSaved();
  const summary=screen.getByRole("region",{name:"Portfolio summary"});
  expect(within(summary).getByText(words.sleevesUnavailable)).toBeTruthy();
  expect(within(summary).queryByRole("table")).toBeNull();
  if(typeof initial==="string")expect(within(summary).getByRole("alert").textContent).toBe(words.summaryUnavailable);
  expect(screen.getByRole("button",{name:words.addSleeve})).toHaveProperty("disabled",true);
  expect(calls.api.mock.calls.some(([path])=>path.includes("/api/backtest/config"))).toBe(false);
  fireEvent.click(saveButton());
  expect(calls.api.mock.calls.some(([,init])=>init?.method==="POST")).toBe(false);
});

it("does not invent a missing saved sleeve weight",async()=>{
  mockLoad({...payload,sleeves:[{model:"Fake missing weight"}]});render(<Portfolio/>);await chooseSaved();
  const table=screen.getByRole("table",{name:"Portfolio sleeves"});
  expect(within(table).getAllByText("Unavailable")).toHaveLength(2);
  expect(within(table).getByLabelText("Weight for Fake missing weight (row 1)")).toHaveProperty("value","");
  expect(within(table).queryByText("100.00%")).toBeNull();
  fireEvent.click(saveButton());expect(calls.api.mock.calls.some(([,init])=>init?.method==="POST")).toBe(false);
});

it("shows the actual saved total and updates it without normalizing weights",async()=>{
  mockLoad({...payload,sleeves:[{model:"Fake first",weight:50},{model:"Fake second",weight:40}]});
  render(<Portfolio/>);await chooseSaved();
  expect(screen.getByRole("row",{name:/Total/}).textContent).toBe("Total90.00%");
  fireEvent.change(screen.getByLabelText("Weight for Fake first (row 1)"),{target:{value:"45"}});
  expect(screen.getByRole("row",{name:/Total/}).textContent).toBe("Total85.00%");
});

it("keeps phone wrapping and overflow rules local to Portfolio without mid-word breaks",()=>{
  const css=readFileSync("./app/portfolio/portfolio.module.css","utf8");
  expect(css).toContain("word-break: normal");expect(css).toContain("overflow-wrap: normal");
  expect(css).toContain("overflow-x: auto");expect(css).toContain("flex-wrap: wrap");
  expect(css).not.toMatch(/break-all|break-word|anywhere|overflow:\s*hidden/);
});

it('preserves legacy capital, FX, custom metadata and sleeve identity while editing name and weights',async()=>{
  vi.spyOn(window,'confirm').mockReturnValue(true);
  const initial={...payload,total_ils:5432.1234,ils_per_usd:3.612345,custom_note:'Fake retained field',sleeves:[{id:17,model:'Buy and Hold SPY',weight:100}]};
  mockLoad(initial);render(<Portfolio/>);await chooseSaved();openRename();
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:'Fake builder name'}});
  const input=screen.getByLabelText('Weight for Buy and Hold SPY (row 1)');
  fireEvent.focus(input);fireEvent.change(input,{target:{value:'95.126'}});fireEvent.blur(input);
  expect(input).toHaveProperty('value','95.13');
  expect(screen.getByRole('row',{name:/Total/}).textContent).toBe('Total95.13%');
  expect(screen.getByRole('alert').textContent).toContain('not 100%');
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  expect(savedPayload()).toEqual({...initial,name:'Fake builder name',sleeves:[{id:17,model:'Buy and Hold SPY',weight:95.13}]});
});

it('uses the Backtest model list without duplicates and removes the requested row, not the last',async()=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  fireEvent.click(screen.getByRole('button',{name:words.addSleeve}));
  const results=await screen.findByRole("group",{name:"Search models"});
  expect(calls.api).toHaveBeenCalledWith('/api/backtest/config?mode=portfolio');
  expect(within(results).queryByRole('button',{name:/Buy and Hold · S&P 500 SPY/})).toBeNull();
  const bond = within(results).getAllByRole('button',{name:/Buy and Hold · US Treasury Bonds IEF/});
  expect(bond).toHaveLength(1);
  fireEvent.click(bond[0]);fireEvent.click(screen.getByRole('button',{name:words.addSleeveButton}));
  expect(screen.getByLabelText('Weight for Buy and Hold IEF (row 2)')).toHaveProperty('value','0.00');
  expect(screen.getByLabelText('Weight for Buy and Hold SPY (row 1)')).toHaveProperty('value','100.00');
  fireEvent.click(screen.getByRole('button',{name:'Remove Buy and Hold SPY (row 1)'}));
  expect(screen.queryByLabelText('Weight for Buy and Hold SPY (row 1)')).toBeNull();
  expect(screen.getByLabelText('Weight for Buy and Hold IEF (row 1)')).toHaveProperty('value','0.00');
  fireEvent.click(screen.getByRole("button",{name:words.addSleeve}));
  expect(screen.getByRole('button',{name:/Buy and Hold · S&P 500 SPY/})).toBeTruthy();
  expect(screen.queryByRole('button',{name:/Buy and Hold · US Treasury Bonds IEF/})).toBeNull();
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

it('loads editable fields and available models from saved payloads',async()=>{
  const next={...payload,total_ils:500,ils_per_usd:3.5,sleeves:[{model:'Buy and Hold IEF',weight:100}]};
  mockLoad(next);render(<Portfolio/>);await chooseSaved();openRename();
  expect(screen.getByLabelText(words.portfolioName)).toHaveProperty('value',payload.name);
  expect(screen.getByLabelText('Weight for Buy and Hold IEF (row 1)')).toHaveProperty('value','100.00');
  expect(screen.queryByLabelText('Weight for Buy and Hold SPY (row 1)')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:words.addSleeve}));
  const results=await screen.findByRole("group",{name:"Search models"});
  expect(within(results).getByRole('button',{name:/Buy and Hold · S&P 500 SPY/})).toBeTruthy();
  expect(within(results).queryByRole('button',{name:/Buy and Hold · US Treasury Bonds IEF/})).toBeNull();
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  expect(savedPayload()).toEqual(next);
});

it.each(['Weight for Buy and Hold SPY (row 1)'])('guards unsaved table edit %s before another portfolio is loaded',async label=>{
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
  expect(screen.queryByLabelText('Total capital (ILS)')).toBeNull();
  expect(screen.queryByLabelText('ILS per USD rate')).toBeNull();
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:'Fake new'}});
  fireEvent.click(screen.getByRole('button',{name:words.addSleeve}));
  fireEvent.click(await screen.findByRole('button',{name:/Buy and Hold · S&P 500 SPY/}));
  fireEvent.click(screen.getByRole('button',{name:words.addSleeveButton}));
  fireEvent.change(screen.getByLabelText('Weight for Buy and Hold SPY (row 1)'),{target:{value:'100'}});
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body)).toMatchObject({id:null,expected_updated_at:null,is_default:false,payload:{version:1,name:'Fake new',sleeves:[{model:'Buy and Hold SPY',weight:100}]}});
});

it.each([[],[{model:'Buy and Hold SPY',weight:0}],[{model:'Buy and Hold SPY',weight:null}],
  [{model:'Buy and Hold SPY',weight:50},{model:'Buy and Hold SPY',weight:50}]].map(sleeves=>[sleeves]))('does not save empty, invalid or duplicate saved sleeves %j',async sleeves=>{
  mockLoad({...payload,sleeves});render(<Portfolio/>);await chooseSaved();
  fireEvent.click(saveButton());
  expect(screen.getAllByRole('alert').some(node=>node.textContent?.includes('No save was attempted'))).toBe(true);
  expect(calls.api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
});

it('retries a failed model list without losing the editable draft',async()=>{
  mockLoad();const original=calls.api.getMockImplementation()!;let fail=true;
  calls.api.mockImplementation(async(path,init)=>{if(path==='/api/backtest/config?mode=portfolio'&&fail)throw Error('Mock failure');return original(path,init);});
  render(<Portfolio/>);await chooseSaved();fireEvent.click(screen.getByRole('button',{name:words.addSleeve}));
  await screen.findByText('Available models could not be loaded. Existing drafts are unchanged.');
  openRename();
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:'Fake draft preserved'}});
  fail=false;fireEvent.click(screen.getByText('Retry model list'));
  await screen.findByRole('searchbox',{name:'Search models'});
  expect(screen.getByLabelText('Portfolio name')).toHaveProperty('value','Fake draft preserved');
});

it('preserves legacy portfolios with no stored transfer rule on save',async()=>{
  mockLoad();const original=calls.api.getMockImplementation()!;
  calls.api.mockImplementation(async(path,init)=>path==="/api/backtest/config?mode=portfolio"
    ?{models:[{label:"Buy and Hold SPY",signal_mode:"internal"}]}:original(path,init));
  render(<Portfolio/>);await chooseSaved();
  expect(screen.queryByLabelText('Sleeve transfer rule')).toBeNull();
  expect(screen.queryByText('Advanced: edit JSON')).toBeNull();
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body).payload).toEqual(payload);
});

it('edits and saves the quarterly cap with its model identity and precise parameters',async()=>{
  const base={...payload,sleeves:[{id:991,model:'A-RVol Shifter V3 Cash-Only',weight:20},{model:'Buy and Hold SPY',weight:80}]};
  mockLoad(base);render(<Portfolio/>);await chooseSaved();
  fireEvent.click(screen.getByRole('button',{name:'Transfer rule: None'}));
  fireEvent.change(screen.getByLabelText('Sleeve transfer rule'),{target:{value:'rvol_cap'}});
  fireEvent.change(screen.getByLabelText('RVol sleeve to cap'),{target:{value:'A-RVol Shifter V3 Cash-Only'}});
  fireEvent.change(screen.getByLabelText('RVol cap (%)'),{target:{value:'17.5'}});
  fireEvent.change(screen.getByLabelText('RVol reset target (%)'),{target:{value:'9.25'}});
  const rule={mode:'rvol_cap',sleeve_model:'A-RVol Shifter V3 Cash-Only',cap_percent:17.5,target_percent:9.25};
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body)).toMatchObject({expected_updated_at:saved.updated_at,is_default:true,payload:{...base,transfer_rule:rule}});
});

it('keeps transfer controls in sync with JSON and warns instead of retargeting a removed cap sleeve',async()=>{
  const rule={mode:'rvol_cap',sleeve_model:'A-RVol Shifter V3 Cash-Only',cap_percent:22,target_percent:11};
  const next={...payload,sleeves:[{model:rule.sleeve_model,weight:10},{model:'Buy and Hold SPY',weight:90}],transfer_rule:rule};
  mockLoad(next);render(<Portfolio/>);await chooseSaved();
  fireEvent.click(screen.getByRole('button',{name:'Transfer rule: Quarterly RVol cap'}));
  expect(screen.getByLabelText('Sleeve transfer rule')).toHaveProperty('value','rvol_cap');
  expect(screen.getByLabelText('RVol cap (%)')).toHaveProperty('value','22');
  expect(screen.getByLabelText('RVol reset target (%)')).toHaveProperty('value','11');
  fireEvent.click(screen.getByRole('button',{name:`Remove ${rule.sleeve_model} (row 1)`}));
  expect(screen.getByText('Select an existing RVol sleeve to cap. The stored selection is not changed automatically.')).toBeTruthy();
  expect(calls.api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
  fireEvent.click(saveButton());
  expect(calls.api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
  fireEvent.change(screen.getByLabelText('Sleeve transfer rule'),{target:{value:'annual_target'}});
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  expect(savedPayload().transfer_rule.mode).toBe('annual_target');
  expect(screen.queryByLabelText('RVol cap (%)')).toBeNull();
});

it('treats transfer edits as unsaved and refuses invalid cap parameters',async()=>{
  mockLoad();const confirm=vi.spyOn(window,'confirm').mockReturnValue(false);
  render(<Portfolio/>);await chooseSaved();
  fireEvent.click(screen.getByRole('button',{name:'Transfer rule: None'}));
  fireEvent.change(screen.getByLabelText('Sleeve transfer rule'),{target:{value:'annual_target'}});
  fireEvent.click(screen.getByText('New portfolio'));expect(confirm).toHaveBeenCalledWith('Discard unsaved portfolio edits?');
  const next={...payload,sleeves:[{model:'A-RVol Shifter V3 Cash-Only',weight:100}],transfer_rule:{mode:'rvol_cap',sleeve_model:'A-RVol Shifter V3 Cash-Only',cap_percent:10,target_percent:20}};
  mockLoad(next);render(<Portfolio/>);await chooseSaved();
  fireEvent.click(saveButton());
  expect(screen.getByText('Enter an RVol cap from 1–99% and a reset target from 1–98%, below the cap. No save was attempted.')).toBeTruthy();
  expect(calls.api.mock.calls.some(([,init])=>init?.method==='POST')).toBe(false);
});

it.each([false,true])('saves weights without inventing capital/FX for a new or selected portfolio (selected=%s)',async selected=>{
  const initial={...payload,total_ils:null,ils_per_usd:null};
  mockLoad(initial);render(<Portfolio/>);await screen.findByRole("option",{name:saved.name});
  if(selected) await chooseSaved();
  else {
    fireEvent.click(screen.getByRole("button",{name:words.newPortfolio}));
    fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:payload.name}});
    fireEvent.click(screen.getByRole('button',{name:words.addSleeve}));
    fireEvent.click(await screen.findByRole('button',{name:/Buy and Hold · S&P 500 SPY/}));
    fireEvent.click(screen.getByRole('button',{name:words.addSleeveButton}));
    fireEvent.change(screen.getByLabelText('Weight for Buy and Hold SPY (row 1)'),{target:{value:'100'}});
  }
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  const [,init]=calls.api.mock.calls.find(([,init])=>init?.method==='POST')!;
  expect(JSON.parse(init.body)).toEqual({payload:selected?initial:{version:1,name:payload.name,sleeves:payload.sleeves},
    id:selected?saved.id:null,expected_updated_at:selected?saved.updated_at:null,is_default:selected});
  expect(screen.queryByLabelText('Total capital (ILS)')).toBeNull();
  expect(screen.queryByLabelText('ILS per USD rate')).toBeNull();
});

it('saves omitted capital/FX without auto-filling or adding fields',async()=>{
  const {total_ils:capital,ils_per_usd:fx,...draft}=payload;
  mockLoad(draft);render(<Portfolio/>);await chooseSaved();
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  expect(savedPayload()).toEqual(draft);
});

it.each(['total_ils','ils_per_usd'])('keeps legacy optional %s untouched in the saved payload',async field=>{
  mockLoad();render(<Portfolio/>);await chooseSaved();
  const label=field==='total_ils'?'Total capital (ILS)':'ILS per USD rate';
  expect(screen.queryByLabelText(label)).toBeNull();
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  expect(JSON.parse(calls.api.mock.calls.find(([,init])=>init?.method==='POST')![1].body).payload[field]).toEqual(payload[field as "total_ils" | "ils_per_usd"]);
});


it.each([
  {mode:'rvol_cap',sleeve_model:'Buy and Hold SPY',cap_percent:20.12345678,target_percent:10.12345678,extra:'kept'},
  {mode:'annual_target',extra:'kept'}, {mode:'unknown'}, null,
  {mode:'rvol_cap',sleeve_model:'A-RVol missing',cap_percent:20,target_percent:10},
])('preserves untouched stored transfer metadata when renaming: %j',async transfer_rule=>{
  const initial={...payload,transfer_rule,custom_note:'Kept exactly'};
  mockLoad(initial);render(<Portfolio/>);await chooseSaved();openRename();
  fireEvent.change(screen.getByLabelText(words.portfolioName),{target:{value:'Visible rename'}});
  fireEvent.click(saveButton());await screen.findByText('Portfolio saved.');
  expect(savedPayload()).toEqual({...initial,name:'Visible rename'});
});

it("changes a sleeve only on Apply and saves the canonical key without dropping other sleeve fields", async () => {
  const initial = { ...payload, sleeves: [{ ...payload.sleeves[0], id: 42 }] };
  mockLoad(initial); render(<Portfolio/>); await chooseSaved();
  fireEvent.click(screen.getByRole("button",{name:"Edit Buy and Hold SPY (row 1)"}));
  expect(calls.api.mock.calls.some(([path])=>path.includes("/api/backtest/config"))).toBe(false);
  fireEvent.click(screen.getByRole("button",{name:"Change"}));
  const choice = await screen.findByRole("button",{name:/Buy and Hold · US Treasury Bonds IEF/});
  fireEvent.keyDown(screen.getByRole("searchbox"),{key:"Escape"});
  expect(choice.isConnected).toBe(false);
  expect(screen.getByLabelText("Weight for Buy and Hold SPY (row 1)")).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:"Change"}));
  fireEvent.click(screen.getByRole("button",{name:/Buy and Hold · US Treasury Bonds IEF/}));
  expect(screen.getByLabelText("Weight for Buy and Hold SPY (row 1)")).toBeTruthy();
  fireEvent.click(screen.getByRole("button",{name:words.apply}));
  expect(screen.getByLabelText("Weight for Buy and Hold IEF (row 1)")).toHaveProperty("value","100.00");
  fireEvent.click(saveButton()); await screen.findByText("Portfolio saved.");
  expect(savedPayload()).toEqual({...initial,sleeves:[{id:42,model:"Buy and Hold IEF",weight:100}]});
});
