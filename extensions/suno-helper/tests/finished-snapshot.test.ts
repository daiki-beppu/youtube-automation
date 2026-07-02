// 完了時リロード後の進捗復元 (#1411 followup) を支える退避 snapshot の stale 判定テスト。
//
// リロードは content script の in-memory snapshot（queryProgress の復元 SSOT, #852）を破棄する。
// FINISHED 到達時に chrome.storage.local へ退避した snapshot を復元ソースにするが、古い退避分を
// いつまでも「直近完了 run の結果」として出さないよう、timestamp による鮮度判定を純関数で担保する。
// now を注入可能にし、時刻依存を排してテストする（resume-state の shouldShowResumeBanner と同じ規約）。
import { describe, expect, it } from "vitest";

import { PHASE } from "../../shared/constants";
import {
  FINISHED_SNAPSHOT_STALE_MS,
  type FinishedSnapshotState,
  isFinishedSnapshotFresh,
} from "../lib/finished-snapshot";
import { applyProgress, initSnapshot } from "../lib/snapshot";
import { makePromptEntries } from "./_helpers";

function makeFinishedState(timestamp: number): FinishedSnapshotState {
  const snapshot = applyProgress(initSnapshot(makePromptEntries(2), "pl"), { phase: PHASE.FINISHED, total: 2 });
  return { snapshot, collectionId: "coll-1", timestamp };
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
    expect(isFinishedSnapshotFresh(makeFinishedState(NOW - FINISHED_SNAPSHOT_STALE_MS), NOW)).toBe(true);
  });

  it("Given 閾値を 1ms 超えた state When 判定 Then false（stale）", () => {
    expect(isFinishedSnapshotFresh(makeFinishedState(NOW - FINISHED_SNAPSHOT_STALE_MS - 1), NOW)).toBe(false);
  });
});
