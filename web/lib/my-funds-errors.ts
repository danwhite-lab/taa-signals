import words from "../content/my-funds.json";

export function registryMessage(value: unknown): string | undefined {
  return value === words.registryUnavailable || value === words.rejectedRows ? value : undefined;
}

export async function registryResponseMessage(response: Response) {
  if (response.status !== 503) return undefined;
  const body = await response.json().catch(() => null);
  return registryMessage(body?.detail);
}
