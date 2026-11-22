import { activePortfolio, resultKey, readDeviceResult, saveDeviceResult } from "./device-results";
// Device-only, account/portfolio-scoped display snapshots. Never used by calculations or APIs.
export type SavedToday<T> = { version: 1; loadedAt: string; result: T };
export const todayStorageKey = (userId: string) => resultKey({userId, portfolio:activePortfolio(userId) ?? "unverified"}, "today");
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const array = (value: unknown): value is unknown[] => Array.isArray(value);

export function completeToday(value: unknown): boolean {
  if (!object(value) || value.has_default !== true || typeof value.has_holdings !== "boolean"
      || typeof value.caption !== "string" || typeof value.latest_caption !== "string"
      || (value.comparison !== null && !array(value.comparison))
      || typeof value.stale !== "boolean" || !["changed", "unchanged"].includes(String(value.monthly_action))
      || !array(value.issues) || value.issues.length || !array(value.signals) || !value.signals.length
      || !array(value.actions) || !array(value.previews) || !array(value.warnings) || !array(value.public_sleeves)) return false;
  if (!value.warnings.every(warning => typeof warning === "string")) return false;
  if (!value.signals.every(row => object(row) && row.status_code === "ok" && !row.error_code
      && typeof row.label === "string" && array(row.holding_display) && row.holding_display.length > 0
      && row.holding_display.every(part => object(part) && typeof part.name === "string"))) return false;
  if (!value.actions.every(row => object(row) && typeof row.id === "string" && typeof row.fund === "string"
      && typeof row.amount_text === "string" && ["buy", "over"].includes(String(row.direction))
      && array(row.moved_here) && row.moved_here.every(name => typeof name === "string"))) return false;
  if (value.has_holdings && (!array(value.comparison) || ["cannot_price", "valuation_failed"].includes(String(value.action_notice)))) return false;
  return true;
}

export function readSavedToday<T>(userId: string | null): SavedToday<T> | null {
  const portfolio = userId ? activePortfolio(userId) : null;
  return readDeviceResult<T>(userId && portfolio ? {userId,portfolio} : undefined, "today", completeToday);
}

export function saveToday<T>(userId: string | null, result: T): string | null {
  const portfolio = userId ? activePortfolio(userId) : null;
  return saveDeviceResult(userId && portfolio ? {userId,portfolio} : undefined, "today", result, completeToday);
}

export function completePreview(value: unknown): boolean {
  if (!completeToday(value) || !object(value) || !array(value.previews) || !array(value.signals)
      || value.previews.length !== value.signals.length) return false;
  return value.previews.every(row => object(row) && !row.error_code &&
    (["always_held", "daily_signals"].includes(String(row.kind)) ||
     (array(row.allocation_display) && row.allocation_display.length > 0 && typeof row.price_as_of === "string")));
}

export function loadedTodayTime(stamp: string): string {
  return new Intl.DateTimeFormat("en-GB", { day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(new Date(stamp));
}

export function loadedBeforeToday(stamp: string): boolean {
  const saved = new Date(stamp), now = new Date();
  return new Date(saved.getFullYear(), saved.getMonth(), saved.getDate()).getTime()
    < new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
}
