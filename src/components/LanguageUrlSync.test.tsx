import { afterEach, describe, expect, it } from "vitest";
import React from "react";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { JSDOM } from "jsdom";
import { MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { LanguageUrlSync, buildLocationWithLanguage, resolveLanguageFromExternalState, type UrlSyncI18n } from "./LanguageUrlSync";
import { LANGUAGE_STORAGE_KEY } from "../lib/language";

const dom = new JSDOM("<!doctype html><html><body></body></html>", { url: "https://example.test/" });
const { window } = dom;

Object.assign(globalThis, {
  window,
  document: window.document,
  HTMLElement: window.HTMLElement,
  Event: window.Event,
  StorageEvent: window.StorageEvent,
});

const mockT = (() => "") as unknown as never;

function createI18n(initialLanguage: "en" | "he", { deferLanguageChange = false }: { deferLanguageChange?: boolean } = {}) {
  let language = initialLanguage;
  let pendingLanguage: "en" | "he" | null = null;
  let resolvePendingChange: (() => void) | null = null;
  const calls: string[] = [];

  return {
    i18n: {
      get language() {
        return language;
      },
      get resolvedLanguage() {
        return language;
      },
      changeLanguage(next?: string) {
        if (!next) return Promise.resolve(mockT);
        calls.push(next);
        if (deferLanguageChange) {
          pendingLanguage = next as "en" | "he";
          return new Promise((resolve) => {
            resolvePendingChange = () => resolve(mockT);
          });
        }
        language = next as "en" | "he";
        return Promise.resolve(mockT);
      },
    } as unknown as UrlSyncI18n,
    calls,
    resolvePendingLanguageChange() {
      if (!pendingLanguage) return;
      language = pendingLanguage;
      pendingLanguage = null;
      resolvePendingChange?.();
      resolvePendingChange = null;
    },
  };
}

function LocationEcho() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}${location.hash}`}</output>;
}

function RouterControl() {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => void navigate("/")}>
      go-home
    </button>
  );
}

function renderSync(i18n: UrlSyncI18n, lang: "en" | "he", initialEntry: string) {
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <LanguageUrlSync i18n={i18n} lang={lang} />
      <LocationEcho />
      <RouterControl />
    </MemoryRouter>
  );
}

async function flushMicrotasks() {
  await Promise.resolve();
}

afterEach(() => {
  cleanup();
  window.localStorage.clear();
});

describe("buildLocationWithLanguage", () => {
  it("keeps unrelated params and adds english", () => {
    expect(buildLocationWithLanguage("/", "?easy=1", "", "en")).toBe("/?easy=1&lng=en");
  });

  it("removes language parameter for default Hebrew", () => {
    expect(buildLocationWithLanguage("/", "?easy=1&lng=en", "#v5", "he")).toBe("/?easy=1#v5");
  });
});

describe("resolveLanguageFromExternalState", () => {
  it("prefers URL language over storage", () => {
    expect(resolveLanguageFromExternalState("?lng=en", "he")).toBe("en");
  });

  it("falls back to storage language when URL is missing", () => {
    expect(resolveLanguageFromExternalState("", "en")).toBe("en");
  });
});

describe("LanguageUrlSync", () => {
  it("renders null and syncs current language into the router location", async () => {
    const { i18n } = createI18n("en");
    const view = renderSync(i18n, "en", "/?easy=1");

    await act(async () => {
      await flushMicrotasks();
    });

    expect(view.getByTestId("location")).toHaveTextContent("/?easy=1&lng=en");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
  });

  it("updates the location when the current language prop changes", async () => {
    const { i18n } = createI18n("he");
    const view = renderSync(i18n, "he", "/");

    await act(async () => {
      await flushMicrotasks();
    });

    expect(view.getByTestId("location")).toHaveTextContent("/");

    await act(async () => {
      await i18n.changeLanguage("en");
      view.rerender(
        <MemoryRouter initialEntries={["/"]}>
          <LanguageUrlSync i18n={i18n} lang="en" />
          <LocationEcho />
          <RouterControl />
        </MemoryRouter>
      );
      await flushMicrotasks();
    });

    expect(view.getByTestId("location")).toHaveTextContent("/?lng=en");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
  });

  it("does not overwrite an explicit URL language during boot", async () => {
    const { i18n, calls, resolvePendingLanguageChange } = createI18n("he", { deferLanguageChange: true });
    const view = renderSync(i18n, "he", "/?lng=en");

    expect(calls).toEqual(["en"]);
    expect(view.getByTestId("location")).toHaveTextContent("/?lng=en");

    await act(async () => {
      resolvePendingLanguageChange();
      await flushMicrotasks();
      view.rerender(
        <MemoryRouter initialEntries={["/?lng=en"]}>
          <LanguageUrlSync i18n={i18n} lang="en" />
          <LocationEcho />
          <RouterControl />
        </MemoryRouter>
      );
    });

    expect(view.getByTestId("location")).toHaveTextContent("/?lng=en");
    expect(window.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
  });

  it("reacts when router navigation removes the language query", async () => {
    const { i18n, calls } = createI18n("en");
    const view = renderSync(i18n, "en", "/?lng=en");

    await act(async () => {
      await flushMicrotasks();
    });

    fireEvent.click(view.getByRole("button", { name: "go-home" }));

    await act(async () => {
      await flushMicrotasks();
    });

    expect(view.getByTestId("location")).toHaveTextContent("/");
    expect(calls).toContain("he");
  });
});
