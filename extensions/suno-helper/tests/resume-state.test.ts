// lib/resume-state.ts の純ロジック回帰テスト (#872)。
//
// resume-state は「失敗 index の永続化」と「1-click 再開実行」を支える純関数群を集約する。
// Vitest env は node（chrome モック無し, vitest.config.ts）のため、storage.defineItem を包む
// I/O (readResumeState / writeResumeState / clearResumeStateForCollection) はここでは検証せず、
// node でテスト可能な純関数のみを tester surface とする（既存 lib/storage.ts が untested なのと同方針）。
//   - shouldShowResumeBanner: 起動時バナー表示条件（collection 一致 + stale 判定）。要件4
//   - resumeRunRange: バナー承認時に run() へ直接渡す 0-based inclusive range。要件6
import { describe, expect, it } from "vitest";

import {
  RESUME_STALE_MS,
  resolvePlaylistClipIds,
  resolvePlaylistExpectedClipCountForResume,
  resolveInterruptIndex,
  resumeRunRange,
  shouldShowResumeBanner,
} from "../lib/resume-state";
import type { ResumeState } from "../lib/resume-state";

const HOUR_MS = 60 * 60 * 1000;
const DAY_MS = 24 * HOUR_MS;
// テスト基準の「現在時刻」。Date.now を注入できるよう shouldShowResumeBanner は now を引数で受ける。
const NOW = 1_700_000_000_000;

function makeResumeState(overrides: Partial<ResumeState> = {}): ResumeState {
  return {
    collectionId: "20260601-clm-night-collection",
    failedIndex: 19,
    total: 24,
    timestamp: NOW - HOUR_MS,
    ...overrides,
  };
}

describe("RESUME_STALE_MS: stale 判定の既定閾値", () => {
  it("Given 定数 When 読む Then 24 時間 (ms) である（要件4 の stale 既定値）", () => {
    expect(RESUME_STALE_MS).toBe(DAY_MS);
  });
});

describe("shouldShowResumeBanner: 起動時バナーの表示条件 (要件4)", () => {
  it("Given state=null When 判定 Then 表示しない（resume 履歴なし）", () => {
    expect(shouldShowResumeBanner(null, "20260601-clm-night-collection", NOW)).toBe(false);
  });

  it("Given collectionId 一致 + 1 時間前 When 判定 Then 表示する", () => {
    const state = makeResumeState({ timestamp: NOW - HOUR_MS });
    expect(shouldShowResumeBanner(state, state.collectionId, NOW)).toBe(true);
  });

  it("Given collectionId 一致 + ちょうど 24 時間前 When 判定 Then 表示する（境界は inclusive）", () => {
    const state = makeResumeState({ timestamp: NOW - DAY_MS });
    expect(shouldShowResumeBanner(state, state.collectionId, NOW)).toBe(true);
  });

  it("Given collectionId 一致 + 24 時間 + 1ms 前 When 判定 Then 表示しない（stale）", () => {
    const state = makeResumeState({ timestamp: NOW - DAY_MS - 1 });
    expect(shouldShowResumeBanner(state, state.collectionId, NOW)).toBe(false);
  });

  it("Given collectionId 不一致（fresh でも）When 判定 Then 表示しない（別 collection 選択中）", () => {
    const state = makeResumeState({ timestamp: NOW - HOUR_MS });
    expect(shouldShowResumeBanner(state, "20260601-clm-other-collection", NOW)).toBe(false);
  });

  it("Given 選択中 collectionId が空文字 When 判定 Then 表示しない（collection 不一致）", () => {
    const state = makeResumeState({ timestamp: NOW - HOUR_MS });
    expect(shouldShowResumeBanner(state, "", NOW)).toBe(false);
  });
});

