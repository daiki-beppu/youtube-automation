import { afterEach, describe, expect, it, vi } from "vitest";

type Handler = (message: {
  data: unknown;
  sender: { tab?: { id?: number } };
}) => unknown;

async function loadBackground() {
  vi.resetModules();
  const handlers = new Map<string, Handler>();
  const actionListeners: Array<(tab: { id?: number }) => void> = [];
  const sendMessage = vi.fn(async () => undefined);
  const checkServerCompatibility = vi.fn(async () => ({
    status: "compatible" as const,
    serverVersion: "0.1.0",
    minExtensionVersion: "0.1.0",
    extensionVersion: "0.1.0",
  }));
  const fetchCommunityPosts = vi.fn(async () => []);
  const fetchCommunityImage = vi.fn(
    async () => new Blob(["image"], { type: "image/png" })
  );

  vi.stubGlobal("defineBackground", (callback: () => void) => {
    callback();
    return callback;
  });
  vi.stubGlobal("browser", {
    action: {
      onClicked: {
        addListener: vi.fn((listener: (tab: { id?: number }) => void) =>
          actionListeners.push(listener)
        ),
      },
    },
  });
  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((name: string, handler: Handler) => {
      handlers.set(name, handler);
      return vi.fn();
    }),
    sendMessage,
  }));
  vi.doMock("../../shared/api", () => ({
    checkServerCompatibility,
    fetchCommunityImage,
    fetchCommunityPosts,
  }));

  await import("../entrypoints/background");
  return {
    actionListeners,
    checkServerCompatibility,
    fetchCommunityImage,
    fetchCommunityPosts,
    handlers,
    sendMessage,
  };
}

afterEach(() => {
  vi.doUnmock("../lib/messaging");
  vi.doUnmock("../../shared/api");
  vi.unstubAllGlobals();
});

describe("community-helper background relay", () => {
  it("fetches compatibility, posts and images in extension context", async () => {
    const context = await loadBackground();
    const compatibility = {
      baseUrl: "http://localhost:7873",
      extensionVersion: "0.1.0",
    };

    await context.handlers.get("checkCompatibility")?.({
      data: compatibility,
      sender: {},
    });
    await context.handlers.get("fetchCommunityPosts")?.({
      data: { baseUrl: compatibility.baseUrl },
      sender: {},
    });
    const imageWire = await context.handlers.get("fetchCommunityImage")?.({
      data: { baseUrl: compatibility.baseUrl, index: 2 },
      sender: {},
    });

    expect(context.checkServerCompatibility).toHaveBeenCalledWith(
      compatibility.baseUrl,
      compatibility.extensionVersion
    );
    expect(context.fetchCommunityPosts).toHaveBeenCalledWith(
      compatibility.baseUrl
    );
    expect(context.fetchCommunityImage).toHaveBeenCalledWith(
      compatibility.baseUrl,
      2
    );
    expect(imageWire).toEqual({
      base64: btoa("image"),
      filename: "community-post-3",
      mimeType: "image/png",
    });
    expect(imageWire).not.toBeInstanceOf(Blob);
  });

  it("relays run and stop to the sender tab", async () => {
    const { handlers, sendMessage } = await loadBackground();
    const request = { baseUrl: "http://localhost:7873" };

    const sender = { tab: { id: 42 } };
    await handlers.get("run")?.({ data: request, sender });
    await handlers.get("stop")?.({ data: undefined, sender });

    expect(sendMessage).toHaveBeenNthCalledWith(1, "run", request, 42);
    expect(sendMessage).toHaveBeenNthCalledWith(2, "stop", undefined, 42);
  });

  it("relays content progress and errors to the sender tab overlay", async () => {
    const { handlers, sendMessage } = await loadBackground();
    const progress = {
      index: 0,
      phase: "injecting",
      message: "本文を入力中",
      total: 3,
    };

    const sender = { tab: { id: 42 } };
    await handlers.get("contentProgress")?.({ data: progress, sender });
    await handlers.get("contentError")?.({
      data: { message: "selector drift" },
      sender,
    });

    expect(sendMessage).toHaveBeenNthCalledWith(1, "progress", progress, 42);
    expect(sendMessage).toHaveBeenNthCalledWith(
      2,
      "error",
      {
        message: "selector drift",
      },
      42
    );
  });

  it("action click toggles only the clicked tab overlay", async () => {
    const { actionListeners, sendMessage } = await loadBackground();

    actionListeners[0]({ id: 42 });
    await Promise.resolve();

    expect(sendMessage).toHaveBeenCalledWith("toggleOverlay", undefined, 42);
  });

  it("fails loudly when a relay sender has no tab", async () => {
    const { handlers, sendMessage } = await loadBackground();

    expect(() =>
      handlers.get("run")?.({ data: { baseUrl: "x" }, sender: {} })
    ).toThrow("run: 送信元タブが特定できません");
    expect(sendMessage).not.toHaveBeenCalled();
  });
});
