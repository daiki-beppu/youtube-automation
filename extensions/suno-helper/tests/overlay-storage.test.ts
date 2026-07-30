import { beforeEach, describe, expect, it, vi } from "vitest";

import type { OverlayState } from "../../shared/overlay-state";

const overlayItem = vi.hoisted(() => ({
  getValue: vi.fn(),
  setValue: vi.fn(),
  defineItem: vi.fn(),
}));

vi.mock("wxt/utils/storage", () => ({
  storage: {
    defineItem: overlayItem.defineItem.mockReturnValue(overlayItem),
  },
}));

import { readOverlayState, writeOverlayState } from "../lib/overlay-storage";

const state: OverlayState = {
  position: { x: 20, y: 40 },
  minimized: false,
  hidden: true,
};

describe("overlay storage adapter I/O (#2905)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    overlayItem.getValue.mockResolvedValue(null);
    overlayItem.setValue.mockResolvedValue(undefined);
  });

  it("正しい helper key/fallback で lazy item を作り read/write を委譲する", async () => {
    overlayItem.getValue.mockResolvedValueOnce(state);

    await expect(readOverlayState()).resolves.toBe(state);
    await writeOverlayState(state);

    expect(overlayItem.defineItem).toHaveBeenCalledWith(
      "local:sunoOverlayState",
      { fallback: null }
    );
    expect(overlayItem.getValue).toHaveBeenCalledOnce();
    expect(overlayItem.setValue).toHaveBeenCalledWith(state);
  });

  it("read の reject を同じ Error で伝播する", async () => {
    const failure = new Error("overlay read failed");
    overlayItem.getValue.mockRejectedValueOnce(failure);

    await expect(readOverlayState()).rejects.toBe(failure);
  });

  it("write の reject を同じ Error で伝播する", async () => {
    const failure = new Error("overlay write failed");
    overlayItem.setValue.mockRejectedValueOnce(failure);

    await expect(writeOverlayState(state)).rejects.toBe(failure);
  });
});
