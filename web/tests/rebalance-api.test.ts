import { afterEach, expect, it, vi } from "vitest";
import text from "../content/rebalance.json";
const mock = vi.hoisted(() => ({ response: vi.fn() }));
vi.mock("../lib/api", () => ({ authorizedResponse: mock.response, ApiError: class extends Error { constructor(public status: number, message: string) { super(message); } } }));
import { saveHoldings, saveAllocationMode, rebalanceRequest } from "../lib/rebalanceApi";
afterEach(() => mock.response.mockReset());
const account = { revision: 1, positions: { "US:SPY": { units: "2" } }, cash_ils: "3", last_operation_id: "fake" };
const saved = { revision: 2, payload: { holdings_account: account } };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status });

it("uses the existing workspace route once with only account fields", async () => {
  mock.response.mockResolvedValue(json(saved));
  expect(await saveHoldings(1, account)).toEqual({ saved, uncertain: false });
  expect(mock.response).toHaveBeenCalledTimes(1);
  const [path, init] = mock.response.mock.calls[0];
  expect(path).toBe("/api/workspace"); expect(init.method).toBe("PUT");
  expect(JSON.parse(init.body)).toEqual({ revision: 1, payload: { holdings_account: account } });
});
it("reads back after a lost response, never repeats the write", async () => {
  mock.response.mockRejectedValueOnce(new Error("lost")).mockResolvedValueOnce(json(saved));
  expect(await saveHoldings(1, account)).toEqual({ saved, uncertain: true });
  expect(mock.response.mock.calls.map(([path]) => path)).toEqual(["/api/workspace", "/api/workspace"]);
  expect(mock.response.mock.calls[1][1]).toEqual({});
});
it("does not claim success if read-back differs, even with the same operation ID", async () => {
  mock.response.mockRejectedValueOnce(new Error()).mockResolvedValueOnce(json({ ...saved, payload: { holdings_account: { ...account, cash_ils: "4" } } }));
  expect(await saveHoldings(1, account)).toEqual({ saved: null, uncertain: true });
});
it("409 pauses without a repeated write or leaking the response body", async () => {
  mock.response.mockResolvedValue(json({ detail: "fake private data" }, 409));
  await expect(saveHoldings(1, account)).rejects.toThrow(text.paused);
  expect(mock.response).toHaveBeenCalledTimes(1);
});
it("masks raw gateway errors and uses supplied safe validation text", async () => {
  mock.response.mockResolvedValueOnce(new Response("raw private body", { status: 502 }));
  await expect(rebalanceRequest("/api/rebalance")).rejects.toThrow(text.validation);
  mock.response.mockResolvedValueOnce(json({ detail: "Enter cash explicitly" }, 400));
  await expect(rebalanceRequest("/api/rebalance/editor", {})).rejects.toThrow("Enter cash explicitly");
});

it("saves only the allocation preference in a revision-checked workspace patch",async()=>{
  const choice={revision:2,payload:{rebalance_allocation_mode:"proportional"}};
  mock.response.mockResolvedValue(json(choice));
  expect(await saveAllocationMode(1,"proportional")).toEqual(choice);
  expect(mock.response).toHaveBeenCalledTimes(1);
  expect(JSON.parse(mock.response.mock.calls[0][1].body)).toEqual({revision:1,payload:{rebalance_allocation_mode:"proportional"}});
  expect(mock.response.mock.calls[0][1].method).toBe("PUT");
});

it("never retries uncertain preference writes or silently accepts a different mode",async()=>{
  mock.response.mockRejectedValueOnce(new Error("Lost response"));
  await expect(saveAllocationMode(1,"proportional")).rejects.toThrow(text.allocationUncertain);
  expect(mock.response).toHaveBeenCalledTimes(1);
  mock.response.mockResolvedValue(json({revision:2,payload:{rebalance_allocation_mode:"biggest_gap_first"}}));
  await expect(saveAllocationMode(1,"proportional")).rejects.toThrow(text.allocationUncertain);
});

it("shows the clear mode validation error from the save path",async()=>{
  mock.response.mockResolvedValue(json({detail:"Choose allocation mode: proportional or biggest_gap_first."},422));
  await expect(saveAllocationMode(1,"proportional")).rejects.toThrow("Choose allocation mode:");
});
