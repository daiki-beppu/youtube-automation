import { afterEach, describe, expect, it, vi } from "vitest";

type Handler = (message: { data: unknown }) => unknown;

async function loadBackground(
  url = "https://www.youtube.com/channel/abc/posts"
) {
  vi.resetModules();
  const handlers = new Map<string, Handler>();
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
  vi.doMock("../../shared/api", () => ({
    checkServerCompatibility,
    fetchCommunityImage,
    fetchCommunityPosts,
  }));

  await import("../entrypoints/background");
  return {
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
    });
    await context.handlers.get("fetchCommunityPosts")?.({
      data: { baseUrl: compatibility.baseUrl },
    });
    const imageWire = await context.handlers.get("fetchCommunityImage")?.({
      data: { baseUrl: compatibility.baseUrl, index: 2 },
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

  it("relays run and stop only to an active channel posts tab", async () => {
    const { handlers, sendMessage } = await loadBackground();
    const request = { baseUrl: "http://localhost:7873" };

    await handlers.get("run")?.({ data: request });
    await handlers.get("stop")?.({ data: undefined });

    expect(sendMessage).toHaveBeenNthCalledWith(1, "run", request, 42);
    expect(sendMessage).toHaveBeenNthCalledWith(2, "stop", undefined, 42);
  });

  it("relays content progress and errors to the popup", async () => {
    const { handlers, sendMessage } = await loadBackground();
    const progress = {
      index: 0,
      phase: "injecting",
      message: "本文を入力中",
      total: 3,
    };

    await handlers.get("contentProgress")?.({ data: progress });
    await handlers.get("contentError")?.({
      data: { message: "selector drift" },
    });

    expect(sendMessage).toHaveBeenNthCalledWith(1, "progress", progress);
    expect(sendMessage).toHaveBeenNthCalledWith(2, "error", {
      message: "selector drift",
    });
  });

  it.each([
    "https://studio.youtube.com/channel/abc",
    "https://www.youtube.com/",
    "https://www.youtube.com/channel/abc/videos",
  ])("fails loudly outside a channel posts page: %s", async (url) => {
    const { handlers, sendMessage } = await loadBackground(url);

    await expect(
      handlers.get("run")?.({ data: { baseUrl: "x" } })
    ).rejects.toThrow("チャンネル投稿ページ");
    expect(sendMessage).not.toHaveBeenCalled();
  });
});
