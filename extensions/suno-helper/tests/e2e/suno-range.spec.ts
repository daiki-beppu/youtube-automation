// 要件8 (#872): entry 範囲指定の連続実行を実ブラウザ文脈で検証する E2E スモーク (実 Suno 非依存)。
//
// content script は manifest の matches (`https://suno.com/*`) でしか注入されず、Playwright の
// page.evaluate は本番モジュール (`lib/resume-state.ts` / `entrypoints/content.ts`) を import
// できない（既存 suno-inject.spec.ts / popup-reopen-progress.spec.ts と同じ制約）。よってここでは
// resolveRunRange / resumeBannerRange / runAll の range ループと同手法を inline 再現し、
// 「範囲指定が 0-based inclusive へ正しく解決され、content ループが絶対 index / 全体 total を
// 保ったまま部分実行する」（判断A）ことを実ブラウザ文脈で示す。
// 本番関数自体の回帰は unit (resume-state.test.ts) が担う。
import { expect, test } from "@playwright/test";

test("entry 5〜8 を範囲指定すると 0-based indices 4..7 のみを絶対 index / 全体 total で実行する (#872)", async ({
  page,
}) => {
  await page.setContent("<!doctype html><html><body></body></html>");

  const result = await page.evaluate(() => {
    type Range = { start: number; end: number };

    // --- 本番 lib/resume-state.ts resolveRunRange と同手法を inline 再現 (1-based → 0-based inclusive) ---
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

    // --- 本番 content.ts runAll の range ループと同手法を inline 再現 (判断A: 絶対 index を維持) ---
    // 全 entries (24 件) を保持したまま range 内だけを処理し、progress は絶対 index / 全体 total を運ぶ。
    const entries = Array.from({ length: 24 }, (_, i) => ({ name: `pattern-${i + 1}` }));
    const total = entries.length;

    const range = resolveRunRange(5, 8, total); // UI の 1-based 入力
    const processedIndices: number[] = [];
    const progress: Array<{ index: number; total: number }> = [];
    for (let i = range.start; i <= range.end; i++) {
      processedIndices.push(i);
      // 本番 emitProgress({ phase, index: i, total }) と同様、index は絶対値・total は全体長。
      progress.push({ index: i, total });
    }

    return { range, total, processedIndices, progress };
  });

  // 1-based (5,8) → 0-based inclusive {4,7} へ解決される。
  expect(result.range).toEqual({ start: 4, end: 7 });
  // range 内 entry のみ処理し、絶対 index (4..7) を保つ（slice 再採番による 0..3 ズレを起こさない）。
  expect(result.processedIndices).toEqual([4, 5, 6, 7]);
  // 全体 total は range 長 (4) ではなく entries 全長 (24) を維持する。
  expect(result.total).toBe(24);
  expect(result.progress).toEqual([
    { index: 4, total: 24 },
    { index: 5, total: 24 },
    { index: 6, total: 24 },
    { index: 7, total: 24 },
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

    // バナー承認 → range UI に 1-based 値を prefill。
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
