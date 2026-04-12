import { afterEach, describe, expect, it, vi } from "vitest";
import React, { StrictMode } from "react";
import { cleanup, render } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { JSDOM } from "jsdom";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { resources } from "../i18n";
import { resetSourceDataCache } from "../lib/sourceData";
import { ReadBookPage, ReadBooksPage, ReadChapterPage } from "./SourceReader";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://example.test/" });
const { window } = dom;

Object.assign(globalThis, {
  window,
  document: window.document,
  HTMLElement: window.HTMLElement,
  Event: window.Event,
  PopStateEvent: window.PopStateEvent,
  requestAnimationFrame: (cb: FrameRequestCallback) => setTimeout(() => cb(Date.now()), 0),
  cancelAnimationFrame: (id: number) => clearTimeout(id),
});

function createI18n() {
  const i18n = createInstance();
  void i18n.use(initReactI18next).init({
    resources,
    lng: "en",
    fallbackLng: "en",
    supportedLngs: ["en", "he"],
    load: "languageOnly",
    interpolation: { escapeValue: false },
    initImmediate: false,
  });
  return i18n;
}

function renderReader(initialEntry: string) {
  return render(
    <I18nextProvider i18n={createI18n()}>
      <StrictMode>
        <MemoryRouter initialEntries={[initialEntry]}>
          <Routes>
            <Route path="/read" element={<ReadBooksPage />} />
            <Route path="/read/:bookSlug" element={<ReadBookPage />} />
            <Route path="/read/:bookSlug/:chapter" element={<ReadChapterPage />} />
          </Routes>
        </MemoryRouter>
      </StrictMode>
    </I18nextProvider>
  );
}

afterEach(() => {
  cleanup();
  resetSourceDataCache();
  vi.restoreAllMocks();
  window.history.replaceState({}, "", "/");
});

describe("SourceReader", () => {
  it("renders the source book list from the generated index", async () => {
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      value: vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url === "/source/index.json") {
          return new Response(
            JSON.stringify({
              books: [{ code: "EXO", slug: "exodus", en: "Exodus", he: "שמות", chapter_count: 40 }],
            }),
            { status: 200 }
          );
        }
        throw new Error(`unexpected fetch ${url}`);
      }),
    });

    const view = renderReader("/read?lng=en");

    const link = await view.findByRole("link", { name: /Exodus/i });
    expect(link).toHaveAttribute("href", "/read/exodus?lng=en");
    expect(view.getByText("שמות")).toBeInTheDocument();
  });

  it("renders chapter links from chapter_count", async () => {
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      value: vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url === "/source/index.json") {
          return new Response(
            JSON.stringify({
              books: [{ code: "EXO", slug: "exodus", en: "Exodus", he: "שמות", chapter_count: 3 }],
            }),
            { status: 200 }
          );
        }
        throw new Error(`unexpected fetch ${url}`);
      }),
    });

    const view = renderReader("/read/exodus?lng=en");

    expect(await view.findByRole("link", { name: "Chapter 1" })).toHaveAttribute("href", "/read/exodus/1?lng=en");
    expect(view.getByRole("link", { name: "Chapter 3" })).toHaveAttribute("href", "/read/exodus/3?lng=en");
  });

  it("renders verses with hebrew on the left and canonical verse links", async () => {
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      value: vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url === "/source/index.json") {
          return new Response(
            JSON.stringify({
              books: [
                { code: "GEN", slug: "genesis", en: "Genesis", he: "בראשית", chapter_count: 50 },
                { code: "EXO", slug: "exodus", en: "Exodus", he: "שמות", chapter_count: 40 },
              ],
            }),
            { status: 200 }
          );
        }
        if (url === "/source/exodus/chapter33.json") {
          return new Response(
            JSON.stringify({
              book_code: "EXO",
              slug: "exodus",
              book: "Exodus",
              book_he: "שמות",
              chapter: 33,
              verses: [{ verse: 5, en: "For the LORD had said unto Moses.", he: "וַיֹּאמֶר יְהוָה אֶל־מֹשֶׁה" }],
            }),
            { status: 200 }
          );
        }
        throw new Error(`unexpected fetch ${url}`);
      }),
    });

    const view = renderReader("/read/exodus/33?lng=en#v5");

    expect(await view.findByText("For the LORD had said unto Moses.")).toBeInTheDocument();
    const verse = document.getElementById("v5");
    expect(verse).toBeInTheDocument();
    expect(verse?.children[1]).toHaveClass("reader-verse-text-he");
    expect(verse?.children[2]).toHaveClass("reader-verse-text-en");
    expect(view.getByRole("link", { name: "5" })).toHaveAttribute("href", "/read/exodus/33?lng=en#v5");
    expect(view.getAllByRole("link", { name: "Previous chapter" })[0]).toHaveAttribute("href", "/read/exodus/32?lng=en");
    expect(view.getAllByRole("link", { name: "Next chapter" })[0]).toHaveAttribute("href", "/read/exodus/34?lng=en");
  });

  it("navigates across books at chapter boundaries", async () => {
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      value: vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url === "/source/index.json") {
          return new Response(
            JSON.stringify({
              books: [
                { code: "GEN", slug: "genesis", en: "Genesis", he: "בראשית", chapter_count: 50 },
                { code: "EXO", slug: "exodus", en: "Exodus", he: "שמות", chapter_count: 40 },
              ],
            }),
            { status: 200 }
          );
        }
        if (url === "/source/exodus/chapter1.json") {
          return new Response(
            JSON.stringify({
              book_code: "EXO",
              slug: "exodus",
              book: "Exodus",
              book_he: "שמות",
              chapter: 1,
              verses: [{ verse: 1, en: "Now these are the names.", he: "וְאֵלֶּה שְׁמוֹת" }],
            }),
            { status: 200 }
          );
        }
        throw new Error(`unexpected fetch ${url}`);
      }),
    });

    const view = renderReader("/read/exodus/1?lng=en");

    expect(await view.findByText("Now these are the names.")).toBeInTheDocument();
    expect(view.getAllByRole("link", { name: "Previous chapter" })[0]).toHaveAttribute("href", "/read/genesis/50?lng=en");
    expect(view.getAllByRole("link", { name: "Next chapter" })[0]).toHaveAttribute("href", "/read/exodus/2?lng=en");
  });
});
