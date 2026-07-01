// entry 部分実行の indices 解決を実ブラウザ文脈で検証する E2E スモーク (実 Suno 非依存)。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されず、Playwright の
// page.evaluate は本番モジュール (`lib/resume-state.ts` / `entrypoints/content.ts`) を import
// できない（既存 suno-inject.spec.ts / popup-reopen-progress.spec.ts と同じ制約）。よってここでは
// checkbox selection → indices / runAll の indices ループと同手法を inline 再現し、
// 「選択された 0-based index だけを、絶対 index / 全体 total を保ったまま部分実行する」
// ことを実ブラウザ文脈で示す。本番関数自体の回帰は unit が担う。
import { expect, test } from "@playwright/test";

test("checkbox selection は選択された 0-based indices のみを絶対 index / 全体 total で実行する (#1267)", async ({
  page,
}) => {
  await page.setContent("<!doctype html><html><body></body></html>");

  const result = await page.evaluate(() => {
    // --- 本番 buildSelectedEntriesRunOverrides と同手法を inline 再現 ---
    const selectedEntries = [true, false, true, false, true, true, false, true];
    const indices = selectedEntries.flatMap((selected, index) => (selected ? [index] : []));

    // --- 本番 content.ts runAll の indices ループと同手法を inline 再現 (絶対 index を維持) ---
    const entries = Array.from({ length: selectedEntries.length }, (_, i) => ({ name: `pattern-${i + 1}` }));
    const total = entries.length;

    const processedIndices: number[] = [];
    const progress: Array<{ index: number; total: number }> = [];
    for (const i of indices) {
      processedIndices.push(i);
      // 本番 emitProgress({ phase, index: i, total }) と同様、index は絶対値・total は全体長。
      progress.push({ index: i, total });
    }

    return { indices, total, processedIndices, progress };
  });

  // checkbox ON の entry だけが 0-based indices として渡される。
  expect(result.indices).toEqual([0, 2, 4, 5, 7]);
  // indices 内 entry のみ処理し、絶対 index を保つ（slice 再採番による 0..N ズレを起こさない）。
  expect(result.processedIndices).toEqual([0, 2, 4, 5, 7]);
  // 全体 total は選択件数 (5) ではなく entries 全長 (8) を維持する。
  expect(result.total).toBe(8);
  expect(result.progress).toEqual([
    { index: 0, total: 8 },
    { index: 2, total: 8 },
    { index: 4, total: 8 },
    { index: 5, total: 8 },
    { index: 7, total: 8 },
  ]);
});

test("ERROR 停止後のバナー承認は failedIndex から末尾までを絶対 index で再実行する (#872 受け入れ基準)", async ({
  page,
}) => {
  await page.setContent("<!doctype html><html><body></body></html>");

  const result = await page.evaluate(() => {
    type Range = { start: number; end: number };
    type ResumeState = { collectionId: string; failedIndex: number; total: number; timestamp: number };

    const resolveRunRange = (rawStart1: number, rawEnd1: number | undefined, total: number): Range => {
      if (!Number.isInteger(rawStart1) || rawStart1 < 1 || rawStart1 > total) {
        throw new Error(`不正な start: ${rawStart1}`);
      }
      let end1 = rawEnd1;
      if (end1 === undefined) {
        end1 = total;
      } else if (!Number.isInteger(end1) || end1 < rawStart1 || end1 > total) {
        throw new Error(`不正な end: ${end1}`);
      }
      return { start: rawStart1 - 1, end: end1 - 1 };
    };
    // 本番 resumeBannerRange と同手法: 1-based {start: failedIndex+1, end: total}。
    const resumeBannerRange = (state: ResumeState) => ({ start: state.failedIndex + 1, end: state.total });

    // === シナリオ: entry 19 (0-based) で ERROR 停止 → resume state 永続化 → バナー承認 ===
    const resumeState: ResumeState = {
      collectionId: "20260601-clm-night-collection",
      failedIndex: 19,
      total: 24,
      timestamp: 1_700_000_000_000,
    };

    // バナー承認 → 1-based 値を作る旧 helper と同等の range override を確認する。
    const prefilled = resumeBannerRange(resumeState);
    // run → 0-based inclusive range へ解決し、content ループで実行。
    const range = resolveRunRange(prefilled.start, prefilled.end, resumeState.total);

    const processedIndices: number[] = [];
    for (let i = range.start; i <= range.end; i++) {
      processedIndices.push(i);
    }

    return { prefilled, range, processedIndices };
  });

  // バナー承認は 1-based start=20 (= failedIndex 19 + 1) / end=24 (= total) を prefill する。
  expect(result.prefilled).toEqual({ start: 20, end: 24 });
  // 0-based inclusive {19, 23} へ解決し、失敗した entry 19 から末尾 entry 23 まで再実行する。
  expect(result.range).toEqual({ start: 19, end: 23 });
  expect(result.processedIndices).toEqual([19, 20, 21, 22, 23]);
});
