import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import SearchPicker from "../components/SearchPicker";
import { fundChoice, fundName, loadPickerMetadata, matchingChoices, modelChoice } from "../lib/picker-display";

afterEach(cleanup);

it("uses real identity, quote currency, and model-specific series separately", async () => {
  const data = await loadPickerMetadata();
  const local = data.funds["TASE:5140850"];
  expect(local).toMatchObject({ticker:null, security_number:"5140850", market:"TASE", currency:"ILS", aliases:["SPMO_IL"], tracks:null});
  const model = data.models["Century Momentum Move to Cash Israel"];
  expect(model.held).toEqual(["TASE:5140850","TASE:5117700"]);
  expect(model.signal).toEqual([expect.objectContaining({identifier:"SPMO",currency:"USD"})]);
  expect(data.models["Buy and Hold Japan Israel"].signal).toEqual([]);
  expect(data.funds["TASE:1150531"].tracks).toBe("Nikkei 225");
  expect(data.funds["TASE:1150531"].underlying_currency).toBeNull();
  expect(data.models["HAA 4 Israel"].proxies).toEqual([expect.objectContaining({series:expect.objectContaining({identifier:"VXUS"})})]);
  expect(data.funds["TASE:5142476"].ticker).toBeNull();
  expect(data.funds["TASE:5142476"].aliases).not.toContain("VXUS");
  expect(data.funds["TASE:5141627"].aliases).not.toContain("GOLD_IL");
  expect(fundName("TASE:1147875","1147875")).not.toBe(fundName("TASE:5141627","5141627"));
  expect(fundName(local.id,"Custom nickname")).toBe("Custom nickname");
  expect(matchingChoices([fundChoice(local,data)], "spmo_il 5140850", "")).toHaveLength(1);
  expect(matchingChoices([fundChoice(local,data)], "US:SPMO", "")).toEqual([]);
});

it("finds explicit proxy, signal and fund aliases without adding unsupported models", async () => {
  const data = await loadPickerMetadata();
  const permitted = ["Century Momentum","Century Momentum Israel","Century Momentum Move to Cash Israel","Buy and Hold S&P 500 x3 Israel"];
  const choices = permitted.map(label => modelChoice({label},data));
  expect(matchingChoices(choices,"5140850","").map(row=>row.key)).toEqual([
    "Century Momentum Move to Cash Israel","Century Momentum Israel",
  ]);
  expect(matchingChoices(choices,"spmo","originals").map(row=>row.key)).toEqual(["Century Momentum"]);
  expect(matchingChoices(choices,"x3 hedged","israel").map(row=>row.key)).toEqual(["Buy and Hold S&P 500 x3 Israel"]);
  expect(matchingChoices(choices,"VXUS","")).toHaveLength(0);
});

it("preserves missing references, cancels with focus restored and commits only an explicit result", async () => {
  const select = vi.fn();
  render(<SearchPicker models={[{label:"HAA-Simple"},{label:"HAA-Simple Israel"}]}
    value="Retired model key" onSelect={select} />);
  expect(screen.getByText("Retired model key")).toBeTruthy();
  expect(screen.getByText("Unavailable")).toBeTruthy();
  const opener=screen.getByRole("button",{name:"Change"});
  fireEvent.click(opener);
  const input=screen.getByRole("searchbox");
  expect(document.activeElement).toBe(input);
  fireEvent.change(input,{target:{value:"israel"}});
  fireEvent.keyDown(input,{key:"Enter"});
  expect(select).not.toHaveBeenCalled();
  fireEvent.keyDown(input,{key:"Escape"});
  expect(document.activeElement).toBe(opener);
  expect(screen.queryByRole("searchbox")).toBeNull();
  expect(select).not.toHaveBeenCalled();
  fireEvent.click(opener);
  const search=screen.getByRole("searchbox");
  fireEvent.change(search,{target:{value:"israel"}});
  fireEvent.keyDown(search,{key:"ArrowDown"});
  expect(document.activeElement).toBe(screen.getByRole("button",{name:"HAA Simple · Israel"}));
  fireEvent.keyDown(document.activeElement!,{key:"Enter"});
  expect(select).toHaveBeenCalledExactlyOnceWith("HAA-Simple Israel");
  expect(document.activeElement).toBe(opener);
});

it("paginates long lists and keeps a selected model visible when it is filtered out", async () => {
  const models=Array.from({length:12},(_,i)=>({label:`Model ${String(i+1).padStart(2,"0")}`}));
  const select=vi.fn();
  render(<SearchPicker models={models} value="Model 12" onSelect={select} />);
  fireEvent.click(screen.getByRole("button",{name:"Change"}));
  const results=screen.getByRole("group",{name:"Search models"});
  expect(within(results).getAllByRole("button")).toHaveLength(10);
  fireEvent.click(screen.getByRole("button",{name:"Next"}));
  expect(within(results).getAllByRole("button")).toHaveLength(2);
  fireEvent.change(screen.getByRole("searchbox"),{target:{value:"model 01"}});
  expect(within(results).getAllByRole("button")).toHaveLength(1);
  expect(screen.getByText("Model 12")).toBeTruthy();
  expect(select).not.toHaveBeenCalled();
});

it("shows the exposure before the buy-and-hold rule and preserves the canonical choice", async () => {
  const select = vi.fn();
  const labels = ["Buy and Hold QQQ", "Buy and Hold World Value Israel"];
  render(<SearchPicker models={labels.map(label => ({ label }))} value={labels[0]} onSelect={select} />);
  expect(screen.getByText("QQQ")).toBeTruthy();
  expect(screen.getByText("Buy and hold · QQQ")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Change" }));
  const search = screen.getByRole("searchbox");
  fireEvent.change(search, { target: { value: "world value" } });
  const row = screen.getByRole("button", { name: "World Value Buy and hold · Israel · USD hedged" });
  const details = row.parentElement!.querySelector("details")!;
  fireEvent.click(details.querySelector("summary")!);
  expect(details.open).toBe(true);
  expect(select).not.toHaveBeenCalled();
  expect(screen.getAllByRole("searchbox")).toHaveLength(1);
  fireEvent.click(row);
  expect(select).toHaveBeenCalledExactlyOnceWith(labels[1]);
});
