// Display-only device storage. No results enter server calculations or writes.
export type ResultScope = { userId: string; portfolio: string };
export type DeviceResult<T> = { version: 1; loadedAt: string; result: T };
const prefix = 'signalboard.results.v1:';
export const scopeEvent = 'signalboard-results-scope';
const ownerKey = prefix + 'owner';
const userPrefix = (userId: string) => prefix + encodeURIComponent(userId) + ':';
export const activePortfolio = (userId: string): string | null => {
  try { return localStorage.getItem(userPrefix(userId) + 'portfolio'); } catch { return null; }
};
export function clearDeviceResults(userId: string) {
  try {
    for (const key of Object.keys(localStorage))
      if (key.startsWith(userPrefix(userId)) || key === `signalboard.today.v1:${encodeURIComponent(userId)}`) localStorage.removeItem(key);
  } catch { /* Storage is optional. */ }
  if (typeof window !== 'undefined') window.dispatchEvent(new Event(scopeEvent));
}
export function activateDeviceUser(userId: string | null) {
  try {
    const old = localStorage.getItem(ownerKey);
    if (old && old !== userId) clearDeviceResults(old);
    if (userId) localStorage.setItem(ownerKey,userId); else localStorage.removeItem(ownerKey);
  } catch { /* Auth still works when device storage is disabled. */ }
}
export function invalidatePortfolioResults() {
  try { const userId = localStorage.getItem(ownerKey); if (userId) clearDeviceResults(userId); } catch { /* Optional storage. */ }
}
export function syncPortfolio(userId: string, portfolios: unknown): string | null {
  if (!Array.isArray(portfolios)) throw new Error('Invalid portfolio metadata');
  const defaults = portfolios.filter(p => p && p.is_default === true);
  const selected = defaults.length === 1 ? defaults[0] : null;
  if(selected && (typeof selected.id !== 'string' || typeof selected.updated_at !== 'string' || !selected.payload || typeof selected.payload !== 'object')) throw new Error('Incomplete portfolio metadata');
  const next = selected ? JSON.stringify([selected.id, selected.updated_at]) : 'none';
  if (activePortfolio(userId) !== next) clearDeviceResults(userId);
  try { localStorage.setItem(userPrefix(userId)+'portfolio',next); } catch { /* Optional storage. */ }
  window.dispatchEvent(new Event(scopeEvent));
  return next;
}
export const resultKey = (scope: ResultScope, section: string) => userPrefix(scope.userId) + encodeURIComponent(scope.portfolio) + ':' + section;
export function readDeviceResult<T>(scope: ResultScope | undefined, section: string, valid: (value: unknown) => boolean): DeviceResult<T> | null {
  if (!scope || typeof window === 'undefined') return null;
  try {
    const value = JSON.parse(localStorage.getItem(resultKey(scope,section)) ?? 'null');
    return value?.version === 1 && typeof value.loadedAt === 'string' && Number.isFinite(new Date(value.loadedAt).getTime()) && valid(value.result) ? value : null;
  } catch { return null; }
}
export function saveDeviceResult<T>(scope: ResultScope | undefined, section: string, result: T, valid: (value: unknown) => boolean): string | null {
  if (!valid(result)) return null;
  const loadedAt = new Date().toISOString();
  if (scope && activePortfolio(scope.userId) === scope.portfolio) {
    try { localStorage.setItem(resultKey(scope,section),JSON.stringify({version:1,loadedAt,result})); } catch { /* Retain the successful display. */ }
  }
  return loadedAt;
}
