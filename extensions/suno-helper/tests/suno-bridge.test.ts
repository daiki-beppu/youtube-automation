// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  BRIDGE_MSG,
  BRIDGE_SOURCE,
  FEED_V3_METHOD,
  FEED_V3_PATH,
  GENERATE_ENDPOINT_PATH,
  SUNO_API_ORIGIN,
} from "../../shared/constants";

const FEED_V2_PATH = "/api/feed/v2";

function jsonResponse(json: unknown): Response {
  return new Response(JSON.stringify(json), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

async function loadBridge(): Promise<void> {
  vi.resetModules();
  vi.stubGlobal("defineContentScript", (definition: { main: () => void }) => definition);
  const bridge = await import("../entrypoints/suno-bridge.content");
  bridge.default.main({} as NonNullable<Parameters<typeof bridge.default.main>[0]>);
}

async function flushObservedFetch(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("suno-bridge fetch interceptor", () => {
  it("Given feed v3 POST response When fetch resolves Then FEED_CLIPS を postMessage する", async () => {
    const originalFetch = vi.fn(async () => jsonResponse({ clips: [{ id: "clip-1", status: "complete" }] }));
    vi.stubGlobal("fetch", originalFetch);
    const postMessage = vi.spyOn(window, "postMessage").mockImplementation(() => undefined);

    await loadBridge();
    await window.fetch(`${SUNO_API_ORIGIN}${FEED_V3_PATH}`, { method: FEED_V3_METHOD });
    await flushObservedFetch();

    expect(postMessage).toHaveBeenCalledWith(
      {
        source: BRIDGE_SOURCE,
        type: BRIDGE_MSG.FEED_CLIPS,
        clips: [{ id: "clip-1", status: "complete" }],
      },
      window.location.origin,
    );
  });

  it("Given feed v2 GET response When fetch resolves Then FEED_CLIPS を postMessage しない", async () => {
    const originalFetch = vi.fn(async () => jsonResponse({ clips: [{ id: "clip-1", status: "complete" }] }));
    vi.stubGlobal("fetch", originalFetch);
    const postMessage = vi.spyOn(window, "postMessage").mockImplementation(() => undefined);

    await loadBridge();
    await window.fetch(`${SUNO_API_ORIGIN}${FEED_V2_PATH}?ids=clip-1`);
    await flushObservedFetch();

    expect(postMessage).not.toHaveBeenCalledWith(
      expect.objectContaining({ source: BRIDGE_SOURCE, type: BRIDGE_MSG.FEED_CLIPS }),
      expect.any(String),
    );
  });

  it("Given generate response When fetch resolves Then GENERATE_CLIPS は従来通り postMessage する", async () => {
    const originalFetch = vi.fn(async () => jsonResponse({ clips: [{ id: "clip-1", status: "submitted" }] }));
    vi.stubGlobal("fetch", originalFetch);
    const postMessage = vi.spyOn(window, "postMessage").mockImplementation(() => undefined);

    await loadBridge();
    await window.fetch(`${SUNO_API_ORIGIN}${GENERATE_ENDPOINT_PATH}`, { method: "POST" });
    await flushObservedFetch();

    expect(postMessage).toHaveBeenCalledWith(
      {
        source: BRIDGE_SOURCE,
        type: BRIDGE_MSG.GENERATE_CLIPS,
        clips: [{ id: "clip-1", status: "submitted" }],
      },
      window.location.origin,
    );
  });

  it("Given auth 捕捉済み When active poll request を受ける Then feed v3 POST で duration 付き clip を返す", async () => {
    const originalFetch = vi.fn(async () =>
      jsonResponse({ clips: [{ id: "clip-1", status: "complete", metadata: { duration: 121.5 } }] }),
    );
    vi.stubGlobal("fetch", originalFetch);
    const postMessage = vi.spyOn(window, "postMessage").mockImplementation(() => undefined);

    await loadBridge();
    await window.fetch(`${SUNO_API_ORIGIN}${FEED_V3_PATH}`, {
      method: FEED_V3_METHOD,
      headers: { authorization: "Bearer token" },
    });
    window.dispatchEvent(
      new MessageEvent("message", {
        source: window,
        data: {
          source: BRIDGE_SOURCE,
          type: BRIDGE_MSG.FEED_V3_POLL_REQUEST,
          requestId: 123,
          ids: ["clip-1"],
        },
      }),
    );
    await flushObservedFetch();

    expect(originalFetch).toHaveBeenLastCalledWith(`${SUNO_API_ORIGIN}${FEED_V3_PATH}`, {
      method: FEED_V3_METHOD,
      headers: { authorization: "Bearer token", "content-type": "application/json" },
      body: JSON.stringify({ ids: ["clip-1"] }),
    });
    expect(postMessage).toHaveBeenCalledWith(
      {
        source: BRIDGE_SOURCE,
        type: BRIDGE_MSG.FEED_V3_POLL_RESPONSE,
        requestId: 123,
        clips: [{ id: "clip-1", status: "complete", duration: 121.5 }],
      },
      window.location.origin,
    );
  });
});
