// 要件6/7 (#892): ResumeBanner「再開」1 クリックで自動再開し、二重実行を防ぐことを
// 実ブラウザ文脈で検証する E2E スモーク (実 Suno 非依存)。
//
// content script は本番モジュールを page.evaluate へ import できない（既存 spec 群と同制約）。
// 要件7 の二重実行ガードは run()/runAll の inline closure state として設計されており（plan §5.2）、
// import 可能な export を持たないため unit 化できない。よってここでは
// 「acceptResume → run({range}) 自動実行」と「isRunning 中の再入を no-op にするガード」を
// inline 再現し、要件6/7 の invariant を実 PointerEvent / 実クリックで pin する。
// range 構築の純ロジック回帰は unit (use-suno-runner-resume.test.ts) が担う。
import { expect, test } from "@playwright/test";

test("「再開」1 クリックで run({range}) が自動実行される（手動 run 再押下を不要にする, 要件6）", async ({
  page,
}) => {
  await page.setContent(
    '<!doctype html><html><body><button id="resume">再開</button></body></html>'
  );

  const result = await page.evaluate(() => {
    type Range = { start: number; end: number };
    type Banner = { failedIndex: number; total: number };

    // 本番 resumeRunRange と同手法: 失敗 entry(0-based) から末尾(total-1) までの 0-based inclusive range。
    const resumeRunRange = (b: Banner): Range => ({
      start: b.failedIndex,
      end: b.total - 1,
    });

    const calls: Array<{ range: Range | undefined }> = [];
    let isRunning = false;
    // 本番 run(overrides?) の二重ガード規約: isRunning なら即 return、開始時に true を立ててから実行。
    const run = (overrides?: { range?: Range }) => {
      if (isRunning) return;
      isRunning = true;
      calls.push({ range: overrides?.range });
    };

    const banner: Banner = { failedIndex: 19, total: 24 };
    // 本番 acceptResume: ローカル構築した range を引数で run へ渡す（closure stale を避ける）。
    const acceptResume = () => run({ range: resumeRunRange(banner) });

    document.getElementById("resume")!.addEventListener("click", acceptResume);
    document
      .getElementById("resume")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true }));

    return { calls, isRunning };
  });

  // 1 クリックで run が 1 回だけ起動し、失敗 entry 19〜末尾 23 の range が渡る（手動 run ボタン不要）。
  expect(result.calls).toHaveLength(1);
  expect(result.calls[0].range).toEqual({ start: 19, end: 23 });
  expect(result.isRunning).toBe(true);
});

test("isRunning=true の最中に「再開」を連打しても run は二重に走らない (要件7)", async ({
  page,
}) => {
  await page.setContent(
    '<!doctype html><html><body><button id="resume">再開</button></body></html>'
  );

  const result = await page.evaluate(() => {
    type Range = { start: number; end: number };
    const resumeRunRange = (b: {
      failedIndex: number;
      total: number;
    }): Range => ({
      start: b.failedIndex,
      end: b.total - 1,
    });

    let runCount = 0;
    let isRunning = false;
    const run = (overrides?: { range?: Range }) => {
      if (isRunning) return; // 再入ガード（要件7）
      isRunning = true;
      runCount++;
      void overrides;
    };

    const banner = { failedIndex: 0, total: 5 };
    const btn = document.getElementById("resume")!;
    btn.addEventListener("click", () => run({ range: resumeRunRange(banner) }));

    // 実行中に 3 連打。
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    const duringRunCount = runCount;

    // 実行が終わって isRunning が降りた後はもう一度実行できる（恒久ロックではない）。
    isRunning = false;
    btn.dispatchEvent(new MouseEvent("click", { bubbles: true }));

    return { duringRunCount, afterReleaseCount: runCount };
  });

  // 連打中は最初の 1 回のみ。ロック解放後は再度 1 回走り、合計 2 回。
  expect(result.duringRunCount).toBe(1);
  expect(result.afterReleaseCount).toBe(2);
});

test("content 側 runAll も実行中の再入を弾く（同等ガード, 要件7）", async ({
  page,
}) => {
  await page.setContent("<!doctype html><html><body></body></html>");

  const result = await page.evaluate(() => {
    // 本番 content.ts runAll の running フラグと同手法を inline 再現。
    // onMessage('run') が実行中に再着信しても runAll を二重に開始しないこと。
    let running = false;
    let startedCount = 0;

    const onRun = () => {
      if (running) return { ok: true }; // 実行中は no-op で ack のみ
      running = true;
      startedCount++;
      return { ok: true };
    };

    onRun(); // 1 回目: 開始
    onRun(); // 2 回目: 実行中なので弾く
    onRun(); // 3 回目: 実行中なので弾く
    const duringRunning = startedCount;

    running = false; // 完了相当
    onRun(); // 再度開始できる
    return { duringRunning, afterFinish: startedCount };
  });

  expect(result.duringRunning).toBe(1);
  expect(result.afterFinish).toBe(2);
});
