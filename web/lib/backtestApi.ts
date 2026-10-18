import content from "../content/backtest.json";
import { authorizedResponse, ApiError } from "./api";

export async function backtestRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try { response = await authorizedResponse(path, init); }
  catch (error) { throw new Error(error instanceof ApiError && error.status === 401 ? content.unauthorized : content.requestError); }
  if ([408, 504, 524].includes(response.status)) throw new Error(content.timeout);
  if (!response.ok) {
    if (response.status === 401) throw new Error(content.unauthorized);
    if (response.status === 400) {
      const body = await response.json().catch(() => null);
      throw new Error(typeof body?.detail === "string" ? body.detail : content.validationError);
    }
    throw new Error(content.requestError);
  }
  return response.json() as Promise<T>;
}

export async function backtestDownload(key: string, kind: string, filename: string) {
  const response = await authorizedResponse(`/api/backtest/download?key=${encodeURIComponent(key)}&kind=${encodeURIComponent(kind)}`);
  if (!response.ok) throw new Error(content.downloadError);
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a"); link.href = url; link.download = filename;
  document.body.appendChild(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}
