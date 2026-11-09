import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import SearchPicker from "../components/SearchPicker";

const { request } = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("../lib/api", () => ({ authorizedResponse: request }));
afterEach(() => { cleanup(); request.mockReset(); });

it.each([
  ["TASE", "5139837", "ILS", "Harel Russell 2000", "Add by seven-digit TASE security number"],
  ["Global", "IWDA.AS", "EUR", "iShares Core MSCI World", "Add by exact Yahoo Finance listing ticker"],
] as const)("checks and confirms the exact %s fund before offering it", async (market, identifier, currency, name, inputLabel) => {
  const select = vi.fn();
  const update = vi.fn();
  const checked = { market, identifier, currency, name, kind: market === "TASE" ? "mutual" : "etf" };
  const saved = { ...checked, model: "MY-FUND-test", archived: false };
  request.mockImplementation((path: string, init?: RequestInit) => {
    if (path === "/api/my-funds/check") return Promise.resolve(Response.json({
      fund: checked, quote: { price: "5.7", as_of: "2026-11-05", source: "Published close" }
    }));
    if (init?.method === "POST") return Promise.resolve(Response.json(saved));
    return Promise.resolve(Response.json({ configured: true, funds: [] }));
  });
  render(<SearchPicker models={[]} value="" onSelect={select} onFundChange={update} />);
  fireEvent.click(screen.getByRole("button", { name: "Choose model" }));
  expect(request).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: market }));
  fireEvent.change(await screen.findByLabelText(inputLabel), { target: { value: identifier } });
  fireEvent.click(screen.getByRole("button", { name: "Check listing" }));
  expect(await screen.findByText(name)).toBeTruthy();
  expect(screen.getByText(new RegExp(`5.7 ${currency} · 2026-11-05`))).toBeTruthy();
  expect(select).not.toHaveBeenCalled();
  expect(update).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Add this fund" }));
  fireEvent.click(await screen.findByRole("button", { name: new RegExp(name) }));
  expect(update).toHaveBeenCalledWith(saved);
  expect(select).toHaveBeenCalledExactlyOnceWith(saved.model);
});
