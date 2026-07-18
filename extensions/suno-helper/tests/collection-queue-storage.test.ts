import { beforeEach, describe, expect, it, vi } from "vitest";

const storageMock = vi.hoisted(() => ({
  value: null as unknown,
  getValue: vi.fn(),
  setValue: vi.fn(),
  defineItem: vi.fn(),
}));

vi.mock("wxt/utils/storage", () => {
  storageMock.getValue.mockImplementation(async () => storageMock.value);
  storageMock.setValue.mockImplementation(async (value: unknown) => {
    storageMock.value = value;
  });
  storageMock.defineItem.mockReturnValue({
    getValue: storageMock.getValue,
    setValue: storageMock.setValue,
  });
  return { storage: { defineItem: storageMock.defineItem } };
});

import {
  createCollectionQueue,
  currentCollectionId,
  settleStoredCollectionQueueRun,
  writeCollectionQueue,
} from "../lib/collection-queue-state";

describe("collection queue storage boundary (#2029)", () => {
  beforeEach(() => {
    storageMock.value = null;
    vi.clearAllMocks();
  });

  it("terminal result を永続化してから次 collection を返す", async () => {
    const state = createCollectionQueue({
      queueId: "queue-storage",
      baseUrl: "http://localhost:8765",
      collectionIds: ["first", "second"],
      runMode: "queue",
      regenerateDurationOutliers: true,
      now: 100,
    });
    await writeCollectionQueue(state);

    const transition = await settleStoredCollectionQueueRun("queue-storage", {
      collectionId: "first",
      phase: "error",
      failedEntryCount: 0,
      message: "download failed",
      now: 200,
    });

    expect(transition?.requiresPageReload).toBe(true);
    expect(currentCollectionId(transition!.state)).toBe("second");
    expect(storageMock.value).toEqual(transition?.state);
    expect(storageMock.setValue).toHaveBeenCalledTimes(2);
  });

  it("stale queue id の terminal event は保存中 queue を変更しない", async () => {
    const state = createCollectionQueue({
      queueId: "active-queue",
      baseUrl: "http://localhost:8765",
      collectionIds: ["first"],
      runMode: "serial",
      regenerateDurationOutliers: true,
      now: 100,
    });
    await writeCollectionQueue(state);
    storageMock.setValue.mockClear();

    const transition = await settleStoredCollectionQueueRun("stale-queue", {
      collectionId: "first",
      phase: "finished",
      failedEntryCount: 0,
      now: 200,
    });

    expect(transition).toBeNull();
    expect(storageMock.setValue).not.toHaveBeenCalled();
    expect(storageMock.value).toEqual(state);
  });
});
