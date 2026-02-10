#!/usr/bin/env bun

import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const QUOTES_DIR = path.join(ROOT, "data", "quotes");
const OUT_PATH = path.join(ROOT, "data", "daily.json");

async function main() {
  const names = await readdir(QUOTES_DIR);
  const files = names.filter((name) => name.endsWith(".json")).sort();

  const items = [];
  for (const name of files) {
    const fullPath = path.join(QUOTES_DIR, name);
    const raw = await readFile(fullPath, "utf8");
    const data = JSON.parse(raw);
    if (!Array.isArray(data.items)) {
      throw new Error(`Invalid items payload in ${fullPath}`);
    }
    items.push(...data.items);
  }

  await writeFile(OUT_PATH, `${JSON.stringify({ items }, null, 2)}\n`, "utf8");
  console.log(`Wrote ${OUT_PATH} with ${items.length} items from ${files.length} files`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
