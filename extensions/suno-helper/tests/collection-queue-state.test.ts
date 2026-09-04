import { describe, expect, it } from "vitest";

import {
  createCollectionQueue,
  currentCollectionId,
  orderSelectedCollectionIds,
  recordCollectionResult,
  resumeCollectionQueue,
  settleCollectionQueueRun,
} from "../lib/collection-queue-state";
import { buildRunPayload } from "../lib/run-overrides";

const collections = [
  { id: "first", name: "First", status: "ready" as const },
  { id: "second", name: "Second", status: "ready" as const },
  { id: "third", name: "Third", status: "ready" as const },
];

describe("collection queue state (#2029)", () => {
  const createOptions = {
    queueId: "queue-validation",
    baseUrl: "http://localhost:8765",
    collectionIds: ["first", "second"],
    runMode: "queue" as const,
    regenerateDurationOutliers: true,
    now: 100,
  };

  it.each([
    ["空の collectionIds", { collectionIds: [] }, "at least one collection"],
    ["空白 queueId", { queueId: " \t" }, "queueId must be non-empty"],
    ["空白 baseUrl", { baseUrl: "\n" }, "baseUrl must be non-empty"],
    [
      "空白 collectionId",
      { collectionIds: ["first", " "] },
      "collectionIds[1] must be non-empty",
    ],
    [
      "重複 collectionId",
      { collectionIds: ["first", "first"] },
      "collectionIds must be unique",
    ],
  ])("%s を拒否して入力を変更しない", (_label, overrides, message) => {
    const options = { ...createOptions, ...overrides };
    const before = structuredClone(options);

    expect(() => createCollectionQueue(options)).toThrow(message);
    expect(options).toEqual(before);
  });

  it.each(["paused", "completed"] as const)(
    "%s queue への result 記録を拒否して state を変更しない",
    (status) => {
      const state = { ...createCollectionQueue(createOptions), status };
      const before = structuredClone(state);

      expect(() =>
        recordCollectionResult(state, {
          collectionId: "first",
          outcome: "succeeded",
          now: 200,
        })
      ).toThrow("collection queue must be running");
      expect(state).toEqual(before);
    }
  );

  it("current item と異なる result を拒否して state を変更しない", () => {
    const state = createCollectionQueue(createOptions);
    const before = structuredClone(state);

    expect(() =>
      recordCollectionResult(state, {
        collectionId: "second",
        outcome: "failed",
        now: 200,
      })
    ).toThrow("collection queue expected first, got second");
    expect(state).toEqual(before);
  });

  it.each(["finished", "error", "stopped"] as const)(
    "current item と異なる %s settlement を拒否して state を変更しない",
    (phase) => {
      const state = createCollectionQueue(createOptions);
      const before = structuredClone(state);

      expect(() =>
        settleCollectionQueueRun(state, {
          collectionId: "second",
          phase,
          failedEntryCount: 0,
          now: 200,
        })
      ).toThrow("collection queue settlement does not match current item");
      expect(state).toEqual(before);
    }
  );

  it("server の一覧順で選択 collection を直列進行し、境界 reload を要求する", () => {
    const ordered = orderSelectedCollectionIds(
      collections,
      new Set(["third", "first"])
    );
    const initial = createCollectionQueue({
      queueId: "queue-1",
      baseUrl: "http://127.0.0.1:8765",
      collectionIds: ordered,
      runMode: "queue",
      regenerateDurationOutliers: true,
      now: 100,
    });

    expect(ordered).toEqual(["first", "third"]);
    expect(currentCollectionId(initial)).toBe("first");

    const first = recordCollectionResult(initial, {
      collectionId: "first",
      outcome: "succeeded",
      now: 200,
    });

    expect(first.requiresPageReload).toBe(true);
    expect(currentCollectionId(first.state)).toBe("third");
    expect(first.state.items).toEqual([
      { collectionId: "first", status: "succeeded" },
      { collectionId: "third", status: "pending" },
    ]);

    const final = recordCollectionResult(first.state, {
      collectionId: "third",
      outcome: "succeeded",
      now: 300,
    });
    expect(final.requiresPageReload).toBe(false);
    expect(final.state.status).toBe("completed");
    expect(currentCollectionId(final.state)).toBeNull();
  });

  it("collection 失敗を記録して後続へ進み、成功/失敗 summary を保持する", () => {
    const initial = createCollectionQueue({
      queueId: "queue-2",
      baseUrl: "http://localhost:8765",
      collectionIds: ["first", "second"],
      runMode: "serial",
      regenerateDurationOutliers: false,
      now: 100,
    });

    const failed = recordCollectionResult(initial, {
      collectionId: "first",
      outcome: "failed",
      message: "playlist timeout",
      now: 200,
    });

    expect(failed.requiresPageReload).toBe(true);
    expect(currentCollectionId(failed.state)).toBe("second");
    expect(failed.state.items[0]).toEqual({
      collectionId: "first",
      status: "failed",
      message: "playlist timeout",
    });
  });

  it("中断 state は同じ collection から resume できる", () => {
    const initial = createCollectionQueue({
      queueId: "queue-3",
      baseUrl: "http://localhost:8765",
      collectionIds: ["first", "second"],
      runMode: "queue",
      regenerateDurationOutliers: true,
      now: 100,
    });
    const paused = { ...initial, status: "paused" as const, updatedAt: 150 };

    const resumed = resumeCollectionQueue(paused, 200);

    expect(resumed.status).toBe("running");
    expect(currentCollectionId(resumed)).toBe("first");
    expect(resumed.updatedAt).toBe(200);
  });

  it("queue id を run payload に保持して content 境界へ渡す", () => {
    const payload = buildRunPayload({
      entries: [
        { name: "pattern", style: "ambient", lyrics: "[Instrumental]" },
      ],
      playlistName: "Playlist",
      range: undefined,
      collectionId: "first",
      collectionQueueId: "queue-1",
      runMode: "queue",
      regenerateDurationOutliers: true,
      downloadEnabled: true,
      overrides: undefined,
    });

    expect(payload.collectionQueueId).toBe("queue-1");
  });

  it("entry failure を含む finished は collection failure として次へ進める", () => {
    const initial = createCollectionQueue({
      queueId: "queue-4",
      baseUrl: "http://localhost:8765",
      collectionIds: ["first", "second"],
      runMode: "queue",
      regenerateDurationOutliers: true,
      now: 100,
    });

    const settled = settleCollectionQueueRun(initial, {
      collectionId: "first",
      phase: "finished",
      failedEntryCount: 1,
      message: "1 entry failed",
      now: 200,
    });

    expect(settled.state.items[0]).toEqual({
      collectionId: "first",
      status: "failed",
      message: "1 entry failed",
    });
    expect(currentCollectionId(settled.state)).toBe("second");
    expect(settled.requiresPageReload).toBe(true);
  });

  it("明示 stop は current collection を進めず queue を pause する", () => {
    const initial = createCollectionQueue({
      queueId: "queue-5",
      baseUrl: "http://localhost:8765",
      collectionIds: ["first", "second"],
      runMode: "queue",
      regenerateDurationOutliers: true,
      now: 100,
    });

    const settled = settleCollectionQueueRun(initial, {
      collectionId: "first",
      phase: "stopped",
      failedEntryCount: 0,
      now: 200,
    });

    expect(settled.state.status).toBe("paused");
    expect(currentCollectionId(settled.state)).toBe("first");
    expect(settled.requiresPageReload).toBe(false);
  });
});
