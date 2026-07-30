// 完了時リロード後の進捗復元 (#1411 followup) を支える退避 snapshot の stale 判定テスト。
//
// リロードは content script の in-memory snapshot（queryProgress の復元 SSOT, #852）を破棄する。
// FINISHED 到達時に chrome.storage.local へ退避した snapshot を復元ソースにするが、古い退避分を
// いつまでも「直近完了 run の結果」として出さないよう、timestamp による鮮度判定を純関数で担保する。
// now を注入可能にし、時刻依存を排してテストする（resume-state の shouldShowResumeBanner と同じ規約）。
import { beforeEach, describe, expect, it, vi } from "vitest";

const finishedStorage = vi.hoisted(() => ({
  getValue: vi.fn(),
  setValue: vi.fn(),
  defineItem: vi.fn(),
}));

vi.mock("wxt/utils/storage", () => ({
  storage: {
    defineItem: finishedStorage.defineItem.mockReturnValue(finishedStorage),
  },
}));

import { PHASE } from "../../shared/constants";
import {
  FINISHED_SNAPSHOT_STALE_MS,
  clearFinishedSnapshot,
  type FinishedSnapshotState,
  isFinishedSnapshotFresh,
  readFreshFinishedSnapshot,
  writeFinishedSnapshot,
} from "../lib/finished-snapshot";
import { applyProgress, initSnapshot } from "../lib/snapshot";
import { makePromptEntries, snapshotOptions } from "./_helpers";

function makeFinishedState(timestamp: number): FinishedSnapshotState {
  const snapshot = applyProgress(
    initSnapshot(makePromptEntries(2), snapshotOptions("pl")),
    {
      phase: PHASE.FINISHED,
      total: 2,
    }
  );
  return { snapshot, timestamp };
}

describe("isFinishedSnapshotFresh: 退避 snapshot の鮮度判定", () => {
  const NOW = 1_700_000_000_000;

  it("Given state 無し (null) When 判定 Then false（復元しない）", () => {
    expect(isFinishedSnapshotFresh(null, NOW)).toBe(false);
  });

  it("Given 退避直後の state When 判定 Then true", () => {
    expect(isFinishedSnapshotFresh(makeFinishedState(NOW), NOW)).toBe(true);
  });

  it("Given ちょうど閾値経過の state When 判定 Then true（境界は inclusive、shouldShowResumeBanner と同じ規約）", () => {
    expect(
      isFinishedSnapshotFresh(
        makeFinishedState(NOW - FINISHED_SNAPSHOT_STALE_MS),
        NOW
      )
    ).toBe(true);
  });

  it("Given 閾値を 1ms 超えた state When 判定 Then false（stale）", () => {
    expect(
      isFinishedSnapshotFresh(
        makeFinishedState(NOW - FINISHED_SNAPSHOT_STALE_MS - 1),
        NOW
      )
    ).toBe(false);
  });
});

describe("finished snapshot storage I/O (#2899)", () => {
  const NOW = 1_700_000_000_000;

  beforeEach(() => {
    vi.clearAllMocks();
    finishedStorage.getValue.mockResolvedValue(null);
    finishedStorage.setValue.mockResolvedValue(undefined);
  });

  it("write/read/clear を同じ storage item へ委譲する", async () => {
    const state = makeFinishedState(NOW);
    finishedStorage.getValue.mockResolvedValueOnce(state);

    await writeFinishedSnapshot(state);
    await expect(readFreshFinishedSnapshot(NOW)).resolves.toBe(state.snapshot);
    await clearFinishedSnapshot();

    expect(finishedStorage.defineItem).toHaveBeenCalledWith(
      "local:sunoFinishedSnapshot",
      { fallback: null }
    );
    expect(finishedStorage.setValue).toHaveBeenNthCalledWith(1, state);
    expect(finishedStorage.setValue).toHaveBeenNthCalledWith(2, null);
  });

  it("stale read は null を返し storage の stale 値を一度だけ null 保存する", async () => {
    finishedStorage.getValue.mockResolvedValueOnce(
      makeFinishedState(NOW - FINISHED_SNAPSHOT_STALE_MS - 1)
    );

    await expect(readFreshFinishedSnapshot(NOW)).resolves.toBeNull();
    await vi.waitFor(() =>
      expect(finishedStorage.setValue).toHaveBeenCalledOnce()
    );
    expect(finishedStorage.setValue).toHaveBeenCalledWith(null);
  });

  it("未保存 read は null を返して storage を変更しない", async () => {
    await expect(readFreshFinishedSnapshot(NOW)).resolves.toBeNull();
    expect(finishedStorage.setValue).not.toHaveBeenCalled();
  });
});
