import { execFile as execFileCallback } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { promisify } from "node:util";
import { afterEach, describe, expect, it } from "vitest";
import { extractSourceReaderAssets } from "../scripts/prepare_quote_assets";

const execFile = promisify(execFileCallback);
const tempRoots: string[] = [];

afterEach(async () => {
  await Promise.all(tempRoots.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

async function createTempRoot(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "vayomer-source-assets-"));
  tempRoots.push(root);
  return root;
}

describe("extractSourceReaderAssets", () => {
  it("extracts the generated source reader zip into the public output directory", async () => {
    const root = await createTempRoot();
    const sourceDir = path.join(root, "zip-source");
    const archivePath = path.join(root, "source.zip");
    const outputRoot = path.join(root, "public", "source");

    await mkdir(path.join(sourceDir, "exodus"), { recursive: true });
    await writeFile(path.join(sourceDir, "index.json"), JSON.stringify({ books: [{ slug: "exodus", chapter_count: 40 }] }));
    await writeFile(path.join(sourceDir, "exodus", "chapter33.json"), JSON.stringify({ chapter: 33 }));

    await execFile("zip", ["-qr", archivePath, "."], { cwd: sourceDir });
    await extractSourceReaderAssets(archivePath, outputRoot);

    expect(JSON.parse(await readFile(path.join(outputRoot, "index.json"), "utf8"))).toEqual({
      books: [{ slug: "exodus", chapter_count: 40 }],
    });
    expect(JSON.parse(await readFile(path.join(outputRoot, "exodus", "chapter33.json"), "utf8"))).toEqual({ chapter: 33 });
  });
});
