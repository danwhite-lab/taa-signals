import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

// Build-time only: invalidate device Health results when their calculator,
// loaders, mappings, policy or bundled reference data changes, not on every visit.
export function healthRevision(root: string): string {
  const files: string[] = [];
  function collect(relative: string, pythonOnly = false) {
    for (const entry of readdirSync(join(root, relative), { withFileTypes: true })) {
      const path = `${relative}/${entry.name}`;
      if (entry.isDirectory() && entry.name !== "__pycache__") collect(path, pythonOnly);
      else if (entry.isFile() && (!pythonOnly || entry.name.endsWith(".py"))) files.push(path);
    }
  }
  collect("server", true);
  collect("src/haa", true);
  collect("data/deep_history");
  files.push("data/usd_equivalents.json", "web/content/strategy-health.json", "web/content/usd-equivalents.json");
  const hash = createHash("sha256");
  for (const path of files.sort()) {
    const contents = readFileSync(join(root, path));
    hash.update(JSON.stringify([path, contents.length]));
    hash.update(contents);
  }
  return hash.digest("hex");
}
