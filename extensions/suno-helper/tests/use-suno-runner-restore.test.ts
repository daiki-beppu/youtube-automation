// buildRestoreState (#852) の回帰テスト。
//
// popup の mount 時に content から取得した snapshot を、popup state へ復元するための
// 純関数。useSunoRunner の restore effect はこの戻り値を setEntries / setItemStates /
// setIsRunning / report にそのまま流す。content がまだ実行履歴を持たない (null) 場合は
// 復元せず従来表示にフォールバックするため null を返す（silent fallback の根拠）。
//
// @testing-library/react は未導入のため、フック本体ではなく抽出した純関数を tester surface とする。
import { describe, expect, it } from "vitest";

import { PHASE } from "../../shared/constants";
import { buildRestoreState } from "../components/runner-errors";
import { applyProgress, initSnapshot } from "../lib/snapshot";
import {
  makePromptEntries,
  snapshotOptions,
  TEST_COLLECTION_ID,
} from "./_helpers";

describe("buildRestoreState: snapshot 無し (silent fallback)", () => {
  it("Given null When buildRestoreState Then null を返す（復元せず従来表示へフォールバック）", () => {
    expect(buildRestoreState(null)).toBeNull();
  });
});

describe("buildRestoreState: 実行中 snapshot の復元", () => {
  it("Given 注入中 snapshot When buildRestoreState Then entries / itemStates / isRunning / status を復元する", () => {
    const entries = makePromptEntries(3);
    const snap = applyProgress(initSnapshot(entries, snapshotOptions()), {
      phase: PHASE.INJECTING,
      index: 0,
      total: 3,
    });

    const restored = buildRestoreState(snap);

    expect(restored).toEqual({
      collectionId: TEST_COLLECTION_ID,
      entries,
      itemStates: ["active", "idle", "idle"],
      isRunning: true,
      status: "[1/3] 注入中: pattern-1",
      isError: false,
      regenerateDurationOutliers: true,
      durationOutlierWarnings: {},
    });
  });

  it("Given 一部 done + 注入中 snapshot When buildRestoreState Then 進行済みの itemStates を維持して復元する", () => {
    const entries = makePromptEntries(3);
    let snap = applyProgress(initSnapshot(entries, snapshotOptions()), {
      phase: PHASE.DONE,
      index: 0,
      total: 3,
    });
    snap = applyProgress(snap, { phase: PHASE.DONE, index: 1, total: 3 });
    snap = applyProgress(snap, { phase: PHASE.INJECTING, index: 2, total: 3 });

    const restored = buildRestoreState(snap);

    expect(restored?.itemStates).toEqual(["done", "done", "active"]);
    expect(restored?.status).toBe("[3/3] 注入中: pattern-3");
    expect(restored?.isRunning).toBe(true);
  });

  it("Given duration-check log 付き snapshot When buildRestoreState Then duration log 文言を復元する", () => {
    const snap = applyProgress(
      initSnapshot(makePromptEntries(3), snapshotOptions()),
      {
        phase: PHASE.DONE,
        index: 1,
        total: 3,
        log: {
          kind: "duration-check",
          entryName: "pattern-2",
          durationSec: 259,
          ok: true,
          maxSec: 300,
        },
      }
    );

    const restored = buildRestoreState(snap);

    expect(restored?.status).toBe('"pattern-2": 259s ✓');
    expect(restored?.isError).toBe(false);
  });

  it("Given 再生成 OFF warning 付き DONE snapshot When buildRestoreState Then warning 文言とdone stateを復元する", () => {
    const snap = applyProgress(
      initSnapshot(makePromptEntries(1), {
        ...snapshotOptions(),
        regenerateDurationOutliers: false,
      }),
      {
        phase: PHASE.DONE,
        index: 0,
        total: 1,
        message:
          "duration guard NG; 再生成 OFF のため全 clip を採用候補として保持します",
        durationOutlierWarning:
          "duration guard NG; 再生成 OFF のため全 clip を採用候補として保持します",
        acceptedClipIds: ["clip-ng-a", "clip-ng-b"],
      }
    );

    const finished = applyProgress(snap, { phase: PHASE.FINISHED, total: 1 });
    const restored = buildRestoreState(finished);

    expect(restored?.status).toContain("異常値警告");
    expect(restored?.status).toContain("duration guard NG");
    expect(restored?.itemStates).toEqual(["done"]);
    expect(restored?.regenerateDurationOutliers).toBe(false);
  });

  it("Given retry log 付き snapshot When buildRestoreState Then retry 文言を復元する", () => {
    const snap = applyProgress(
      initSnapshot(makePromptEntries(3), snapshotOptions()),
      {
        phase: PHASE.WAITING_SLOT,
        index: 1,
        total: 3,
        log: { kind: "retry", entryName: "pattern-2", attempt: 1, max: 2 },
      }
    );

    const restored = buildRestoreState(snap);

    expect(restored?.status).toBe('"pattern-2": リトライ 1/2');
    expect(restored?.isError).toBe(false);
  });

  it("Given skip log 付き snapshot When buildRestoreState Then skip 文言と失敗理由を復元する", () => {
    const snap = applyProgress(
      initSnapshot(makePromptEntries(3), snapshotOptions()),
      {
        phase: PHASE.ENTRY_FAILED,
        index: 1,
        total: 3,
        message: "queue timeout",
        log: { kind: "skip", entryName: "pattern-2" },
      }
    );

    const restored = buildRestoreState(snap);

    expect(restored?.status).toBe(
      '"pattern-2": 全滅 — スキップ: queue timeout'
    );
    expect(restored?.isError).toBe(false);
  });
});

