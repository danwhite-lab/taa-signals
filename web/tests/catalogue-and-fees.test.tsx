import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import Catalogue from "../app/strategy-catalogue/page";

afterEach(() => { cleanup(); localStorage.clear(); vi.unstubAllGlobals(); });
const rows = [
  {label:"Zulu", execution_currency:"USD", markdown:"Technical Zulu", plain_text:null, plain_flags:[], implementation:"Example", risk_warning:"Risk warning"},
  {label:"Alpha", execution_currency:"ILS", markdown:"Technical Alpha", plain_text:"Plain Alpha", plain_flags:["experimental"], implementation:"Example", risk_warning:"Risk warning"},
];
function open() {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({models:rows, implementation_notes:"Implementation notes", source:"shared"}))));
  return render(<Catalogue />);
}

it("defaults to Plain, switches exact technical text, and remembers the choice", async () => {
  const view = open();
  await screen.findByText("Plain Alpha");
  expect(screen.getByRole("radio", {name:"Plain"})).toHaveProperty("checked", true);
  expect(screen.getByText("experimental")).toBeTruthy();
  expect(screen.getByText("Risk warning")).toBeTruthy();
  fireEvent.click(screen.getByRole("radio", {name:"Technical"}));
  expect(screen.getByText("Technical Alpha")).toBeTruthy();
  expect(screen.queryByText("Plain Alpha")).toBeNull();
  expect(localStorage.getItem("catalogue-view")).toBe("technical");
  view.unmount(); open();
  await screen.findByText("Technical Alpha");
  expect(screen.getByRole("radio", {name:"Technical"})).toHaveProperty("checked", true);
});

it("filters by execution currency, selects the first visible strategy and falls back safely", async () => {
  open(); await screen.findByText("Plain Alpha");
  fireEvent.click(screen.getByRole("radio", {name:"US"}));
  const list = screen.getByRole("list", {name:"Strategies"});
  expect(within(list).getAllByRole("button").map(row => row.textContent)).toEqual(["Zulu USD"]);
  expect(screen.getByText("1 strategies")).toBeTruthy();
  expect(screen.getByText("Technical Zulu")).toBeTruthy();
  expect(screen.getByText("No plain version yet")).toBeTruthy();
  expect(within(list).getByRole("button").getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(screen.getByRole("radio", {name:"Israel"}));
  expect(screen.getByText("Plain Alpha")).toBeTruthy();
  fireEvent.click(screen.getByRole("radio", {name:"All"}));
  expect(within(list).getAllByRole("button").map(row => row.textContent)).toEqual(["Alpha ILS", "Zulu USD"]);
});

it("works when localStorage is unavailable", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw Error("Blocked"); });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw Error("Blocked"); });
  open(); await screen.findByText("Plain Alpha");
  fireEvent.click(screen.getByRole("radio", {name:"Technical"}));
  expect(screen.getByText("Technical Alpha")).toBeTruthy();
  vi.restoreAllMocks();
});
