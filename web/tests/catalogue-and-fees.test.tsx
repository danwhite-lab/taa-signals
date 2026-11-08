import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import Catalogue from "../app/strategy-catalogue/page";

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });
const rows = [
  {label:"Zulu", execution_currency:"USD", markdown:"Technical Zulu", plain_text:null, plain_flags:[], strategy:"Zulu", implementation:"Original", risk_warning:"Risk warning"},
  {label:"Alpha", execution_currency:"ILS", markdown:"Technical Alpha", plain_text:"Plain Alpha", plain_flags:["experimental"], strategy:"Alpha", implementation:"Israel", risk_warning:"Risk warning"},
];
function open() {
  vi.stubGlobal("fetch", vi.fn(async (path: string) => {
    const label = new URL(path, "https://fixture.invalid").searchParams.get("label");
    return Response.json(label ? {model:rows.find(row=>row.label===label), implementation_notes:"Implementation notes", source:"shared"}
      : {models:rows, source:"shared"});
  }));
  return render(<Catalogue />);
}

it("defaults to Plain, switches exact technical text, and remembers the choice", async () => {
  const view = open();
  fireEvent.click(await screen.findByRole("button",{name:"Alpha Israel"}));
  await screen.findByText("Plain Alpha");
  expect(screen.getByRole("radio", {name:"Plain"})).toHaveProperty("checked", true);
  expect(screen.getByText("experimental")).toBeTruthy();
  expect(screen.getByText("Risk warning")).toBeTruthy();
  fireEvent.click(screen.getByRole("radio", {name:"Technical"}));
  expect(screen.getByText("Technical Alpha")).toBeTruthy();
  expect(screen.queryByText("Plain Alpha")).toBeNull();
  expect(localStorage.getItem("catalogue-view")).toBe("technical");
  view.unmount(); open();
  fireEvent.click(await screen.findByRole("button",{name:"Alpha Israel"}));
  await screen.findByText("Technical Alpha");
  expect(screen.getByRole("radio", {name:"Technical"})).toHaveProperty("checked", true);
});

it("filters explicit implementations and fetches rules only for the chosen model", async () => {
  open(); const list=await screen.findByRole("group",{name:"Search models"});
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button",{name:"Israel"}));
  expect(within(list).getAllByRole("button").map(row=>row.textContent)).toEqual(["Alpha Israel"]);
  expect(fetch).toHaveBeenCalledTimes(1);
  fireEvent.click(within(list).getByRole("button",{name:"Alpha Israel"}));
  await screen.findByText("Plain Alpha");
  fireEvent.change(screen.getByRole("searchbox"),{target:{value:"zulu"}});
  expect(screen.getByText("Plain Alpha")).toBeTruthy();
  expect(fetch).toHaveBeenCalledTimes(2);
  fireEvent.click(screen.getByRole("button",{name:"All"}));
  fireEvent.click(within(list).getByRole("button",{name:"Zulu Original"}));
  await screen.findByText("Technical Zulu");
  expect(screen.getByText("No plain version yet")).toBeTruthy();
});

it("works when localStorage is unavailable", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw Error("Blocked"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw Error("Blocked"); });
  open(); fireEvent.click(await screen.findByRole("button",{name:"Alpha Israel"})); await screen.findByText("Plain Alpha");
  fireEvent.click(screen.getByRole("radio", {name:"Technical"}));
  expect(screen.getByText("Technical Alpha")).toBeTruthy();
  vi.restoreAllMocks();
});
