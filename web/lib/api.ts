import { supabaseBrowser } from "./supabaseBrowser";

export class ApiError extends Error {
  constructor(public status: number, message: string) { super(message); }
}

export async function authorizedResponse(path: string, init: RequestInit = {}): Promise<Response> {
  const { data, error } = await supabaseBrowser().auth.getSession();
  if (error || !data.session) throw new ApiError(401, "Sign in to continue.");
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${data.session.access_token}`);
  if (init.body) headers.set("Content-Type", "application/json");
  let response: Response;
  try { response = await fetch(path, { ...init, headers, cache: "no-store" }); }
  catch { throw new ApiError(0, "Connection interrupted. Reload to confirm the saved state before retrying."); }
  return response;
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await authorizedResponse(path, init);
  if (!response.ok) {
    // Don't display raw proxy/SDK bodies: they may echo submitted private data.
    throw new ApiError(response.status,
      response.status === 409 ? "Changed on another device or save not confirmed. Reload before editing." :
      response.status === 401 ? "Your session expired. Sign in again." :
      response.status === 422 ? "Check the entered fields, name and portfolio JSON." :
      "The service could not confirm the request. Reload before retrying.");
  }
  return response.json() as Promise<T>;
}

export type Workspace = { payload: Record<string, unknown>; revision: number };
export type SavedPortfolio = { id: string; name: string; payload: Record<string, unknown>;
  is_default: boolean; updated_at: string };
