// 1-click 自動再開 (#892 要件6) の range 構築ロジックの回帰テスト。
//
// 旧挙動: ResumeBanner「再開」は range UI を 1-based で prefill するだけで止まり、
//         ユーザーが「連続実行」を再押下して初めて生成が走り出した（2 操作）。
// 新挙動 (要件6): 「再開」1 クリックで run() まで自動実行する。React state は次レンダ反映で
//         closure から読めないため、acceptResume は 0-based inclusive な RunRange を
//         ローカルに構築して run({ range }) へ引数で渡す（order.md §2）。
//
// その「0-based RunRange 構築」を純関数 resumeRunRange へ抽出して tester surface とする
// （@testing-library/react 未導入のため、フック本体ではなく純関数で担保する＝既存 plan §6 の推奨）。
// 想定インターフェース（draft step で lib/resume-state.ts に追加すること。range SSOT に同居）:
//   export function resumeRunRange(banner: ResumeBanner): RunRange
//   // 失敗 entry (0-based failedIndex) から末尾 (total-1) まで。手動経路と同じ絶対 index を返す。
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { buildFailedEntriesRunOverrides, buildResumeRunOverrides, buildRunPayload } from "../lib/run-overrides";
import { resolveRunRange, resumeBannerRange, resumeRunRange } from "../lib/resume-state";
import type { ResumeBanner } from "../lib/resume-state";

function makeBanner(overrides: Partial<ResumeBanner> = {}): ResumeBanner {
  return { failedIndex: 19, total: 24, ...overrides };
}

const read = (rel: string): string => readFileSync(fileURLToPath(new URL(rel, import.meta.url)), "utf8");

describe("resumeRunRange: バナー承認 → 自動 run() に渡す 0-based inclusive range (要件6)", () => {
  it("Given failedIndex=19, total=24 When 構築 Then 0-based inclusive {19, 23}（失敗 entry〜末尾）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 19, total: 24 }))).toEqual({ start: 19, end: 23 });
  });

  it("Given failedIndex=0 (先頭で失敗), total=3 When 構築 Then {0, 2}（全域を再実行）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 0, total: 3 }))).toEqual({ start: 0, end: 2 });
  });

  it("Given failedIndex=total-1 (末尾で失敗), total=3 When 構築 Then 単一要素 {2, 2}", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 2, total: 3 }))).toEqual({ start: 2, end: 2 });
  });

  it("Given total=1 の単一 entry が先頭で失敗 When 構築 Then {0, 0}", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 0, total: 1 }))).toEqual({ start: 0, end: 0 });
  });
});

// 要件6 の核心契約: 1-click 自動再開（resumeRunRange を直接 run へ）と、
// 旧来の「prefill (resumeBannerRange) → run ボタン (resolveRunRange)」経路が
// 同一の絶対 index を生むこと。新経路が UI round-trip を飛ばしても挙動が一致する保証。
describe("整合性: 自動再開 range が prefill→手動 run 経路と同一 index になる (要件6)", () => {
  it("Given failedIndex=19/total=24 When 両経路で range 算出 Then 0-based {19,23} で一致する", () => {
    const banner = makeBanner({ failedIndex: 19, total: 24 });

    const auto = resumeRunRange(banner); // 1-click 経路: 直接 0-based
    const prefilled = resumeBannerRange(banner); // 旧経路: 1-based UI prefill
    const viaUi = resolveRunRange(prefilled.start, prefilled.end, banner.total); // 旧経路: run で 0-based 化

    expect(auto).toEqual(viaUi);
    expect(auto).toEqual({ start: 19, end: 23 });
  });

  it("Given failedIndex=0/total=3 When 両経路で range 算出 Then 一致する（先頭失敗の境界）", () => {
    const banner = makeBanner({ failedIndex: 0, total: 3 });

    const auto = resumeRunRange(banner);
    const prefilled = resumeBannerRange(banner);
    const viaUi = resolveRunRange(prefilled.start, prefilled.end, banner.total);

    expect(auto).toEqual(viaUi);
  });

  it("Given failedIndex=2/total=3 When 両経路で range 算出 Then 単一要素で一致する（末尾失敗の境界）", () => {
    const banner = makeBanner({ failedIndex: 2, total: 3 });

    const auto = resumeRunRange(banner);
    const prefilled = resumeBannerRange(banner);
    const viaUi = resolveRunRange(prefilled.start, prefilled.end, banner.total);

    expect(auto).toEqual(viaUi);
    expect(auto).toEqual({ start: 2, end: 2 });
  });
});

