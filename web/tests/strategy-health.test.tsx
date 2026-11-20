import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import text from "../content/strategy-health.json";

const mock = vi.hoisted(() => ({ response: vi.fn() }));
vi.mock("../lib/api", () => ({ authorizedResponse: mock.response }));
import StrategyHealth from "../components/StrategyHealth";

const metric = { current: .1, percentile: 95, samples: 19, minimum_samples: 8, status: "yellow", review_value: .08, structural_value: .12, distribution: [.02, .04, .06, .08, .12] };
const report = { key: "cm", status: "yellow", summary: "Drawdown reached the yellow warning level.", triggered_by: ["drawdown"], as_of: "2026-11-02", start: "2015-12-01", peak: "2026-03-02", findings: [], metrics: {drawdown: metric, underwater: {...metric, current: 8}, relative: {...metric, current: .03}}, rolling: [{date: "2026-10-01", relative: -.02}, {date: "2026-11-02", relative: -.03}] };
const payload = { reports: [report], checks: { findings: [], proxies: [] } };
const reply = (data: unknown) => new Response(JSON.stringify(data));
afterEach(() => { cleanup(); vi.clearAllMocks(); localStorage.clear(); });

it("waits for Run and sends saved weights with the working defaults", async () => {
  mock.response.mockResolvedValue(reply(payload));
  const input = {sleeves: [{model: "Century Momentum", weight: 65}, {model: "Inflation Compass Standard", weight: 35}], end: "2026-11-02"};
  render(<StrategyHealth input={input} />);
  expect(mock.response).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", {name: text.run}));
  await screen.findByText(report.summary);
  expect(JSON.parse(mock.response.mock.calls[0][1].body)).toEqual({...input, thresholds: text.thresholdDefaults});
  expect(text.thresholdDefaults).toEqual({minimum_falls:8, warning_fraction:2/3, gap_tail_percent:10, minimum_years:20});
});

it("shows only a light and one reason on each card, with settings hidden", async () => {
  mock.response.mockResolvedValue(reply(payload));
  render(<StrategyHealth automatic compact />);
  await screen.findByText(report.summary);
  const card = within(screen.getByRole('article'));
  expect(card.getByText(text.lights.yellow)).toBeTruthy();
  expect(card.getAllByRole('paragraph')).toHaveLength(1);
  expect(card.queryByRole('definition')).toBeNull();
  expect(screen.queryByRole('spinbutton')).toBeNull();
  expect(screen.queryByRole('img')).toBeNull();
  expect(screen.getByRole('button',{name:text.settings}).getAttribute('aria-expanded')).toBe('false');
  expect(screen.getByText(text.trafficRule)).toBeTruthy();
  expect(mock.response).toHaveBeenCalledTimes(1);
});

it("uses a visible grey label when the episode minimum is unmet", async () => {
  mock.response.mockResolvedValue(reply({...payload, reports:[{...report,status:'insufficient',summary:'Drawdown needs more complete reference history.'}]}));
  render(<StrategyHealth automatic />);
  await screen.findByText(text.lights.insufficient);
  expect(screen.getByRole('article').textContent).toContain('Drawdown needs more complete reference history.');
  expect(screen.getByText(text.lights.insufficient).className).toContain('insufficient');
});

it("opens Review thresholds with plain help, and applies edits only when requested", async () => {
  mock.response.mockImplementation(async () => reply(payload));
  render(<StrategyHealth automatic />);
  await screen.findByText(report.summary);
  fireEvent.click(screen.getByRole('button',{name:text.settings}));
  expect(screen.getByText(text.configure)).toBeTruthy();
  for (const key of ['minimum_falls','warning_fraction','gap_tail_percent'] as const) expect(screen.getByText(text.settingHelp[key])).toBeTruthy();
  fireEvent.change(screen.getByRole('spinbutton',{name:text.settingLabels.minimum_falls}),{target:{value:'12'}});
  expect(mock.response).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button',{name:text.apply}));
  await waitFor(()=>expect(mock.response).toHaveBeenCalledTimes(2));
  expect(JSON.parse(mock.response.mock.calls[1][1].body).thresholds.minimum_falls).toBe(12);
  expect(JSON.parse(localStorage.getItem('strategy-health-thresholds-v2')!).minimum_falls).toBe(12);
});

it("reset restores and reapplies all defaults without extra input", async () => {
  localStorage.setItem('strategy-health-thresholds-v2',JSON.stringify({minimum_falls:12,warning_fraction:.75,gap_tail_percent:20}));
  mock.response.mockImplementation(async () => reply(payload));
  render(<StrategyHealth automatic />);
  await screen.findByText(report.summary);
  fireEvent.click(screen.getByRole('button',{name:text.settings}));
  fireEvent.click(screen.getByRole('button',{name:text.reset}));
  await waitFor(()=>expect(mock.response).toHaveBeenCalledTimes(2));
  expect(JSON.parse(mock.response.mock.calls[1][1].body).thresholds).toEqual(text.thresholdDefaults);
  expect((screen.getByRole('spinbutton',{name:text.settingLabels.minimum_falls}) as HTMLInputElement).value).toBe('8');
  expect(localStorage.getItem('strategy-health-thresholds-v2')).toBeNull();
});

