import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import text from "../content/strategy-health.json";

const mock = vi.hoisted(() => ({ response: vi.fn() }));
vi.mock("../lib/api", () => ({ authorizedResponse: mock.response }));
import StrategyHealth from "../components/StrategyHealth";

const metric = { current: .1, percentile: 95, samples: 50, status: "review", review_threshold: 90, structural_threshold: 97.5, review_value: .08, structural_value: .12, distribution: [.02, .04, .06, .08, .12] };
const payload = { reports: [{ key: "cm", status: "review", action: text.drawdownAction, as_of: "2026-11-02", start: "2015-12-01", peak: "2026-03-02", findings: [{message: "Drawdown exceeds earlier experience", action: text.drawdownAction, status: "review", kind: "drawdown"}], metrics: {drawdown: metric, underwater: {...metric, current: 8}, relative: {...metric, current: .03}}, rolling: [{date: "2026-10-01", relative: -.02}, {date: "2026-11-02", relative: -.03}] }], checks: { findings: [], proxies: [] } };
const reply = (data: unknown) => new Response(JSON.stringify(data));
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });

it("waits for Run, renders dated metrics and charts, and sends the actual weights", async () => {
  mock.response.mockResolvedValue(reply(payload));
  const input = {sleeves: [{model: "Century Momentum", weight: 65}, {model: "Inflation Compass Standard", weight: 35}], end: "2026-11-02"};
  render(<StrategyHealth input={input} />);
  expect(mock.response).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: text.run}));
  await screen.findByText(text.drawdownAction);
  expect(mock.response.mock.calls[0][0]).toBe("/api/strategy-health");
  expect(JSON.parse(mock.response.mock.calls[0][1].body)).toEqual({...input, thresholds: text.thresholdDefaults});
  expect(screen.getAllByText(text.review).length).toBeGreaterThan(0);
  fireEvent.click(screen.getByText(text.details));
  expect(screen.getAllByRole("img").length).toBe(4);
  expect(screen.getByText(text.simulation)).toBeTruthy();
});

it("automatically loads the visible Today summary and links to the default portfolio analysis", async () => {
  mock.response.mockResolvedValue(reply(payload));
  render(<StrategyHealth automatic compact />);
  await screen.findByText(text.shortDrawdown);
  expect(mock.response).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("link", {name: text.open}).getAttribute("href")).toMatch(/\/backtest\/?\?health=default#strategy-health/);
});

it("keeps technical findings separate from the historical rating and prioritizes their action", async () => {
  mock.response.mockResolvedValue(reply({...payload, checks: {findings: [{kind: "data", status: "review", message: "Mock dated missing quote", action: text.technicalAction}], proxies: []}}));
  render(<StrategyHealth automatic />);
  await screen.findByText("Mock dated missing quote");
  expect(screen.getByText(text.drawdownAction)).toBeTruthy();
  const warning = screen.getByText("Mock dated missing quote").closest("div")!;
  expect(within(warning).getByText(new RegExp(text.technicalAction))).toBeTruthy();
});

it("applies edited thresholds only on submit and persists the explicit values", async () => {
  mock.response.mockImplementation(async () => reply(payload));
  render(<StrategyHealth automatic />);
  await screen.findByText(text.drawdownAction);
  fireEvent.click(screen.getByText(text.configure));
  fireEvent.change(screen.getByLabelText(text.reviewPercentile), {target: {value: "92"}});
  expect(mock.response).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole("button", {name: text.apply}));
  await waitFor(() => expect(mock.response).toHaveBeenCalledTimes(2));
  expect(JSON.parse(mock.response.mock.calls[1][1].body).thresholds.review).toBe(92);
  expect(JSON.parse(localStorage.getItem("strategy-health-thresholds-v1")!).review).toBe(92);
});

