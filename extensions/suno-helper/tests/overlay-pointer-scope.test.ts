// @vitest-environment jsdom

import { describe, expect, it } from "vitest";

import { scopeOverlayPointerEvents } from "../lib/overlay-pointer-scope";

describe("scopeOverlayPointerEvents", () => {
  it("host と shadow 内コンテナを透過にする", () => {
    const host = document.createElement("suno-helper-overlay");
    const shadow = host.attachShadow({ mode: "open" });
    const html = document.createElement("html");
    const body = document.createElement("body");
    html.appendChild(body);
    shadow.appendChild(html);

    scopeOverlayPointerEvents(host, body);

    expect(host.style.pointerEvents).toBe("none");
    expect(body.style.pointerEvents).toBe("none");
    expect(html.style.pointerEvents).toBe("none");
  });

  it("コンテナの親が無くても例外にならない", () => {
    const host = document.createElement("suno-helper-overlay");
    const body = document.createElement("body");

    expect(() => scopeOverlayPointerEvents(host, body)).not.toThrow();
    expect(host.style.pointerEvents).toBe("none");
    expect(body.style.pointerEvents).toBe("none");
  });

  it("引数が未定義でも例外にならない", () => {
    expect(() => scopeOverlayPointerEvents(undefined, undefined)).not.toThrow();
  });
});
