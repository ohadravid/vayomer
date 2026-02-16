import { Glob } from "bun";
import { readFileSync } from "node:fs";
import path from "node:path";

type ChapterPayload = {
  items?: unknown;
};

export function loadPuzzleChapterPayloadsJson(relativeDirPath: string): string {
  const absoluteDirPath = path.resolve(process.cwd(), relativeDirPath);
  const glob = new Glob("*.json");
  const files = [...glob.scanSync({ cwd: absoluteDirPath })].sort((a, b) => a.localeCompare(b));

  const payloads = files.map((file) => {
    const raw = readFileSync(path.join(absoluteDirPath, file), "utf8");
    return JSON.parse(raw) as ChapterPayload;
  });

  return JSON.stringify(payloads);
}
