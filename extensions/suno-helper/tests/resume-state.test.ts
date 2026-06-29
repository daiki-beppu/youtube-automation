// lib/resume-state.ts の純ロジック回帰テスト (#872)。
//
// resume-state は「失敗 index の永続化」と「範囲指定実行」を支える純関数群を集約する。
// Vitest env は node（chrome モック無し, vitest.config.ts）のため、storage.defineItem を包む
// I/O (readResumeState / writeResumeState / clearResumeStateForCollection) はここでは検証せず、
// node でテスト可能な純関数のみを tester surface とする（既存 lib/storage.ts が untested なのと同方針）。
//   - shouldShowResumeBanner: 起動時バナー表示条件（collection 一致 + stale 判定）。要件4
//   - resolveRunRange: 1-based UI 入力 → 0-based inclusive range への変換 + バリデーション。要件1/2
//   - resumeBannerRange: バナー承認時に range UI へ prefill する 1-based start/end。要件4
import { describe, expect, it } from "vitest";

import {
  RESUME_STALE_MS,
  resolvePlaylistClipIds,
  resolvePlaylistExpectedClipCountForResume,
  resolveInterruptIndex,
  resolveRunRange,
  resumeBannerRange,
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

  it("Given 選択中 collectionId が空文字 When 判定 Then 表示しない（単一ファイル mode）", () => {
    const state = makeResumeState({ timestamp: NOW - HOUR_MS });
    expect(shouldShowResumeBanner(state, "", NOW)).toBe(false);
  });
});

describe("resolveRunRange: 1-based UI 入力 → 0-based inclusive range (要件1/2)", () => {
  it("Given start のみ (5, undefined, total=24) When 変換 Then end=total-1 まで（省略時は末尾）", () => {
    expect(resolveRunRange(5, undefined, 24)).toEqual({ start: 4, end: 23 });
  });

  it("Given start+end (5, 8, total=24) When 変換 Then 0-based inclusive {4, 7}（entry 5〜8）", () => {
    expect(resolveRunRange(5, 8, 24)).toEqual({ start: 4, end: 7 });
  });

  it("Given start=1, end=total When 変換 Then 全域 {0, total-1}（従来の全実行と等価）", () => {
    expect(resolveRunRange(1, 24, 24)).toEqual({ start: 0, end: 23 });
  });

  it("Given start=end (同一 entry) When 変換 Then 単一要素 range を返す", () => {
    expect(resolveRunRange(7, 7, 24)).toEqual({ start: 6, end: 6 });
  });

  it("Given start < 1 When 変換 Then throw（1-based の下限違反は fail-loud）", () => {
    expect(() => resolveRunRange(0, undefined, 24)).toThrow();
  });

  it("Given start > total When 変換 Then throw（範囲外の開始）", () => {
    expect(() => resolveRunRange(25, undefined, 24)).toThrow();
  });

  it("Given end < start When 変換 Then throw（逆転 range）", () => {
    expect(() => resolveRunRange(8, 5, 24)).toThrow();
  });

  it("Given end > total When 変換 Then throw（範囲外の終了）", () => {
    expect(() => resolveRunRange(5, 25, 24)).toThrow();
  });

  it("Given start が非整数 (NaN) When 変換 Then throw（空入力の取りこぼしを silent 通過させない）", () => {
    expect(() => resolveRunRange(Number.NaN, undefined, 24)).toThrow();
  });

  it("Given end が非整数 (NaN) When 変換 Then throw", () => {
    expect(() => resolveRunRange(5, Number.NaN, 24)).toThrow();
  });
});

describe("resumeBannerRange: バナー承認時の range prefill (要件4)", () => {
  it("Given failedIndex=19, total=24 When 算出 Then 1-based {start: failedIndex+1, end: total}", () => {
    const state = makeResumeState({ failedIndex: 19, total: 24 });
    expect(resumeBannerRange(state)).toEqual({ start: 20, end: 24 });
  });

  it("Given failedIndex=0 (先頭で失敗), total=3 When 算出 Then {start: 1, end: 3}", () => {
    const state = makeResumeState({ failedIndex: 0, total: 3 });
    expect(resumeBannerRange(state)).toEqual({ start: 1, end: 3 });
  });
});

describe("round-trip: バナー prefill → run range が「失敗 index..末尾」を絶対 index で再現する", () => {
  it("Given failedIndex=19/total=24 When resumeBannerRange → resolveRunRange Then 0-based {19, 23}（判断A: 絶対 index 維持）", () => {
    const state = makeResumeState({ failedIndex: 19, total: 24 });

    const prefilled = resumeBannerRange(state); // 1-based UI 値
    const range = resolveRunRange(prefilled.start, prefilled.end, state.total); // content へ渡す 0-based

    expect(range).toEqual({ start: 19, end: 23 });
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
