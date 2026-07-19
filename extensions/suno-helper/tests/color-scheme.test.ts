// @vitest-environment jsdom

import { watchColorScheme } from "@youtube-automation/ui";
import { afterEach, describe, expect, it, vi } from "vitest";

interface MatchMediaMock {
  emit(matches: boolean): void;
  mediaQuery: MediaQueryList;
}

function mockMatchMedia(initialMatches: boolean): MatchMediaMock {
  let listener: ((event: MediaQueryListEvent) => void) | undefined;
  const mediaQuery = {
    matches: initialMatches,
    addEventListener: vi.fn(
      (_type: "change", nextListener: (event: MediaQueryListEvent) => void) => {
        listener = nextListener;
      }
    ),
    removeEventListener: vi.fn(
      (
        _type: "change",
        removedListener: (event: MediaQueryListEvent) => void
      ) => {
        if (listener === removedListener) {
          listener = undefined;
        }
      }
    ),
  } as unknown as MediaQueryList;

  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => mediaQuery)
  );

  return {
    mediaQuery,
    emit(matches) {
      listener?.({ matches } as MediaQueryListEvent);
    },
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("watchColorScheme", () => {
  it("adds dark for an initially dark OS theme", () => {
    mockMatchMedia(true);
    const target = document.createElement("div");

    watchColorScheme(target);

    expect(target.classList.contains("dark")).toBe(true);
  });

  it("removes dark for an initially light OS theme", () => {
    mockMatchMedia(false);
    const target = document.createElement("div");
    target.classList.add("dark");

    watchColorScheme(target);

    expect(target.classList.contains("dark")).toBe(false);
  });

  it("follows OS theme changes without reloading", () => {
    const matchMedia = mockMatchMedia(false);
    const target = document.createElement("div");
    watchColorScheme(target);

    matchMedia.emit(true);
    expect(target.classList.contains("dark")).toBe(true);

    matchMedia.emit(false);
    expect(target.classList.contains("dark")).toBe(false);
  });

  it("removes the change listener during cleanup", () => {
    const { mediaQuery } = mockMatchMedia(false);
    const cleanup = watchColorScheme(document.createElement("div"));

    cleanup();

    expect(mediaQuery.removeEventListener).toHaveBeenCalledOnce();
    expect(mediaQuery.removeEventListener).toHaveBeenCalledWith(
      "change",
      expect.any(Function)
    );
  });
});
