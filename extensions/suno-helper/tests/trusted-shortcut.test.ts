import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { sendTrustedCmdP } from "../lib/trusted-shortcut";

// REQ-2917-01: debugger detach is attempted once and its failures stay visible.
describe("trusted shortcut debugger cleanup", () => {
  const attach = vi.fn(async () => undefined);
  const sendCommand = vi.fn(async () => undefined);
  const detach = vi.fn(async () => undefined);

  beforeEach(() => {
    vi.clearAllMocks();
    vi.stubGlobal("chrome", {
      debugger: { attach, sendCommand, detach },
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("detach reject を warn して呼び出し側へ伝播する", async () => {
    const error = new Error("detach failed");
    detach.mockRejectedValueOnce(error);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    await expect(sendTrustedCmdP(42, true)).rejects.toBe(error);

    expect(detach).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("sendTrustedCmdP failed"),
      error
    );
  });

  it("send と detach が両方 reject しても detach を一回試行して reject する", async () => {
    sendCommand.mockRejectedValueOnce(new Error("send failed"));
    const detachError = new Error("detach failed");
    detach.mockRejectedValueOnce(detachError);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    await expect(sendTrustedCmdP(42, false)).rejects.toBe(detachError);

    expect(detach).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("sendTrustedCmdP failed"),
      detachError
    );
  });

  it("send reject 時も detach を一回試行し、元の失敗を warn して伝播する", async () => {
    const error = new Error("send failed");
    sendCommand.mockRejectedValueOnce(error);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    await expect(sendTrustedCmdP(42, true)).rejects.toBe(error);

    expect(detach).toHaveBeenCalledOnce();
    expect(warn).toHaveBeenCalledWith(
      expect.stringContaining("sendTrustedCmdP failed"),
      error
    );
  });
});
