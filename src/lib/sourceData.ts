import type { SourceChapterPayload, SourceIndexPayload } from "./sourceReader";

const SOURCE_BASE_URL = "/source";

let sourceIndexPromise: Promise<SourceIndexPayload> | null = null;
const sourceChapterCache = new Map<string, Promise<SourceChapterPayload>>();

async function loadJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to fetch ${path}: ${response.status} ${response.statusText}`);
  }
  return (await response.json()) as T;
}

export function loadSourceIndex(): Promise<SourceIndexPayload> {
  if (sourceIndexPromise) return sourceIndexPromise;

  sourceIndexPromise = loadJson<SourceIndexPayload>(`${SOURCE_BASE_URL}/index.json`);
  return sourceIndexPromise;
}

export function loadSourceChapter(bookSlug: string, chapter: number): Promise<SourceChapterPayload> {
  const key = `${bookSlug}:${chapter}`;
  const cached = sourceChapterCache.get(key);
  if (cached) return cached;

  const promise = loadJson<SourceChapterPayload>(`${SOURCE_BASE_URL}/${bookSlug}/chapter${chapter}.json`);
  sourceChapterCache.set(key, promise);
  return promise;
}

export function resetSourceDataCache(): void {
  sourceIndexPromise = null;
  sourceChapterCache.clear();
}
