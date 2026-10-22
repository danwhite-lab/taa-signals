export const byLabel = (a: string, b: string) => a.localeCompare(b, "en", { sensitivity: "base" });

export function savedOrder<T extends { name: string; is_default?: boolean }>(rows: T[]): T[] {
  return [...rows].sort((a, b) => Number(b.is_default === true) - Number(a.is_default === true) || byLabel(a.name, b.name));
}

// Compare's lightweight options omit default flags. Enrich only the listed
// IDs from the existing private library; never change the selectable universe.
export async function savedChoices<T extends { id: string; name: string; is_default?: boolean }>(rows: T[], read: () => Promise<{ id: string; is_default?: boolean }[]>): Promise<T[]> {
  if (rows.every(row => typeof row.is_default === "boolean")) return savedOrder(rows);
  try {
    const flags = new Map((await read()).map(row => [row.id, row.is_default === true]));
    return savedOrder(rows.map(row => ({ ...row, is_default: flags.get(row.id) ?? row.is_default })));
  } catch {
    // A failed optional metadata read must not hide the existing choices.
    return savedOrder(rows);
  }
}
