import {expect,it} from "vitest";
import {cell,configuration,date,json,number,percent,text} from "../lib/format";
it("rounds only display, keeps negatives and money separators",()=>{
  expect(number(1.005)).toBe("1.01");expect(number(-1234.567,true)).toBe("-1,234.57");
  expect(number(.000001)).toBe("0");expect(percent(.06165)).toBe("6.17%");expect(percent(-.000001)).toBe("-0.00%");
  expect(cell(null)).toBe("—");expect(cell(undefined)).toBe("—");expect(cell(NaN)).toBe("—");
});
it("formats fractional rates, arbitrary table metrics, dates and identifiers",()=>{
  expect(cell(.06165,"Probability of loss")).toBe("6.17%");expect(cell(12345.678,"Final value")).toBe("12,345.68");
  expect(cell(1147875,"Security")).toBe("1147875");expect(date("2026-10-19T23:59:59Z")).toBe("19 Oct 2026");
  expect(date("2026-02-30")).toBe("2026-02-30");expect(text("Latest: 2026-10-19; 40% / 3.14159")).toBe("Latest: 19 Oct 2026; 40.00% / 3.14");
});
it("does not mutate full precision source data or export payloads",()=>{
  const input={probability:.06165,date:"2026-10-19",amount:1234.56789};const before=JSON.stringify(input);
  expect(json(input)).toContain("6.17%");expect(json(input)).toContain("1,234.57");expect(JSON.stringify(input)).toBe(before);
});
it("preserves ratios, FX rates, years and IDs rather than calling everything a percentage",()=>{
  expect(cell(3.14159,"FX rate")).toBe("3.14");expect(cell(.12345,"tax_rate")).toBe("12.35%");
  expect(cell("2024","identifier")).toBe("2024");expect(cell(2024,"index")).toBe("2024");
  expect(cell(.06165,"P(loss)")).toBe("6.17%");expect(cell(1.2345,"Sharpe")).toBe("1.23");
  expect(json({fx:{rate:3.14159}})).toContain('"3.14"');
});
it("distinguishes form percentage points from fractional engine settings",()=>{
  expect(configuration(25,"tax_rate")).toBe("25.00%");expect(cell(.25,"tax_rate")).toBe("25.00%");
  expect(configuration(.05,"fee_value",true)).toBe("0.05%");expect(cell(.0005,"transaction_cost")).toBe("0.05%");
  expect(configuration([{model:"Fake",weight:40}],"sleeves")).toContain("40.00%");
});
