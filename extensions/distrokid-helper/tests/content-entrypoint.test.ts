// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from "vitest";

const contentMocks = vi.hoisted(() => ({
  definition: undefined as { main: () => void } | undefined,
  handlers: new Map<string, (message?: { data: unknown }) => unknown>(),
  injector: { boundary: "document" },
  reporter: undefined as
    | ((
        phase: "injecting" | "done" | "error" | "stopped",
        message: string
      ) => unknown)
    | undefined,
  start: vi.fn(),
  track: vi.fn(),
  cover: vi.fn(),
  finish: vi.fn(),
  stop: vi.fn(),
  sendMessage: vi.fn(),
}));

vi.mock("../lib/content-injector", () => ({
  createDocumentInjector: vi.fn(() => contentMocks.injector),
}));
vi.mock("../lib/inject-session", () => ({
  InjectSession: class {
    constructor(injector: unknown, reporter: typeof contentMocks.reporter) {
      expect(injector).toBe(contentMocks.injector);
      contentMocks.reporter = reporter;
    }
    start = contentMocks.start;
    track = contentMocks.track;
    cover = contentMocks.cover;
    finish = contentMocks.finish;
    stop = contentMocks.stop;
  },
}));
vi.mock("../lib/messaging", () => ({
  onMessage: vi.fn(
    (name: string, handler: (message: { data: unknown }) => unknown) => {
      contentMocks.handlers.set(name, (message) => handler(message!));
      return vi.fn();
    }
  ),
  sendMessage: contentMocks.sendMessage,
}));

describe("distrokid content entrypoint", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
    vi.clearAllMocks();
    contentMocks.handlers.clear();
    contentMocks.definition = undefined;
    contentMocks.reporter = undefined;
  });

  it("registers exact handlers, preserves payloads/order, and relays progress", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(new Blob(["asset"])))
    );
    vi.stubGlobal(
      "defineContentScript",
      (definition: typeof contentMocks.definition) => {
        contentMocks.definition = definition;
        return definition;
      }
    );
    await import("../entrypoints/content");
    contentMocks.definition!.main();

    expect([...contentMocks.handlers.keys()]).toEqual([
      "injectStart",
      "injectTrack",
      "injectCover",
      "injectFinish",
      "stop",
    ]);
    const payload = { release: { tracks: [] } };
    const trackAsset = { filename: "track.mp3", blobUrl: "blob:track" };
    const coverAsset = { filename: "main.png", blobUrl: "blob:cover" };
    await contentMocks.handlers.get("injectStart")!({
      data: { payload },
    });
    await contentMocks.handlers.get("injectTrack")!({
      data: { trackIndex: 2, asset: trackAsset },
    });
    await contentMocks.handlers.get("injectCover")!({
      data: { asset: coverAsset },
    });
    await contentMocks.handlers.get("injectFinish")!();
    contentMocks.handlers.get("stop")!();

    expect(contentMocks.start).toHaveBeenCalledWith(payload);
    expect(contentMocks.track).toHaveBeenCalledWith(
      2,
      expect.objectContaining({ name: "track.mp3" })
    );
    expect(contentMocks.cover).toHaveBeenCalledWith(
      expect.objectContaining({ name: "main.png" })
    );
    expect(contentMocks.finish).toHaveBeenCalledOnce();
    expect(contentMocks.stop).toHaveBeenCalledOnce();
    expect(contentMocks.start.mock.invocationCallOrder[0]).toBeLessThan(
      contentMocks.track.mock.invocationCallOrder[0]
    );
    expect(contentMocks.track.mock.invocationCallOrder[0]).toBeLessThan(
      contentMocks.cover.mock.invocationCallOrder[0]
    );
    expect(contentMocks.cover.mock.invocationCallOrder[0]).toBeLessThan(
      contentMocks.finish.mock.invocationCallOrder[0]
    );
    expect(contentMocks.finish.mock.invocationCallOrder[0]).toBeLessThan(
      contentMocks.stop.mock.invocationCallOrder[0]
    );
    await contentMocks.reporter!("injecting", "track 1");
    expect(contentMocks.sendMessage).toHaveBeenCalledWith("progress", {
      phase: "injecting",
      message: "track 1",
    });
  });

  it.each([
    "injectStart",
    "injectTrack",
    "injectCover",
    "injectFinish",
    "stop",
  ])("propagates %s handler rejection to the message caller", async (name) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(new Blob(["asset"])))
    );
    vi.stubGlobal(
      "defineContentScript",
      (definition: typeof contentMocks.definition) => {
        contentMocks.definition = definition;
        return definition;
      }
    );
    const method = {
      injectStart: contentMocks.start,
      injectTrack: contentMocks.track,
      injectCover: contentMocks.cover,
      injectFinish: contentMocks.finish,
      stop: contentMocks.stop,
    }[name]!;
    method.mockRejectedValueOnce(new Error(`${name} rejected`));
    await import("../entrypoints/content");
    contentMocks.definition!.main();

    const result = contentMocks.handlers.get(name)!({
      data: {
        payload: {},
        trackIndex: 0,
        asset: { filename: "asset", blobUrl: "blob:asset" },
      },
    });
    await expect(Promise.resolve(result)).rejects.toThrow(`${name} rejected`);
  });
});
