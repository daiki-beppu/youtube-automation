// 1-click 自動再開 (#892 要件6) の range 構築ロジックの回帰テスト。
//
// 現行挙動 (要件6): 「再開」1 クリックで run() まで自動実行する。React state は次レンダ反映で
//         closure から読めないため、acceptResume は 0-based inclusive な RunRange を
//         ローカルに構築して run({ range }) へ引数で渡す（order.md §2）。
//
// その「0-based RunRange 構築」を純関数 resumeRunRange へ抽出して tester surface とする
// （@testing-library/react 未導入のため、フック本体ではなく純関数で担保する＝既存 plan §6 の推奨）。
//   export function resumeRunRange(banner: ResumeBanner): RunRange
//   // 失敗 entry (0-based failedIndex) から末尾 (total-1) までの絶対 index を返す。
import { describe, expect, it } from "vitest";

import { resumeRunRange } from "../lib/resume-state";
import type { ResumeBanner } from "../lib/resume-state";
import {
  buildFailedEntriesRunOverrides,
  buildResumeRunOverrides,
  buildRunPayload,
  buildSelectedEntriesRunOverrides,
} from "../lib/run-overrides";

function makeBanner(overrides: Partial<ResumeBanner> = {}): ResumeBanner {
  return { failedIndex: 19, total: 24, ...overrides };
}

describe("resumeRunRange: バナー承認 → 自動 run() に渡す 0-based inclusive range (要件6)", () => {
  it("Given failedIndex=19, total=24 When 構築 Then 0-based inclusive {19, 23}（失敗 entry〜末尾）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 19, total: 24 }))).toEqual({
      start: 19,
      end: 23,
    });
  });

  it("Given failedIndex=0 (先頭で失敗), total=3 When 構築 Then {0, 2}（全域を再実行）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 0, total: 3 }))).toEqual({
      start: 0,
      end: 2,
    });
  });

  it("Given failedIndex=total-1 (末尾で失敗), total=3 When 構築 Then 単一要素 {2, 2}", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 2, total: 3 }))).toEqual({
      start: 2,
      end: 2,
    });
  });

  it("Given total=1 の単一 entry が先頭で失敗 When 構築 Then {0, 0}", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 0, total: 1 }))).toEqual({
      start: 0,
      end: 0,
    });
  });
});

// #898: playlist phase で STOPPED したときは entry が全件 done のため、保存する failedIndex は
// `total`（最終 entry の次）になる（plan 7b）。その値で再開すると entry ループは空回しし、
// playlist 追加のみが再実行される。resumeRunRange は無改修でこの境界を扱う（要件6）ことを担保する。
describe("resumeRunRange: playlist phase 停止 (failedIndex=total) は空 entry range を返す (#898 要件6/7b)", () => {
  it("Given failedIndex=total=8 (全 entry done 後の playlist 停止) When 構築 Then {8, 7}（start>end の空 entry range）", () => {
    // start(8) > end(7) なので runAll の for ループは 1 度も回らず、playlist phase だけが再実行される。
    expect(resumeRunRange(makeBanner({ failedIndex: 8, total: 8 }))).toEqual({
      start: 8,
      end: 7,
    });
  });

  it("Given failedIndex=total=1 (単一 entry 完了後の playlist 停止) When 構築 Then {1, 0}（空 entry range）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 1, total: 1 }))).toEqual({
      start: 1,
      end: 0,
    });
  });

  it("Given playlist 停止の failedIndex=total When start と end を比べる Then start > end（entry を 1 件も再生成しない）", () => {
    const range = resumeRunRange(makeBanner({ failedIndex: 5, total: 5 }));

    expect(range.start).toBeGreaterThan(range.end);
  });
});

