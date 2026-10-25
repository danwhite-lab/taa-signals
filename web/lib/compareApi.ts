import text from "../content/compare.json";
import { authorizedResponse, ApiError } from "./api";

export async function compareRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try { response = await authorizedResponse(path, init); }
  catch (error) { throw new Error(error instanceof ApiError && error.status === 401 ? text.unauthorized : text.requestError); }
  if ([408, 504, 524].includes(response.status)) throw new Error(text.timeout);
  if (!response.ok) {
    if (response.status === 401) throw new Error(text.unauthorized);
    const body = await response.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : Array.isArray(body?.detail)
      ? body.detail.map((issue: {msg?:unknown})=>typeof issue?.msg === "string" ? issue.msg : "").filter(Boolean).join("; ") : "";
    throw new Error(detail || text.requestError);
  }
  return response.json() as Promise<T>;
}

export async function compareDownload(key: string, kind: string, filename: string) {
  const response = await authorizedResponse(`/api/compare/download?key=${encodeURIComponent(key)}&kind=${encodeURIComponent(kind)}`);
  if (!response.ok) throw new Error(text.downloadError);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a"); link.href = url; link.download = filename;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
