import { describe, expect, it } from "vitest";

import { acquireDomRunLock, releaseDomRunLock } from "../lib/dom-run-lock";

function createRoot(): HTMLElement {
  const attributes = new Map<string, string>();
  return {
    hasAttribute: (name: string) => attributes.has(name),
    getAttribute: (name: string) => attributes.get(name) ?? null,
    setAttribute: (name: string, value: string) => attributes.set(name, value),
    removeAttribute: (name: string) => attributes.delete(name),
  } as unknown as HTMLElement;
}

describe("DOM run lock", () => {
  it("最初の owner だけが取得でき、解放後は次の owner が取得できる", () => {
    const root = createRoot();

    expect(acquireDomRunLock(root, "first")).toBe(true);
    expect(acquireDomRunLock(root, "second")).toBe(false);

    releaseDomRunLock(root, "first");
    expect(acquireDomRunLock(root, "second")).toBe(true);
  });

  it("別 owner は lock を解放できない", () => {
    const root = createRoot();
    acquireDomRunLock(root, "first");

    releaseDomRunLock(root, "second");

    expect(acquireDomRunLock(root, "third")).toBe(false);
  });
});
