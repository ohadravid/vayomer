import { Glob } from "bun";
import { existsSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

type ChapterPayload = {
  items?: unknown;
};

function loadPayloadsFromDir(relativeDirPath: string): ChapterPayload[] {
  const absoluteDirPath = path.resolve(process.cwd(), relativeDirPath);
  if (!existsSync(absoluteDirPath) || !statSync(absoluteDirPath).isDirectory()) return [];

  const glob = new Glob("*.json");
  const files = [...glob.scanSync({ cwd: absoluteDirPath })].sort((a, b) => a.localeCompare(b));
  return files.map((file) => {
    const raw = readFileSync(path.join(absoluteDirPath, file), "utf8");
    return JSON.parse(raw) as ChapterPayload;
  });
}

export function loadPuzzleChapterPayloadsJson(relativeDirPath: string | string[]): string {
  const dirPaths = Array.isArray(relativeDirPath) ? relativeDirPath : [relativeDirPath];
  const payloads = dirPaths.flatMap((dirPath) => loadPayloadsFromDir(dirPath));
  return JSON.stringify(payloads);
}
