import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { afterEach, describe, expect, it } from "vitest";
import { mirrorSourceReaderAssets } from "../scripts/prepare_quote_assets";

const tempRoots: string[] = [];

afterEach(async () => {
  await Promise.all(tempRoots.splice(0).map((dir) => rm(dir, { recursive: true, force: true })));
});

async function createTempRoot(): Promise<string> {
  const root = await mkdtemp(path.join(os.tmpdir(), "vayomer-source-assets-"));
  tempRoots.push(root);
  return root;
}

describe("mirrorSourceReaderAssets", () => {
  it("copies the generated source reader tree into the public output directory", async () => {
    const root = await createTempRoot();
    const inputRoot = path.join(root, "source");
    const outputRoot = path.join(root, "public", "source");
    await mkdir(path.join(inputRoot, "exodus"), { recursive: true });
    await writeFile(path.join(inputRoot, "index.json"), JSON.stringify({ books: [{ slug: "exodus" }] }));
    await writeFile(path.join(inputRoot, "exodus", "chapter33.json"), JSON.stringify({ chapter: 33 }));

    await mirrorSourceReaderAssets(inputRoot, outputRoot);

    expect(JSON.parse(await readFile(path.join(outputRoot, "index.json"), "utf8"))).toEqual({ books: [{ slug: "exodus" }] });
    expect(JSON.parse(await readFile(path.join(outputRoot, "exodus", "chapter33.json"), "utf8"))).toEqual({ chapter: 33 });
  });
});
