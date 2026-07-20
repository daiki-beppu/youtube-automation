import { afterEach, describe, expect, it, vi } from "vitest";

type Handler = (message: { data: Record<string, string> }) => unknown;
type RunCommunityPosts = (typeof import("../lib/runner"))["runCommunityPosts"];

async function loadContent() {
  vi.resetModules();
  const handlers = new Map<string, Handler>();
  const sendMessage = vi.fn(async (name: string) => {
    if (name === "fetchCommunityPosts") {
      return [];
    }
    if (name === "fetchCommunityImage") {
      return {
        base64: btoa("image"),
        filename: "community-post-1",
        mimeType: "image/png",
      };
    }
    return undefined;
  });
  const runCommunityPosts = vi.fn<RunCommunityPosts>(async () => undefined);

  vi.stubGlobal("defineContentScript", (definition: { main: () => void }) => {
    definition.main();
    return definition;
  });
  vi.doMock("../lib/messaging", () => ({
    onMessage: vi.fn((name: string, handler: Handler) => {
      handlers.set(name, handler);
      return vi.fn();
    }),
    sendMessage,
  }));
  vi.doMock("../lib/runner", () => ({ runCommunityPosts }));
  vi.doMock("../../shared/community-dom", () => ({
    attachImage: vi.fn(),
    cancelCommunityPostForm: vi.fn(),
    clickPost: vi.fn(),
    openCommunityPostForm: vi.fn(),
    openSchedulePicker: vi.fn(),
    setCommunityText: vi.fn(),
    setScheduleDateTime: vi.fn(),
  }));

  await import("../entrypoints/content");
  return { handlers, runCommunityPosts, sendMessage };
}

afterEach(() => {
  vi.doUnmock("../lib/messaging");
  vi.doUnmock("../lib/runner");
  vi.doUnmock("../../shared/community-dom");
  vi.unstubAllGlobals();
});

describe("community-helper content runner integration", () => {
  it("starts the runner with background fetch relays", async () => {
    const { handlers, runCommunityPosts } = await loadContent();

    await handlers.get("run")?.({
      data: { baseUrl: "http://localhost:7873" },
    });

    expect(runCommunityPosts).toHaveBeenCalledOnce();
    expect(runCommunityPosts.mock.calls[0][0]).toBe("http://localhost:7873");
    expect(runCommunityPosts.mock.calls[0][1]).toEqual(
      expect.objectContaining({
        fetchImage: expect.any(Function),
        fetchPosts: expect.any(Function),
        reportProgress: expect.any(Function),
      })
    );
    const image = await runCommunityPosts.mock.calls[0][1].fetchImage(
      "http://localhost:7873",
      0
    );
    expect(image).toBeInstanceOf(Blob);
    expect(image.type).toBe("image/png");
    await expect(image.text()).resolves.toBe("image");
  });

  it("blocks a duplicate run after all three posts complete", async () => {
    const { handlers, runCommunityPosts } = await loadContent();

    await handlers.get("run")?.({
      data: { baseUrl: "http://localhost:7873" },
    });
    await expect(
      handlers.get("run")?.({
        data: { baseUrl: "http://localhost:7873" },
      })
    ).rejects.toThrow("完了済み");

    expect(runCommunityPosts).toHaveBeenCalledTimes(1);
  });

  it("relays runner errors to the popup and rejects without retry", async () => {
    const { handlers, runCommunityPosts, sendMessage } = await loadContent();
    runCommunityPosts.mockRejectedValueOnce(new Error("selector drift"));

    await expect(
      handlers.get("run")?.({
        data: { baseUrl: "http://localhost:7873" },
      })
    ).rejects.toThrow("selector drift");
    expect(sendMessage).toHaveBeenCalledWith("contentError", {
      message: "selector drift",
    });
    expect(runCommunityPosts).toHaveBeenCalledTimes(1);
  });

  it("blocks a restart after partial completion until the page is reconciled", async () => {
    const { handlers, runCommunityPosts } = await loadContent();
    const partialError = Object.assign(new Error("second post failed"), {
      requiresReconciliation: true,
    });
    runCommunityPosts.mockRejectedValueOnce(partialError);

    await expect(
      handlers.get("run")?.({
        data: { baseUrl: "http://localhost:7873" },
      })
    ).rejects.toThrow("second post failed");
    await expect(
      handlers.get("run")?.({
        data: { baseUrl: "http://localhost:7873" },
      })
    ).rejects.toThrow("照合");

    expect(runCommunityPosts).toHaveBeenCalledTimes(1);
  });

  it("aborts the active run when stop is received", async () => {
    const { handlers, runCommunityPosts } = await loadContent();
    let signal: AbortSignal | undefined;
    runCommunityPosts.mockImplementationOnce(
      async (_baseUrl, _dependencies, activeSignal) => {
        signal = activeSignal;
        await new Promise<void>((resolve) => {
          activeSignal?.addEventListener("abort", () => resolve(), {
            once: true,
          });
        });
      }
    );

    const run = handlers.get("run")?.({
      data: { baseUrl: "http://localhost:7873" },
    });
    await handlers.get("stop")?.({ data: {} });
    await run;

    expect(signal?.aborted).toBe(true);
  });
});
