import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ASSET_CHUNK_SIZE,
  fetchLocalAssetChunk,
  fetchLocalText,
} from "../lib/local-fetch";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("background local fetch boundary", () => {
  it.each([
    "https://localhost:7873/version",
    "http://example.com/version",
    "http://user:pass@localhost:7873/version",
    "http://127.0.0.2:7873/version",
  ])("loopback HTTP 以外を fetch 前に拒否する: %s", async (url) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchLocalText({ url })).rejects.toThrow(
      "local fetch URL must use a loopback HTTP host"
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("JSON response の status・Content-Type・body を relay wire にする", async () => {
    const fetchMock = vi.fn(
      async () =>
        new Response('{"ok":true}', {
          status: 200,
          headers: { "Content-Type": "application/json" },
        })
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      fetchLocalText({ url: "http://localhost:7873/version" })
    ).resolves.toEqual({
      body: '{"ok":true}',
      contentType: "application/json",
      status: 200,
      statusText: "",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      new URL("http://localhost:7873/version"),
      { method: "GET", redirect: "error" }
    );
  });

  it.each([
    "http://127.0.0.1:7873/version",
    "http://music.localhost:7873/version",
  ])("accepts the explicit loopback host boundary: %s", async (url) => {
    const fetchMock = vi.fn(async () => new Response("ok", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchLocalText({ url })).resolves.toMatchObject({
      status: 200,
      body: "ok",
    });
    expect(fetchMock).toHaveBeenCalledWith(new URL(url), {
      method: "GET",
      redirect: "error",
    });
  });

  it("asset を固定長 chunk で往復し、境界・端数・全 byte 値を保持する", async () => {
    const source = Uint8Array.from(
      { length: ASSET_CHUNK_SIZE + 257 },
      (_, index) => index % 256
    );
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(source, {
            status: 200,
            headers: { "Content-Type": "audio/flac" },
          })
      )
    );

    const first = await fetchLocalAssetChunk({
      url: "http://localhost:7873/distrokid/assets/track.flac",
      offset: 0,
    });
    const last = await fetchLocalAssetChunk({
      url: "http://localhost:7873/distrokid/assets/track.flac",
      offset: ASSET_CHUNK_SIZE,
    });
    const decode = (value: string) =>
      Uint8Array.from(atob(value), (c) => c.charCodeAt(0));
    const restored = new Uint8Array(source.length);
    restored.set(decode(first.base64));
    restored.set(decode(last.base64), ASSET_CHUNK_SIZE);
    expect(restored).toEqual(source);
    expect(first.base64.length).toBeLessThan(6 * 1024 * 1024);
    expect(first.totalSize).toBe(source.length);
    expect(last.contentType).toBe("audio/flac");
  }, 60_000);

  it.each([404, 500])(
    "rejects a non-OK asset response: HTTP %i",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => new Response("failed", { status }))
      );
      await expect(
        fetchLocalAssetChunk({
          url: `http://localhost:7873/distrokid/assets/${status}.mp3`,
          offset: 0,
        })
      ).rejects.toThrow(`asset fetch failed: HTTP ${status}`);
    }
  );
});