describe("resumeRunRange: バナー承認時の direct run range (要件6)", () => {
  it("Given failedIndex=19, total=24 When 算出 Then 失敗 entry から末尾までの 0-based range を返す", () => {
    const state = makeResumeState({ failedIndex: 19, total: 24 });
    expect(resumeRunRange(state)).toEqual({ start: 19, end: 23 });
  });

  it("Given failedIndex=0 (先頭で失敗), total=3 When 算出 Then 全域 {0, 2} を返す", () => {
    const state = makeResumeState({ failedIndex: 0, total: 3 });
    expect(resumeRunRange(state)).toEqual({ start: 0, end: 2 });
  });
});

describe("resolveInterruptIndex: 中断時の「次に実行する index」決定 (#924)", () => {
  it("Given submitted=false When 算出 Then i（click 前の中断・エラーなので当該 entry を再生成する）", () => {
    expect(resolveInterruptIndex(5, false, false)).toBe(5);
  });

  it("Given submitted=true, isNotAcknowledged=false When 算出 Then i+1（投入済み受理確認済み: 次の entry から再開）", () => {
    expect(resolveInterruptIndex(5, true, false)).toBe(6);
  });

  it("Given submitted=true, isNotAcknowledged=true When 算出 Then i（silent drop 確定: 当該 entry を再生成する）", () => {
    expect(resolveInterruptIndex(5, true, true)).toBe(5);
  });

  it("Given i=total-1 (末尾), submitted=true, isNotAcknowledged=false When 算出 Then total になり playlist-phase persist と同義", () => {
    const total = 24;
    const i = total - 1; // 最後の entry
    const interruptIndex = resolveInterruptIndex(i, true, false);
    expect(interruptIndex).toBe(total); // = 24

    // resumeRunRange({ failedIndex: total, total }) → { start: total, end: total-1 } → 0 回ループ
    // → playlist 追加のみ実行される round-trip を確認する。
    const range = resumeRunRange({ failedIndex: interruptIndex, total });
    expect(range).toEqual({ start: total, end: total - 1 }); // start > end → 0 回ループ
  });
});

describe("resolvePlaylistClipIds: resume を跨ぐ playlist 対象 ID 解決 (#1183)", () => {
  it("Given 失敗分のみ再実行の前回 ID と今回 ID When 合成 Then 全 collection 分を順序維持で返す", () => {
    expect(resolvePlaylistClipIds(["old-a", "old-b"], ["fresh-a", "fresh-b"], 4)).toEqual([
      "old-a",
      "old-b",
      "fresh-a",
      "fresh-b",
    ]);
  });

  it("Given playlist-only resume の保存済み ID When 今回 ID が空 Then 保存済み ID だけで全件を返す", () => {
    expect(resolvePlaylistClipIds(["clip-a", "clip-b"], [], 2)).toEqual(["clip-a", "clip-b"]);
  });

  it("Given 重複 ID が混ざる When 合成 Then 重複を除外して件数検証する", () => {
    expect(resolvePlaylistClipIds(["clip-a", "clip-b"], ["clip-b", "clip-c"], 3)).toEqual([
      "clip-a",
      "clip-b",
      "clip-c",
    ]);
  });

  it("Given 合成後も不足 When 解決 Then 部分 playlist を作らず throw する", () => {
    expect(() => resolvePlaylistClipIds(["clip-a"], ["clip-b"], 4)).toThrow(
      "playlist 対象の clip ID 数が不足しています: expected 4, got 2",
    );
  });

  it("Given 0 件 When 解決 Then throw する", () => {
    expect(() => resolvePlaylistClipIds([], [], 4)).toThrow("playlist 対象の clip ID が 0 件です");
  });
});

describe("resolvePlaylistExpectedClipCountForResume: 旧 resume state の期待件数復元 (#1183)", () => {
  it("Given 保存済み期待件数がある When 解決 Then その値を使う", () => {
    expect(resolvePlaylistExpectedClipCountForResume(22, 12)).toBe(22);
  });

  it("Given 旧 ResumeState で期待件数が無い When 解決 Then total entries x 2 clips を期待件数にする", () => {
    expect(resolvePlaylistExpectedClipCountForResume(undefined, 12)).toBe(24);
  });
});