it("old percentile preferences do not override the new traffic-light defaults", async () => {
  localStorage.setItem('strategy-health-thresholds-v1',JSON.stringify({review:90,structural:97.5,ic_review:80,ic_structural:95}));
  mock.response.mockResolvedValue(reply(payload));
  render(<StrategyHealth automatic />);
  await screen.findByText(report.summary);
  expect(JSON.parse(mock.response.mock.calls[0][1].body).thresholds).toEqual(text.thresholdDefaults);
});

it("source warnings and IWM proxy disclosures stay outside the coloured card", async () => {
  mock.response.mockResolvedValue(reply({...payload, reports:[{...report,caveats:[{model:'Russell 2000 Israel',warning:'IWM proxy with adjusted closes.'}]}],checks:{findings:[{kind:'data',status:'review',message:'T5YIE dated source warning',action:text.technicalAction}],proxies:[]}}));
  render(<StrategyHealth automatic />);
  await screen.findByText(/IWM proxy with adjusted closes/);
  expect(within(screen.getByRole('article')).getByText(text.lights.yellow)).toBeTruthy();
  expect(within(screen.getByRole('article')).queryByText(/IWM proxy/)).toBeNull();
  expect(screen.getByText(/IWM proxy with adjusted closes/).className).toContain('note');
  expect(screen.getByText('T5YIE dated source warning').closest('.signal-warning')).toBeNull();
});

it("keeps historical metrics inspectable inside the hidden settings panel", async () => {
  mock.response.mockResolvedValue(reply(payload));
  render(<StrategyHealth automatic />);
  await screen.findByText(report.summary);
  fireEvent.click(screen.getByRole('button',{name:text.settings}));
  fireEvent.click(screen.getByText(`${text.cm} · ${text.details}`));
  expect(screen.getAllByRole('img')).toHaveLength(4);
  expect(screen.getByText(text.simulation)).toBeTruthy();
});

it("contains provider failures and permits a retry", async () => {
  mock.response.mockRejectedValueOnce(new Error('private detail')).mockResolvedValueOnce(reply(payload));
  render(<StrategyHealth automatic />);
  expect(await screen.findByRole('alert')).toHaveProperty('textContent',text.error);
  expect(screen.queryByText('private detail')).toBeNull();
  fireEvent.click(screen.getByRole('button',{name:text.retry}));
  await screen.findByText(report.summary);
});

it("keeps the existing Backtest link beside the cards", async () => {
  mock.response.mockResolvedValue(reply(payload));
  render(<StrategyHealth automatic compact />);
  await screen.findByText(report.summary);
  expect(screen.getByRole('link',{name:text.open}).getAttribute('href')).toMatch(/\/backtest\/?\?health=default#strategy-health/);
});

it("shows the proxy cutoff, reference start and worst earlier fall on an extended card", async () => {
  mock.response.mockResolvedValue(reply({...payload,reports:[{...report,proxy_before:'2016-07-01',reference_start:'1928-04-30',metrics:{...report.metrics,drawdown:{...metric,structural_value:.275}}}]}));
  render(<StrategyHealth automatic />);
  await screen.findByText('History extended with a proxy before 1 Jul 2016');
  expect(screen.getByText('History starts 30 Apr 1928 · Worst earlier fall 27.50%')).toBeTruthy();
});

it("shows grey Short history for cash CM without claiming a bond extension", async () => {
  mock.response.mockResolvedValue(reply({...payload,reports:[{...report,status:'short_history',summary:'Real history is shorter than 20 years and no earlier health proxy is available.',proxy_before:null,reference_start:'2016-07-01'}]}));
  render(<StrategyHealth automatic />);
  const light=await screen.findByText(text.lights.short_history);
  expect(light.className).toContain('short_history');
  expect(screen.queryByText(/History extended with a proxy/)).toBeNull();
  expect(screen.getByText('History starts 1 Jul 2016 · Worst earlier fall 12.00%')).toBeTruthy();
});

it("adds the 20-year setting while preserving existing browser threshold preferences", async () => {
  localStorage.setItem('strategy-health-thresholds-v2',JSON.stringify({minimum_falls:12,warning_fraction:.75,gap_tail_percent:20}));
  mock.response.mockImplementation(async()=>reply(payload));
  render(<StrategyHealth automatic />);
  await screen.findByText(report.summary);
  expect(JSON.parse(mock.response.mock.calls[0][1].body).thresholds).toEqual({minimum_falls:12,warning_fraction:.75,gap_tail_percent:20,minimum_years:20});
  fireEvent.click(screen.getByRole('button',{name:text.settings}));
  const setting=screen.getByRole('spinbutton',{name:text.settingLabels.minimum_years}) as HTMLInputElement;
  expect(setting.value).toBe('20');
  expect(screen.getByText(text.settingHelp.minimum_years)).toBeTruthy();
  fireEvent.change(setting,{target:{value:'10'}});
  expect(mock.response).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button',{name:text.apply}));
  await waitFor(()=>expect(mock.response).toHaveBeenCalledTimes(2));
  expect(JSON.parse(mock.response.mock.calls[1][1].body).thresholds.minimum_years).toBe(10);
});