it("shows an error and supports retry without hiding the rest of the page", async () => {
  mock.response.mockRejectedValueOnce(new Error("private detail")).mockResolvedValueOnce(reply(payload));
  render(<StrategyHealth automatic />);
  expect(await screen.findByRole("alert")).toHaveProperty("textContent", text.error);
  expect(screen.queryByText("private detail")).toBeNull();
  fireEvent.click(screen.getByRole("button", {name: text.retry}));
  await screen.findByText(text.drawdownAction);
});

it("shows insufficient data without fabricating a healthy rating", async () => {
  mock.response.mockResolvedValue(reply({...payload, reports: [{key: "cm", status: "insufficient", reason: "shortSample", findings: [], action: text.missingAction, metrics: {}}]}));
  render(<StrategyHealth automatic />);
  await screen.findByText(text.missingAction);
  expect(screen.queryByText(text.normal)).toBeNull();
  expect(screen.getByText(text.shortSample)).toBeTruthy();
});

it("names the triggering measure and labels both directions of the annual gap", async () => {
  mock.response.mockResolvedValue(reply({...payload, reports: [
    {...payload.reports[0], triggered_by: ['drawdown'], metrics: {...payload.reports[0].metrics, relative: {...metric, current: -.0295}}},
    {...payload.reports[0], key: 'ic', triggered_by: ['underwater'], metrics: {...payload.reports[0].metrics, relative: {...metric, current: .0184}}},
  ]}));
  render(<StrategyHealth automatic compact />);
  await screen.findByText('Ahead of the S&P 500 by 2.95% a year');
  expect(screen.getByText('Behind the S&P 500 by 1.84% a year')).toBeTruthy();
  const cards = screen.getAllByRole('article');
  expect(cards[0].textContent).toContain('Triggered by · drawdown');
  expect(cards[1].textContent).toContain('Triggered by · time underwater');
});

it("keeps the rating with a visible named loader caveat", async () => {
  mock.response.mockResolvedValue(reply({...payload, reports: [{...payload.reports[0], caveats: [{model: 'Inflation Compass Standard', warning: 'T5YIE source fallback notice'}]}]}));
  render(<StrategyHealth automatic />);
  await screen.findByText(/T5YIE source fallback notice/);
  expect(screen.getByRole('article').textContent).toContain(text.review);
  expect(screen.getByRole('article').textContent).toContain('Inflation Compass Standard');
});

it("names unavailable sleeves and makes the all-sleeve composition visible", async () => {
  mock.response.mockResolvedValue(reply({...payload, weights: [{model:'Century Momentum', weight:90}, {model:'Gold Cross-Asset Israel', weight:10}], reports: [{key:'combined', status:'insufficient', composition:'all_sleeves', triggered_by:[], metrics:{}, findings:[], action:text.missingAction, failures:[{model:'Gold Cross-Asset Israel', message:'Gold Cross-Asset Israel has no configured USD mapping.'}]}]}));
  render(<StrategyHealth automatic />);
  await screen.findByText('Gold Cross-Asset Israel has no configured USD mapping.');
  expect(screen.getByText('Combined uses all 2 configured sleeves at their saved weights.')).toBeTruthy();
});

it("uses a grey note for a one-day-old TASE quote and has one checks disclosure", async () => {
  const finding={kind:'data', status:'normal', trading_days_old:1, message:'TASE:5141627 · Price is dated 2026-11-18, one trading day old. Signals are not affected (they use US index data).'};
  mock.response.mockResolvedValue(reply({...payload, checks:{findings:[finding], proxies:[]}}));
  render(<StrategyHealth automatic compact />);
  const quote=await screen.findByText(finding.message, {exact:false});
  expect(quote.closest('div')?.className).toContain('priceNote');
  expect(quote.closest('.signal-warning')).toBeNull();
  expect([...document.querySelectorAll('summary')].filter(element=>element.textContent===text.checks)).toHaveLength(1);
  expect(screen.getByRole('link',{name:text.open}).parentElement?.textContent).toContain(text.title);
});
