import { promises as fs } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

type PuzzleManifestEntry = {
  id: string;
  file: string;
};

type PuzzleChapterPayload = {
  items?: Array<{ id?: string }>;
};

const ROOT = process.cwd();
const SOURCES = [
  { key: "options", dir: path.join(ROOT, "data", "processed", "generated_options") },
  { key: "manual", dir: path.join(ROOT, "data", "manual_quotes") },
] as const;
const OUTPUT_ROOT = path.join(ROOT, "public", "quotes");
const MANIFEST_SOURCE_PATH = path.join(ROOT, "src", "lib", "puzzleManifest.json");
export const DAILY_ORDER_SEED = 20220805;

function parsePayloadItems(payload: PuzzleChapterPayload): Array<{ id?: string }> {
  return Array.isArray(payload.items) ? payload.items : [];
}

async function listJsonFiles(dir: string): Promise<string[]> {
  const entries = await fs.readdir(dir, { withFileTypes: true });
  return entries
    .filter((entry) => entry.isFile() && entry.name.endsWith(".json"))
    .map((entry) => entry.name)
    .sort((left, right) => left.localeCompare(right));
}

export function fnv1a(str: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < str.length; i += 1) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

export function compareDailyOrderIds(leftId: string, rightId: string): number {
  const leftHash = fnv1a(`${DAILY_ORDER_SEED}:${leftId}`);
  const rightHash = fnv1a(`${DAILY_ORDER_SEED}:${rightId}`);

  if (leftHash !== rightHash) {
    return leftHash - rightHash;
  }

  return leftId.localeCompare(rightId);
}

async function main(): Promise<void> {
  await fs.rm(OUTPUT_ROOT, { recursive: true, force: true });
  await fs.mkdir(OUTPUT_ROOT, { recursive: true });

  const manifest: PuzzleManifestEntry[] = [];
  const seenIds = new Set<string>();

  for (const source of SOURCES) {
    const sourceFiles = await listJsonFiles(source.dir);
    const outputDir = path.join(OUTPUT_ROOT, source.key);
    await fs.mkdir(outputDir, { recursive: true });

    for (const fileName of sourceFiles) {
      const inputPath = path.join(source.dir, fileName);
      const outputPath = path.join(outputDir, fileName);
      const raw = await fs.readFile(inputPath, "utf8");
      const payload = JSON.parse(raw) as PuzzleChapterPayload;

      for (const item of parsePayloadItems(payload)) {
        const id = typeof item.id === "string" ? item.id.trim() : "";
        if (!id) continue;
        if (seenIds.has(id)) continue;
        seenIds.add(id);
        manifest.push({
          id,
          file: `${source.key}/${fileName}`,
        });
      }

      await fs.writeFile(outputPath, JSON.stringify(payload));
    }
  }

  manifest.sort((left, right) => compareDailyOrderIds(left.id, right.id));

  await fs.writeFile(MANIFEST_SOURCE_PATH, JSON.stringify(manifest));
  console.log(`Prepared ${manifest.length} puzzle IDs and chapter mappings.`);
}

const entryHref = process.argv[1] ? pathToFileURL(path.resolve(process.argv[1])).href : null;

if (entryHref === import.meta.url) {
  void main().catch((error: unknown) => {
    console.error(error);
    process.exit(1);
  });
}
