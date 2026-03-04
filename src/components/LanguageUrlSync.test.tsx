import { afterEach, describe, expect, it } from "vitest";
import { act, create, type ReactTestRenderer } from "react-test-renderer";
import { LanguageUrlSync, buildLocationWithLanguage, resolveLanguageFromExternalState, syncLanguageInUrl, type UrlSyncI18n } from "./LanguageUrlSync";
import { LANGUAGE_STORAGE_KEY } from "../lib/language";

type Listener = (event?: unknown) => void;

type FakeWindow = {
  location: { pathname: string; search: string; hash: string };
  history: { state: unknown; replaceState: (state: unknown, title: string, url: string) => void };
  localStorage: {
    getItem: (key: string) => string | null;
    setItem: (key: string, value: string) => void;
    removeItem: (key: string) => void;
  };
  addEventListener: (type: string, listener: Listener) => void;
  removeEventListener: (type: string, listener: Listener) => void;
  dispatchEvent: (type: string, event?: unknown) => void;
};

function createFakeWindow(initialPath: string): FakeWindow {
  const url = new URL(initialPath, "https://example.test");
  const storage = new Map<string, string>();
  const listeners = new Map<string, Set<Listener>>();

  const location = {
    pathname: url.pathname,
    search: url.search,
    hash: url.hash,
  };

  const history = {
    state: null as unknown,
    replaceState(nextState: unknown, _title: string, nextUrl: string) {
      history.state = nextState;
      const parsed = new URL(nextUrl, "https://example.test");
      location.pathname = parsed.pathname;
      location.search = parsed.search;
      location.hash = parsed.hash;
    },
  };

  return {
    location,
    history,
    localStorage: {
      getItem: (key: string) => storage.get(key) ?? null,
      setItem: (key: string, value: string) => void storage.set(key, value),
      removeItem: (key: string) => void storage.delete(key),
    },
    addEventListener(type, listener) {
      if (!listeners.has(type)) listeners.set(type, new Set());
      listeners.get(type)?.add(listener);
    },
    removeEventListener(type, listener) {
      listeners.get(type)?.delete(listener);
    },
    dispatchEvent(type, event) {
      for (const listener of listeners.get(type) ?? []) listener(event);
    },
  };
}

const mockT = (() => "") as unknown as never;

function createI18n(initialLanguage: "en" | "he", { deferLanguageChange = false }: { deferLanguageChange?: boolean } = {}) {
  let language = initialLanguage;
  let pendingLanguage: "en" | "he" | null = null;
  let resolvePendingChange: (() => void) | null = null;
  const calls: string[] = [];
  const listeners = new Set<() => void>();

  const emitLanguageChanged = () => {
    for (const listener of listeners) listener();
  };

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
        emitLanguageChanged();
        return Promise.resolve(mockT);
      },
      on(eventName: string, listener: () => void) {
        if (eventName === "languageChanged") listeners.add(listener);
        return this;
      },
      off(eventName: string, listener: () => void) {
        if (eventName === "languageChanged") listeners.delete(listener);
        return this;
      },
    } as unknown as UrlSyncI18n,
    calls,
    resolvePendingLanguageChange() {
      if (!pendingLanguage) return;
      language = pendingLanguage;
      pendingLanguage = null;
      emitLanguageChanged();
      resolvePendingChange?.();
      resolvePendingChange = null;
    },
  };
}

let root: ReactTestRenderer | null = null;

async function flushMicrotasks() {
  await Promise.resolve();
}

afterEach(() => {
  if (root) {
    act(() => root?.unmount());
    root = null;
  }
  delete (globalThis as { window?: unknown }).window;
});