describe("buildRestoreState: 終了済み snapshot の復元", () => {
  it("Given FINISHED snapshot When buildRestoreState Then isRunning=false + 完了文言を復元する", () => {
    const entries = makePromptEntries(3);
    const snap = applyProgress(initSnapshot(entries, snapshotOptions()), {
      phase: PHASE.FINISHED,
      total: 3,
    });

    const restored = buildRestoreState(snap);

    expect(restored?.isRunning).toBe(false);
    expect(restored?.status).toBe("完了: 3 パターンを実行しました。");
    expect(restored?.isError).toBe(false);
    expect(restored?.entries).toEqual(entries);
  });

  it("Given STOPPED snapshot When buildRestoreState Then isRunning=false + 再実行可能な停止文言を復元する", () => {
    const snap = applyProgress(
      initSnapshot(makePromptEntries(2), snapshotOptions()),
      {
        phase: PHASE.STOPPED,
        index: 0,
        total: 2,
      }
    );

    const restored = buildRestoreState(snap);

    expect(restored?.isRunning).toBe(false);
    expect(restored?.status).toBe("停止しました。再実行できます。");
    expect(restored?.isError).toBe(false);
  });

  it("Given ERROR snapshot When buildRestoreState Then isRunning=false + 中断文言 + isError=true を復元する", () => {
    const snap = applyProgress(
      initSnapshot(makePromptEntries(2), snapshotOptions()),
      {
        phase: PHASE.ERROR,
        index: 1,
        total: 2,
        message: "Lyrics 欄が見つかりません。",
      }
    );

    const restored = buildRestoreState(snap);

    expect(restored?.isRunning).toBe(false);
    expect(restored?.status).toBe("中断: Lyrics 欄が見つかりません。");
    expect(restored?.isError).toBe(true);
  });
});

// #872 要件3: snapshot.failedIndex を popup の進捗復元と二重化する。buildRestoreState が
// failedIndex を surface し、restore effect が再開バナーの冗長ソースとして消費する経路を担保する
// （write-only な dead field への退行防止）。
describe("buildRestoreState: failedIndex の surface (#872 要件3 二重化)", () => {
  it("Given ERROR snapshot (index=1) When buildRestoreState Then failedIndex=1 を surface する", () => {
    const snap = applyProgress(
      initSnapshot(makePromptEntries(3), snapshotOptions()),
      {
        phase: PHASE.ERROR,
        index: 1,
        total: 3,
        message: "stop",
      }
    );

    expect(buildRestoreState(snap)?.failedIndex).toBe(1);
  });

  it("Given 非 ERROR snapshot When buildRestoreState Then failedIndex は undefined（確定前は surface しない）", () => {
    const snap = applyProgress(
      initSnapshot(makePromptEntries(3), snapshotOptions()),
      {
        phase: PHASE.INJECTING,
        index: 0,
        total: 3,
      }
    );

    expect(buildRestoreState(snap)?.failedIndex).toBeUndefined();
  });

  it("Given collectionId 付き snapshot When buildRestoreState Then collectionId を surface する", () => {
    const snap = initSnapshot(makePromptEntries(2), {
      collectionId: "20260601-clm-theme-a-collection",
      playlistName: "clm | theme-a",
    });

    expect(buildRestoreState(snap)?.collectionId).toBe(
      "20260601-clm-theme-a-collection"
    );
  });

  it("Given durationFilter 付き snapshot When buildRestoreState Then durationFilter を surface する", () => {
    const durationFilter = { min_sec: 75, max_sec: 180 };
    const snap = initSnapshot(makePromptEntries(2), {
      collectionId: "20260601-clm-theme-a-collection",
      playlistName: "clm | theme-a",
      durationFilter,
    });

    expect(buildRestoreState(snap)?.durationFilter).toEqual(durationFilter);
  });

  it("Given option OFF の snapshot When buildRestoreState Then OFF を surface する", () => {
    const snap = initSnapshot(makePromptEntries(2), {
      collectionId: "20260601-clm-theme-a-collection",
      regenerateDurationOutliers: false,
    });

    expect(buildRestoreState(snap)?.regenerateDurationOutliers).toBe(false);
  });
});
