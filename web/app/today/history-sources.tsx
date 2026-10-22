import DisplayTable, { type DisplayTableValue } from "../../components/DisplayTable";
import text from "../../content/today.json";
import styles from "./history-sources.module.css";

export type HistorySleeve = { model: string; provenance?: DisplayTableValue; data_ranges?: DisplayTableValue | null };

export function historyTable(sleeves: HistorySleeve[]): DisplayTableValue {
  const labels = text.historyColumns;
  const rows: Record<string, unknown>[] = [];
  const seen = new Set<string>();
  for (const sleeve of sleeves) {
    if (!sleeve.provenance) continue;
    const assetColumn = sleeve.provenance.columns[0];
    for (const row of sleeve.provenance.rows) {
      const asset = row[assetColumn];
      if (typeof asset !== "string" || seen.has(asset)) continue;
      seen.add(asset);
      const ranges = sleeve.data_ranges;
      const range = ranges?.rows.find(candidate => candidate[ranges.columns[0]] === asset);
      rows.push({
        [labels.asset]: asset,
        [labels.source]: row.source ?? text.unavailable,
        [labels.first]: range?.first_available ?? text.unavailable,
        [labels.series]: row.price_field ?? text.unavailable,
        [labels.identifier]: row.identifier ?? text.unavailable,
        [labels.kind]: row.history_kind ?? text.unavailable,
        [labels.extension]: row.automatic_proxy_extension ?? text.unavailable,
      });
    }
  }
  return { columns: Object.values(labels), rows };
}

export function historyCsv(table: DisplayTableValue): string {
  const quote = (value: unknown) => `"${String(value ?? "").replaceAll('"', '""')}"`;
  return [table.columns, ...table.rows.map(row => table.columns.map(column => row[column]))]
    .map(row => row.map(quote).join(",")).join("\r\n") + "\r\n";
}

export default function HistorySources({ sleeves }: { sleeves: HistorySleeve[] }) {
  const table = historyTable(sleeves);
  if (!table.rows.length) return null;
  function download() {
    const url = URL.createObjectURL(new Blob([historyCsv(table)], { type: "text/csv;charset=utf-8" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "plain_holdings_history_sources.csv";
    link.click();
    URL.revokeObjectURL(url);
  }
  return <div className={styles.history}>
    <p className={styles.note}>{text.buyHoldNote}</p>
    <details><summary>{text.historySources}</summary>
      <DisplayTable value={table} label={text.historySources} />
      <button className="btn btn-secondary" type="button" onClick={download}>{text.historyCsv}</button>
    </details>
  </div>;
}
