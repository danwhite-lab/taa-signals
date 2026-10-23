import text from "../content/rebalance.json";
import { authorizedResponse, ApiError, type Workspace } from "./api";

export class RebalanceError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function rebalanceRequest<T>(path: string, body?: unknown): Promise<T> {
  let response: Response;
  try { response = await authorizedResponse(path, body === undefined ? {} : { method: "POST", body: JSON.stringify(body) }); }
  catch (error) { throw new RebalanceError(error instanceof ApiError ? error.status : 0, text.error); }
  if (!response.ok) {
    const data = response.status === 400 ? await response.json().catch(() => null) : null;
    throw new RebalanceError(response.status, response.status === 409 ? text.paused : response.status === 401 ? text.unauthorized :
      typeof data?.detail === "string" ? data.detail : text.validation);
  }
  return response.json() as Promise<T>;
}

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") return "{" + Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => `${JSON.stringify(key)}:${canonical(item)}`).join(",") + "}";
  return JSON.stringify(value);
}

export type AllocationMode = "proportional" | "biggest_gap_first";

// Preference-only CAS patch. Never retry a possibly completed write.
export async function saveAllocationMode(revision: number, mode: AllocationMode): Promise<Workspace> {
  try {
    const response = await authorizedResponse("/api/workspace", { method: "PUT",
      body: JSON.stringify({ revision, payload: { rebalance_allocation_mode: mode } }) });
    if (response.status === 409) throw new RebalanceError(409, text.paused);
    if (response.status === 401) throw new RebalanceError(401, text.unauthorized);
    if (response.status === 422) {
      const data = await response.json().catch(() => null);
      throw new RebalanceError(422, typeof data?.detail === "string" ? data.detail : text.validation);
    }
    if (!response.ok) throw new Error();
    const saved = await response.json() as Workspace;
    if (saved.payload.rebalance_allocation_mode !== mode) throw new Error();
    return saved;
  } catch (failure) {
    if (failure instanceof RebalanceError) throw failure;
    throw new RebalanceError(409, text.allocationUncertain);
  }
}

// One PUT only. Read-back confirms an uncertain response, never repeats a buy.
export async function saveHoldings(revision: number, account: unknown): Promise<{ saved: Workspace | null; uncertain: boolean }> {
  try {
    const response = await authorizedResponse("/api/workspace", { method: "PUT", body: JSON.stringify({ revision, payload: { holdings_account: account } }) });
    if (response.status === 409) throw new RebalanceError(409, text.paused);
    if (!response.ok) throw new Error();
    const saved = await response.json() as Workspace;
    if (canonical(saved.payload.holdings_account) !== canonical(account)) throw new Error();
    return { saved, uncertain: false };
  } catch (error) {
    if (error instanceof RebalanceError && error.status === 409) throw error;
    try {
      const saved = await rebalanceRequest<Workspace>("/api/workspace");
      return { saved: canonical(saved.payload.holdings_account) === canonical(account) ? saved : null, uncertain: true };
    } catch { return { saved: null, uncertain: true }; }
  }
}