// #898: playlist phase で STOPPED したときは entry が全件 done のため、保存する failedIndex は
// `total`（最終 entry の次）になる（plan 7b）。その値で再開すると entry ループは空回しし、
// playlist 追加のみが再実行される。resumeRunRange は無改修でこの境界を扱う（要件6）ことを担保する。
describe("resumeRunRange: playlist phase 停止 (failedIndex=total) は空 entry range を返す (#898 要件6/7b)", () => {
  it("Given failedIndex=total=8 (全 entry done 後の playlist 停止) When 構築 Then {8, 7}（start>end の空 entry range）", () => {
    // start(8) > end(7) なので runAll の for ループは 1 度も回らず、playlist phase だけが再実行される。
    expect(resumeRunRange(makeBanner({ failedIndex: 8, total: 8 }))).toEqual({ start: 8, end: 7 });
  });

  it("Given failedIndex=total=1 (単一 entry 完了後の playlist 停止) When 構築 Then {1, 0}（空 entry range）", () => {
    expect(resumeRunRange(makeBanner({ failedIndex: 1, total: 1 }))).toEqual({ start: 1, end: 0 });
  });

  it("Given playlist 停止の failedIndex=total When start と end を比べる Then start > end（entry を 1 件も再生成しない）", () => {
    const range = resumeRunRange(makeBanner({ failedIndex: 5, total: 5 }));

    expect(range.start).toBeGreaterThan(range.end);
  });
});