describe("buildLocationWithLanguage", () => {
  it("keeps unrelated params and adds english", () => {
    expect(buildLocationWithLanguage("/", "?easy=1", "", "en")).toBe("/?easy=1&lng=en");
  });

  it("removes language parameter for default Hebrew", () => {
    expect(buildLocationWithLanguage("/", "?easy=1&lng=en", "#about", "he")).toBe("/?easy=1#about");
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

describe("syncLanguageInUrl", () => {
  it("writes shareable english URL", () => {
    const fakeWindow = createFakeWindow("/?easy=1");
    syncLanguageInUrl(fakeWindow, "en");
    expect(fakeWindow.location.search).toBe("?easy=1&lng=en");
  });

  it("removes query language for default Hebrew URL", () => {
    const fakeWindow = createFakeWindow("/?easy=1&lng=en");
    syncLanguageInUrl(fakeWindow, "he");
    expect(fakeWindow.location.search).toBe("?easy=1");
  });
});

describe("LanguageUrlSync", () => {
  it("renders null and syncs current language into URL", () => {
    const fakeWindow = createFakeWindow("/?easy=1");
    (globalThis as { window?: unknown }).window = fakeWindow;
    const { i18n } = createI18n("en");

    act(() => {
      root = create(<LanguageUrlSync i18n={i18n} lang="en" />);
    });

    expect(root?.toJSON()).toBeNull();
    expect(fakeWindow.location.search).toBe("?easy=1&lng=en");
  });

  it("reacts to languageChanged and updates URL", () => {
    const fakeWindow = createFakeWindow("/");
    (globalThis as { window?: unknown }).window = fakeWindow;
    const { i18n } = createI18n("he");

    act(() => {
      root = create(<LanguageUrlSync i18n={i18n} lang="he" />);
    });

    act(() => {
      void i18n.changeLanguage("en");
      root?.update(<LanguageUrlSync i18n={i18n} lang="en" />);
    });

    expect(fakeWindow.location.search).toBe("?lng=en");
    expect(fakeWindow.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
  });

  it("updates URL in both toggle directions on first click", () => {
    const fakeWindow = createFakeWindow("/");
    (globalThis as { window?: unknown }).window = fakeWindow;
    const { i18n } = createI18n("he");

    act(() => {
      root = create(<LanguageUrlSync i18n={i18n} lang="he" />);
    });

    act(() => {
      void i18n.changeLanguage("en");
      root?.update(<LanguageUrlSync i18n={i18n} lang="en" />);
    });
    expect(fakeWindow.location.search).toBe("?lng=en");

    act(() => {
      void i18n.changeLanguage("he");
      root?.update(<LanguageUrlSync i18n={i18n} lang="he" />);
    });
    expect(fakeWindow.location.search).toBe("");
  });

  it("does not overwrite explicit URL language during boot", async () => {
    const fakeWindow = createFakeWindow("/?lng=en");
    (globalThis as { window?: unknown }).window = fakeWindow;
    const { i18n, calls, resolvePendingLanguageChange } = createI18n("he", { deferLanguageChange: true });

    act(() => {
      root = create(<LanguageUrlSync i18n={i18n} lang="he" />);
    });

    expect(calls).toEqual(["en"]);
    expect(fakeWindow.location.search).toBe("?lng=en");

    await act(async () => {
      resolvePendingLanguageChange();
      await flushMicrotasks();
      root?.update(<LanguageUrlSync i18n={i18n} lang="en" />);
    });

    expect(fakeWindow.location.search).toBe("?lng=en");
    expect(fakeWindow.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("en");
  });

  it("popstate trusts URL and can navigate back to default Hebrew", () => {
    const fakeWindow = createFakeWindow("/?lng=en");
    fakeWindow.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    (globalThis as { window?: unknown }).window = fakeWindow;
    const { i18n, calls } = createI18n("en");

    act(() => {
      root = create(<LanguageUrlSync i18n={i18n} lang="en" />);
    });

    fakeWindow.location.search = "";
    act(() => {
      fakeWindow.dispatchEvent("popstate");
    });

    expect(calls).toEqual(["he"]);
    expect(fakeWindow.location.search).toBe("");
  });

  it("uses storage as fallback only during initial boot", async () => {
    const fakeWindow = createFakeWindow("/");
    fakeWindow.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    (globalThis as { window?: unknown }).window = fakeWindow;
    const { i18n, calls } = createI18n("he");

    await act(async () => {
      root = create(<LanguageUrlSync i18n={i18n} lang="he" />);
      await flushMicrotasks();
      root?.update(<LanguageUrlSync i18n={i18n} lang="en" />);
    });

    act(() => {
      fakeWindow.dispatchEvent("storage", { key: LANGUAGE_STORAGE_KEY, storageArea: fakeWindow.localStorage });
    });

    expect(calls).toEqual(["en"]);
    expect(fakeWindow.location.search).toBe("?lng=en");
  });

  it("updates from storage events after boot", () => {
    const fakeWindow = createFakeWindow("/");
    (globalThis as { window?: unknown }).window = fakeWindow;
    const { i18n, calls } = createI18n("he");

    act(() => {
      root = create(<LanguageUrlSync i18n={i18n} lang="he" />);
    });

    act(() => {
      fakeWindow.dispatchEvent("storage", {
        key: LANGUAGE_STORAGE_KEY,
        newValue: "en",
        storageArea: fakeWindow.localStorage,
      });
    });

    expect(calls).toEqual(["en"]);
  });

  it("replaces stale english storage with Hebrew when URL resolves to default Hebrew", async () => {
    const fakeWindow = createFakeWindow("/?lng=he");
    fakeWindow.localStorage.setItem(LANGUAGE_STORAGE_KEY, "en");
    (globalThis as { window?: unknown }).window = fakeWindow;
    const { i18n } = createI18n("en");

    await act(async () => {
      root = create(<LanguageUrlSync i18n={i18n} lang="en" />);
      await flushMicrotasks();
      root?.update(<LanguageUrlSync i18n={i18n} lang="he" />);
    });

    expect(fakeWindow.location.search).toBe("");
    expect(fakeWindow.localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe("he");
  });
});
