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

  it("relays one asset request and returns the serialized wire unchanged", async () => {
    const wire = {
      filename: "track.mp3",
      mimeType: "audio/mpeg",
      base64: "AQID",
    };
    vi.mocked(sendMessage).mockResolvedValueOnce(wire);

    await expect(
      backgroundFetchAsset(
        "http://localhost:7873/distrokid/assets/track.mp3",
        "track.mp3"
      )
    ).resolves.toBe(wire);
    expect(sendMessage).toHaveBeenCalledWith("fetchLocalAsset", {
      url: "http://localhost:7873/distrokid/assets/track.mp3",
      filename: "track.mp3",
    });
  });
});