// #898: runAll は defineContentScript 内の closure で export を持たず unit import できないため、
// content.ts をソーステキストとして読み、STOPPED 箇所すべてで resume save が走る構造を機械担保する
// （ssot-dedup.test.ts の read() 手法を雛形）。実装前は失敗し、draft step の実装後に pass する。
describe("content.ts: STOPPED phase は resume state を保存する (#898 要件1/2/3/7)", () => {
  const contentSource = read("../entrypoints/content.ts");
  const downloadFlowSource = read("../lib/download-flow.ts");

  it("Given runner sources When PHASE.STOPPED emit を数える Then 正確に 10 箇所（download retry flow の中断を含む）", () => {
    const stoppedEmits =
      `${contentSource}\n${downloadFlowSource}`.match(
        /(?:emitProgress|deps\.emitProgress)\(\{ phase: PHASE\.STOPPED/g,
      ) ?? [];

    expect(stoppedEmits).toHaveLength(10);
  });

  it("Given ループ内 STOPPED のうち未 click 箇所 When 直前を読む Then persistInterruptState(i) が隣接する（ループ先頭の 1 箇所, #948 で 2→1: queue 待ち後の中断は outcome=aborted 経路へ統合）", () => {
    // attempt 中（waitForQueueSlot / injectAndGenerate）の中断は entry-retry の outcome=aborted で
    // 一元処理され、resolveInterruptIndex で補正した interruptIndex を使う（未 click なら i と等価）。
    const loopStops =
      contentSource.match(
        /persistInterruptState\(i\);\s*emitProgress\(\{ phase: PHASE\.STOPPED, index: i, total \}\)/g,
      ) ?? [];

    expect(loopStops).toHaveLength(1);
  });

  it("Given injectWithVerification 後の STOPPED 1 箇所 When 直前を読む Then resolveInterruptIndex で補正した interruptIndex を使う (#924)", () => {
    // Generate click 済みの場合は重複を防ぐため interruptIndex = i+1 に補正して persist / emit する。
    const postInjectStops =
      contentSource.match(
        /persistInterruptState\(interruptIndex\);\s*emitProgress\(\{ phase: PHASE\.STOPPED, index: interruptIndex, total \}\)/g,
      ) ?? [];

    expect(postInjectStops).toHaveLength(1);
  });

  it("Given playlist / download phase STOPPED 4 箇所 When 直前を読む Then persistInterruptState(total) が隣接する（全 entry done 後 + 最終生成完了待ち + download 中断）", () => {
    const playlistStops =
      contentSource.match(/persistInterruptState\(total\);\s*emitProgress\(\{ phase: PHASE\.STOPPED, total \}\)/g) ??
      [];

    expect(playlistStops).toHaveLength(4);
  });

  it("Given persistInterruptState 定義 When 中身を読む Then collectionId ガード下で failedIndex/total/timestamp を writeResumeState する（要件1/3）", () => {
    // failedIndex 名を rename せず流用すること（要件3）。引数 interruptedIndex を failedIndex に載せる。
    // ERROR / STOPPED 両 phase 共通ヘルパー（dry-duplication 解消, AI-898-001）。
    expect(contentSource).toMatch(
      /function persistInterruptState\(interruptedIndex: number\): void \{[\s\S]*?if \(collectionId\)[\s\S]*?void writeResumeState\(\{\s*collectionId,\s*failedIndex: interruptedIndex,\s*total,\s*timestamp: Date\.now\(\),/,
    );
  });
});

// #898: 既存 ERROR / FINISHED 経路の resume 挙動を STOPPED 追加で壊さないこと（要件4/5）を機械担保する。
// この 2 件は実装前後どちらでも pass する（不変経路の回帰検出器）。
describe("content.ts: 既存 ERROR / FINISHED の resume 挙動は回帰しない (#898 要件4/5)", () => {
  const contentSource = read("../entrypoints/content.ts");

  it("Given ERROR phase When 読む Then resolveInterruptIndex で補正した interruptIndex で emit・persist する (#924)", () => {
    // #924 修正: ERROR catch は resolveInterruptIndex(i, submitted, isNotAcknowledged) で interruptIndex を決め、
    // emitProgress・persistInterruptState の両方に interruptIndex を渡す（両系統の failedIndex を一致させる）。
    expect(contentSource).toMatch(
      /emitProgress\(\{ phase: PHASE\.ERROR, index: interruptIndex, total, message \}\);[\s\S]*?persistInterruptState\(interruptIndex\);/,
    );
  });

  it("Given FINISHED phase When 読む Then clearResumeStateForCollection で resume state を消す（要件5）", () => {
    // #1411: 完了時リロードの前に消去完了を保証するため void → await（fire-and-forget だと
    // リロード後の ResumeBanner が「中断からの再開」と誤判定しうる）。
    expect(contentSource).toMatch(
      /await clearResumeStateForCollection\(collectionId\);[\s\S]*?emitProgress\(\{ phase: PHASE\.FINISHED, total \}\)/,
    );
  });
});

describe("submitted clip ID resume wiring: failed-only rerun / playlist-only resume (#1183)", () => {
  const contentSource = read("../entrypoints/content.ts");
  const runnerSource = read("../components/useSunoRunner.ts");

  it("Given failed-only rerun の入力 When payload を構築する Then indices と保存済み playlist 情報が同じ戻り値に入る", () => {
    const overrides = buildFailedEntriesRunOverrides([2, 7], {
      submittedClipIds: ["clip-a", "clip-b"],
      playlistExpectedClipCount: 2,
    });

    expect(overrides).toEqual({
      indices: [2, 7],
      submittedClipIds: ["clip-a", "clip-b"],
      playlistExpectedClipCount: 2,
    });
  });

  it("Given playlist-only resume の入力 When payload を構築する Then range と保存済み playlist 情報が同じ戻り値に入る", () => {
    const banner = makeBanner({ failedIndex: 4, total: 4 });
    const overrides = buildResumeRunOverrides(banner, {
      submittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      playlistExpectedClipCount: 4,
    });

    expect(overrides).toEqual({
      range: { start: 4, end: 3 },
      submittedClipIds: ["clip-a", "clip-b", "clip-c", "clip-d"],
      playlistExpectedClipCount: 4,
    });
  });

  it("Given resume overrides When run 送信用 payload を構築する Then entries/range と playlist resume fields が同じ戻り値に入る", () => {
    const entries = [{ name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" }];
    const overrides = buildResumeRunOverrides(makeBanner({ failedIndex: 1, total: 3 }), {
      submittedClipIds: ["clip-a", "clip-b"],
      playlistExpectedClipCount: 2,
    });

    const payload = buildRunPayload({
      entries,
      playlistName: "target-playlist",
      range: overrides.range,
      collectionId: "collection-a",
      overrides,
    });

    expect(payload).toEqual({
      entries,
      playlistName: "target-playlist",
      range: { start: 1, end: 2 },
      collectionId: "collection-a",
      indices: undefined,
      submittedClipIds: ["clip-a", "clip-b"],
      playlistExpectedClipCount: 2,
    });
  });

  it("Given failed-only overrides When run 送信用 payload を構築する Then indices と playlist resume fields が同じ戻り値に入る", () => {
    const entries = [{ name: "pattern-1", style: "ambient", lyrics: "[Instrumental]" }];
    const overrides = buildFailedEntriesRunOverrides([0, 2], {
      submittedClipIds: ["clip-a", "clip-c"],
      playlistExpectedClipCount: 2,
    });

    const payload = buildRunPayload({
      entries,
      playlistName: "target-playlist",
      range: undefined,
      collectionId: "collection-a",
      overrides,
    });

    expect(payload).toEqual({
      entries,
      playlistName: "target-playlist",
      range: undefined,
      collectionId: "collection-a",
      indices: [0, 2],
      submittedClipIds: ["clip-a", "clip-c"],
      playlistExpectedClipCount: 2,
    });
  });

  it("Given 旧 ResumeState に期待件数が無い When useSunoRunner を読む Then total から期待件数を復元して渡す", () => {
    expect(runnerSource).toMatch(
      /resolvePlaylistExpectedClipCountForResume\(\s*persistedResume\.playlistExpectedClipCount,\s*persistedResume\.total,\s*\)/,
    );
  });

  it("Given content run start When data payload を読む Then playlist resume 情報を runAll に渡す", () => {
    expect(contentSource).toMatch(
      /const \{ entries, playlistName, range, collectionId, indices, submittedClipIds, playlistExpectedClipCount \}[\s\S]*?Array\.isArray\(data\)[\s\S]*?void runAll\(entries, \{[\s\S]*?submittedClipIds,[\s\S]*?playlistExpectedClipCount,[\s\S]*?\}\)/,
    );
  });

  it("Given playlist phase When content.ts を読む Then 保存済み ID と今回観測 ID を resolvePlaylistClipIds で合成してから scrollAndMultiSelectByIds で row 解決する", () => {
    expect(contentSource).toMatch(
      /const currentSubmittedIds = tracker\.getSubmittedIds\(\);[\s\S]*?const submittedIds = resolvePlaylistClipIds\(\s*previousSubmittedClipIds,\s*currentSubmittedIds,\s*expectedClipCount,?\s*\);[\s\S]*?scrollAndMultiSelectByIds\(submittedIds,/,
    );
  });

  it("Given resume state persist When content.ts を読む Then playlist resume 情報を storage と snapshot の両方に保持する", () => {
    expect(contentSource).toMatch(
      /const persistedSubmittedClipIds = Array\.from\(\s*new Set\(\[\.\.\.previousSubmittedClipIds, \.\.\.tracker\.getSubmittedIds\(\)\]\),\s*\);[\s\S]*?submittedClipIds: persistedSubmittedClipIds,[\s\S]*?playlistExpectedClipCount: expectedPlaylistClipCount,/,
    );
  });

  it("Given playlist error persist When content.ts を読む Then snapshot に failedIndex も保持する", () => {
    expect(contentSource).toMatch(
      /currentSnapshot =[\s\S]*?\{\s*\.\.\.currentSnapshot,\s*failedIndex: interruptedIndex,\s*submittedClipIds: persistedSubmittedClipIds,\s*playlistExpectedClipCount: expectedPlaylistClipCount,/,
    );
  });

  it("Given playlist error When content.ts を読む Then ERROR progress に index=total を載せる", () => {
    expect(contentSource).toMatch(/emitProgress\(\{ phase: PHASE\.ERROR, index: total, total, message \}\);/);
  });

  it("Given playlist-only resume cannot resolve playlistName When useSunoRunner を読む Then silent return せず UI にエラーを出す", () => {
    expect(runnerSource).toMatch(
      /if \(!playlistName\) \{[\s\S]*?report\(\s*"playlist 名を解決できないため、playlist 追加を再開できません。コレクションを選択し直してください。",\s*true,\s*\);[\s\S]*?return;/,
    );
  });
});
