#!/usr/bin/env bun

import { readdir, readFile, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const QUOTES_DIR = path.join(ROOT, "data", "quotes");
const DAILY_OUT_PATH = path.join(ROOT, "data", "daily.json");
const OPTIONS_OUT_PATH = path.join(ROOT, "data", "options.json");
const OT_BOOKS_EN_ORDER = [
  "Genesis",
  "Exodus",
  "Leviticus",
  "Numbers",
  "Deuteronomy",
  "Joshua",
  "Judges",
  "Ruth",
  "1 Samuel",
  "2 Samuel",
  "1 Kings",
  "2 Kings",
  "1 Chronicles",
  "2 Chronicles",
  "Ezra",
  "Nehemiah",
  "Esther",
  "Job",
  "Psalms",
  "Proverbs",
  "Ecclesiastes",
  "Song of Songs",
  "Isaiah",
  "Jeremiah",
  "Lamentations",
  "Ezekiel",
  "Daniel",
  "Hosea",
  "Joel",
  "Amos",
  "Obadiah",
  "Jonah",
  "Micah",
  "Nahum",
  "Habakkuk",
  "Zephaniah",
  "Haggai",
  "Zechariah",
  "Malachi",
];
const BOOK_ORDER_INDEX = new Map(OT_BOOKS_EN_ORDER.map((book, idx) => [book, idx]));

function pushUnique(list, value) {
  if (typeof value !== "string") return;
  const trimmed = value.trim();
  if (!trimmed) return;
  if (!list.includes(trimmed)) {
    list.push(trimmed);
  }
}

function createBookOptionSet(enBook, heBook) {
  return {
    book: { en: enBook, he: heBook },
    speaker: { en: [], he: [] },
    listener: { en: [], he: [] },
    portion: { en: [], he: [] },
  };
}

async function main() {
  const names = await readdir(QUOTES_DIR);
  const files = names.filter((name) => name.endsWith(".json")).sort();

  const items = [];
  const byBook = new Map();
  for (const name of files) {
    const fullPath = path.join(QUOTES_DIR, name);
    const raw = await readFile(fullPath, "utf8");
    const data = JSON.parse(raw);
    if (!Array.isArray(data.items)) {
      throw new Error(`Invalid items payload in ${fullPath}`);
    }

    for (const item of data.items) {
      items.push(item);

      const enBook = item?.en?.book;
      const heBook = item?.he?.book;
      if (typeof enBook !== "string" || typeof heBook !== "string") {
        continue;
      }

      const bookKey = `${enBook}\u0000${heBook}`;
      if (!byBook.has(bookKey)) {
        byBook.set(bookKey, createBookOptionSet(enBook, heBook));
      }
      const optionSet = byBook.get(bookKey);

      pushUnique(optionSet.speaker.en, item?.en?.speaker);
      pushUnique(optionSet.speaker.he, item?.he?.speaker);
      pushUnique(optionSet.listener.en, item?.en?.listener);
      pushUnique(optionSet.listener.he, item?.he?.listener);
      pushUnique(optionSet.portion.en, item?.portion?.en);
      pushUnique(optionSet.portion.he, item?.portion?.he);
    }
  }

  const books = [...byBook.values()].sort((a, b) => {
    const aIdx = BOOK_ORDER_INDEX.get(a.book.en);
    const bIdx = BOOK_ORDER_INDEX.get(b.book.en);
    if (aIdx !== undefined && bIdx !== undefined) return aIdx - bIdx;
    if (aIdx !== undefined) return -1;
    if (bIdx !== undefined) return 1;
    return a.book.en.localeCompare(b.book.en);
  });

  await writeFile(DAILY_OUT_PATH, `${JSON.stringify({ items }, null, 2)}\n`, "utf8");
  await writeFile(OPTIONS_OUT_PATH, `${JSON.stringify({ books }, null, 2)}\n`, "utf8");

  console.log(`Wrote ${DAILY_OUT_PATH} with ${items.length} items from ${files.length} files`);
  console.log(`Wrote ${OPTIONS_OUT_PATH} with ${books.length} book option sets`);
}

main().catch((error) => {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
});
