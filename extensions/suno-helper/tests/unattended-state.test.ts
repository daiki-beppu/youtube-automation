// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const unattendedStorage = vi.hoisted(() => ({
  getValue: vi.fn(),
  setValue: vi.fn(),
  defineItem: vi.fn(),
}));

vi.mock("wxt/utils/storage", () => ({
  storage: {
    defineItem: unattendedStorage.defineItem.mockReturnValue(unattendedStorage),
  },
}));

import {
  exposeUnattendedRunState,
  writeUnattendedRunState,
} from "../lib/unattended-state";

const runningState = {
  requestId: "scheduled-write",
  collectionId: "collection",
  status: "running" as const,
  checkpoint: "entries" as const,
  pendingEntryIndices: [1],
  updatedAt: 3,
};

describe("exposeUnattendedRunState", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    unattendedStorage.setValue.mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("publishes a machine-readable manual intervention notification", () => {
    exposeUnattendedRunState(document.documentElement, {
      requestId: "scheduled-test",
      collectionId: "collection",
      status: "manual-intervention",
      checkpoint: "download",
      pendingEntryIndices: [],
      stopReason: "captcha-required",
      requiredAction: "CAPTCHA を手動で解決してください。",
      updatedAt: 1,
    });

    expect(document.documentElement.dataset).toMatchObject({
      sunoUnattendedRequestId: "scheduled-test",
      sunoUnattendedCollectionId: "collection",
      sunoUnattendedStatus: "manual-intervention",
      sunoUnattendedCheckpoint: "download",
      sunoUnattendedStopReason: "captcha-required",
      sunoUnattendedRequiredAction: "CAPTCHA を手動で解決してください。",
    });
  });

  it("clears stale manual fields when the next run completes", () => {
    document.documentElement.dataset.sunoUnattendedStopReason =
      "captcha-required";
    document.documentElement.dataset.sunoUnattendedRequiredAction = "manual";
    exposeUnattendedRunState(document.documentElement, {
      requestId: "scheduled-test-2",
      collectionId: "collection",
      status: "completed",
      checkpoint: "complete",
      pendingEntryIndices: [],
      updatedAt: 2,
    });

    expect(document.documentElement.dataset.sunoUnattendedStatus).toBe(
      "completed"
    );
    expect(
      document.documentElement.dataset.sunoUnattendedStopReason
    ).toBeUndefined();
    expect(
      document.documentElement.dataset.sunoUnattendedRequiredAction
    ).toBeUndefined();
  });

  it("document ありでは storage 保存後に documentElement dataset を更新する", async () => {
    await writeUnattendedRunState(runningState);

    expect(unattendedStorage.defineItem).toHaveBeenCalledWith(
      "local:sunoUnattendedRunState",
      { fallback: null }
    );
    expect(unattendedStorage.setValue).toHaveBeenCalledWith(runningState);
    expect(document.documentElement.dataset).toMatchObject({
      sunoUnattendedRequestId: "scheduled-write",
      sunoUnattendedCollectionId: "collection",
      sunoUnattendedStatus: "running",
      sunoUnattendedCheckpoint: "entries",
    });
  });

  it("document なしでも例外なく storage 保存を完了する", async () => {
    vi.stubGlobal("document", undefined);

    await expect(
      writeUnattendedRunState(runningState)
    ).resolves.toBeUndefined();
    expect(unattendedStorage.setValue).toHaveBeenCalledWith(runningState);
  });
});
