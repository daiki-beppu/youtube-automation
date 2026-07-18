import { afterEach, describe, expect, it, vi } from "vitest";

type Handler = (message: { data: Record<string, string> }) => unknown;

async function loadContent() {
  vi.resetModules();
  const handlers = new Map<string, Handler>();
  const checkServerCompatibility = vi.fn(async () => ({
    status: "compatible" as const,
    serverVersion: "0.1.0",
    minExtensionVersion: "0.1.0",
    extensionVersion: "0.1.0",
  }));

  vi.stubGlobal("defineContentScript", (definition: { main: () => void }) => {
    definition.main();
    return definition;
  });
  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((name: string, handler: Handler) => {
      handlers.set(name, handler);
      return vi.fn();
    }),
    sendMessage: vi.fn(async () => undefined),
  }));
  vi.doMock("../../shared/api", () => ({ checkServerCompatibility }));

  await import("../entrypoints/content");
  return { checkServerCompatibility, handlers };
}

afterEach(() => {
  vi.doUnmock("../lib/messaging");
  vi.doUnmock("../../shared/api");
  vi.unstubAllGlobals();
});

describe("community-helper content scaffold", () => {
  it("performs /version compatibility checks from the Studio content context", async () => {
    const { checkServerCompatibility, handlers } = await loadContent();

    await handlers.get("checkCompatibility")?.({
      data: {
        baseUrl: "http://localhost:7873",
        extensionVersion: "0.1.0",
      },
    });

    expect(checkServerCompatibility).toHaveBeenCalledWith(
      "http://localhost:7873",
      "0.1.0"
    );
  });
});