describe("submitted clip ID resume wiring: failed-only rerun / playlist-only resume (#1183)", () => {
  it("Given failed-only rerun の入力 When payload を構築する Then indices と保存済み playlist 情報が同じ戻り値に入る", () => {
    const overrides = buildFailedEntriesRunOverrides([2, 7], {
      submittedClipIds: ["clip-a", "clip-b"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });

    expect(overrides).toEqual({
      indices: [2, 7],
      submittedClipIds: ["clip-a", "clip-b"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });
  });

  it("Given playlist-only resume の入力 When payload を構築する Then range と保存済み playlist 情報が同じ戻り値に入る", () => {
    const banner = makeBanner({ failedIndex: 4, total: 4 });
    const overrides = buildResumeRunOverrides(banner, {
      submittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 4,
    });

    expect(overrides).toEqual({
      range: { start: 4, end: 3 },
      submittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 4,
    });
  });

  it("Given resume overrides When run 送信用 payload を構築する Then entries/range と playlist resume fields が同じ戻り値に入る", () => {
    const entries = [
      { name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" },
    ];
    const overrides = buildResumeRunOverrides(
      makeBanner({ failedIndex: 1, total: 3 }),
      {
        submittedClipIds: ["clip-a", "clip-b"],
        submittedClipIdsAreDurationFiltered: true,
        playlistExpectedClipCount: 2,
      }
    );

    const payload = buildRunPayload({
      entries,
      playlistName: "target-playlist",
      range: overrides.range,
      collectionId: "collection-a",
      runMode: "queue",
      regenerateDurationOutliers: true,
      downloadEnabled: true,
      overrides,
    });

    expect(payload).toEqual({
      entries,
      playlistName: "target-playlist",
      range: { start: 1, end: 2 },
      collectionId: "collection-a",
      runMode: "queue",
      regenerateDurationOutliers: true,
      downloadEnabled: true,
      indices: undefined,
      submittedClipIds: ["clip-a", "clip-b"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });
  });

  it("Given indices 部分実行の resume state When payload を構築する Then range ではなく残り indices を渡す", () => {
    const overrides = buildResumeRunOverrides(
      makeBanner({ failedIndex: 2, total: 5, remainingIndices: [2, 4] }),
      {
        submittedClipIds: ["clip-a", "clip-b"],
        submittedClipIdsAreDurationFiltered: true,
        playlistExpectedClipCount: 6,
      }
    );

    expect(overrides).toEqual({
      indices: [2, 4],
      submittedClipIds: ["clip-a", "clip-b"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 6,
    });
  });

  it("Given failed-only overrides When run 送信用 payload を構築する Then indices と playlist resume fields が同じ戻り値に入る", () => {
    const entries = [
      { name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" },
    ];
    const overrides = buildFailedEntriesRunOverrides([0, 2], {
      submittedClipIds: ["clip-a", "clip-c"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });

    const payload = buildRunPayload({
      entries,
      playlistName: "target-playlist",
      range: undefined,
      collectionId: "collection-a",
      runMode: "serial",
      regenerateDurationOutliers: true,
      downloadEnabled: true,
      overrides,
    });

    expect(payload).toEqual({
      entries,
      playlistName: "target-playlist",
      range: undefined,
      collectionId: "collection-a",
      runMode: "serial",
      regenerateDurationOutliers: true,
      downloadEnabled: true,
      indices: [0, 2],
      submittedClipIds: ["clip-a", "clip-c"],
      submittedClipIdsAreDurationFiltered: true,
      playlistExpectedClipCount: 2,
    });
  });

  it("Given 全 entry が選択済み When selection overrides を構築する Then indices を省略して全実行扱いにする", () => {
    expect(
      buildSelectedEntriesRunOverrides({
        selectedEntries: [true, true, true],
        itemStates: ["idle", "idle", "idle"],
        entryCount: 3,
      })
    ).toBeUndefined();
  });

  it("Given 一部 entry が未選択 When selection overrides を構築する Then 選択済み 0-based indices を返す", () => {
    expect(
      buildSelectedEntriesRunOverrides({
        selectedEntries: [true, false, true, false],
        itemStates: ["idle", "idle", "idle", "idle"],
        entryCount: 4,
      })
    ).toEqual({ indices: [0, 2] });
  });

  it("Given selection が未初期化で done entry がある When selection overrides を構築する Then done 以外を既定選択にする", () => {
    expect(
      buildSelectedEntriesRunOverrides({
        selectedEntries: [],
        itemStates: ["idle", "done", "failed"],
        entryCount: 3,
      })
    ).toEqual({ indices: [0, 2] });
  });

  it("Given 全 entry が未選択 When selection overrides を構築する Then 空 indices を送らず fail-loud にする", () => {
    expect(() =>
      buildSelectedEntriesRunOverrides({
        selectedEntries: [false, false, false],
        itemStates: ["idle", "idle", "idle"],
        entryCount: 3,
      })
    ).toThrow("実行対象が選択されていません。");
  });

  it("Given durationFilter When run 送信用 payload を構築する Then payload に保持する", () => {
    const entries = [
      { name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" },
    ];

    const payload = buildRunPayload({
      entries,
      playlistName: "target-playlist",
      durationFilter: { min_sec: 75, max_sec: 240 },
      range: undefined,
      collectionId: "collection-a",
      runMode: "queue",
      downloadEnabled: true,
      overrides: undefined,
    });

    expect(payload).toMatchObject({
      entries,
      playlistName: "target-playlist",
      durationFilter: { min_sec: 75, max_sec: 240 },
      collectionId: "collection-a",
      runMode: "queue",
    });
  });

  it("Given 異常値再生成 option When payload を構築する Then default ON と override OFF が効く", () => {
    const base = {
      entries: [
        { name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" },
      ],
      playlistName: "target-playlist",
      range: undefined,
      collectionId: "collection-a",
      runMode: "serial" as const,
      downloadEnabled: true,
    };

    expect(
      buildRunPayload({ ...base, overrides: undefined })
        .regenerateDurationOutliers
    ).toBe(true);
    expect(
      buildRunPayload({
        ...base,
        regenerateDurationOutliers: true,
        overrides: { regenerateDurationOutliers: false },
      }).regenerateDurationOutliers
    ).toBe(false);
  });
});
