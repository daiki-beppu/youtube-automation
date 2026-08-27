import { afterEach, describe, expect, it, vi } from "vitest";

import { backgroundFetch, backgroundFetchAsset } from "../lib/background-fetch";
import { sendMessage } from "../lib/messaging";

vi.mock("../lib/messaging", () => ({
  sendMessage: vi.fn(),
}));

afterEach(() => {
  vi.clearAllMocks();
});

describe("background fetch adapter", () => {
  it.each(["POST", "post", "HEAD"])(
    "rejects non-GET init before relay: %s",
    async (method) => {
      await expect(
        backgroundFetch("http://localhost:7873/version", { method })
      ).rejects.toThrow("only supports GET");
      expect(sendMessage).not.toHaveBeenCalled();
    }
  );

  it("rejects a non-GET Request object before relay", async () => {
    await expect(
      backgroundFetch(
        new Request("http://localhost:7873/version", { method: "POST" })
      )
    ).rejects.toThrow("only supports GET");
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("accepts a case-insensitive GET init", async () => {
    vi.mocked(sendMessage).mockResolvedValueOnce({
      body: "ok",
      contentType: "text/plain",
      status: 200,
      statusText: "OK",
    });

    await expect(
      backgroundFetch("http://localhost:7873/version", { method: "get" })
    ).resolves.toBeInstanceOf(Response);
  });

  it.each([
    ["string", "http://localhost:7873/string"],
    ["URL", new URL("http://localhost:7873/url")],
    ["Request", new Request("http://localhost:7873/request")],
  ])(
    "normalizes a %s input and reconstructs the Response wire",
    async (_kind, input) => {
      vi.mocked(sendMessage).mockResolvedValueOnce({
        body: "relay body",
        contentType: "application/json",
        status: 206,
        statusText: "Partial Content",
      });

      const response = await backgroundFetch(input);
      const expectedUrl =
        typeof input === "string"
          ? input
          : input instanceof URL
            ? input.href
            : input.url;
      expect(sendMessage).toHaveBeenCalledWith("fetchLocalText", {
        url: expectedUrl,
      });
      expect(response.status).toBe(206);
      expect(response.statusText).toBe("Partial Content");
      expect(response.headers.get("content-type")).toBe("application/json");
      await expect(response.text()).resolves.toBe("relay body");
    }
  );

  it("assembles chunks into a Blob URL and exposes an explicit revoke handle", async () => {
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:asset"),
      revokeObjectURL: vi.fn(),
    });
    vi.mocked(sendMessage)
      .mockResolvedValueOnce({
        base64: "AQI=",
        contentType: "audio/mpeg",
        totalSize: 3,
      })
      .mockResolvedValueOnce({
        base64: "Aw==",
        contentType: "audio/mpeg",
        totalSize: 3,
      });
    const handle = await backgroundFetchAsset(
      "http://localhost:7873/track.mp3",
      "track.mp3"
    );
    expect(handle).toMatchObject({
      filename: "track.mp3",
      blobUrl: "blob:asset",
    });
    expect(sendMessage).toHaveBeenNthCalledWith(1, "fetchLocalAssetChunk", {
      url: "http://localhost:7873/track.mp3",
      offset: 0,
    });
    expect(sendMessage).toHaveBeenNthCalledWith(2, "fetchLocalAssetChunk", {
      url: "http://localhost:7873/track.mp3",
      offset: 2,
    });
    handle.revoke();
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:asset");
  });
});
