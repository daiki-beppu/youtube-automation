import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchLocalAsset, fetchLocalText } from "../lib/local-fetch";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("background local fetch boundary", () => {
  it.each([
    "https://localhost:7873/version",
    "http://example.com/version",
    "http://user:pass@localhost:7873/version",
  ])("loopback HTTP 以外を fetch 前に拒否する: %s", async (url) => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    await expect(fetchLocalText({ url })).rejects.toThrow(
      "local fetch URL must use a loopback HTTP host"
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("JSON response の status・Content-Type・body を relay wire にする", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response('{"ok":true}', {
            status: 200,
            headers: { "Content-Type": "application/json" },
          })
      )
    );

    await expect(
      fetchLocalText({ url: "http://localhost:7873/version" })
    ).resolves.toEqual({
      body: '{"ok":true}',
      contentType: "application/json",
      status: 200,
      statusText: "",
    });
  });

  it("asset を1件だけ base64 wire に変換する", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(new Uint8Array([1, 2, 3]), {
            status: 200,
            headers: { "Content-Type": "audio/mpeg" },
          })
      )
    );

    await expect(
      fetchLocalAsset({
        url: "http://music.localhost:7873/distrokid/assets/track.mp3",
        filename: "track.mp3",
      })
    ).resolves.toEqual({
      base64: "AQID",
      filename: "track.mp3",
      mimeType: "audio/mpeg",
    });
  });
});
