import { afterEach, describe, expect, it, vi } from "vitest";

type Handler = (message: { data: unknown }) => unknown;

async function loadBackground(url = "https://studio.youtube.com/channel/abc") {
  vi.resetModules();
  const handlers = new Map<string, Handler>();
  const sendMessage = vi.fn(async () => undefined);

  vi.stubGlobal("defineBackground", (callback: () => void) => {
    callback();
    return callback;
  });
  vi.stubGlobal("browser", {
    tabs: {
      query: vi.fn(async () => [{ id: 42, url }]),
    },
  });
  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((name: string, handler: Handler) => {
      handlers.set(name, handler);
      return vi.fn();
    }),
    sendMessage,
  }));

  await import("../entrypoints/background");
  return { handlers, sendMessage };
}

afterEach(() => {
  vi.doUnmock("../lib/messaging");
  vi.unstubAllGlobals();
});

describe("community-helper background relay", () => {
  it("relays compatibility checks to the active Studio content script", async () => {
    const { handlers, sendMessage } = await loadBackground();
    const request = {
      baseUrl: "http://localhost:7873",
      extensionVersion: "0.1.0",
    };

    await handlers.get("checkCompatibility")?.({ data: request });

    expect(sendMessage).toHaveBeenCalledWith("checkCompatibility", request, 42);
  });

  it("relays popup run to the active Studio content script", async () => {
    const { handlers, sendMessage } = await loadBackground();
    const request = { baseUrl: "http://localhost:7873" };

    await handlers.get("run")?.({ data: request });

    expect(sendMessage).toHaveBeenCalledWith("run", request, 42);
  });

  it("relays popup stop to the active Studio content script", async () => {
    const { handlers, sendMessage } = await loadBackground();

    await handlers.get("stop")?.({ data: undefined });

    expect(sendMessage).toHaveBeenCalledWith("stop", undefined, 42);
  });

  it("relays content progress to the popup channel", async () => {
    const { handlers, sendMessage } = await loadBackground();
    const progress = {
      index: 0,
      phase: "injecting",
      message: "投稿を準備中",
    };

    await handlers.get("contentProgress")?.({ data: progress });

    expect(sendMessage).toHaveBeenCalledWith("progress", progress);
  });

  it("fails loudly when the active tab is outside YouTube Studio", async () => {
    const { handlers, sendMessage } = await loadBackground(
      "https://www.youtube.com/"
    );

    await expect(
      handlers.get("run")?.({ data: { baseUrl: "x" } })
    ).rejects.toThrow("YouTube Studio");
    expect(sendMessage).not.toHaveBeenCalled();
  });
});
