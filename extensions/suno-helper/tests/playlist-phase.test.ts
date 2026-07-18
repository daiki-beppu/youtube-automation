// PHASE.ADDING_TO_PLAYLIST (#854) の snapshot / restore 契約テスト。
//
// 生成 FINISHED 直前に挟む新フェーズ。clip 一括 playlist 追加の進捗を表す。
// 既存の content SSOT 機構 (#852: initSnapshot / applyProgress / isTerminalPhase / buildRestoreState)
// に整合する形で組み込むことを担保する:
//   - 非終了 phase（isTerminalPhase=false、isRunning は true 継続）
//   - itemStates は不変（全 entry "done" のまま）
//   - playlistName を snapshot に保持し、popup 再 open 時に restore で復元できる
//
// 契約 (draft が実装すべき public API):
//   - PHASE.ADDING_TO_PLAYLIST: "adding-to-playlist" (shared/constants.ts)
//   - SnapshotPayload.playlistName?: string (shared/constants.ts)
//   - initSnapshot(entries, { collectionId, playlistName? }): SnapshotPayload (lib/snapshot.ts、playlistName を格納)
//   - RestoreState.playlistName?: string + buildRestoreState が surface する (components/runner-errors.ts)
import { describe, expect, it } from "vitest";

import { PHASE } from "../../shared/constants";
import { buildRestoreState } from "../components/runner-errors";
import {
  applyProgress,
  initSnapshot,
  isTerminalPhase,
  nextItemStates,
} from "../lib/snapshot";
import { makePromptEntries, snapshotOptions } from "./_helpers";

describe("PHASE.ADDING_TO_PLAYLIST: 列挙値", () => {
  it("Given PHASE When ADDING_TO_PLAYLIST を読む Then 文字列 adding-to-playlist である", () => {
    expect(PHASE.ADDING_TO_PLAYLIST).toBe("adding-to-playlist");
  });
});

describe("isTerminalPhase: ADDING_TO_PLAYLIST は非終了 phase", () => {
  it("Given ADDING_TO_PLAYLIST When 終了判定する Then false（以降も isRunning を継続する）", () => {
    expect(isTerminalPhase(PHASE.ADDING_TO_PLAYLIST)).toBe(false);
  });
});

describe("nextItemStates: ADDING_TO_PLAYLIST では itemStates 不変", () => {
  it("Given 全 done の itemStates When ADDING_TO_PLAYLIST を適用 Then prev と等価（遷移しない）", () => {
    const prev = ["done", "done", "done"] as const;

    expect(
      nextItemStates([...prev], {
        phase: PHASE.ADDING_TO_PLAYLIST,
        index: 0,
        total: 3,
      })
    ).toEqual([...prev]);
  });
});

describe("applyProgress: ADDING_TO_PLAYLIST は実行中を維持する", () => {
  it("Given 実行中 snap When ADDING_TO_PLAYLIST を適用 Then isRunning=true を維持する（非終了）", () => {
    const snap = initSnapshot(makePromptEntries(2), snapshotOptions());

    const next = applyProgress(snap, {
      phase: PHASE.ADDING_TO_PLAYLIST,
      total: 2,
      message: "rjn-dawn-cloud-fold",
    });

    expect(next.isRunning).toBe(true);
  });

  it("Given done 済み snap When ADDING_TO_PLAYLIST を適用 Then itemStates は不変（全 done のまま）", () => {
    let snap = initSnapshot(makePromptEntries(2), snapshotOptions());
    snap = applyProgress(snap, { phase: PHASE.DONE, index: 0, total: 2 });
    snap = applyProgress(snap, { phase: PHASE.DONE, index: 1, total: 2 });

    const next = applyProgress(snap, {
      phase: PHASE.ADDING_TO_PLAYLIST,
      total: 2,
      message: "rjn-dawn-cloud-fold",
    });

    expect(next.itemStates).toEqual(["done", "done"]);
  });
});

describe("initSnapshot: playlistName の格納", () => {
  it("Given playlistName 付き When initSnapshot Then snapshot に playlistName を保持する", () => {
    const snap = initSnapshot(
      makePromptEntries(2),
      snapshotOptions("rjn-dawn-cloud-fold")
    );

    expect(snap.playlistName).toBe("rjn-dawn-cloud-fold");
  });

  it("Given playlistName 無し When initSnapshot Then playlistName は undefined", () => {
    const snap = initSnapshot(makePromptEntries(2), snapshotOptions());

    expect(snap.playlistName).toBeUndefined();
  });
});

describe("applyProgress: playlistName を progress 更新間で保持する", () => {
  it("Given playlistName 付き snap When progress を適用 Then playlistName を破棄せず維持する", () => {
    const snap = initSnapshot(
      makePromptEntries(2),
      snapshotOptions("rjn-dawn-cloud-fold")
    );

    const next = applyProgress(snap, {
      phase: PHASE.ADDING_TO_PLAYLIST,
      total: 2,
      message: "rjn-dawn-cloud-fold",
    });

    expect(next.playlistName).toBe("rjn-dawn-cloud-fold");
  });
});

describe("buildRestoreState: playlistName を復元 state へ surface する", () => {
  it("Given playlistName 付き snapshot When buildRestoreState Then playlistName を復元する（再 open 時の display 用）", () => {
    const snap = applyProgress(
      initSnapshot(
        makePromptEntries(2),
        snapshotOptions("rjn-dawn-cloud-fold")
      ),
      {
        phase: PHASE.ADDING_TO_PLAYLIST,
        total: 2,
        message: "rjn-dawn-cloud-fold",
      }
    );

    const restored = buildRestoreState(snap);

    expect(restored?.playlistName).toBe("rjn-dawn-cloud-fold");
  });

  it("Given playlistName 無し snapshot When buildRestoreState Then playlistName は undefined", () => {
    const snap = applyProgress(
      initSnapshot(makePromptEntries(2), snapshotOptions()),
      {
        phase: PHASE.FINISHED,
        total: 2,
      }
    );

    const restored = buildRestoreState(snap);

    expect(restored?.playlistName).toBeUndefined();
  });
});
