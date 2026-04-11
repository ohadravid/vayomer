import { afterEach, describe, expect, it, vi } from "vitest";
import React, { StrictMode } from "react";
import { cleanup, render } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { JSDOM } from "jsdom";
import { createInstance } from "i18next";
import { I18nextProvider, initReactI18next } from "react-i18next";
import { resources } from "../i18n";
import { resetSourceDataCache } from "../lib/sourceData";
import { SourceReader } from "./SourceReader";

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

function renderReader(element: React.ReactNode) {
  return render(
    <I18nextProvider i18n={createI18n()}>
      <StrictMode>{element}</StrictMode>
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
              books: [{ code: "EXO", slug: "exodus", en: "Exodus", he: "שמות", chapters: [33] }],
            }),
            { status: 200 }
          );
        }
        throw new Error(`unexpected fetch ${url}`);
      }),
    });

    const view = renderReader(<SourceReader route={{ kind: "read-books" }} lang="en" />);

    const link = await view.findByRole("link", { name: /Exodus/i });
    expect(link).toHaveAttribute("href", "/read/exodus?lng=en");
    expect(view.getByText("שמות")).toBeInTheDocument();
  });

  it("renders chapter verses with side-by-side english and hebrew cells", async () => {
    window.history.replaceState({}, "", "/read/exodus/33#v5");
    Object.defineProperty(globalThis, "fetch", {
      configurable: true,
      value: vi.fn(async (input: string | URL) => {
        const url = String(input);
        if (url === "/source/index.json") {
          return new Response(
            JSON.stringify({
              books: [{ code: "EXO", slug: "exodus", en: "Exodus", he: "שמות", chapters: [33] }],
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

    const view = renderReader(<SourceReader route={{ kind: "read-chapter", bookSlug: "exodus", chapter: 33 }} lang="en" />);

    expect(await view.findByText("For the LORD had said unto Moses.")).toBeInTheDocument();
    expect(view.getByText("וַיֹּאמֶר יְהוָה אֶל־מֹשֶׁה")).toBeInTheDocument();
    expect(document.getElementById("v5")).toBeInTheDocument();
  });
});
