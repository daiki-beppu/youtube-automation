// SnapshotPayload.failedIndex の回帰テスト (#872 要件3)。
//
// ERROR 停止時の失敗 index は chrome.storage に永続化される一方、popup の進捗復元と二重化するため
// SnapshotPayload にも保持する。applyProgress は ERROR phase でのみ failedIndex を index 値に確定させ、
// それ以外の phase では既存値を保つ（純関数なので node でテスト可能）。
import { describe, expect, it } from "vitest";

import { PHASE } from "../../shared/constants";
import { applyProgress, initSnapshot } from "../lib/snapshot";
import { makePromptEntries, snapshotOptions } from "./_helpers";

describe("snapshot.failedIndex: ERROR 停止 index の二重化 (#872)", () => {
  it("Given initSnapshot 直後 When failedIndex を読む Then 未確定 (undefined)", () => {
    const snap = initSnapshot(makePromptEntries(3), snapshotOptions());
    expect(snap.failedIndex).toBeUndefined();
  });

  it("Given INJECTING など非 ERROR phase When applyProgress Then failedIndex は未確定のまま", () => {
    let snap = initSnapshot(makePromptEntries(3), snapshotOptions());
    snap = applyProgress(snap, { phase: PHASE.INJECTING, index: 1, total: 3 });
    snap = applyProgress(snap, { phase: PHASE.DONE, index: 1, total: 3 });
    expect(snap.failedIndex).toBeUndefined();
  });

  it("Given ERROR phase (index=1) When applyProgress Then failedIndex=1 を確定する", () => {
    const snap = applyProgress(initSnapshot(makePromptEntries(3), snapshotOptions()), {
      phase: PHASE.ERROR,
      index: 1,
      total: 3,
      message: "entry 1 の inject が silent drop されました。",
    });
    expect(snap.failedIndex).toBe(1);
  });

  it("Given 進行後に ERROR (index=2) When applyProgress Then 直近の失敗 index を確定する", () => {
    let snap = initSnapshot(makePromptEntries(3), snapshotOptions());
    snap = applyProgress(snap, { phase: PHASE.DONE, index: 0, total: 3 });
    snap = applyProgress(snap, { phase: PHASE.DONE, index: 1, total: 3 });
    snap = applyProgress(snap, { phase: PHASE.ERROR, index: 2, total: 3, message: "stop" });
    expect(snap.failedIndex).toBe(2);
  });
});

describe("applyProgress: ENTRY_FAILED で failedIndices を蓄積する (#948)", () => {
  it("Given ENTRY_FAILED を 2 回受信 When 適用する Then failedIndices に蓄積され itemStates が failed になる", () => {
    const entries = [
      { name: "p1", style: "s" },
      { name: "p2", style: "s" },
      { name: "p3", style: "s" },
    ] as Parameters<typeof initSnapshot>[0];
    let snap = initSnapshot(entries, snapshotOptions());

    snap = applyProgress(snap, { phase: PHASE.ENTRY_FAILED, index: 0, total: 3, message: "x" });
    snap = applyProgress(snap, { phase: PHASE.DONE, index: 1, total: 3 });
    snap = applyProgress(snap, { phase: PHASE.ENTRY_FAILED, index: 2, total: 3, message: "y" });

    expect(snap.failedIndices).toEqual([0, 2]);
    expect(snap.itemStates).toEqual(["failed", "done", "failed"]);
    expect(snap.isRunning).toBe(true); // 非終了 phase（run 全体は継続）
  });

  it("Given FINISHED（失敗付き完走） When 適用する Then failedIndices を保持したまま isRunning=false", () => {
    const entries = [{ name: "p1", style: "s" }] as Parameters<typeof initSnapshot>[0];
    let snap = initSnapshot(entries, snapshotOptions());
    snap = applyProgress(snap, { phase: PHASE.ENTRY_FAILED, index: 0, total: 1, message: "x" });
    snap = applyProgress(snap, { phase: PHASE.FINISHED, total: 1, message: "1 件失敗" });

    expect(snap.failedIndices).toEqual([0]);
    expect(snap.isRunning).toBe(false);
  });
});
