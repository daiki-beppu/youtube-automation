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
import { makePromptEntries } from "./_helpers";

describe("buildRestoreState: snapshot 無し (silent fallback)", () => {
  it("Given null When buildRestoreState Then null を返す（復元せず従来表示へフォールバック）", () => {
    expect(buildRestoreState(null)).toBeNull();
  });
});

describe("buildRestoreState: 実行中 snapshot の復元", () => {
  it("Given 注入中 snapshot When buildRestoreState Then entries / itemStates / isRunning / status を復元する", () => {
    const entries = makePromptEntries(3);
    const snap = applyProgress(initSnapshot(entries), { phase: PHASE.INJECTING, index: 0, total: 3 });

    const restored = buildRestoreState(snap);

    expect(restored).toEqual({
      entries,
      itemStates: ["active", "idle", "idle"],
      isRunning: true,
      status: "[1/3] 注入中: pattern-1",
      isError: false,
    });
  });

  it("Given 一部 done + 注入中 snapshot When buildRestoreState Then 進行済みの itemStates を維持して復元する", () => {
    const entries = makePromptEntries(3);
    let snap = applyProgress(initSnapshot(entries), { phase: PHASE.DONE, index: 0, total: 3 });
    snap = applyProgress(snap, { phase: PHASE.DONE, index: 1, total: 3 });
    snap = applyProgress(snap, { phase: PHASE.INJECTING, index: 2, total: 3 });

    const restored = buildRestoreState(snap);

    expect(restored?.itemStates).toEqual(["done", "done", "active"]);
    expect(restored?.status).toBe("[3/3] 注入中: pattern-3");
    expect(restored?.isRunning).toBe(true);
  });
});

describe("buildRestoreState: 終了済み snapshot の復元", () => {
  it("Given FINISHED snapshot When buildRestoreState Then isRunning=false + 完了文言を復元する", () => {
    const entries = makePromptEntries(3);
    const snap = applyProgress(initSnapshot(entries), { phase: PHASE.FINISHED, total: 3 });

    const restored = buildRestoreState(snap);

    expect(restored?.isRunning).toBe(false);
    expect(restored?.status).toBe("完了: 3 パターンを実行しました。");
    expect(restored?.isError).toBe(false);
    expect(restored?.entries).toEqual(entries);
  });

  it("Given STOPPED snapshot When buildRestoreState Then isRunning=false + 停止文言 + isError=true を復元する", () => {
    const snap = applyProgress(initSnapshot(makePromptEntries(2)), { phase: PHASE.STOPPED, index: 0, total: 2 });

    const restored = buildRestoreState(snap);

    expect(restored?.isRunning).toBe(false);
    expect(restored?.status).toBe("停止しました。手動で続行できます。");
    expect(restored?.isError).toBe(true);
  });

  it("Given ERROR snapshot When buildRestoreState Then isRunning=false + 中断文言 + isError=true を復元する", () => {
    const snap = applyProgress(initSnapshot(makePromptEntries(2)), {
      phase: PHASE.ERROR,
      index: 1,
      total: 2,
      message: "Lyrics 欄が見つかりません。",
    });

    const restored = buildRestoreState(snap);

    expect(restored?.isRunning).toBe(false);
    expect(restored?.status).toBe("中断: Lyrics 欄が見つかりません。");
    expect(restored?.isError).toBe(true);
  });
});
